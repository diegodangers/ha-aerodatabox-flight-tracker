"""Persistent flight records for the AeroDataBox integration.

Records use a compound identity (normalized flight number, departure-local date).
Person entity IDs are stored rather than display names.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import asin, cos, radians, sin, sqrt
from typing import Any, Callable

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN

STORAGE_VERSION = 1
EARTH_RADIUS_MILES = 3958.7613


def great_circle_miles(origin: dict | None, destination: dict | None) -> float | None:
    """Straight-line miles; do not mistake this for flown aircraft distance."""
    if not isinstance(origin, dict) or not isinstance(destination, dict):
        return None
    try:
        lat1, lon1 = float(origin["lat"]), float(origin["lon"])
        lat2, lon2 = float(destination["lat"]), float(destination["lon"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (-90 <= lat1 <= 90 and -90 <= lat2 <= 90 and -180 <= lon1 <= 180 and -180 <= lon2 <= 180):
        return None
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return round(2 * EARTH_RADIUS_MILES * asin(min(1, sqrt(a))), 1)



def flight_id(number: str, departure_date: str) -> str:
    return f"{number.upper().replace(' ', '')}_{departure_date}"


class FlightStore:
    """Save metadata and traveler assignments independently of automations."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.history")
        self._flights: dict[str, dict[str, Any]] = {}
        self._listeners: list[Callable[[], None]] = []

    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        self._flights = data.get("flights", {})

    async def async_save(self) -> None:
        await self._store.async_save({"flights": self._flights})

    def subscribe(self, callback: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(callback)
        def unsubscribe() -> None:
            if callback in self._listeners:
                self._listeners.remove(callback)
        return unsubscribe

    def _notify(self) -> None:
        for callback in list(self._listeners):
            callback()

    def get(self, number: str, departure_date: str) -> dict[str, Any] | None:
        return self._flights.get(flight_id(number, departure_date))

    def all(self) -> list[dict[str, Any]]:
        return sorted(
            self._flights.values(),
            key=lambda value: (value.get("departure_date", ""), value.get("flight_number", "")),
        )

    async def upsert(
        self,
        number: str,
        departure_date: str,
        *,
        travelers: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        key = flight_id(number, departure_date)
        old = self._flights.get(key, {})
        record = {
            **old,
            "id": key,
            "flight_number": number.upper().replace(" ", ""),
            "departure_date": departure_date,
            "created_at": old.get("created_at") or datetime.now(timezone.utc).isoformat(),
        }
        if travelers is not None:
            record["travelers"] = list(dict.fromkeys(travelers))
        else:
            record.setdefault("travelers", [])
        if metadata is not None:
            record["metadata"] = metadata
            record["metadata_updated_at"] = datetime.now(timezone.utc).isoformat()
            miles = great_circle_miles(metadata.get("departure_coordinates"), metadata.get("arrival_coordinates"))
            if miles is not None:
                record["distance_miles"] = miles
                record["distance_type"] = "great_circle"
        self._flights[key] = record
        await self.async_save()
        self._notify()
        return record.copy()

    async def delete(self, number: str, departure_date: str) -> bool:
        """Permanently remove a test record without touching other flights."""
        key = flight_id(number, departure_date)
        if key not in self._flights:
            return False
        del self._flights[key]
        await self.async_save()
        self._notify()
        return True

    async def mark_registered(self, number: str, departure_date: str) -> None:
        record = self._flights.get(flight_id(number, departure_date))
        if record is None or record.get("tracking_registered_at"):
            return
        record["tracking_registered_at"] = datetime.now(timezone.utc).isoformat()
        await self.async_save()
        self._notify()

    async def mark_departed(self, number: str, departure_date: str) -> dict[str, Any]:
        """Idempotently record takeoff without crediting mileage until landing."""
        key = flight_id(number, departure_date)
        record = self._flights.get(key)
        if record is None:
            raise KeyError(key)
        if record.get("finalized_at") or record.get("departed_at"):
            return record.copy()
        record["status"] = "airborne"
        record["departed_at"] = datetime.now(timezone.utc).isoformat()
        await self.async_save()
        self._notify()
        return record.copy()

    async def finalize(
        self,
        number: str,
        departure_date: str,
        *,
        status: str,
    ) -> dict[str, Any]:
        key = flight_id(number, departure_date)
        if key not in self._flights:
            raise KeyError(key)
        record = self._flights[key]
        if record.get("finalized_at"):
            return record.copy()
        record["status"] = status
        record["finalized_at"] = datetime.now(timezone.utc).isoformat()
        await self.async_save()
        self._notify()
        return record.copy()

    def statistics(self) -> dict[str, Any]:
        records = list(self._flights.values())
        completed = [f for f in records if f.get("status") == "landed"]
        travelers: dict[str, dict[str, int | float]] = {}
        for flight in completed:
            miles = flight.get("distance_miles")
            for person in flight.get("travelers", []):
                data = travelers.setdefault(person, {"flights": 0, "miles": 0.0})
                data["flights"] += 1
                if isinstance(miles, (int, float)):
                    data["miles"] += miles
        return {
            "total_flights": len(records),
            "unique_completed_miles": round(sum(f.get("distance_miles") or 0 for f in completed), 1),
            "completed_flights": len(completed),
            "person": travelers,
        }
