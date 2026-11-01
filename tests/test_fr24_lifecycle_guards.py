"""Regression checks for FR24 handoff timing and event validation."""
import importlib.util
from pathlib import Path
from datetime import datetime, timedelta, timezone

spec = importlib.util.spec_from_file_location(
    "fr24_lifecycle", Path(__file__).resolve().parents[1] /
    "custom_components" / "aerodatabox_flights" / "fr24_lifecycle.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

def test_premature_registration_and_confirmation():
    departure = datetime(2026, 10, 31, 15, 10, tzinfo=timezone.utc)
    record = {"flight_number": "DL389", "departure_date": "2026-10-31",
              "metadata": {"scheduled_departure_utc": departure.isoformat()}}
    assert not module.should_register(record, set(), departure - timedelta(hours=10))
    assert not module.within_registration_window(record, departure - timedelta(hours=10))
    assert module.should_register(record, set(), departure - timedelta(hours=2))
    assert module.within_registration_window(record, departure - timedelta(hours=2))

def test_old_landing_cannot_finalize_tomorrows_flight():
    departure = datetime(2026, 10, 31, 15, 10, tzinfo=timezone.utc)
    arrival = datetime(2026, 11, 1, 7, 15, tzinfo=timezone.utc)
    record = {"tracking_registered_at": "2026-10-31T04:40:39+00:00",
              "metadata": {"scheduled_departure_utc": departure.isoformat(),
                           "scheduled_arrival_utc": arrival.isoformat()}}
    early = datetime(2026, 10, 31, 7, 48, tzinfo=timezone.utc)
    assert not module.valid_flight_event(record, "flightradar24_tracked_landed", early)
    assert not module.valid_flight_event(record, "flightradar24_tracked_took_off", early)
    record["departed_at"] = (departure + timedelta(minutes=30)).isoformat()
    assert not module.valid_flight_event(record, "flightradar24_tracked_landed", early)
    assert module.valid_flight_event(record, "flightradar24_tracked_landed", arrival)

if __name__ == "__main__":
    test_premature_registration_and_confirmation()
    test_old_landing_cannot_finalize_tomorrows_flight()
    print("FR24 lifecycle regression checks passed")
