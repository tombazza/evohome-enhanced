"""Config & options flow for evohome_enhanced."""

from __future__ import annotations

from typing import Any

import evohomeasync2 as ec2
import voluptuous as vol
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_HIGH_PRECISION,
    CONF_LOCATION_IDX,
    DOMAIN,
    SCAN_INTERVAL_DEFAULT,
    SCAN_INTERVAL_MINIMUM,
    STORAGE_KEY,
)
from .storage import TokenManager

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): cv.string,
        vol.Required(CONF_PASSWORD): cv.string,
        vol.Optional(CONF_LOCATION_IDX, default=0): cv.positive_int,
    }
)


async def _validate(hass: Any, data: dict[str, Any]) -> str:
    """Validate credentials and the location index; return the location name."""
    token_manager = TokenManager(
        hass,
        data[CONF_USERNAME],
        data[CONF_PASSWORD],
        async_get_clientsession(hass),
        storage_key=f"{STORAGE_KEY}_{data[CONF_USERNAME].lower()}",
    )
    client = ec2.EvohomeClient(token_manager)
    await client.update(dont_update_status=True)

    if data[CONF_LOCATION_IDX] >= len(client.locations):
        raise IndexError("location_idx out of range")
    return client.locations[data[CONF_LOCATION_IDX]].name


class EvoConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the UI config flow."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_USERNAME].lower())
            self._abort_if_unique_id_configured()
            try:
                title = await _validate(self.hass, user_input)
            except ec2.AuthenticationFailedError:
                errors["base"] = "invalid_auth"
            except IndexError:
                errors[CONF_LOCATION_IDX] = "invalid_location_idx"
            except ec2.EvohomeError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(title=title, data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=USER_SCHEMA, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: Any) -> EvoOptionsFlow:
        """Return the options flow."""
        return EvoOptionsFlow()


class EvoOptionsFlow(OptionsFlow):
    """Handle the options flow (scan interval, high precision)."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=options.get(CONF_SCAN_INTERVAL, SCAN_INTERVAL_DEFAULT),
                ): vol.All(vol.Coerce(int), vol.Range(min=SCAN_INTERVAL_MINIMUM)),
                vol.Optional(
                    CONF_HIGH_PRECISION,
                    default=options.get(CONF_HIGH_PRECISION, True),
                ): cv.boolean,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
