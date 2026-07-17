"""Google Maps contributions scraper — the actual reviews/ratings, not just counts.

GHunt's own Maps helper (and the provider's ``maps-reviews`` route) can only
return aggregate counts: Google stripped the individual items out of the
``locationhistory/preview/mas`` endpoint it used, which is why upstream
commented that parsing out. The individual contributions *are* still public,
though — they render on the contributor page
``https://www.google.com/maps/contrib/<gaia_id>/reviews`` to any visitor, no
login. This module drives a headless Chromium (Playwright, same as the
yandeximage provider) over that page and reads them out of the rendered DOM.

Unlike everything else in the ghunt provider this needs **no GHunt session** —
it's a plain public-page scrape keyed on a Gaia ID. The trade-off is fragility:
it depends on Google Maps' CSS class names (`.jftiEf` cards, `.d4r55` place,
`.kvMYJc` stars, `.wiI7pd` text, `.CDe7pd` owner-response), which Google
reshuffles periodically — expect this to need selector upkeep, and it degrades
to an empty result (never raises) when the layout shifts or the browser is
absent.
"""
import logging

from playwright.async_api import async_playwright

log = logging.getLogger("providers.ghunt.maps")

NAV_TIMEOUT_MS = 45_000
SCROLL_TIMEOUT_MS = 60_000  # wall-clock cap on lazy-load scrolling
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Pulls each review/rating card out of the rendered feed. The owner's reply and
# the user's own review both use `.wiI7pd`, so the review text is the one NOT
# inside an owner-response block (`.CDe7pd`); the reply is captured separately.
_EXTRACT_JS = """
() => {
    const parseStars = (al) => {
        if (!al) return null;
        const m = al.match(/(\\d+)\\s*star/i);
        return m ? parseInt(m[1], 10) : null;
    };
    return Array.from(document.querySelectorAll('.jftiEf')).map(c => {
        const reviewEl = Array.from(c.querySelectorAll('.wiI7pd'))
            .find(e => !e.closest('.CDe7pd')) || null;
        const ownerEl = c.querySelector('.CDe7pd .wiI7pd');
        const starEl = c.querySelector("[aria-label*='star']");
        return {
            review_id: c.getAttribute('data-review-id'),
            place: c.querySelector('.d4r55')?.innerText?.trim() || null,
            address: c.querySelector('.RfnDt')?.innerText?.trim() || null,
            rating: parseStars(starEl ? starEl.getAttribute('aria-label') : null),
            date: c.querySelector('.rsqaWe')?.innerText?.trim() || null,
            review_text: reviewEl?.innerText?.trim() || null,
            owner_response: ownerEl?.innerText?.trim() || null,
        };
    });
}
"""


async def scrape_contributions(gaia_id: str, max_items: int = 50) -> list[dict]:
    """Return up to `max_items` public Maps contributions for a Gaia ID.

    Empty list on any failure (browser missing, page/layout change, private or
    non-existent profile) — the caller degrades gracefully.
    """
    url = f"https://www.google.com/maps/contrib/{gaia_id}/reviews?hl=en"
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                return await _run(browser, url, max_items)
            finally:
                await browser.close()
    except Exception as exc:  # noqa: BLE001
        log.warning("maps contributions scrape failed for %s: %s", gaia_id, exc)
        return []


async def _run(browser, url: str, max_items: int) -> list[dict]:
    page = await browser.new_page(user_agent=USER_AGENT, viewport={"width": 1280, "height": 900})
    await page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)

    cards = page.locator(".jftiEf")
    try:
        await cards.first.wait_for(timeout=NAV_TIMEOUT_MS)
    except Exception:
        # No cards ever appeared: empty/private/non-existent contributor profile.
        log.info("no contribution cards rendered for %s", url)
        return []

    await _scroll_to_load(page, cards, max_items)

    # Expand truncated review bodies ("More" buttons) best-effort before reading.
    try:
        more = page.locator("button.w8nwRe.kyuRq")
        for i in range(await more.count()):
            try:
                await more.nth(i).click(timeout=500)
            except Exception:
                pass
    except Exception:
        pass

    items = await page.evaluate(_EXTRACT_JS)
    return items[:max_items]


async def _scroll_to_load(page, cards, max_items: int) -> None:
    """Scroll the feed until it stops growing, hits `max_items`, or times out.

    Contributions lazy-load as the panel scrolls; scrolling the last card into
    view and re-counting is more robust than guessing the scroll container's
    selector.
    """
    import time

    deadline = time.monotonic() + SCROLL_TIMEOUT_MS / 1000
    prev = -1
    stable = 0
    while time.monotonic() < deadline:
        count = await cards.count()
        if count >= max_items:
            break
        if count == prev:
            stable += 1
            if stable >= 2:  # two quiet rounds → feed is exhausted
                break
        else:
            stable = 0
        prev = count
        try:
            await cards.nth(count - 1).scroll_into_view_if_needed(timeout=3000)
        except Exception:
            break
        await page.wait_for_timeout(1200)
