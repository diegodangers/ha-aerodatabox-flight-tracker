"""AeroDataBox scheduled flight lookup service."""
from __future__ import annotations

from datetime import date
import re
from urllib.parse import quote

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import aiohttp_client
import voluptuous as vol

from .const import API_HOST, BASE_URL, CONF_API_KEY, DOMAIN

SERVICE_LOOKUP = "lookup_flight"
SCHEMA = vol.Schema({vol.Required("flight_number"): str, vol.Required("date"): str})

def normalize_time(raw):
    if not isinstance(raw, dict):
        return None
    return raw.get("utc") or raw.get("local")

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    async def lookup(call: ServiceCall) -> dict:
        flight = re.sub(r"\s+", "", call.data["flight_number"].upper())
        if not re.fullmatch(r"[A-Z0-9]{2,3}[0-9]{1,5}[A-Z]?", flight):
            raise HomeAssistantError("Invalid flight number")
        flight_date = call.data["date"]
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
                "arrival_airport": (arrival.get("airport") or {}).get("iata"),
                "scheduled_departure_utc": scheduled.get("utc"),
                "scheduled_departure_local": scheduled.get("local"),
                "revised_departure_utc": revised.get("utc"),
                "scheduled_arrival_utc": (arrival.get("scheduledTime") or {}).get("utc"),
            })
        return {"flight_number": flight, "date": flight_date, "flights": matches, "count": len(matches)}

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = True
    hass.services.async_register(DOMAIN, SERVICE_LOOKUP, lookup, schema=SCHEMA,
                                 supports_response=SupportsResponse.ONLY)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data[DOMAIN].pop(entry.entry_id, None)
    hass.services.async_remove(DOMAIN, SERVICE_LOOKUP)
    return True
