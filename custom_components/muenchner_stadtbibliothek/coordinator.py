"""Data update coordinator: one catalog session per update."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    AccountData,
    LibraryAuthError,
    LibraryClient,
    LibraryError,
    LibraryRenewError,
)
from .const import CONF_SCAN_INTERVAL_HOURS, DEFAULT_SCAN_INTERVAL_HOURS, DOMAIN

_LOGGER = logging.getLogger(__name__)

type LibraryConfigEntry = ConfigEntry[LibraryCoordinator]


class LibraryCoordinator(DataUpdateCoordinator[AccountData]):
    """Fetches card validity and loans."""

    config_entry: LibraryConfigEntry

    def __init__(self, hass: HomeAssistant, entry: LibraryConfigEntry, client: LibraryClient) -> None:
        hours = entry.options.get(CONF_SCAN_INTERVAL_HOURS, DEFAULT_SCAN_INTERVAL_HOURS)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=timedelta(hours=hours),
        )
        self.client = client
        self._renewing: set[str] = set()  # barcodes with a renewal in progress

    async def _async_update_data(self) -> AccountData:
        try:
            return await self.client.async_fetch()
        except LibraryAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except LibraryError as err:
            raise UpdateFailed(str(err)) from err

    async def async_renew(self, barcode: str) -> None:
        """Renew one loan once; a second press while it runs (any card, any device) is rejected."""
        if barcode in self._renewing:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="renew_running")
        self._renewing.add(barcode)
        try:
            await self._async_renew(barcode)
        finally:
            self._renewing.discard(barcode)

    async def _async_renew(self, barcode: str) -> None:
        """Renew one loan and show the catalog's answer right away."""
        try:
            result = await self.client.async_renew(barcode)
        except LibraryAuthError as err:
            self.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="auth_failed"
            ) from err
        except LibraryRenewError as err:
            if err.account is not None:
                self._keep_card_validity(err.account)
                self.async_set_updated_data(err.account)
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="renew_failed",
                translation_placeholders={"reason": str(err)},
            ) from err
        except LibraryError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="connection_failed",
                translation_placeholders={"reason": str(err)},
            ) from err
        self._keep_card_validity(result.account)
        self.async_set_updated_data(result.account)

    def _keep_card_validity(self, account: AccountData) -> None:
        if account.card_valid_until is None and self.data is not None:
            account.card_valid_until = self.data.card_valid_until
