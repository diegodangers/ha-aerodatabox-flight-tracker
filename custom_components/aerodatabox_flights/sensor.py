"""Dynamic flight records and lifetime statistics."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory

from .const import DOMAIN


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    store = hass.data[DOMAIN][entry.entry_id]
    known: dict[str, FlightSensor] = {}
    summary = FlightSummarySensor(store, entry.entry_id)
    async_add_entities([summary])

    def refresh() -> None:
        added = []
        for record in store.all():
            key = record["id"]
            if key not in known:
                sensor = FlightSensor(store, entry.entry_id, key)
                known[key] = sensor
                added.append(sensor)
            else:
                known[key].async_write_ha_state()
        if added:
            async_add_entities(added)
        # Remove stale dynamic sensors when their saved flight is deleted.
        remaining = {record["id"] for record in store.all()}
        for key in list(known):
            if key not in remaining:
                sensor = known.pop(key)
                hass.async_create_task(sensor.async_remove())
        summary.async_write_ha_state()

    # Initial registration must occur without writing states before HA adds entities.
    initial = []
    for record in store.all():
        sensor = FlightSensor(store, entry.entry_id, record["id"])
        known[record["id"]] = sensor
        initial.append(sensor)
    if initial:
        async_add_entities(initial)

    entry.async_on_unload(store.subscribe(refresh))


class FlightSensor(SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, store, entry_id: str, key: str):
        self._store = store
        self._key = key
        self._attr_unique_id = f"{entry_id}_flight_{key}"
        self._attr_name = f"Flight {key.replace('_', ' ')}"

    @property
    def native_value(self):
        record = next((r for r in self._store.all() if r["id"] == self._key), None)
        if record is None:
            return None
        return record.get("status") or record.get("metadata", {}).get("status") or "scheduled"

    @property
    def extra_state_attributes(self):
        record = next((r for r in self._store.all() if r["id"] == self._key), None)
        return record or {}


class FlightSummarySensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Flights Tracked"

    def __init__(self, store, entry_id: str):
        self._store = store
        self._attr_unique_id = f"{entry_id}_flight_total"

    @property
    def native_value(self):
        return self._store.statistics()["total_flights"]

    @property
    def extra_state_attributes(self):
        return self._store.statistics()
