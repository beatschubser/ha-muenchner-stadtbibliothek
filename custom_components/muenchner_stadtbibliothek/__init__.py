"""Münchner Stadtbibliothek: library card and loans in Home Assistant.

- async_setup (once): serve the dashboard card and add it as dashboard resource.
- async_setup_entry (per library card): coordinator, sensors, renew buttons.
"""

from __future__ import annotations

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType

from . import frontend_resource
from .api import LibraryClient
from .const import CONF_CARD_NUMBER, DOMAIN, LOOKUP_STORE_KEY
from .coordinator import STORAGE_VERSION, LibraryConfigEntry, LibraryCoordinator

PLATFORMS = [Platform.SENSOR, Platform.BUTTON]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


def create_client(hass: HomeAssistant, card_number: str, password: str) -> LibraryClient:
    """Client with its own HTTP session and cookie jar (the catalog session must not mix with others).

    The caller closes it with client.async_close() when it is no longer needed.
    """
    session = async_create_clientsession(hass, cookie_jar=aiohttp.CookieJar())
    return LibraryClient(session, card_number, password)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Serve the card once for all library cards."""
    if hass.http is not None:
        await frontend_resource.async_register_view(hass)
        async_at_started(hass, frontend_resource.async_register_card)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: LibraryConfigEntry) -> bool:
    """Set up one library card."""
    client = create_client(hass, entry.data[CONF_CARD_NUMBER], entry.data[CONF_PASSWORD])
    coordinator = LibraryCoordinator(hass, entry, client)
    await coordinator.async_load_lookups()
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass: HomeAssistant, entry: LibraryConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: LibraryConfigEntry) -> bool:
    """Unload a config entry and close its HTTP session."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.client.async_close()
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove the stored cover lookups; after the last library card also the dashboard resource."""
    await Store(hass, STORAGE_VERSION, LOOKUP_STORE_KEY.format(entry_id=entry.entry_id)).async_remove()
    if not any(e.entry_id != entry.entry_id for e in hass.config_entries.async_entries(DOMAIN)):
        await frontend_resource.async_remove_resource(hass)
