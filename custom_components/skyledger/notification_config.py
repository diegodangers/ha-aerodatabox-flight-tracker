"""Selected recipient configuration for flight alert previews.

No notifications are sent by this module. Recipients default to empty
lists; a caller must explicitly select target entities.
"""
from __future__ import annotations

from typing import Any

DEFAULT_RECIPIENTS: dict[str, Any] = {
    "phones": [],
    "alexas": [],
    "tv_services": [],
    "alexa_quiet_start": "22:00",
    "alexa_quiet_end": "07:00",
}


def selected_recipients(
    phones: list[str] | None = None,
    alexas: list[str] | None = None,
    tv_services: list[str] | None = None,
) -> dict[str, Any]:
    """Validate and deduplicate user-selected notification destinations."""
    channels = {
        "phones": phones if phones is not None else [],
        "alexas": alexas if alexas is not None else [],
        "tv_services": tv_services if tv_services is not None else [],
    }
    for kind, names in channels.items():
        if not isinstance(names, list) or any(not isinstance(x, str) for x in names):
            raise ValueError(f"Invalid {kind}")
        if kind == "phones" and any(not x.startswith("notify.") for x in names):
            raise ValueError("Phone targets must be notify entities")
        if kind == "alexas" and any(not x.startswith("media_player.") for x in names):
            raise ValueError("Alexa targets must be media players")
        if kind == "tv_services" and any(not x or "." in x for x in names):
            raise ValueError("TV targets must be notify service names without domain")
    return {
        "phones": list(dict.fromkeys(channels["phones"])),
        "alexas": list(dict.fromkeys(channels["alexas"])),
        "tv_services": list(dict.fromkeys(channels["tv_services"])),
        "alexa_quiet_start": "22:00",
        "alexa_quiet_end": "07:00",
    }
