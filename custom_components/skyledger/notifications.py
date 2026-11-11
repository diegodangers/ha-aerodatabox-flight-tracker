"""Flight alert formatting and opt-in notification delivery.

Disabled by default during migration to avoid duplicate blueprint alerts.
The host integration must explicitly enable this after a live target audit.
"""
from __future__ import annotations

from datetime import datetime, time
from typing import Any

# Migration safety: existing flight blueprints still send alerts.
NATIVE_ALERTS_ENABLED = True


def alert_message(record: dict[str, Any], event: str) -> tuple[str, str]:
    if event not in ("takeoff", "landing"):
        raise ValueError("Unsupported flight event")
    flight = record["flight_number"]
    meta = record.get("metadata") or {}
    origin = meta.get("departure_airport") or "unknown origin"
    destination = meta.get("arrival_airport") or "unknown destination"
    title = f"{flight} took off" if event == "takeoff" else f"{flight} landed"
    activity = "taken off" if event == "takeoff" else "landed"
    return (title, f"{flight} {origin} to {destination} has {activity}.")


def in_alexa_hours(local: datetime, quiet_start: str = "22:00", quiet_end: str = "07:00") -> bool:
    """Return whether an Alexa announcement is allowed by the configured quiet window."""
    try:
        start = time.fromisoformat(quiet_start)
        end = time.fromisoformat(quiet_end)
    except (TypeError, ValueError):
        start, end = time(22, 0), time(7, 0)
    now = local.timetz().replace(tzinfo=None)
    if start == end:
        return True
    quiet = start <= now < end if start < end else (now >= start or now < end)
    return not quiet

def notification_plan(
    record: dict[str, Any], event: str, local_now: datetime,
    phones: list[str], alexas: list[str], televisions: list[str],
    *, tv_is_on: bool = True, quiet_start: str = "22:00", quiet_end: str = "07:00",
) -> list[dict[str, Any]]:
    title, message = alert_message(record, event)
    steps: list[dict[str, Any]] = []
    if phones:
        steps.append({
            "domain": "notify", "service": "send_message",
            "data": {"entity_id": sorted(set(phones)), "title": title, "message": message},
        })
    if alexas and in_alexa_hours(local_now, quiet_start, quiet_end):
        steps.append({
            "domain": "notify", "service": "alexa_media",
            "data": {"target": sorted(set(alexas)), "message": message, "data": {"type": "announce"}},
        })
    for service in sorted(set(televisions)) if tv_is_on else []:
        steps.append({
            "domain": "notify", "service": service,
            "data": {"title": title, "message": message},
        })
    return steps


async def dispatch_plan(hass, steps: list[dict[str, Any]]) -> list[str]:
    """Dispatch supported actions; caller owns idempotence and opt-in."""
    errors = []
    for step in steps:
        if not hass.services.has_service(step["domain"], step["service"]):
            errors.append(f"Unavailable: {step['domain']}.{step['service']}")
            continue
        try:
            await hass.services.async_call(
                step["domain"], step["service"], step["data"], blocking=True,
            )
        except Exception as exc:
            errors.append(f"{step['domain']}.{step['service']}: {type(exc).__name__}")
    return errors
