"""Home Assistant tests with the fake catalog (tests/fake_adis.py).

Needs pytest-homeassistant-custom-component (runs in GitHub Actions).
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_NAME, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.muenchner_stadtbibliothek.api import LibraryClient
from custom_components.muenchner_stadtbibliothek.const import CONF_CARD_NUMBER, DOMAIN

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fake_adis import CARD, PASSWORD, FakeAdis, FakeSession  # noqa: E402


@pytest.fixture
def fake():
    """Fake catalog; every client created by the integration talks to it."""
    catalog = FakeAdis()

    def _create(hass, card_number, password):
        return LibraryClient(FakeSession(catalog), card_number, password, "https://catalog.test")

    with patch("custom_components.muenchner_stadtbibliothek.create_client", side_effect=_create):
        yield catalog


async def _setup(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Testausweis",
        unique_id=CARD,
        data={CONF_CARD_NUMBER: CARD, CONF_PASSWORD: PASSWORD},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _button_ids(hass: HomeAssistant, entry) -> dict[str, str]:
    registry = er.async_get(hass)
    return {
        e.unique_id.rsplit("_", 1)[-1]: e.entity_id
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        if e.domain == "button"
    }


async def test_config_flow(hass: HomeAssistant, fake) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NAME: "Testausweis", CONF_CARD_NUMBER: CARD, CONF_PASSWORD: "wrong"}
    )
    assert result["errors"] == {"base": "invalid_auth"}

    with patch("custom_components.muenchner_stadtbibliothek.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_NAME: "Testausweis", CONF_CARD_NUMBER: CARD, CONF_PASSWORD: PASSWORD}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Testausweis"
    assert result["data"] == {CONF_CARD_NUMBER: CARD, CONF_PASSWORD: PASSWORD}


async def test_sensors_and_buttons(hass: HomeAssistant, fake) -> None:
    entry = await _setup(hass)
    registry = er.async_get(hass)
    ids = {e.unique_id.removeprefix(entry.entry_id + "_"): e.entity_id for e in er.async_entries_for_config_entry(registry, entry.entry_id)}

    assert hass.states.get(ids["card_valid_until"]).state == "2030-12-31"
    assert hass.states.get(ids["next_due_date"]).state == "2030-03-16"
    loans = hass.states.get(ids["loans"])
    assert loans.state == "3"
    assert loans.attributes["renewable"] == 2
    assert loans.attributes["card_valid_until"] == "2030-12-31"
    assert loans.attributes["loans"][0]["title"] == "Der kleine Testdrache"
    # cover lookup: unique hit for the first item, none for the others; every item searched once
    first = loans.attributes["loans"][0]
    assert first["isbn"] == "9783000000002"
    assert first["cover_url"] == "/muenchner_stadtbibliothek_files/covers/9783000000002.jpg"
    assert loans.attributes["loans"][1]["cover_url"] is None
    assert len(fake.searches) == 3 and len(fake.cover_requests) == 1
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert len(fake.searches) == 3 and len(fake.cover_requests) == 1, "known items are not searched again"

    buttons = _button_ids(hass, entry)
    assert len(buttons) == 3
    state = hass.states.get(buttons["00000100000001"])
    assert state.attributes["due_date"] == "2030-03-16"
    assert state.attributes["renewable"] is True


async def test_renew(hass: HomeAssistant, fake) -> None:
    entry = await _setup(hass)
    buttons = _button_ids(hass, entry)

    await hass.services.async_call("button", "press", {"entity_id": buttons["00000100000002"]}, blocking=True)
    state = hass.states.get(buttons["00000100000002"])
    assert state.attributes["due_date"] == "2030-03-30"
    assert state.attributes["renewable"] is False
    assert state.attributes["renewed_today"] is True
    assert fake.renew_posts == 1

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call("button", "press", {"entity_id": buttons["00000100000003"]}, blocking=True)
    assert fake.renew_posts == 1, "a loan that is not renewable must not be sent to the catalog"


async def test_second_press_while_renewing_is_rejected(hass: HomeAssistant, fake) -> None:
    entry = await _setup(hass)
    coordinator = entry.runtime_data
    coordinator._renewing.add("00000100000002")
    with pytest.raises(HomeAssistantError):
        await coordinator.async_renew("00000100000002")
    assert fake.renew_posts == 0


async def test_returned_loan_removes_button(hass: HomeAssistant, fake) -> None:
    entry = await _setup(hass)
    fake.loans.pop(0)
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    buttons = _button_ids(hass, entry)
    assert set(buttons) == {"00000100000002", "00000100000003"}


async def test_card_is_served(hass: HomeAssistant, hass_client, fake) -> None:
    entry = await _setup(hass)
    await hass.async_add_executor_job(lambda: None)
    assert entry.runtime_data.data.loans[0].cover_url
    client = await hass_client()
    response = await client.get("/muenchner_stadtbibliothek_files/muenchner-stadtbibliothek-card.js")
    assert response.status == 200
    assert "muenchner-stadtbibliothek-card" in await response.text()
    response = await client.get("/muenchner_stadtbibliothek_files/manifest.json")
    assert response.status == 404
    # the stored cover is served by Home Assistant
    response = await client.get("/muenchner_stadtbibliothek_files/covers/9783000000002.jpg")
    assert response.status == 200
    assert (await response.read()).startswith(b"\xff\xd8")
    response = await client.get("/muenchner_stadtbibliothek_files/covers/9783000000019.jpg")
    assert response.status == 404


async def test_cover_lookup_can_be_switched_off(hass: HomeAssistant, fake) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Testausweis",
        unique_id=CARD,
        data={CONF_CARD_NUMBER: CARD, CONF_PASSWORD: PASSWORD},
        options={"lookup_covers": False},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert fake.searches == []


async def test_wrong_password_starts_reauth(hass: HomeAssistant, fake) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, title="Testausweis", unique_id=CARD, data={CONF_CARD_NUMBER: CARD, CONF_PASSWORD: "old"}
    )
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    flows = hass.config_entries.flow.async_progress()
    assert any(flow["context"]["source"] == "reauth" for flow in flows)
