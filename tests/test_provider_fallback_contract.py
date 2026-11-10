"""Regression checks for provider-only flight completion.

These source-level checks complement the Home Assistant integration tests and
catch accidental removal of the fallback when FR24 cannot register a flight.
"""
from pathlib import Path

SOURCE = (Path(__file__).resolve().parents[1] /
          "custom_components/skyledger/__init__.py").read_text()


def test_provider_arrival_reconciles_completion():
    assert 'status in ("arrived", "landed")' in SOURCE
    assert 'await store.finalize(number, day, status="landed")' in SOURCE
    assert 'event = "landing"' in SOURCE


def test_fallback_does_not_override_fr24_or_repeat_completion():
    assert 'record.get("finalized_at") or record.get("tracking_registered_at")' in SOURCE
    assert 'await deliver_event(' in SOURCE


def test_active_untracked_flights_are_refreshed():
    assert 'timedelta(minutes=30) if active else timedelta(hours=11)' in SOURCE
    assert 'hass, scheduled_refresh, timedelta(minutes=15)' in SOURCE
    assert 'await reconcile_provider_status(flight, flight_date, matches[0])' in SOURCE
