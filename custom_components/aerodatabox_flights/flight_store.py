"""Persistent flight records for the AeroDataBox integration.

Records use a compound identity (normalized flight number, departure-local date).
Person entity IDs are stored rather than display names.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN

STORAGE_VERSION = 1


def flight_id(number: str, departure_date: str) -> str:
    return f"{number.upper().replace(' ', '')}_{departure_date}"


class FlightStore:
    """Save metadata and traveler assignments independently of automations."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.history")
        self._flights: dict[str, dict[str, Any]] = {}

    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        self._flights = data.get("flights", {})

    async def async_save(self) -> None:
        await self._store.async_save({"flights": self._flights})

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
        self._flights[key] = record
        await self.async_save()
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
            "completed_flights": len(completed),
            "person": travelers,
        }
