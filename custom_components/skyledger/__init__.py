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
from homeassistant.components import persistent_notification
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util
import voluptuous as vol

from .const import API_HOST, BASE_URL, CONF_API_KEY, DOMAIN
from .flight_store import FlightStore
from .fr24_lifecycle import matched_record, should_register, is_fr24_tracked, canonical_flight, valid_flight_event, within_registration_window
from .notifications import NATIVE_ALERTS_ENABLED, notification_plan
from .notification_dispatch import deliver_event
from .notification_config import selected_recipients, DEFAULT_RECIPIENTS

SERVICE_LOOKUP = "lookup_flight"
SERVICE_SAVE_FLIGHT = "save_flight"
SERVICE_LIST_FLIGHTS = "list_flights"
SERVICE_FINALIZE_FLIGHT = "finalize_flight"
SERVICE_DELETE_FLIGHT = "delete_flight"
SERVICE_SET_STATISTICS_INCLUDED = "set_flight_statistics_included"
SERVICE_PREVIEW_ALERT = "preview_flight_alert"
SERVICE_SET_RECIPIENTS = "set_flight_alert_recipients"
SERVICE_SET_AIRCRAFT = "set_flight_aircraft"
SCHEMA = vol.Schema({vol.Required("flight_number"): str, vol.Required("date"): str})

