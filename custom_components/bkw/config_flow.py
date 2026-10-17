"""Config flow for the BKW Smart Meter integration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .api import BkwApi, BkwApiError, BkwAuthError, PkceLogin
from .const import CONF_FIXED_FEE, CONF_PRICE, CONF_PRICE_ENTITY, CONF_REFRESH_TOKEN, DOMAIN

CONF_ADDRESS = "address"

SCHEMA = vol.Schema({vol.Required(CONF_ADDRESS): str})

OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_PRICE_ENTITY): EntitySelector(EntitySelectorConfig(domain="sensor")),
        vol.Optional(CONF_PRICE): NumberSelector(
            NumberSelectorConfig(min=0, step="any", mode=NumberSelectorMode.BOX)
        ),
        vol.Optional(CONF_FIXED_FEE): NumberSelector(
            NumberSelectorConfig(min=0, step="any", mode=NumberSelectorMode.BOX)
        ),
    }
)


class BkwOptionsFlow(OptionsFlowWithReload):
    """Choose the price the imported consumption is costed at."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for a price entity or a fixed price per kWh."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if CONF_PRICE_ENTITY in user_input and CONF_PRICE in user_input:
                errors["base"] = "one_price"
            else:
                return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                OPTIONS_SCHEMA, user_input or self.config_entry.options
            ),
            errors=errors,
        )


class BkwConfigFlow(ConfigFlow, domain=DOMAIN):
    """Log in to myBKW once in the browser and keep the offline token."""

    VERSION = 1

    def __init__(self) -> None:
        self._login = PkceLogin()

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> BkwOptionsFlow:
        """Return the price options."""
        return BkwOptionsFlow()

    async def _authenticate(self, address: str) -> tuple[BkwApi, list[dict[str, Any]]]:
        """Accept the redirected address of a browser login, or a refresh token as is."""
        api = BkwApi(async_get_clientsession(self.hass))
        if address.strip().startswith("eyJ"):
            api.refresh_token = address.strip()
            await api.async_refresh()
        else:
            await api.async_login(self._login, address)
        return api, await api.async_metering_points()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the address the browser landed on after logging in."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                api, points = await self._authenticate(user_input[CONF_ADDRESS])
            except BkwAuthError:
                errors["base"] = "invalid_auth"
            except BkwApiError:
                errors["base"] = "cannot_connect"
            else:
                if not points:
                    return self.async_abort(reason="no_metering_points")
                code = points[0]["meteringPointCode"]
                await self.async_set_unique_id(code)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"BKW {code[-6:]}",
                    data={CONF_REFRESH_TOKEN: api.refresh_token},
                )
        return self.async_show_form(
            step_id="user",
            data_schema=SCHEMA,
            errors=errors,
            description_placeholders={"login_url": self._login.url},
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Start over with a new browser login once the offline token has expired."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the address of a new browser login."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                api, points = await self._authenticate(user_input[CONF_ADDRESS])
            except BkwAuthError:
                errors["base"] = "invalid_auth"
            except BkwApiError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(points[0]["meteringPointCode"] if points else None)
                self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(
                    self._get_reauth_entry(),
                    data_updates={CONF_REFRESH_TOKEN: api.refresh_token},
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=SCHEMA,
            errors=errors,
            description_placeholders={"login_url": self._login.url},
        )
