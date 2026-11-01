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

from .api import (
    AccountData,
    LibraryAuthError,
    LibraryClient,
    LibraryError,
    LibraryRenewError,
)
from .const import (
    COVER_DIR,
    COVER_URL_PATH,
    CONF_LOOKUP_COVERS,
    CONF_SCAN_INTERVAL_HOURS,
    DEFAULT_LOOKUP_COVERS,
    DEFAULT_SCAN_INTERVAL_HOURS,
    DOMAIN,
)

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
        # barcode -> {"isbn": str | None, "file": cover file name | None}; kept for good (also for returned
        # items, so a book borrowed again needs no new search); every item is searched once
        self._isbn_store: Store[dict[str, dict]] = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}.isbn")
        self._isbns: dict[str, dict] = {}
        self._cover_dir = Path(hass.config.path(".storage", COVER_DIR))

    async def async_load_isbns(self) -> None:
        """Load the stored lookup results (before the first update)."""
        stored = await self._isbn_store.async_load() or {}
        # 0.5.0 stored only the ISBN (no cover file): search those items once more to get the cover
        self._isbns = {code: value for code, value in stored.items() if isinstance(value, dict) or value is None}
        self._isbns = {code: value or {"isbn": None, "file": None} for code, value in self._isbns.items()}

    async def _async_update_data(self) -> AccountData:
        try:
            account = await self.client.async_fetch(set(self._isbns) if self._lookup_covers else None)
        except LibraryAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except LibraryError as err:
            raise UpdateFailed(str(err)) from err
        if account.looked_up:
            for code, result in account.looked_up.items():
                file = await self._save_cover(result.isbn, result.cover, result.content_type)
                self._isbns[code] = {"isbn": result.isbn, "file": file}
            self._isbn_store.async_delay_save(lambda: self._isbns, 5)
        self._apply_isbns(account)
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

    def _apply_isbns(self, account: AccountData) -> None:
        if not self._lookup_covers:
            return
        for loan in account.loans:
            known = self._isbns.get(loan.barcode) or {}
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
                self._apply_isbns(err.account)
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
        self._apply_isbns(result.account)
        self.async_set_updated_data(result.account)

    def _keep_card_validity(self, account: AccountData) -> None:
        if account.card_valid_until is None and self.data is not None:
            account.card_valid_until = self.data.card_valid_until
