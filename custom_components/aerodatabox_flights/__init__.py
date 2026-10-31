"""AeroDataBox scheduled flight lookup service."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import re
import logging

_LOGGER = logging.getLogger(__name__)
from urllib.parse import quote

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.event import async_track_time_interval
import voluptuous as vol

from .const import API_HOST, BASE_URL, CONF_API_KEY, DOMAIN
from .flight_store import FlightStore
from .fr24_lifecycle import matched_record, should_register, is_fr24_tracked, canonical_flight
from .notifications import NATIVE_ALERTS_ENABLED, notification_plan
from .notification_dispatch import deliver_event
from .notification_config import selected_recipients, DEFAULT_RECIPIENTS

SERVICE_LOOKUP = "lookup_flight"
SERVICE_SAVE_FLIGHT = "save_flight"
SERVICE_LIST_FLIGHTS = "list_flights"
SERVICE_FINALIZE_FLIGHT = "finalize_flight"
SERVICE_DELETE_FLIGHT = "delete_flight"
SERVICE_PREVIEW_ALERT = "preview_flight_alert"
SERVICE_SET_RECIPIENTS = "set_flight_alert_recipients"
SCHEMA = vol.Schema({vol.Required("flight_number"): str, vol.Required("date"): str})

def normalize_time(raw):
    if not isinstance(raw, dict):
        return None
    return raw.get("utc") or raw.get("local")

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    store = FlightStore(hass)
    await store.async_load()

    async def save_flight(call: ServiceCall) -> dict:
        """Register a flight from the app without requiring a blueprint.

        A new flight is validated by AeroDataBox before it is saved. Existing
        records can have their traveler assignments edited without an API call.
        """
        number = call.data["flight_number"]
        day = call.data["date"]
        existing = store.get(number, day)
        if existing is None:
            result = await lookup_flight_data(number, day)
            if not result["flights"]:
                raise HomeAssistantError("AeroDataBox did not find this flight")
            await store.upsert(number, day, metadata=result["flights"][0])
        record = await store.upsert(
            number, day, travelers=call.data.get("travelers"),
        )
        return {"flight": record}

    async def list_flights(call: ServiceCall) -> dict:
        return {"flights": store.all(), "statistics": store.statistics()}

    async def finalize_flight(call: ServiceCall) -> dict:
        try:
            record = await store.finalize(
                call.data["flight_number"], call.data["date"],
                status=call.data["status"],
            )
        except KeyError as exc:
            raise HomeAssistantError("Flight has not been saved") from exc
        return {"flight": record}

    async def delete_flight(call: ServiceCall) -> dict:
        deleted = await store.delete(call.data["flight_number"], call.data["date"])
        return {"deleted": deleted}

    async def set_flight_alert_recipients(call: ServiceCall) -> dict:
        try:
            preferences = selected_recipients(
                call.data.get("phones", []),
                call.data.get("alexas", []),
                call.data.get("tv_services", []),
            )
            record = await store.set_recipients(
                call.data["flight_number"], call.data["date"], preferences,
            )
        except (ValueError, KeyError) as exc:
            raise HomeAssistantError(str(exc)) from exc
        return {"enabled": False, "recipients": record["alert_recipients"]}

    async def preview_flight_alert(call: ServiceCall) -> dict:
        """Show exact routing without delivering an alert."""
        record = store.get(call.data["flight_number"], call.data["date"])
        if record is None:
            raise HomeAssistantError("Flight is not saved")
        return {
            "enabled": NATIVE_ALERTS_ENABLED,
            "actions": notification_plan(
                record, call.data["event"], datetime.now().astimezone(),
                (record.get("alert_recipients") or DEFAULT_RECIPIENTS)["phones"],
                (record.get("alert_recipients") or DEFAULT_RECIPIENTS)["alexas"],
                (record.get("alert_recipients") or DEFAULT_RECIPIENTS)["tv_services"],
                tv_is_on=hass.states.is_state("media_player.family_room_tv", "on"),
            ),
        }

    async def lookup_flight_data(number: str, flight_date: str) -> dict:
        flight = re.sub(r"\\s+", "", number.upper())
        if not re.fullmatch(r"[A-Z0-9]{2,3}[0-9]{1,5}[A-Z]?", flight):
            raise HomeAssistantError("Invalid flight number")
        try:
            date.fromisoformat(flight_date)
        except ValueError as exc:
            raise HomeAssistantError("Date must be YYYY-MM-DD") from exc
        session = aiohttp_client.async_get_clientsession(hass)
        try:
            async with session.get(
                f"{BASE_URL}/flights/number/{quote(flight)}/{flight_date}",
                params={"dateLocalRole": "Departure", "withAircraftImage": "false", "withLocation": "false"},
                headers={"X-RapidAPI-Key": entry.data[CONF_API_KEY], "X-RapidAPI-Host": API_HOST},
                timeout=25,
            ) as response:
                if response.status == 429:
                    raise HomeAssistantError("AeroDataBox quota or rate limit exceeded")
                if response.status in (401, 403):
                    raise HomeAssistantError("AeroDataBox authentication failed")
                if response.status >= 400:
                    raise HomeAssistantError(f"AeroDataBox HTTP {response.status}")
                result = await response.json()
        except HomeAssistantError:
            raise
        except Exception as exc:
            raise HomeAssistantError("AeroDataBox request failed") from exc
        flights = result if isinstance(result, list) else [result] if isinstance(result, dict) else []
        matches = []
        for item in flights:
            if not isinstance(item, dict):
                continue
            departure = item.get("departure") or {}
            arrival = item.get("arrival") or {}
            scheduled = departure.get("scheduledTime") or {}
            revised = departure.get("revisedTime") or {}
            matches.append({
                "flight_number": item.get("number", flight),
                "status": item.get("status"),
                "departure_airport": (departure.get("airport") or {}).get("iata"),
                "departure_airport_name": (departure.get("airport") or {}).get("name"),
                "departure_coordinates": (departure.get("airport") or {}).get("location"),
                "arrival_airport": (arrival.get("airport") or {}).get("iata"),
                "arrival_coordinates": (arrival.get("airport") or {}).get("location"),
                "scheduled_departure_utc": scheduled.get("utc"),
                "scheduled_departure_local": scheduled.get("local"),
                "revised_departure_utc": revised.get("utc"),
                "scheduled_arrival_utc": (arrival.get("scheduledTime") or {}).get("utc"),
            })
        if matches:
            await store.upsert(
                flight, flight_date,
                metadata=matches[0],
            )
        return {"flight_number": flight, "date": flight_date, "flights": matches, "count": len(matches)}

    async def lookup(call: ServiceCall) -> dict:
        return await lookup_flight_data(call.data["flight_number"], call.data["date"])

    async def lookup(call: ServiceCall) -> dict:
        return await lookup_flight_data(call.data["flight_number"], call.data["date"])

    async def scheduled_refresh(now) -> None:
        """Refresh known upcoming flights, skipping recently refreshed records.

        Successful lookup timestamps prevent repeat requests within 11 hours.
        This timer is owned by the integration, not a per-flight blueprint.
        """
        for record in store.all():
            if record.get("finalized_at"):
                continue
            try:
                departure = date.fromisoformat(record["departure_date"])
                age = (datetime.now(timezone.utc) -
                       datetime.fromisoformat(record["metadata_updated_at"])
                      ) if record.get("metadata_updated_at") else None
            except (ValueError, TypeError):
                continue
            if not (date.today() <= departure <= date.today() + timedelta(days=2)):
                continue
            if age is not None and age < timedelta(hours=11):
                continue
            try:
                await hass.services.async_call(
                    DOMAIN, SERVICE_LOOKUP,
                    {"flight_number": record["flight_number"],
                     "date": record["departure_date"]},
                    blocking=True, return_response=True,
                )
            except Exception:
                # Individual API failures must not prevent other flights.
                _LOGGER.exception("Scheduled lookup failed for %s", record["id"])

    async def handle_fr24_event(event) -> None:
        record = matched_record(store.all(), event.data)
        if record is None:
            _LOGGER.debug("Ignoring FR24 event without an unambiguous matching flight")
            return
        try:
            if event.event_type == "flightradar24_tracked_took_off":
                if record.get("departed_at"):
                    return
                await store.mark_departed(record["flight_number"], record["departure_date"])
                alert = "takeoff"
            elif event.event_type == "flightradar24_tracked_landed":
                if record.get("finalized_at"):
                    return
                await store.finalize(
                    record["flight_number"], record["departure_date"], status="landed",
                )
                alert = "landing"
            else:
                return
            if NATIVE_ALERTS_ENABLED:
                selected = record.get("alert_recipients") or DEFAULT_RECIPIENTS
                steps = notification_plan(
                    record, alert, datetime.now().astimezone(),
                    selected["phones"], selected["alexas"], selected["tv_services"],
                tv_is_on=hass.states.is_state("media_player.family_room_tv", "on"),
                )
                result = await deliver_event(
                    hass, store, record, alert, steps, enabled=NATIVE_ALERTS_ENABLED,
                )
                for recipient in result["errors"]:
                    _LOGGER.warning("Flight notification failed for %s", recipient)
        except Exception:
            _LOGGER.exception("Could not record FR24 event for %s", record["id"])

    for event_type in ("flightradar24_tracked_took_off", "flightradar24_tracked_landed"):
        entry.async_on_unload(hass.bus.async_listen(event_type, handle_fr24_event))

    async def register_upcoming(now) -> None:
        """Confirm from FR24 sensor first; only retry after persisted backoff."""
        if not hass.states.get("text.flightradar24_add_to_track"):
            return
        state = hass.states.get("sensor.flightradar24_additional_tracked")
        if state is None or state.state in ("unknown", "unavailable"):
            return  # FR24 unavailable: never send speculative duplicates
        current = state.attributes.get("flights", [])
        if not isinstance(current, list):
            return
        tracked = {
            str(f.get("flight_number") or f.get("callsign") or "")
            for f in current if isinstance(f, dict)
        }
        records = store.all()
        for record in records:
            # FR24 omits dates for some tracked entries. Avoid falsely confirming
            # a different departure of the same flight number.
            duplicates = [
                other for other in records
                if canonical_flight(other["flight_number"]) == canonical_flight(record["flight_number"])
                and other["departure_date"] != record["departure_date"]
                and not other.get("finalized_at")
            ]
            if not duplicates and is_fr24_tracked(record, current):
                await store.mark_registered(record["flight_number"], record["departure_date"])
                continue
            if duplicates or not should_register(record, tracked, now):
                continue
            # Persist the attempt before dispatch to avoid re-sending after a restart
            # or if FR24's text service accepts a command but loses its response.
            await store.note_registration_attempt(record["flight_number"], record["departure_date"])
            try:
                await hass.services.async_call(
                    "text", "set_value",
                    {"entity_id": "text.flightradar24_add_to_track",
                     "value": record["flight_number"]},
                    blocking=True,
                )
            except Exception:
                _LOGGER.exception("FR24 registration request failed for %s", record["id"])

    entry.async_on_unload(async_track_time_interval(
        hass, register_upcoming, timedelta(minutes=5),
    ))
    entry.async_on_unload(async_track_time_interval(
        hass, scheduled_refresh, timedelta(hours=12),
    ))
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = store
    hass.services.async_register(
        DOMAIN, SERVICE_SAVE_FLIGHT, save_flight,
        schema=vol.Schema({
            vol.Required("flight_number"): str,
            vol.Required("date"): str,
            vol.Optional("travelers"): vol.All([vol.Match(r"^person\.[a-z0-9_]+$")]),
        }),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_LIST_FLIGHTS, list_flights,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SET_RECIPIENTS, set_flight_alert_recipients,
        schema=vol.Schema({
            vol.Required("flight_number"): str,
            vol.Required("date"): str,
            vol.Optional("phones", default=[]): [str],
            vol.Optional("alexas", default=[]): [str],
            vol.Optional("tv_services", default=[]): [str],
        }),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_PREVIEW_ALERT, preview_flight_alert,
        schema=vol.Schema({
            vol.Required("flight_number"): str,
            vol.Required("date"): str,
            vol.Required("event"): vol.In(["takeoff", "landing"]),
            vol.Optional("phones", default=[]): [str],
            vol.Optional("alexas", default=[]): [str],
            vol.Optional("tv_services", default=[]): [str],
        }),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_DELETE_FLIGHT, delete_flight,
        schema=SCHEMA, supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_FINALIZE_FLIGHT, finalize_flight,
        schema=vol.Schema({
            vol.Required("flight_number"): str,
            vol.Required("date"): str,
            vol.Required("status"): vol.In(["landed", "canceled"]),
        }),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(DOMAIN, SERVICE_LOOKUP, lookup, schema=SCHEMA,
                                 supports_response=SupportsResponse.ONLY)
    await hass.config_entries.async_forward_entry_setups(entry, ["sensor"])
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if not await hass.config_entries.async_unload_platforms(entry, ["sensor"]):
        return False
    hass.data[DOMAIN].pop(entry.entry_id, None)
    hass.services.async_remove(DOMAIN, SERVICE_LOOKUP)
    hass.services.async_remove(DOMAIN, SERVICE_SAVE_FLIGHT)
    hass.services.async_remove(DOMAIN, SERVICE_LIST_FLIGHTS)
    hass.services.async_remove(DOMAIN, SERVICE_FINALIZE_FLIGHT)
    hass.services.async_remove(DOMAIN, SERVICE_DELETE_FLIGHT)
    hass.services.async_remove(DOMAIN, SERVICE_PREVIEW_ALERT)
    hass.services.async_remove(DOMAIN, SERVICE_SET_RECIPIENTS)
    return True
