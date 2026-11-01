"""One renew button per current loan (added and removed with the loans)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .coordinator import LibraryConfigEntry, LibraryCoordinator
from .entity import LibraryEntity
from .parser import Loan

KEY_PREFIX = "renew_"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LibraryConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    registry = er.async_get(hass)
    prefix = f"{entry.entry_id}_{KEY_PREFIX}"
    known: set[str] = set()

    @callback
    def _sync() -> None:
        current = {loan.barcode: loan for loan in coordinator.data.loans}
        new = [RenewButton(coordinator, loan) for code, loan in current.items() if code not in known]
        known.update(button.barcode for button in new)
        if new:
            async_add_entities(new)
        # returned items: remove their buttons from Home Assistant
        for reg_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
            if reg_entry.domain != "button" or not reg_entry.unique_id.startswith(prefix):
                continue
            barcode = reg_entry.unique_id.removeprefix(prefix)
            if barcode not in current:
                known.discard(barcode)
                registry.async_remove(reg_entry.entity_id)

    _sync()
    entry.async_on_unload(coordinator.async_add_listener(_sync))


class RenewButton(LibraryEntity, ButtonEntity):
    """Renews one loan."""

    _attr_translation_key = "renew"
    _unrecorded_attributes = frozenset({"title", "author", "full_title", "signature", "hint"})

    def __init__(self, coordinator: LibraryCoordinator, loan: Loan) -> None:
        super().__init__(coordinator, f"{KEY_PREFIX}{loan.barcode}")
        self.barcode = loan.barcode
        self._attr_translation_placeholders = {"title": loan.title}

    @property
    def _loan(self) -> Loan | None:
        return next((loan for loan in self.coordinator.data.loans if loan.barcode == self.barcode), None)

    @property
    def available(self) -> bool:
        return super().available and self._loan is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        loan = self._loan
        return loan.as_dict() if loan else None

    async def async_press(self) -> None:
        loan = self._loan
        if loan is None:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="loan_gone")
        if not loan.renewable:
            # no request to the catalog: it would only answer with the same hint
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="not_renewable",
                translation_placeholders={"title": loan.title, "hint": loan.hint or "-"},
            )
        await self.coordinator.async_renew(self.barcode)
