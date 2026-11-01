"""Serve the card and register it as dashboard resource (like HACS does)."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import CARD_FILE, CARD_URL, COVER_DIR, FRONTEND_URL, VERSION

COVER_FILE = re.compile(r"^covers/(\d{13}\.(?:jpg|png|webp|gif))$")

_LOGGER = logging.getLogger(__name__)
FOLDER = Path(__file__).parent / "frontend"


class FrontendView(HomeAssistantView):
    """Serves the card.

    "Cache-Control: no-cache" makes browsers and the companion app check for a
    newer file on every load (a cheap 304 if unchanged), so updates show up
    after a normal reload instead of needing a cache reset.
    """

    url = FRONTEND_URL + "/{path:.+}"
    name = "muenchner_stadtbibliothek:frontend"
    requires_auth = False  # loaded by the browser as a module, like /local files

    def __init__(self, hass: HomeAssistant, files: dict[str, Path], cover_dir: Path) -> None:
        self._hass = hass
        self._files = files
        self._cover_dir = cover_dir

    async def get(self, request: web.Request, path: str) -> web.StreamResponse:
        # stored covers: file names are ISBNs, a cover never changes, so browsers may keep it
        cover = COVER_FILE.match(path)
        if cover:
            file = self._cover_dir / cover.group(1)
            if not await self._hass.async_add_executor_job(file.is_file):
                raise web.HTTPNotFound()
            return web.FileResponse(file, headers={"Cache-Control": "public, max-age=31536000, immutable"})
        file = self._files.get(path)
        if file is None:
            raise web.HTTPNotFound()
        return web.FileResponse(file, headers={"Cache-Control": "no-cache"})


def _list_files() -> dict[str, Path]:
    """Only these files are served (no directory access)."""
    return {CARD_FILE: FOLDER / CARD_FILE}


async def async_register_view(hass: HomeAssistant) -> None:
    files = await hass.async_add_executor_job(_list_files)
    hass.http.register_view(FrontendView(hass, files, Path(hass.config.path(".storage", COVER_DIR))))


def _resources(hass: HomeAssistant):
    """The dashboard resource collection, or None if dashboards run in YAML mode."""
    lovelace = hass.data.get("lovelace")
    if lovelace is None:
        return None
    if hasattr(lovelace, "resources"):  # HA 2025.2+
        resources = lovelace.resources
    elif isinstance(lovelace, dict):  # older versions
        resources = lovelace.get("resources")
    else:
        return None
    return resources if hasattr(resources, "async_create_item") else None


async def _async_loaded(resources) -> None:
    if not getattr(resources, "loaded", True):
        await resources.async_load()
        resources.loaded = True


def _is_card(item: dict) -> bool:
    return str(item.get("url") or "").split("?")[0] == CARD_URL


async def async_register_card(hass: HomeAssistant) -> None:
    """Add the card as dashboard resource, or update its ?v= after an update (like HACS does)."""
    url = f"{CARD_URL}?v={VERSION}"
    try:
        resources = _resources(hass)
        if resources is not None:
            await _async_loaded(resources)
            item = next((i for i in resources.async_items() if _is_card(i)), None)
            if item is None:
                await resources.async_create_item({"res_type": "module", "url": url})
                _LOGGER.info("Library card resource %s added", url)
            elif item["url"] != url:
                await resources.async_update_item(item["id"], {"res_type": "module", "url": url})
                _LOGGER.info("Library card resource updated to %s", url)
            return
    except Exception:  # noqa: BLE001 - never block the integration because of the resource
        _LOGGER.exception("Could not register the library card as dashboard resource")

    # Dashboards in YAML mode (or an error above): load the card on every page instead
    from homeassistant.components.frontend import add_extra_js_url

    add_extra_js_url(hass, url)
    _LOGGER.warning(
        "Dashboard resources are not in UI mode. Add '%s' as JavaScript module if the library card does not load",
        CARD_URL,
    )


async def async_remove_resource(hass: HomeAssistant) -> None:
    """Remove the dashboard resource (after the last library card was removed)."""
    try:
        resources = _resources(hass)
        if resources is None:
            return
        await _async_loaded(resources)
        for item in [i for i in resources.async_items() if _is_card(i)]:
            await resources.async_delete_item(item["id"])
    except Exception:  # noqa: BLE001
        _LOGGER.debug("Dashboard resource could not be removed", exc_info=True)
