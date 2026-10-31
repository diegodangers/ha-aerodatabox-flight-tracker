"""UI configuration flow for the AeroDataBox RapidAPI key.

The key is saved without an unrelated health-check request. After setup,
use the aerodatabox_flights.lookup_flight action to validate the subscription.
"""
from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector

from .const import CONF_API_KEY, DOMAIN


class AeroDataBoxConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            key = user_input[CONF_API_KEY].strip()
            if key:
                await self.async_set_unique_id("rapidapi")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="RapidAPI AeroDataBox", data={CONF_API_KEY: key}
                )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_API_KEY): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                )
            }),
        )
