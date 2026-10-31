"""Registration payload validation, independent of Home Assistant."""
import importlib.util
from pathlib import Path
import unittest

source = Path(__file__).resolve().parents[1] / "custom_components" / "aerodatabox_flights" / "discovery.py"
spec = importlib.util.spec_from_file_location("flight_discovery_test", source)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class DiscoveryTests(unittest.TestCase):
    def test_normalizes_registration(self):
        self.assertEqual(
            module.parse_registration({
                "flight_number": "dl 2084", "departure_date": "2026-10-31",
                "travelers": ["person.diego", "person.diego", "person.keri"],
            }),
            ("DL2084", "2026-10-31", ["person.diego", "person.keri"]),
        )

    def test_rejects_bad_inputs(self):
        for payload in (
            {"flight_number": "DL2084", "departure_date": "not-a-date", "travelers": []},
            {"flight_number": "INVALID", "departure_date": "2026-10-31", "travelers": []},
            {"flight_number": "DL2084", "departure_date": "2026-10-31", "travelers": ["light.kitchen"]},
            {"flight_number": "DL2084", "departure_date": "2026-10-31", "travelers": "Diego"},
        ):
            with self.subTest(payload=payload):
                self.assertIsNone(module.parse_registration(payload))
