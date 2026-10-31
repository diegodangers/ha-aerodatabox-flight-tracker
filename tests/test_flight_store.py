"""Test persistence and deduplication without a Home Assistant installation."""
import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path

ha = types.ModuleType("homeassistant")
core = types.ModuleType("homeassistant.core")
core.HomeAssistant = object
helpers = types.ModuleType("homeassistant.helpers")
storage = types.ModuleType("homeassistant.helpers.storage")

class FakeStore:
    state = {}
    def __init__(self, hass, version, key):
        self.key = key
    async def async_load(self):
        return self.state.get(self.key)
    async def async_save(self, data):
        self.state[self.key] = data

storage.Store = FakeStore
sys.modules.update({
    "homeassistant": ha,
    "homeassistant.core": core,
    "homeassistant.helpers": helpers,
    "homeassistant.helpers.storage": storage,
})
package = types.ModuleType("flight_test_package")
package.__path__ = [str(Path(__file__).resolve().parents[1] / "custom_components" / "aerodatabox_flights")]
sys.modules["flight_test_package"] = package
for name in ("const", "flight_store"):
    path = Path(package.__path__[0]) / (name + ".py")
    spec = importlib.util.spec_from_file_location("flight_test_package." + name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

FlightStore = sys.modules["flight_test_package.flight_store"].FlightStore
flight_id = sys.modules["flight_test_package.flight_store"].flight_id

class FlightHistoryTests(unittest.TestCase):
    def setUp(self):
        FakeStore.state.clear()

    def test_deduplicate_and_persist(self):
        async def run():
            store = FlightStore(None)
            await store.async_load()
            await store.upsert("3u 6996", "2026-11-01", travelers=["person.diego", "person.diego"])
            await store.upsert("3U6996", "2026-11-01", metadata={"status": "Expected"})
            self.assertEqual(len(store.all()), 1)
            self.assertEqual(store.all()[0]["travelers"], ["person.diego"])
            restored = FlightStore(None)
            await restored.async_load()
            self.assertEqual(restored.get("3U6996", "2026-11-01")["metadata"]["status"], "Expected")
        asyncio.run(run())

    def test_finalize_once(self):
        async def run():
            store = FlightStore(None)
            await store.async_load()
            await store.upsert("DL2084", "2026-10-31", travelers=["person.diego"])
            first = await store.finalize("DL2084", "2026-10-31", status="landed")
            second = await store.finalize("DL2084", "2026-10-31", status="landed")
            self.assertEqual(first["finalized_at"], second["finalized_at"])
            self.assertEqual(store.statistics()["completed_flights"], 1)
        asyncio.run(run())

    def test_id(self):
        self.assertEqual(flight_id("dl 2084", "2026-10-31"), "DL2084_2026-10-31")
