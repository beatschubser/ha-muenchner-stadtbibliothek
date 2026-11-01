"""Münchner Stadtbibliothek: library card and loans in Home Assistant."""

from __future__ import annotations

import aiohttp
from homeassistant.const import CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import LibraryClient
from .const import CONF_CARD_NUMBER
from .coordinator import LibraryConfigEntry, LibraryCoordinator

PLATFORMS = [Platform.SENSOR, Platform.BUTTON]


def create_client(hass: HomeAssistant, card_number: str, password: str) -> LibraryClient:
    """Client with its own cookie jar (the catalog session must not mix with others)."""
    session = async_create_clientsession(hass, cookie_jar=aiohttp.CookieJar())
    return LibraryClient(session, card_number, password)


async def async_setup_entry(hass: HomeAssistant, entry: LibraryConfigEntry) -> bool:
    """Set up one library card."""
    client = create_client(hass, entry.data[CONF_CARD_NUMBER], entry.data[CONF_PASSWORD])
    coordinator = LibraryCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass: HomeAssistant, entry: LibraryConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: LibraryConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
