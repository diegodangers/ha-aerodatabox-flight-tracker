"""Punctuality regression tests. Run with: python -m unittest discover -s tests."""
import importlib.util
from pathlib import Path
import unittest

path = Path(__file__).resolve().parents[1] / "custom_components" / "skyledger" / "airline_performance.py"
spec = importlib.util.spec_from_file_location("airline_performance", path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

def flight(number, day, scheduled, actual, travelers=None):
    return {"flight_number":number, "departure_date":day, "status":"landed",
            "finalized_at":actual, "actual_arrival_utc":actual,
            "operational_times":{"gate_arrival_utc":{"utc":actual,"source":"flightradar24:event_detected"}},
            "published_arrival_utc":scheduled, "travelers":travelers or ["person.diego"]}

class PerformanceTests(unittest.TestCase):
    def test_iata_prefix_parsing(self):
        self.assertEqual(mod.airline_code("DL2084"), "DL")
        self.assertEqual(mod.airline_code("DL389"), "DL")
        self.assertEqual(mod.airline_code("3U6996"), "3U")
        self.assertEqual(mod.airline_code("AA100"), "AA")
        self.assertEqual(mod.airline_code("ABC123"), "ABC")
        self.assertIsNone(mod.airline_code("invalid"))


    def test_cancellations_count_against_reliability(self):
        on_time = flight("DL2084", "2026-10-31", "2026-10-31T12:00:00+00:00", "2026-10-31T12:05:00+00:00")
        canceled = {"flight_number": "DL389", "status": "canceled",
                    "finalized_at": "2026-10-31T10:00:00+00:00",
                    "travelers": ["person.diego"]}
        result = mod.punctuality([on_time, canceled])["DL"]
        self.assertEqual(result["completed_flights"], 1)
        self.assertEqual(result["canceled_flights"], 1)
        self.assertEqual(result["arrival_samples"], 1)
        self.assertEqual(result["on_time_arrival_pct"], 100.0)
        self.assertEqual(result["overall_on_time_pct"], 50.0)
        self.assertEqual(result["cancellation_rate_pct"], 50.0)

    def test_grouping_and_delay_threshold(self):
        records = [
            flight("DL2084","2026-10-31","2026-10-31T12:00:00+00:00","2026-10-31T11:50:00+00:00"),
            flight("DL389","2026-10-31","2026-11-01T07:00:00+00:00","2026-11-01T07:15:00+00:00"),
            flight("DL280","2026-11-08","2026-11-08T20:00:00+00:00","2026-11-08T20:16:00+00:00"),
            flight("3U6996","2026-11-01",None,"2026-11-01T13:00:00+00:00"),
        ]
        p=mod.punctuality(records)
        self.assertEqual(p["DL"]["early_arrivals"],1)
        self.assertEqual(p["DL"]["late_arrivals"],1)
        self.assertEqual(p["DL"]["on_time_arrivals"],2)
        self.assertEqual(p["DL"]["arrival_samples"],3)
        self.assertEqual(p["3U"]["arrival_samples"],0)
        self.assertEqual(p["DL"]["travelers"]["person.diego"]["completed_flights"],3)

if __name__=="__main__":
    unittest.main()
