#!/usr/bin/env python3
"""Render the README device mockup from assets/raw/ screenshots.

Requires Playwright with Chromium. Run: python3 scripts/render_mockups.py
assets/mockups/mockups.html holds one element per image (id = file name).
Covers in raw screenshots must be pixelated (publisher artwork).
"""

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

ASSETS = Path(__file__).resolve().parent.parent / "assets"
IMAGES = ["tablet-card"]


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1200, "height": 1400}, device_scale_factor=1.25)
        await page.goto((ASSETS / "mockups" / "mockups.html").as_uri())
        await page.wait_for_load_state("networkidle")
        for name in IMAGES:
            await page.locator(f"#{name}").screenshot(path=str(ASSETS / f"{name}.png"))
            print(f"assets/{name}.png")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
