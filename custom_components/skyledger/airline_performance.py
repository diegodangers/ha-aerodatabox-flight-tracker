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
    normalized = str(number).upper().replace(" ", "")
    # IATA flight designators are two characters. Prefer them before the
    # numeric flight suffix; otherwise a digit can be swallowed as code #3.
    match = re.fullmatch(r"([A-Z0-9]{2})([0-9]{1,5}[A-Z]?)", normalized)
    if match:
        return match.group(1)
    # Accept distinct three-letter identifiers without treating a digit
    # from a two-character IATA flight number as part of the airline.
    match = re.fullmatch(r"([A-Z]{3})([0-9]{1,5}[A-Z]?)", normalized)
    return match.group(1) if match else None


def punctuality(records: list[dict]) -> dict:
    groups = defaultdict(list)
    for record in records:
        code = airline_code(record.get("flight_number", ""))
        if code and record.get("status") in ("landed", "canceled") and record.get("finalized_at"):
            groups[code].append(record)

    def aggregate(flights):
        result = {"completed_flights": sum(f.get("status") == "landed" for f in flights),
                  "canceled_flights": sum(f.get("status") == "canceled" for f in flights),
                  "scheduled_outcomes": len(flights),
                  "cancellation_rate_pct": round(100 * sum(f.get("status") == "canceled" for f in flights) / len(flights), 1) if flights else None,
                  "overall_on_time_pct": None, "departure_samples": 0,
                  "arrival_samples": 0, "early_departures": 0, "late_departures": 0,
                  "early_arrivals": 0, "late_arrivals": 0, "on_time_arrivals": 0,
                  "average_departure_variance_min": None,
                  "average_arrival_variance_min": None, "on_time_arrival_pct": None,
                  "worst_arrival_delay_min": None}
        dep, arr = [], []
        for f in flights:
            if f.get("status") != "landed":
                continue
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
        if flights:
            result["overall_on_time_pct"] = round(100 * result["on_time_arrivals"] / len(flights), 1)
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
