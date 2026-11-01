"""Verify disabled delivery, independent recipients and durable duplicate blocking."""
import asyncio
import importlib.util
from pathlib import Path
import unittest

path = Path(__file__).resolve().parents[1] / "custom_components/aerodatabox_flights/notification_dispatch.py"
spec = importlib.util.spec_from_file_location("notification_dispatch_test", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FakeStore:
    def __init__(self):
        self.saved = set()
        self.outcomes = {}
    async def reserve_delivery(self, number, day, event, channel, target):
        key = (number, day, event, channel, target)
        if key in self.saved:
            return False
        self.saved.add(key)
        return True
    async def resolve_delivery(self, number, day, event, channel, target, success, error=None):
        self.outcomes[(event, channel, target)] = success


class FakeServices:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail
    def has_service(self, domain, service):
        return True
    async def async_call(self, domain, service, data, blocking):
        self.calls.append((domain, service, data))
        if self.fail:
            raise RuntimeError("test")


class FakeHA:
    def __init__(self, fail=False):
        self.services = FakeServices(fail)


class DeliveryTests(unittest.TestCase):
    def test_disabled_does_not_reserve_or_send(self):
        store, ha = FakeStore(), FakeHA()
        result = asyncio.run(module.deliver_event(ha, store, {"flight_number": "DL2084", "departure_date": "2026-10-31"},
            "takeoff", [{"domain": "notify", "service": "send_message", "data": {"entity_id": ["notify.diego_2"], "message": "test"}}]))
        self.assertFalse(result["enabled"])
        self.assertFalse(store.saved)
        self.assertFalse(ha.services.calls)

    def test_duplicate_suppression_and_new_landing_event(self):
        store, ha = FakeStore(), FakeHA()
        flight = {"flight_number": "DL2084", "departure_date": "2026-10-31"}
        steps = [{"domain": "notify", "service": "send_message", "data": {"entity_id": ["notify.diego_2", "notify.keris_iphone"], "message": "test"}}]
        first = asyncio.run(module.deliver_event(ha, store, flight, "takeoff", steps, enabled=True))
        second = asyncio.run(module.deliver_event(ha, store, flight, "takeoff", steps, enabled=True))
        landed = asyncio.run(module.deliver_event(ha, store, flight, "landing", steps, enabled=True))
        self.assertEqual(len(first["sent"]), 2)
        self.assertEqual(len(second["skipped"]), 2)
        self.assertEqual(len(landed["sent"]), 2)
        self.assertEqual(len(ha.services.calls), 4)

    def test_failed_send_stays_reserved(self):
        store, ha = FakeStore(), FakeHA(True)
        flight = {"flight_number": "DL2084", "departure_date": "2026-10-31"}
        steps = [{"domain": "notify", "service": "android_tv_fire_tv_192_168_68_72", "data": {"message": "test"}}]
        result = asyncio.run(module.deliver_event(ha, store, flight, "landing", steps, enabled=True))
        retry = asyncio.run(module.deliver_event(ha, store, flight, "landing", steps, enabled=True))
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(len(retry["skipped"]), 1)
        self.assertEqual(len(ha.services.calls), 1)
