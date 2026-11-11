"""Contract tests for the offline, non-destructive migration preflight."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "scripts" / "migrate_skyledger_domain.py"
spec = importlib.util.spec_from_file_location("skyledger_migration", SOURCE)
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)

class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        storage = self.root / ".storage"
        storage.mkdir()
        self.entry = {"entry_id": "entry-1", "domain": "aerodatabox_flights", "title": "Old",
                      "data": {"api_key": "test-secret"}, "options": {"phones": ["notify.phone"]}}
        self.entity = {"entity_id": "sensor.flights_tracked", "platform": "aerodatabox_flights",
                       "config_entry_id": "entry-1", "unique_id": "entry-1_flight_total"}
        self.history = {"DL88_2026-11-08": {"id": "DL88_2026-11-08", "distance_miles": 7248,
                        "travelers": ["person.diego"]}}
        for name, data in {
            "core.config_entries": {"data": {"entries": [self.entry]}},
            "core.entity_registry": {"data": {"entities": [self.entity]}},
            "aerodatabox_flights.history": {"key": "aerodatabox_flights.history",
                                           "data": {"flights": self.history}},
        }.items():
            (storage / name).write_text(json.dumps(data))

    def test_preserves_config_entity_identity_and_history(self):
        sources, docs, history, count, flights, entry_id = migration.plan(self.root)
        self.assertEqual((count, flights, entry_id), (1, 1, "entry-1"))
        self.assertEqual(docs["core.config_entries"]["data"]["entries"][0]["data"], self.entry["data"])
        self.assertEqual(docs["core.config_entries"]["data"]["entries"][0]["options"], self.entry["options"])
        entity = docs["core.entity_registry"]["data"]["entities"][0]
        self.assertEqual((entity["platform"], entity["entity_id"], entity["unique_id"]),
                         ("skyledger", "sensor.flights_tracked", "entry-1_flight_total"))
        self.assertEqual(history["data"]["flights"], self.history)
        self.assertEqual(json.loads(sources["core.config_entries"].read_text())["data"]["entries"][0]["domain"],
                         "aerodatabox_flights")

    def test_refuses_existing_target_history(self):
        (self.root / ".storage" / "skyledger.history").write_text("{}")
        with self.assertRaises(ValueError):
            migration.plan(self.root)

    def test_refuses_duplicate_target_entry(self):
        file = self.root / ".storage" / "core.config_entries"
        doc = json.loads(file.read_text())
        doc["data"]["entries"].append({"entry_id": "new", "domain": "skyledger"})
        file.write_text(json.dumps(doc))
        with self.assertRaises(ValueError):
            migration.plan(self.root)

if __name__ == "__main__":
    unittest.main()
