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
