"""UI setup and native configuration flow for SkyLedger.

The key is saved without an unrelated health-check request. After setup,
use the skyledger.lookup_flight action to validate the subscription.
"""
from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector

from .const import CONF_API_KEY, DOMAIN


class SkyLedgerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            key = user_input[CONF_API_KEY].strip()
            if key:
                await self.async_set_unique_id("rapidapi")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="SkyLedger", data={CONF_API_KEY: key}
                )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_API_KEY): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                )
            }),
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        return SkyLedgerOptionsFlow()


class SkyLedgerOptionsFlow(config_entries.OptionsFlow):
    """User-approved recipients and alert settings for future flights."""

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        current = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional("phones", default=current.get("phones", [])):
                    selector.EntitySelector(selector.EntitySelectorConfig(
                        domain="notify", multiple=True)),
                vol.Optional("alexas", default=current.get("alexas", [])):
                    selector.EntitySelector(selector.EntitySelectorConfig(
                        domain="media_player", multiple=True)),
                vol.Optional("tv_services", default=current.get("tv_services", "")):
                    selector.TextSelector(selector.TextSelectorConfig(multiline=False)),
                vol.Optional("alexa_quiet_start", default=current.get("alexa_quiet_start", "22:00")):
                    selector.TimeSelector(),
                vol.Optional("alexa_quiet_end", default=current.get("alexa_quiet_end", "07:00")):
                    selector.TimeSelector(),
            }),
        )
