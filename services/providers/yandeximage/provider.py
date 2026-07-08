"""Yandex reverse image search provider — finds pages that contain a given image.

This was originally scoped for Google reverse image search, but Google's Lens
backend serves an immediate CAPTCHA ("unusual traffic") to headless automation
— verified live, and it persisted even with a headed browser plus basic
anti-detection JS (spoofed navigator.webdriver/plugins/chrome runtime). Yandex
runs the equivalent flow without that wall and is the OSINT community's
standard substitute for exactly this reason, so this provider targets Yandex
Images instead.

Drives a real (headless) Chromium via Playwright: uploads the image through
Yandex's own file input, waits for the results navigation, then reads the
"Sites" result set straight out of the page's embedded React hydration state
(``#ImagesApp-*[data-state]``) rather than scraping rendered DOM elements —
that JSON shape is far more stable across Yandex frontend redesigns than CSS
selectors/classes would be.
"""
import logging

from playwright.async_api import async_playwright

log = logging.getLogger("providers.yandeximage")

YANDEX_IMAGES_URL = "https://yandex.com/images/"
NAV_TIMEOUT_MS = 30_000
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Reads the SPA's own hydration state rather than the rendered DOM — the
# browser has already HTML-unescaped `dataset.state` for us, so this is a
# plain JSON.parse, no manual unescaping needed.
_STATE_JS = """
() => {
    const el = document.querySelector('[id^="ImagesApp-"]');
    if (!el) return null;
    return JSON.parse(el.dataset.state);
}
"""


async def reverse_image_search(
    image_bytes: bytes, top_n: int = 10, filename: str = "image.jpg", content_type: str = "image/jpeg"
) -> list[dict]:
    """Upload `image_bytes` to Yandex Images and return up to `top_n` source pages."""
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                state = await _run_search(browser, image_bytes, filename, content_type)
            finally:
                await browser.close()
    except Exception as exc:  # noqa: BLE001
        log.warning("yandex reverse image search failed: %s", exc)
        return []

    if not state:
        log.warning("could not find Yandex's hydration state in the results page")
        return []

    sites = state.get("initialState", {}).get("cbirSites", {}).get("sites", [])
    return [_normalize_site(s) for s in sites[:top_n]]


async def _run_search(browser, image_bytes: bytes, filename: str, content_type: str) -> dict | None:
    page = await browser.new_page(user_agent=USER_AGENT, viewport={"width": 1280, "height": 800})
    await page.goto(YANDEX_IMAGES_URL, wait_until="networkidle", timeout=NAV_TIMEOUT_MS)

    async with page.expect_navigation(timeout=NAV_TIMEOUT_MS):
        await page.locator("input[type=file]").set_input_files(
            {"name": filename, "mimeType": content_type, "buffer": image_bytes}
        )
    await page.wait_for_load_state("networkidle", timeout=NAV_TIMEOUT_MS)

    return await page.evaluate(_STATE_JS)


def _normalize_site(site: dict) -> dict:
    thumb = site.get("thumb") or {}
    thumb_url = thumb.get("url")
    if thumb_url and thumb_url.startswith("//"):
        thumb_url = f"https:{thumb_url}"
    return {
        "title": site.get("title"),
        "url": site.get("url"),
        "domain": site.get("domain"),
        "description": (site.get("description") or "").strip() or None,
        "thumbnail_url": thumb_url,
    }
