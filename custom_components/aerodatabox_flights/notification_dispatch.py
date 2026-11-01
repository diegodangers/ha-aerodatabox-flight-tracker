"""At-most-once flight alerts using persisted per-destination reservations."""
from __future__ import annotations


def delivery_key(event: str, channel: str, recipient: str) -> str:
    if event not in ("takeoff", "landing") or channel not in ("phones", "alexa", "tv"):
        raise ValueError("Invalid notification key")
    return f"{event}:{channel}:{recipient}"


def destinations(steps):
    for step in steps:
        domain, service, data = step["domain"], step["service"], step["data"]
        if domain != "notify":
            raise ValueError("Unexpected notification domain")
        if service == "send_message":
            for entity in data.get("entity_id", []):
                if not entity.startswith("notify."):
                    raise ValueError("Invalid phone entity")
                yield ("phones", entity, domain, service, {**data, "entity_id": [entity]})
        elif service == "alexa_media":
            for entity in data.get("target", []):
                if not entity.startswith("media_player."):
                    raise ValueError("Invalid Alexa entity")
                yield ("alexa", entity, domain, service, {**data, "target": [entity]})
        else:
            if not service or "." in service:
                raise ValueError("Invalid TV notification service")
            yield ("tv", service, domain, service, dict(data))


async def deliver_event(hass, storage, record, event, steps, *, enabled=False):
    """Persist a reservation before each send; never retry uncertain delivery."""
    result = {"enabled": enabled, "sent": [], "skipped": [], "errors": []}
    if not enabled:
        return result
    number, day = record["flight_number"], record["departure_date"]
    for channel, target, domain, service, data in destinations(steps):
        claimed = await storage.reserve_delivery(number, day, event, channel, target)
        if not claimed:
            result["skipped"].append(target)
            continue
        try:
            if not hass.services.has_service(domain, service):
                raise RuntimeError("Notification service unavailable")
            await hass.services.async_call(domain, service, data, blocking=True)
        except Exception as exc:
            await storage.resolve_delivery(number, day, event, channel, target, False, type(exc).__name__)
            result["errors"].append(target)
        else:
            await storage.resolve_delivery(number, day, event, channel, target, True)
            result["sent"].append(target)
    return result
