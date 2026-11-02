"""Sensors: card validity, loans (with full list), next due date."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import LibraryConfigEntry, LibraryCoordinator
from .entity import LibraryEntity
from .models import AccountData


def _next_due(data: AccountData) -> date | None:
    dates = [loan.due_date for loan in data.loans if loan.due_date]
    return min(dates) if dates else None


def _loans_attributes(data: AccountData) -> dict[str, Any]:
    return {
        "loans": [loan.as_dict() for loan in sorted(data.loans, key=lambda l: (l.due_date or date.max, l.title))],
        "renewable_count": sum(1 for loan in data.loans if loan.renewable),
        "fetched_at": data.fetched_at.isoformat(timespec="seconds"),
    }


def _next_due_attributes(data: AccountData) -> dict[str, Any]:
    due = _next_due(data)
    items = [loan for loan in data.loans if due and loan.due_date == due]
    return {
        "count": len(items),
        "titles": [loan.title for loan in items],
    }


@dataclass(frozen=True, kw_only=True)
class LibrarySensorDescription(SensorEntityDescription):
    """Sensor with value and attribute functions."""

    value_fn: Callable[[AccountData], Any]
    attributes_fn: Callable[[AccountData], dict[str, Any]] | None = None


SENSORS: tuple[LibrarySensorDescription, ...] = (
    LibrarySensorDescription(
        key="card_valid_until",
        translation_key="card_valid_until",
        device_class=SensorDeviceClass.DATE,
        value_fn=lambda data: data.card_valid_until,
    ),
    LibrarySensorDescription(
        key="loans",
        translation_key="loans",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: len(data.loans),
        attributes_fn=_loans_attributes,
    ),
    LibrarySensorDescription(
        key="next_due_date",
        translation_key="next_due_date",
        device_class=SensorDeviceClass.DATE,
        value_fn=_next_due,
        attributes_fn=_next_due_attributes,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LibraryConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(LibrarySensor(coordinator, description) for description in SENSORS)


class LibrarySensor(LibraryEntity, SensorEntity):
    """One value of the account."""

    entity_description: LibrarySensorDescription
    _unrecorded_attributes = frozenset({"loans", "titles", "fetched_at"})

    def __init__(self, coordinator: LibraryCoordinator, description: LibrarySensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attributes_fn is None:
            return None
        return self.entity_description.attributes_fn(self.coordinator.data)
