"""Data update coordinator: one catalog session per update."""

from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import LibraryAuthError, LibraryClient, LibraryError, LibraryRenewError
from .const import (
    COVER_DIR,
    COVER_URL_PATH,
    CONF_LOOKUP_COVERS,
    CONF_SCAN_INTERVAL_HOURS,
    DEFAULT_LOOKUP_COVERS,
    DEFAULT_SCAN_INTERVAL_HOURS,
    DOMAIN,
    LOOKUP_STORE_KEY,
)
from .models import AccountData

STORAGE_VERSION = 1
IMAGE_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif"}

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
        self._lookup_covers = entry.options.get(CONF_LOOKUP_COVERS, DEFAULT_LOOKUP_COVERS)
        # cover lookups: barcode -> {"isbn": str | None, "file": cover file name | None}. Kept for good
        # (also for returned items, so a book borrowed again needs no new search); every item is searched once.
        self._lookup_store: Store[dict[str, dict]] = Store(
            hass, STORAGE_VERSION, LOOKUP_STORE_KEY.format(entry_id=entry.entry_id)
        )
        self._lookups: dict[str, dict] = {}
        self._cover_dir = Path(hass.config.path(".storage", COVER_DIR))

    async def async_load_lookups(self) -> None:
        """Load the stored cover lookups (before the first update)."""
        stored = await self._lookup_store.async_load() or {}
        self._lookups = {code: value for code, value in stored.items() if isinstance(value, dict)}

    async def _async_update_data(self) -> AccountData:
        try:
            account = await self.client.async_fetch(set(self._lookups) if self._lookup_covers else None)
        except LibraryAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except LibraryError as err:
            raise UpdateFailed(str(err)) from err
        if account.looked_up:
            for code, result in account.looked_up.items():
                file = await self._save_cover(result.isbn, result.cover, result.content_type)
                self._lookups[code] = {"isbn": result.isbn, "file": file}
            self._lookup_store.async_delay_save(lambda: self._lookups, 5)
        self._apply_lookups(account)
        return account

    async def _save_cover(self, isbn: str | None, image: bytes | None, content_type: str | None) -> str | None:
        """Store a cover image once (by ISBN); returns its file name."""
        ext = IMAGE_TYPES.get(content_type or "")
        if not isbn or not image or not ext:
            return None
        name = f"{isbn}.{ext}"

        def _write() -> None:
            self._cover_dir.mkdir(parents=True, exist_ok=True)
            (self._cover_dir / name).write_bytes(image)

        await self.hass.async_add_executor_job(_write)
        return name

    def _apply_lookups(self, account: AccountData) -> None:
        """Add ISBN and local cover URL of the stored lookups to the loans."""
        if not self._lookup_covers:
            return
        for loan in account.loans:
            known = self._lookups.get(loan.barcode) or {}
            loan.isbn = loan.isbn or known.get("isbn")
            loan.cover_url = COVER_URL_PATH.format(file=known["file"]) if known.get("file") else None

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
                self._apply_lookups(err.account)
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
        self._apply_lookups(result.account)
        self.async_set_updated_data(result.account)

    def _keep_card_validity(self, account: AccountData) -> None:
        if account.card_valid_until is None and self.data is not None:
            account.card_valid_until = self.data.card_valid_until
