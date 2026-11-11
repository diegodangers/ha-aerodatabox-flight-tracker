"""Discover flights announced by the AeroDataBox tracking blueprint.

Only the named event creates a record; unrelated automations are ignored.
"""
from __future__ import annotations

from datetime import date
import re
from typing import Any

EVENT = "aerodatabox_flight_registered"


def parse_registration(data: dict[str, Any]) -> tuple[str, str, list[str]] | None:
    """Validate a blueprint registration event without mutating HA config."""
    number = str(data.get("flight_number", "")).upper().replace(" ", "")
    day = str(data.get("departure_date", ""))
    travelers = data.get("travelers", [])
    if not re.fullmatch(r"[A-Z0-9]{2,3}[0-9]{1,5}[A-Z]?", number):
        return None
    try:
        date.fromisoformat(day)
    except ValueError:
        return None
    if not isinstance(travelers, list) or any(
        not isinstance(person, str) or not person.startswith("person.")
        for person in travelers
    ):
        return None
    return number, day, list(dict.fromkeys(travelers))
