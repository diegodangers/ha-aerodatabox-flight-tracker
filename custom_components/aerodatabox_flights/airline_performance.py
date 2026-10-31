"""Airline punctuality derived from completed saved flight records.

An airline is the IATA prefix of a stored flight number. Variances compare
FR24 actual timestamps to the first AeroDataBox schedule retained at creation.
"""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime, timezone
import re


def _timestamp(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00").replace(" ", "T"))
    except (TypeError, ValueError):
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None


def airline_code(number: str) -> str | None:
    match = re.fullmatch(r"([A-Z0-9]{2,3})([0-9]{1,5}[A-Z]?)", str(number).upper().replace(" ", ""))
    return match.group(1) if match else None


def punctuality(records: list[dict]) -> dict:
    groups = defaultdict(list)
    for record in records:
        code = airline_code(record.get("flight_number", ""))
        if code and record.get("status") == "landed" and record.get("finalized_at"):
            groups[code].append(record)

    def aggregate(flights):
        result = {"completed_flights": len(flights), "departure_samples": 0,
                  "arrival_samples": 0, "early_departures": 0, "late_departures": 0,
                  "early_arrivals": 0, "late_arrivals": 0, "on_time_arrivals": 0,
                  "average_departure_variance_min": None,
                  "average_arrival_variance_min": None, "on_time_arrival_pct": None,
                  "worst_arrival_delay_min": None}
        dep, arr = [], []
        for f in flights:
            meta = f.get("metadata") or {}
            base_dep = _timestamp(f.get("published_departure_utc") or meta.get("scheduled_departure_utc"))
            base_arr = _timestamp(f.get("published_arrival_utc") or meta.get("scheduled_arrival_utc"))
            actual_dep = _timestamp(f.get("actual_departure_utc") or f.get("departed_at"))
            actual_arr = _timestamp(f.get("actual_arrival_utc") or f.get("finalized_at"))
            if base_dep and actual_dep:
                v = (actual_dep - base_dep).total_seconds() / 60
                dep.append(v)
            if base_arr and actual_arr:
                v = (actual_arr - base_arr).total_seconds() / 60
                arr.append(v)
        result["departure_samples"] = len(dep)
        result["arrival_samples"] = len(arr)
        result["early_departures"] = sum(v < 0 for v in dep)
        result["late_departures"] = sum(v > 0 for v in dep)
        result["early_arrivals"] = sum(v < 0 for v in arr)
        result["late_arrivals"] = sum(v > 15 for v in arr)
        result["on_time_arrivals"] = sum(v <= 15 for v in arr)
        if dep:
            result["average_departure_variance_min"] = round(sum(dep) / len(dep), 1)
        if arr:
            result["average_arrival_variance_min"] = round(sum(arr) / len(arr), 1)
            result["on_time_arrival_pct"] = round(100 * result["on_time_arrivals"] / len(arr), 1)
            result["worst_arrival_delay_min"] = round(max(0, max(arr)), 1)
        return result

    return {
        code: {
            **aggregate(flights),
            "travelers": {
                traveler: aggregate([f for f in flights if traveler in f.get("travelers", [])])
                for traveler in sorted({p for f in flights for p in f.get("travelers", [])})
            },
        }
        for code, flights in sorted(groups.items())
    }
