"""Diagnostics for bug reports (card number and password removed)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD
from homeassistant.core import HomeAssistant

from .const import CONF_CARD_NUMBER, VERSION
from .coordinator import LibraryConfigEntry

TO_REDACT = {CONF_CARD_NUMBER, CONF_PASSWORD, "unique_id", "title"}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: LibraryConfigEntry) -> dict[str, Any]:
    coordinator = entry.runtime_data
    data = coordinator.data
    return {
        "version": VERSION,
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "last_update_success": coordinator.last_update_success,
        "card_valid_until": data.card_valid_until.isoformat() if data and data.card_valid_until else None,
        "loans": [
            {key: value for key, value in loan.as_dict().items() if key in ("due_date", "library", "hint", "renewable", "renewals")}
            for loan in (data.loans if data else [])
        ],
    }