def normalize_time(raw):
    if not isinstance(raw, dict):
        return None
    return raw.get("utc") or raw.get("local")

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    store = FlightStore(hass)
    await store.async_load()

    async def check_fr24_dependency() -> None:
        """Guide setup without installing or changing third-party integrations."""
        notification_id = "skyledger_fr24_dependency"
        entries = hass.config_entries.async_entries("flightradar24")
        tracked = hass.states.get("sensor.flightradar24_additional_tracked")
        add = hass.states.get("text.flightradar24_add_to_track")
        remove = hass.states.get("text.flightradar24_remove_from_track")
        if all(state is not None and state.state not in ("unavailable", "unknown") for state in (tracked, add, remove)):
            persistent_notification.async_dismiss(hass, notification_id)
            return
        if entries:
            message = (
                "Flightradar24 is configured, but its live-tracking entities are missing "
                "or unavailable. Check **Settings → Devices & services → Flightradar24** "
                "and enable the tracking entities. Scheduling and history remain usable."
            )
        else:
            message = (
                "Live tracking requires the community Flightradar24 integration. "
                "[Install Flightradar24 through HACS]"
                "(https://github.com/AlexandrErohin/home-assistant-flightradar24), "
                "then configure it under **Settings → Devices & services**. "
                "Scheduling and history remain usable without it."
            )
        persistent_notification.async_create(
            hass, message, title="SkyLedger: Flightradar24 setup required",
            notification_id=notification_id,
        )

    await check_fr24_dependency()


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
        # Apply integration defaults only to newly created flights.
        if existing is None:
            choices = entry.options
            tv_raw = choices.get("tv_services", "")
            tv_services = [s.strip() for s in tv_raw.split(",") if s.strip()] if isinstance(tv_raw, str) else list(tv_raw)
            recipients = selected_recipients(
                list(choices.get("phones", [])),
                list(choices.get("alexas", [])),
                tv_services,
            )
            recipients["alexa_quiet_start"] = choices.get("alexa_quiet_start", "22:00")
            recipients["alexa_quiet_end"] = choices.get("alexa_quiet_end", "07:00")
            record = await store.set_recipients(number, day, recipients)
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

    async def set_flight_statistics_included(call: ServiceCall) -> dict:
        try:
            record = await store.set_statistics_included(
                call.data["flight_number"], call.data["date"], call.data["included"]
            )
        except KeyError as exc:
            raise HomeAssistantError("Flight has not been saved") from exc
        return {"flight": record}

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
        return {"enabled": NATIVE_ALERTS_ENABLED, "recipients": record["alert_recipients"]}

    async def preview_flight_alert(call: ServiceCall) -> dict:
        """Show exact routing without delivering an alert."""
        record = store.get(call.data["flight_number"], call.data["date"])
        if record is None:
            raise HomeAssistantError("Flight is not saved")
        return {
            "enabled": NATIVE_ALERTS_ENABLED,
            "actions": notification_plan(
                record, call.data["event"], dt_util.now(),
                (record.get("alert_recipients") or DEFAULT_RECIPIENTS)["phones"],
                (record.get("alert_recipients") or DEFAULT_RECIPIENTS)["alexas"],
                (record.get("alert_recipients") or DEFAULT_RECIPIENTS)["tv_services"],
                tv_is_on=hass.states.is_state("media_player.family_room_tv", "on"),
                quiet_start=entry.options.get("alexa_quiet_start", "22:00"),
                quiet_end=entry.options.get("alexa_quiet_end", "07:00"),
            ),
        }

    async def reconcile_provider_status(number: str, day: str, metadata: dict) -> None:
        """Fallback lifecycle when FR24 did not confirm this flight.

        Provider statuses are only actionable near the published schedule;
        repeat lookups and subsequent FR24 events cannot duplicate delivery.
        """
        record = store.get(number, day)
        if not record or record.get("finalized_at") or record.get("tracking_registered_at"):
            return
        status = str(metadata.get("status") or "").strip().lower()
        if status not in ("departed", "arrived", "landed", "canceled", "cancelled"):
            return

        def parse_utc(value):
            if not value:
                return None
            try:
                parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00").replace(" ", "T"))
                return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
            except (ValueError, TypeError):
                return None

        now = dt_util.utcnow()
        departure = parse_utc(record.get("published_departure_utc"))
        arrival = parse_utc(record.get("published_arrival_utc"))
        if not departure or not arrival or arrival <= departure:
            return
        # Reject stale or implausibly early provider responses.
        if not (departure - timedelta(hours=2) <= now <= arrival + timedelta(hours=12)):
            return
        event = None
        if status in ("canceled", "cancelled"):
            if record.get("departed_at"):
                return
            await store.finalize(number, day, status="canceled")
        elif status == "departed":
            if now > departure + timedelta(hours=6) or record.get("departed_at"):
                return
            await store.mark_departed(number, day)
            event = "takeoff"
        elif status in ("arrived", "landed"):
            if now < arrival - timedelta(hours=3):
                return
            await store.finalize(number, day, status="landed")
            event = "landing"

        if event and NATIVE_ALERTS_ENABLED:
            selected = record.get("alert_recipients") or DEFAULT_RECIPIENTS
            steps = notification_plan(
                record, event, dt_util.now(),
                selected["phones"], selected["alexas"], selected["tv_services"],
                tv_is_on=hass.states.is_state("media_player.family_room_tv", "on"),
                quiet_start=entry.options.get("alexa_quiet_start", "22:00"),
                quiet_end=entry.options.get("alexa_quiet_end", "07:00"),
            )
            result = await deliver_event(
                hass, store, record, event, steps, enabled=NATIVE_ALERTS_ENABLED,
            )
            for recipient in result["errors"]:
                _LOGGER.warning("Fallback flight notification failed for %s: %s", record["id"], recipient)

    async def set_flight_aircraft(call: ServiceCall) -> dict:
        """Backfill a verified aircraft registration into a saved flight."""
        try:
            aircraft = {
                "registration": call.data["registration"],
                "model": call.data.get("model"),
                "code": call.data.get("code"),
                "photo_small": call.data.get("photo_small"),
                "photo_medium": call.data.get("photo_medium"),
                "photo_large": call.data.get("photo_large"),
                "jetphotos_url": (
                    "https://www.jetphotos.com/registration/"
                    + quote(call.data["registration"].strip().upper())
                ),
            }
            record = await store.set_aircraft(
                call.data["flight_number"], call.data["date"], aircraft
            )
        except (KeyError, ValueError) as exc:
            raise HomeAssistantError(str(exc)) from exc
        return {"flight": record}

    async def lookup_flight_data(number: str, flight_date: str) -> dict:
        # No further AeroDataBox requests after successful FR24 handoff.
        existing = store.get(number, flight_date)
        if existing and existing.get("tracking_registered_at"):
            saved = existing.get("metadata") or {}
            return {"flight_number": number, "date": flight_date,
                    "flights": [saved] if saved else [], "count": 1 if saved else 0}
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
                "revised_arrival_utc": (arrival.get("revisedTime") or {}).get("utc"),
            })
        if matches:
            await store.upsert(flight, flight_date, metadata=matches[0])
            current_record = store.get(flight, flight_date)
            api_status = str(matches[0].get("status") or "").lower()
            await reconcile_provider_status(flight, flight_date, matches[0])
        return {"flight_number": flight, "date": flight_date, "flights": matches, "count": len(matches)}

    async def lookup(call: ServiceCall) -> dict:
        return await lookup_flight_data(call.data["flight_number"], call.data["date"])

    async def lookup(call: ServiceCall) -> dict:
        return await lookup_flight_data(call.data["flight_number"], call.data["date"])

    async def scheduled_refresh(now) -> None:
        """Refresh known upcoming flights, skipping recently refreshed records.

        Active untracked flights are refreshed every 30 minutes; future
        flights retain the 11-hour cache to conserve provider quota.
        """
        for record in store.all():
            if record.get("finalized_at") or record.get("tracking_registered_at"):
                continue
            try:
                departure = date.fromisoformat(record["departure_date"])
                age = (datetime.now(timezone.utc) -
                       datetime.fromisoformat(record["metadata_updated_at"])
                      ) if record.get("metadata_updated_at") else None
            except (ValueError, TypeError):
                continue
            now_utc = dt_util.utcnow()
            scheduled = (record.get("scheduled_departure_utc")
                         or (record.get("metadata") or {}).get("scheduled_departure_utc"))
            try:
                departure_utc = datetime.fromisoformat(str(scheduled).replace("Z", "+00:00").replace(" ", "T"))
                if departure_utc.tzinfo is None:
                    continue
                departure_utc = departure_utc.astimezone(timezone.utc)
            except (ValueError, TypeError):
                continue
            # Use UTC timestamps, not the HA host's local calendar day.
            active = departure_utc - timedelta(hours=2) <= now_utc <= departure_utc + timedelta(hours=36)
            upcoming = now_utc < departure_utc <= now_utc + timedelta(days=2)
            if not (active or upcoming):
                continue
            if age is not None and age < (timedelta(minutes=30) if active else timedelta(hours=11)):
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

    def fr24_event_time(payload, kind):
        """Use an explicit provider event time when available."""
        keys = ("time_real_departure", "actual_departure", "takeoff_time") if kind == "takeoff" else ("time_real_arrival", "actual_arrival", "landing_time")
        for key in keys:
            value = payload.get(key)
            if value is None:
                continue
            try:
                if isinstance(value, (float, int)):
                    parsed = datetime.fromtimestamp(value, timezone.utc)
                else:
                    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00").replace(" ", "T"))
                if parsed.tzinfo is not None and parsed <= datetime.now(timezone.utc):
                    return parsed.astimezone(timezone.utc).isoformat()
            except (ValueError, TypeError, OverflowError):
                continue
        return None

    async def handle_fr24_event(event) -> None:
        record = matched_record(store.all(), event.data)
        if record is None:
            _LOGGER.debug("Ignoring FR24 event without an unambiguous matching flight")
            return
        if not valid_flight_event(record, event.event_type, dt_util.utcnow()):
            _LOGGER.warning("Rejected out-of-window or unverified FR24 %s for %s", event.event_type, record["id"])
            return
        try:
            if event.event_type == "flightradar24_tracked_took_off":
                if record.get("departed_at"):
                    return
                await store.mark_departed(record["flight_number"], record["departure_date"], actual_time=fr24_event_time(event.data, "takeoff"))
                alert = "takeoff"
            elif event.event_type == "flightradar24_tracked_landed":
                if record.get("finalized_at"):
                    return
                await store.finalize(
                    record["flight_number"], record["departure_date"], status="landed",
                    actual_time=fr24_event_time(event.data, "landing"),
                )
                alert = "landing"
            else:
                return
            if NATIVE_ALERTS_ENABLED:
                selected = record.get("alert_recipients") or DEFAULT_RECIPIENTS
                steps = notification_plan(
                    record, alert, dt_util.now(),
                    selected["phones"], selected["alexas"], selected["tv_services"],
                tv_is_on=hass.states.is_state("media_player.family_room_tv", "on"),
                quiet_start=entry.options.get("alexa_quiet_start", "22:00"),
                quiet_end=entry.options.get("alexa_quiet_end", "07:00"),
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

    async def handle_fr24_gate_event(event) -> None:
        """Record FR24 gate-transition detection times without changing lifecycle.

        The upstream events are inferred transitions, not certified OOOI times.
        Gate arrival may occur after SkyLedger has finalized the flight.
        """
        event_field = {
            "flightradar24_tracked_left_gate": "gate_departure_utc",
            "flightradar24_tracked_arrived_gate": "gate_arrival_utc",
        }.get(event.event_type)
        if event_field is None:
            return
        payload = event.data
        number = canonical_flight(payload.get("flight_number") or payload.get("callsign") or "")
        origin = payload.get("airport_origin_code_iata")
        destination = payload.get("airport_destination_code_iata")
        scheduled = payload.get("time_scheduled_departure")
        # A scheduled timestamp and both airports are mandatory: never associate
        # an event with a recurring flight on flight number alone.
        if not number or not origin or not destination or not scheduled:
            return
        try:
            scheduled_utc = datetime.fromtimestamp(float(scheduled), timezone.utc)
        except (ValueError, TypeError, OverflowError):
            return
        matches = []
        for record in store.all():
            metadata = record.get("metadata") or {}
            if (canonical_flight(record["flight_number"]) != number
                    or metadata.get("departure_airport") != origin
                    or metadata.get("arrival_airport") != destination):
                continue
            published = record.get("published_departure_utc") or metadata.get("scheduled_departure_utc")
            try:
                departure_utc = datetime.fromisoformat(str(published).replace("Z", "+00:00").replace(" ", "T"))
                if departure_utc.tzinfo and abs((departure_utc - scheduled_utc).total_seconds()) <= 12 * 3600:
                    matches.append(record)
            except (ValueError, TypeError):
                continue
        if len(matches) != 1:
            return
        record = matches[0]
        # Do not let a recurring flight's later event rewrite an older record.
        fired = event.time_fired.astimezone(timezone.utc)
        if not (scheduled_utc - timedelta(hours=8) <= fired <= scheduled_utc + timedelta(days=3)):
            return
        if event_field == "gate_departure_utc" and record.get("finalized_at"):
            return
        try:
            await store.set_operational_event(
                record["flight_number"], record["departure_date"],
                event_field, fired.isoformat(),
                source="flightradar24:event_detected:" + event.event_type,
            )
        except (KeyError, ValueError):
            _LOGGER.exception("Failed to store gate event for %s", record["id"])

    for gate_event_type in (
        "flightradar24_tracked_left_gate",
        "flightradar24_tracked_arrived_gate",
    ):
        entry.async_on_unload(hass.bus.async_listen(gate_event_type, handle_fr24_gate_event))

    async def capture_aircraft_from_fr24(flights: list[dict]) -> None:
        """Backfill current and historical records only from verified live data."""
        for flight in flights:
            if not isinstance(flight, dict) or not flight.get("aircraft_registration"):
                continue
            # FR24 schedule placeholders do not identify a flown aircraft.
            if flight.get("tracked_type") != "live":
                continue
            number = canonical_flight(flight.get("flight_number") or flight.get("callsign") or "")
            origin = flight.get("airport_origin_code_iata")
            destination = flight.get("airport_destination_code_iata")
            candidates = [
                record for record in store.all()
                if canonical_flight(record["flight_number"]) == number
                and (record.get("metadata") or {}).get("departure_airport") == origin
                and (record.get("metadata") or {}).get("arrival_airport") == destination
            ]
            # A live FR24 record must not be attached to another day's flight.
            departure_epoch = flight.get("time_scheduled_departure")
            if departure_epoch:
                try:
                    departure_utc = datetime.fromtimestamp(float(departure_epoch), timezone.utc)
                    candidates = [
                        record for record in candidates
                        if record.get("published_departure_utc")
                        and abs((datetime.fromisoformat(
                            str(record["published_departure_utc"]).replace("Z", "+00:00").replace(" ", "T")
                        ) - departure_utc).total_seconds()) <= 12 * 3600
                    ]
                except (ValueError, TypeError, OverflowError):
                    candidates = []
            elif len(candidates) == 1:
                # No provider date: only accept a recent occurrence.
                candidates = [
                    record for record in candidates
                    if record.get("published_arrival_utc")
                    and abs((dt_util.utcnow() - datetime.fromisoformat(
                        str(record["published_arrival_utc"]).replace("Z", "+00:00").replace(" ", "T")
                    )).total_seconds()) <= 48 * 3600
                ]
            else:
                candidates = []
            if len(candidates) != 1:
                continue
            record = candidates[0]
            aircraft = {
                "registration": flight["aircraft_registration"],
                "jetphotos_url": f"https://www.jetphotos.com/registration/{quote(str(flight['aircraft_registration']).upper())}",
                "model": flight.get("aircraft_model"),
                "code": flight.get("aircraft_code"),
                "photo_small": flight.get("aircraft_photo_small"),
                "photo_medium": flight.get("aircraft_photo_medium"),
                "photo_large": flight.get("aircraft_photo_large"),
            }
            current = record.get("aircraft") or {}
            if current.get("registration") == aircraft["registration"] and all(
                not value or current.get(key) == value for key, value in aircraft.items()
            ):
                continue
            await store.set_aircraft(record["flight_number"], record["departure_date"], aircraft)

    async def capture_gate_events_from_fr24(flights: list[dict]) -> None:
        """Store only explicitly labeled gate timestamps from matched FR24 flights.

        FR24's gate_arrived_sent flag is not a timestamp. Generic
        time_real_departure/arrival fields are not treated as gate events.
        """
        field_names = {
            "gate_departure_utc": ("time_gate_departure", "time_gate_out", "gate_departure_time"),
            "gate_arrival_utc": ("time_gate_arrival", "time_gate_in", "gate_arrival_time"),
        }
        for flight in flights:
            if not isinstance(flight, dict) or flight.get("tracked_type") != "live":
                continue
            if not any(flight.get(key) for keys in field_names.values() for key in keys):
                continue
            number = canonical_flight(flight.get("flight_number") or flight.get("callsign") or "")
            origin = flight.get("airport_origin_code_iata")
            destination = flight.get("airport_destination_code_iata")
            scheduled = flight.get("time_scheduled_departure")
            if not scheduled or not origin or not destination:
                continue
            try:
                scheduled_utc = datetime.fromtimestamp(float(scheduled), timezone.utc)
            except (ValueError, TypeError, OverflowError):
                continue
            matches = []
            for record in store.all():
                metadata = record.get("metadata") or {}
                if (canonical_flight(record["flight_number"]) != number
                        or metadata.get("departure_airport") != origin
                        or metadata.get("arrival_airport") != destination):
                    continue
                published = record.get("published_departure_utc")
                if not published:
                    continue
                try:
                    reference = datetime.fromisoformat(str(published).replace("Z", "+00:00").replace(" ", "T"))
                    if reference.tzinfo and abs((reference - scheduled_utc).total_seconds()) <= 12 * 3600:
                        matches.append(record)
                except (TypeError, ValueError):
                    continue
            if len(matches) != 1:
                continue
            record = matches[0]
            for event_name, keys in field_names.items():
                for key in keys:
                    value = flight.get(key)
                    if value is None or isinstance(value, bool):
                        continue
                    try:
                        if isinstance(value, (int, float)):
                            stamp = datetime.fromtimestamp(value, timezone.utc)
                        else:
                            stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00").replace(" ", "T"))
                        if stamp.tzinfo is None:
                            continue
                        stamp = stamp.astimezone(timezone.utc)
                        if not (scheduled_utc - timedelta(days=1) <= stamp <= scheduled_utc + timedelta(days=3)):
                            continue
                        await store.set_operational_event(
                            record["flight_number"], record["departure_date"],
                            event_name, stamp.isoformat(), source="flightradar24:" + key,
                        )
                        break
                    except (ValueError, TypeError, OverflowError):
                        continue

    async def register_upcoming(now) -> None:
        """Confirm from FR24 sensor first; only retry after persisted backoff."""
        await check_fr24_dependency()
        if not hass.states.get("text.flightradar24_add_to_track"):
            return
        state = hass.states.get("sensor.flightradar24_additional_tracked")
        if state is None or state.state in ("unknown", "unavailable"):
            return  # FR24 unavailable: never send speculative duplicates
        current = state.attributes.get("flights", [])
        if not isinstance(current, list):
            return
        await capture_aircraft_from_fr24(current)
        await capture_gate_events_from_fr24(current)
        # Capture explicit reported actual departures before FR24 rotates the live record.
        for flight in current:
            if not isinstance(flight, dict) or flight.get("tracked_type") != "live":
                continue
            raw = flight.get("time_real_departure")
            scheduled = flight.get("time_scheduled_departure")
            if raw is None or scheduled is None:
                continue
            try:
                actual = datetime.fromtimestamp(float(raw), timezone.utc)
                planned = datetime.fromtimestamp(float(scheduled), timezone.utc)
            except (ValueError, TypeError, OverflowError):
                continue
            candidates = []
            for record in store.all():
                meta = record.get("metadata") or {}
                if (canonical_flight(record["flight_number"]) != canonical_flight(flight.get("flight_number") or flight.get("callsign") or "")
                        or meta.get("departure_airport") != flight.get("airport_origin_code_iata")
                        or meta.get("arrival_airport") != flight.get("airport_destination_code_iata")):
                    continue
                try:
                    reference = datetime.fromisoformat(str(record.get("published_departure_utc")).replace("Z", "+00:00").replace(" ", "T"))
                    if reference.tzinfo and abs((reference - planned).total_seconds()) <= 12 * 3600:
                        candidates.append(record)
                except (ValueError, TypeError):
                    continue
            if len(candidates) == 1:
                await store.set_actual_departure(candidates[0]["flight_number"], candidates[0]["departure_date"], actual.isoformat())

        # Only remove tracking that SkyLedger itself requested and confirmed.
        # Require a matching dated live record to avoid removing a recurring flight.
        if hass.states.get("text.flightradar24_remove_from_track"):
            for record in store.all():
                if not (record.get("tracking_owned") and record.get("status") == "landed"
                        and (record.get("operational_times") or {}).get("gate_arrival_utc")
                        and record.get("actual_departure_utc")
                        and record.get("tracking_status") != "removed_after_gate_arrival"):
                    continue
                matching = []
                for flight in current:
                    if not isinstance(flight, dict) or flight.get("tracked_type") != "live":
                        continue
                    if canonical_flight(flight.get("flight_number") or "") != canonical_flight(record["flight_number"]):
                        continue
                    try:
                        planned = datetime.fromtimestamp(float(flight["time_scheduled_departure"]), timezone.utc)
                        published = datetime.fromisoformat(str(record["published_departure_utc"]).replace("Z", "+00:00").replace(" ", "T"))
                    except (KeyError, ValueError, TypeError, OverflowError):
                        continue
                    if published.tzinfo and abs((planned - published).total_seconds()) <= 12 * 3600:
                        matching.append(flight)
                if len(matching) != 1:
                    continue
                try:
                    await hass.services.async_call("text", "set_value", {
                        "entity_id": "text.flightradar24_remove_from_track",
                        "value": canonical_flight(record["flight_number"]),
                    }, blocking=True)
                    await store.mark_tracking_removed(record["flight_number"], record["departure_date"])
                except Exception:
                    _LOGGER.exception("FR24 cleanup failed for %s", record["id"])
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
            if (not duplicates and record.get('tracking_last_attempt_at')
                    and within_registration_window(record, now)
                    and is_fr24_tracked(record, current)):
                await store.mark_registered(record["flight_number"], record["departure_date"])
                continue
            if duplicates or not should_register(record, tracked, now):
                continue
            # Persist the attempt before dispatch to avoid re-sending after a restart
            # or if FR24's text service accepts a command but loses its response.
            await store.note_registration_attempt(record["flight_number"], record["departure_date"], new_tracking=True)
            try:
                await hass.services.async_call(
                    "text", "set_value",
                    {"entity_id": "text.flightradar24_add_to_track",
                     "value": canonical_flight(record["flight_number"])},
                    blocking=True,
                )
            except Exception:
                _LOGGER.exception("FR24 registration request failed for %s", record["id"])

    entry.async_on_unload(async_track_time_interval(
        hass, register_upcoming, timedelta(minutes=5),
    ))
    entry.async_on_unload(async_track_time_interval(
        hass, scheduled_refresh, timedelta(minutes=15),
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
        DOMAIN, SERVICE_SET_AIRCRAFT, set_flight_aircraft,
        schema=vol.Schema({
            vol.Required("flight_number"): str,
            vol.Required("date"): str,
            vol.Required("registration"): str,
            vol.Optional("model"): str,
            vol.Optional("code"): str,
            vol.Optional("photo_small"): str,
            vol.Optional("photo_medium"): str,
            vol.Optional("photo_large"): str,
        }),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SET_STATISTICS_INCLUDED, set_flight_statistics_included,
        schema=vol.Schema({
            vol.Required("flight_number"): str,
            vol.Required("date"): str,
            vol.Required("included"): bool,
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
    hass.services.async_remove(DOMAIN, SERVICE_SET_STATISTICS_INCLUDED)
    hass.services.async_remove(DOMAIN, SERVICE_PREVIEW_ALERT)
    hass.services.async_remove(DOMAIN, SERVICE_SET_RECIPIENTS)
    hass.services.async_remove(DOMAIN, SERVICE_SET_AIRCRAFT)
    return True
