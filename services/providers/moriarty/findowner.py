"""Moriarty FindOwner — Truecaller name lookup via Google OAuth login.

Ported from Moriarty-Project/Investigation/FindOwner.py. The original wraps
the browser in pyvirtualdisplay.Display(), which wraps Xvfb — Linux-only, and
redundant here anyway since Playwright's headless mode needs no virtual X
server on any OS. Dropped.

Requires a Google account configured via MORIARTY_GOOGLE_EMAIL /
MORIARTY_GOOGLE_PASSWORD — use a disposable/burner account. Automating a
Google sign-in trips Google's anti-automation checks ("This browser or app
may not be secure") more often than not, especially for accounts with no
prior sign-in history; this can lock or challenge the account. Skipped
entirely when the credentials aren't configured. Selectors are copied from
the original project and are inherently brittle — Truecaller's/Google's
markup changes over time, so failures here are expected and degrade to an
error dict rather than raising.
"""
import asyncio
import logging

from shared.config import settings

log = logging.getLogger("providers.moriarty.findowner")

_lock = asyncio.Lock()


async def find_owner(phone_number: str) -> dict:
    if not settings.moriarty_google_email or not settings.moriarty_google_password:
        return {"error": "MORIARTY_GOOGLE_EMAIL / MORIARTY_GOOGLE_PASSWORD not configured"}

    async with _lock:
        try:
            return await asyncio.wait_for(_run(phone_number), timeout=90)
        except asyncio.TimeoutError:
            return {"error": "find_owner timed out after 90s"}
        except Exception as exc:  # noqa: BLE001
            log.warning("find_owner failed for %s: %s", phone_number, exc)
            return {"error": str(exc)}


async def _run(phone_number: str) -> dict:
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        # Automation-flag suppression helps (but does not guarantee) getting
        # past Google's "unsafe browser" heuristics.
        browser = await pw.firefox.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            )
        )
        page = await context.new_page()
        try:
            await page.goto("https://truecaller.com", timeout=30000)
            await page.locator("#app > main > header > div > form > input").fill(phone_number)
            await page.locator("#app > main > header > div > form > button").click()
            await page.locator("#app > main > div > div > a:nth-child(2)").click()
            login_note = await _google_login(
                page, settings.moriarty_google_email, settings.moriarty_google_password
            )
            name = await _read_name(page)
            result = {"name": name, "source": "truecaller"}
            if login_note:
                result["note"] = login_note
            return result
        finally:
            await browser.close()


async def _google_login(page, email: str, password: str) -> str | None:
    try:
        await page.locator("#identifierId").fill(email)
        await page.click("#identifierNext > div > button > span")
        await page.locator(
            "#password > div.aCsJod.oJeWuf > div > div.Xb9hP > input"
        ).fill(password, timeout=15000)
        await page.locator("#passwordNext > div > button > span").click()
        try:
            await page.click(
                "#submit_approve_access > div > button > div.VfPpkd-RLmnJb", timeout=5000
            )
        except Exception:  # noqa: BLE001
            await page.click(
                "#submit_approve_access > div:nth-child(1) > button:nth-child(1) > div:nth-child(1)",
                timeout=5000,
            )
        return None
    except Exception as exc:  # noqa: BLE001
        return f"google login step failed (stale selectors or Google blocked automated sign-in): {exc}"


async def _read_name(page) -> str:
    try:
        return (
            await page.text_content(
                "#app > main > div > div > div > div.rounded-xl.overflow-hidden.shadow > "
                "header > div:nth-child(1) > div.font-montserrat.text-lg.sm\\:text-2xl.flex-none",
                timeout=10000,
            )
            or "not found"
        )
    except Exception:  # noqa: BLE001
        try:
            text = await page.text_content(
                "#app > main > div > div > div > div.flex.items-center.gap-4.mb-4 > div > h3",
                timeout=5000,
            )
            if text and "Oops! Search limit exceeded." in text:
                return "search limit exceeded"
            return text or "not found"
        except Exception:  # noqa: BLE001
            return "not found"
