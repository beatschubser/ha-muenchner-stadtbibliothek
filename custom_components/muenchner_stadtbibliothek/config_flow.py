"""Config flow: one entry per library card."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_NAME, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import LibraryAuthError, LibraryConnectionError, LibraryError
from .const import (
    CONF_CARD_NUMBER,
    CONF_SCAN_INTERVAL_HOURS,
    DEFAULT_SCAN_INTERVAL_HOURS,
    DOMAIN,
    MAX_SCAN_INTERVAL_HOURS,
    MIN_SCAN_INTERVAL_HOURS,
)

_LOGGER = logging.getLogger(__name__)

DEFAULT_NAME = "Münchner Stadtbibliothek"
PASSWORD_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


async def _validate(hass, card_number: str, password: str) -> str | None:
    """Try one login; returns an error key or None."""
    from . import create_client  # avoids a circular import

    try:
        await create_client(hass, card_number, password).async_fetch()
    except LibraryAuthError:
        return "invalid_auth"
    except LibraryConnectionError:
        return "cannot_connect"
    except LibraryError:
        _LOGGER.exception("Unexpected catalog page")
        return "unknown_page"
    return None


class LibraryConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add a library card."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            card = user_input[CONF_CARD_NUMBER].replace(" ", "")
            await self.async_set_unique_id(card)
            self._abort_if_unique_id_configured()
            error = await _validate(self.hass, card, user_input[CONF_PASSWORD])
            if error is None:
                return self.async_create_entry(
                    title=user_input[CONF_NAME].strip() or DEFAULT_NAME,
                    data={CONF_CARD_NUMBER: card, CONF_PASSWORD: user_input[CONF_PASSWORD]},
                )
            errors["base"] = error

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=DEFAULT_NAME): str,
                vol.Required(CONF_CARD_NUMBER): str,
                vol.Required(CONF_PASSWORD): PASSWORD_SELECTOR,
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, user_input or {}),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            error = await _validate(self.hass, entry.data[CONF_CARD_NUMBER], user_input[CONF_PASSWORD])
            if error is None:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )
            errors["base"] = error
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): PASSWORD_SELECTOR}),
            description_placeholders={"name": entry.title},
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        return LibraryOptionsFlow()


class LibraryOptionsFlow(OptionsFlow):
    """Update interval."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                data={CONF_SCAN_INTERVAL_HOURS: int(user_input[CONF_SCAN_INTERVAL_HOURS])}
            )
        current = self.config_entry.options.get(CONF_SCAN_INTERVAL_HOURS, DEFAULT_SCAN_INTERVAL_HOURS)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SCAN_INTERVAL_HOURS, default=current): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_SCAN_INTERVAL_HOURS,
                            max=MAX_SCAN_INTERVAL_HOURS,
                            step=1,
                            unit_of_measurement="h",
                            mode=NumberSelectorMode.BOX,
                        )
                    )
                }
            ),
        )
