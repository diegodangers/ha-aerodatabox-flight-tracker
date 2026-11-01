"""FR24 matching and scheduling tests; no live HA calls."""
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest

path = Path(__file__).resolve().parents[1] / "custom_components/aerodatabox_flights/fr24_lifecycle.py"
spec = importlib.util.spec_from_file_location("fr24_lifecycle_test", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FlightLifecycleTests(unittest.TestCase):
    def test_callsign_normalization(self):
        self.assertEqual(module.canonical_flight("DAL0389"), "DL389")
        self.assertEqual(module.canonical_flight("DL 0389"), "DL389")

    def test_ambiguous_number_rejected(self):
        today = datetime.now(timezone.utc).date().isoformat()
        records = [{"flight_number": "DL389", "departure_date": today},
                   {"flight_number": "DL389", "departure_date": (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()}]
        self.assertIsNone(module.matched_record(records, {"flight_number": "DAL389"}))
        self.assertEqual(module.matched_record(records, {"flight_number": "DAL389", "departure_date": today}), records[0])

    def test_stale_event_rejected(self):
        records = [{"flight_number": "DL865", "departure_date": "2026-01-01"}]
        self.assertIsNone(module.matched_record(records, {"flight_number": "DL865"}))

    def test_scheduled_start_utc(self):
        row = {"metadata": {"scheduled_departure_utc": "2026-11-01 10:45Z"}}
        self.assertEqual(module.scheduled_start(row).isoformat(), "2026-11-01T08:45:00+00:00")

    def test_registration_window(self):
        start = datetime(2026, 11, 1, 10, 45, tzinfo=timezone.utc)
        record = {
            "flight_number": "3U6996",
            "metadata": {"scheduled_departure_utc": "2026-11-01 10:45Z"},
        }
        self.assertFalse(module.should_register(record, set(), start - timedelta(hours=3)))
        self.assertTrue(module.should_register(record, set(), start - timedelta(minutes=30)))
        self.assertFalse(module.should_register(record, set(), start + timedelta(minutes=1)))
        self.assertFalse(module.should_register(record, {"3U6996"}, start - timedelta(minutes=30)))
        self.assertFalse(module.should_register({**record, "finalized_at": "done"}, set(), start - timedelta(minutes=30)))

    def test_confirmation_and_wrong_date(self):
        record = {"flight_number": "DL389", "departure_date": "2026-10-31"}
        self.assertTrue(module.is_fr24_tracked(record, [{"flight_number": "DAL389"}]))
        self.assertFalse(module.is_fr24_tracked(record, [{"flight_number": "DL389", "departure_date": "2026-11-01"}]))
        self.assertFalse(module.is_fr24_tracked(record, [{"flight_number": "DL280"}]))

    def test_retry_backoff_and_confirmed_stop(self):
        departure = datetime(2026, 11, 1, 10, 45, tzinfo=timezone.utc)
        now = departure - timedelta(minutes=45)
        row = {"flight_number": "3U6996", "metadata": {"scheduled_departure_utc": "2026-11-01 10:45Z"}}
        for attempts, delay in [(1, 15), (2, 30), (3, 60), (4, 60)]:
            attempt_time = now - timedelta(minutes=delay - 1)
            pending = {**row, "tracking_attempts": attempts, "tracking_last_attempt_at": attempt_time.isoformat()}
            self.assertFalse(module.should_register(pending, set(), now))
            pending["tracking_last_attempt_at"] = (now - timedelta(minutes=delay)).isoformat()
            self.assertTrue(module.should_register(pending, set(), now))
        self.assertFalse(module.should_register({**row, "tracking_registered_at": "confirmed"}, set(), now))

    def test_invalid_attempt_timestamp_fails_closed(self):
        row = {"flight_number": "3U6996", "metadata": {"scheduled_departure_utc": "2026-11-01 10:45Z"},
               "tracking_last_attempt_at": "invalid"}
        self.assertFalse(module.should_register(row, set(), datetime(2026, 11, 1, 10, tzinfo=timezone.utc)))
