"""Conservative FR24 lifecycle matching for AeroDataBox flights.

A match requires both flight number and a departure-local date when supplied.
An event without a date is ambiguous when the same flight number has multiple
saved dates, so it must not finalize any flight.
"""
from __future__ import annotations

from datetime import date, datetime, timezone, timedelta
import re


def canonical_flight(value: str) -> str:
    text = re.sub(r"[^A-Z0-9]", "", str(value).upper())
    if text.startswith("DAL") and text[3:].isdigit():
        return "DL" + str(int(text[3:]))
    if text.startswith("DL") and text[2:].isdigit():
        return "DL" + str(int(text[2:]))
    return text


def matched_record(records: list[dict], payload: dict) -> dict | None:
    raw = payload.get("flight_number") or payload.get("callsign")
    number = canonical_flight(raw or "")
    day = payload.get("departure_date") or payload.get("flight_date")
    candidates = [
        item for item in records
        if canonical_flight(item.get("flight_number", "")) == number
        and not item.get("finalized_at")
    ]
    if day:
        try:
            date.fromisoformat(str(day))
        except ValueError:
            return None
        candidates = [item for item in candidates if item.get("departure_date") == day]
    # No date: reject stale events and ambiguity; do not infer a flight across days.
    if not day:
        from datetime import timedelta
        today = datetime.now(timezone.utc).date()
        candidates = [
            item for item in candidates
            if today - timedelta(days=1) <= date.fromisoformat(item["departure_date"])
               <= today + timedelta(days=2)
        ]
    return candidates[0] if len(candidates) == 1 else None


def scheduled_start(record: dict, offset_hours: float = 2.0) -> datetime | None:
    value = (record.get("metadata") or {}).get("scheduled_departure_utc")
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00").replace(" ", "T"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    from datetime import timedelta
    return dt.astimezone(timezone.utc) - timedelta(hours=offset_hours)


def should_register(record: dict, tracked_numbers: set[str], now: datetime) -> bool:
    """Only register near departure; never queue old, finalized or already-tracked flights."""
    if record.get("finalized_at") or record.get("tracking_registered_at"):
        return False
    if canonical_flight(record.get("flight_number", "")) in {
        canonical_flight(number) for number in tracked_numbers
    }:
        return False
    start = scheduled_start(record)
    if start is None:
        return False
    departure = start + timedelta(hours=2)
    current = now.astimezone(timezone.utc)
    return start <= current < departure
