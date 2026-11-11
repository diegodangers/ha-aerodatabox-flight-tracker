"""Ownership regression tests for FR24 tracking."""
import asyncio
import unittest
from test_flight_store import FlightStore, FakeStore


class TrackingOwnershipTests(unittest.TestCase):
    def setUp(self):
        FakeStore.state.clear()

    def test_existing_tracking_is_external_and_cannot_be_promoted(self):
        async def run():
            store = FlightStore(None)
            await store.async_load()
            await store.upsert("DL100", "2026-11-11")
            await store.mark_external_tracking("DL100", "2026-11-11")
            self.assertIs(store.get("DL100", "2026-11-11")["tracking_owned"], False)
            await store.mark_registered("DL100", "2026-11-11")
            self.assertIs(store.get("DL100", "2026-11-11")["tracking_owned"], False)
        asyncio.run(run())

    def test_new_tracking_owned_after_confirmation(self):
        async def run():
            store = FlightStore(None)
            await store.async_load()
            await store.upsert("DL100", "2026-11-11")
            await store.note_registration_attempt("DL100", "2026-11-11", new_tracking=True)
            await store.mark_registered("DL100", "2026-11-11")
            self.assertIs(store.get("DL100", "2026-11-11")["tracking_owned"], True)
        asyncio.run(run())
