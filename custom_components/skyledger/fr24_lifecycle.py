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


def within_registration_window(record: dict, now: datetime) -> bool:
    """Only acknowledge FR24 tracking inside the predeparture handoff window."""
    start = scheduled_start(record)
    return bool(start and start <= now.astimezone(timezone.utc) < start + timedelta(hours=2))


def valid_flight_event(record: dict, event_type: str, now: datetime) -> bool:
    """Reject events for other daily occurrences and impossible flight sequences."""
    if not record.get("tracking_registered_at"):
        return False
    meta = record.get("metadata") or {}
    def parse(value):
        if not value:
            return None
        try:
            result = datetime.fromisoformat(str(value).replace("Z", "+00:00").replace(" ", "T"))
            return result.astimezone(timezone.utc) if result.tzinfo else None
        except (ValueError, TypeError):
            return None
    departure = parse(meta.get("revised_departure_utc")) or parse(meta.get("scheduled_departure_utc"))
    arrival = parse(meta.get("scheduled_arrival_utc"))
    current = now.astimezone(timezone.utc)
    if not departure:
        return False
    if event_type == "flightradar24_tracked_took_off":
        return departure - timedelta(hours=2) <= current <= departure + timedelta(hours=6)
    if event_type == "flightradar24_tracked_landed":
        departed_at = parse(record.get("departed_at"))
        return bool(
            departed_at and arrival
            and departure < departed_at <= current
            and current >= departure + timedelta(minutes=30)
            and arrival - timedelta(hours=3) <= current <= arrival + timedelta(hours=8)
        )
    return False


def retry_delay(attempts: int) -> timedelta:
    """15, 30, 60 minute backoff, capped at 60 minutes."""
    return timedelta(minutes=min(60, 15 * (2 ** min(max(attempts - 1, 0), 2))))


def is_fr24_tracked(record: dict, tracked: list[dict]) -> bool:
    """Confirm by flight number AND date when FR24 supplies one.

    The FR24 additional-tracked sensor generally does not expose the local
    departure date. In that case only confirm if the record's number matches;
    never make this check against ambiguous duplicate-date records.
    """
    expected = canonical_flight(record.get("flight_number", ""))
    for flight in tracked:
        if not isinstance(flight, dict):
            continue
        number = flight.get("flight_number") or flight.get("callsign")
        if canonical_flight(number or "") != expected:
            continue
        day = flight.get("departure_date") or flight.get("flight_date")
        if day and day != record.get("departure_date"):
            continue
        return True
    return False


def should_register(record: dict, tracked_numbers: set[str], now: datetime) -> bool:
    """Do not retry within backoff or after the scheduled departure."""
    if record.get("finalized_at") or record.get("tracking_registered_at"):
        return False
    if canonical_flight(record.get("flight_number", "")) in {
        canonical_flight(number) for number in tracked_numbers
    }:
        return False
    start = scheduled_start(record)
    if start is None:
        return False
    current = now.astimezone(timezone.utc)
    if not (start <= current < start + timedelta(hours=2)):
        return False
    last = record.get("tracking_last_attempt_at")
    if last:
        try:
            attempted = datetime.fromisoformat(last)
            if attempted.tzinfo is None:
                return False
            if current < attempted.astimezone(timezone.utc) + retry_delay(int(record.get("tracking_attempts", 1))):
                return False
        except (ValueError, TypeError, OverflowError):
            return False
    return True
