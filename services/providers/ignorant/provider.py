"""Ignorant provider — phone-number registration checks across several sites.

ignorant (external/ignorant/) is holehe's sibling from the same author, for
phone numbers instead of emails, and shares holehe's architecture exactly: its
site-checkers are trio coroutines built around a shared ``httpx.AsyncClient``,
discovered via ``core.import_submodules`` and run concurrently in a trio
nursery. So this provider is the holehe provider with two differences — it
splits the number into ``country_code`` + national ``phone`` (what ignorant's
checkers expect), and the raw dicts use ignorant's ``rateLimit`` key. It's
imported in-process from the local clone, not pip-installed (same reasoning as
holehe/moriarty), and runs on a background thread because trio can't share the
provider's asyncio loop.

ignorant currently ships only a handful of checkers (amazon, instagram,
snapchat), and each already degrades a failed/blocked check to a safe
``{"rateLimit": True, "exists": False}`` dict, so one flaky site can't take
down the scan. ``PER_SITE_TIMEOUT`` bounds each site's HTTP calls;
``SCAN_TIMEOUT`` is a wall-clock backstop for the scan as a whole.

Only sites where the number is found to be registered are returned — a caller
wants "where is this number used", not a full negative-result dump. The result
shape mirrors the holehe provider's (a lean purpose-built dict, not the
Account schema — there's no username/bio/avatar, just an existence check).
"""
import asyncio
import logging
import sys
from pathlib import Path

import phonenumbers

from shared.config import settings

log = logging.getLogger("providers.ignorant")

_IGNORANT_ROOT = Path(
    settings.ignorant_project_path
    or Path(__file__).resolve().parents[3] / "external" / "ignorant"
)

PER_SITE_TIMEOUT = 10   # seconds, per HTTP call (httpx client timeout)
SCAN_TIMEOUT = 60       # seconds, wall-clock cap for the whole scan


def _ensure_on_path() -> bool:
    if not (_IGNORANT_ROOT / "ignorant" / "core.py").is_file():
        return False
    root = str(_IGNORANT_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    return True


def split_number(phone: str, country_code: str | None) -> tuple[str, str] | None:
    """Return (country_code, national_number) as digit-only strings.

    ignorant's checkers take the country calling code and the national number
    separately. If the caller already split them we trust that; otherwise we
    parse a full international number (``+919876543210``) with phonenumbers.
    Returns None if the number can't be resolved into both parts.
    """
    if country_code:
        cc = country_code.lstrip("+").strip()
        national = "".join(ch for ch in phone if ch.isdigit())
        if cc and national:
            return cc, national
        return None
    try:
        parsed = phonenumbers.parse(phone if phone.strip().startswith("+") else "+" + phone.strip(), None)
    except phonenumbers.NumberParseException:
        return None
    if not parsed.country_code or not parsed.national_number:
        return None
    return str(parsed.country_code), str(parsed.national_number)


async def check_phone(country_code: str, phone: str) -> list[dict]:
    """Run every ignorant site-checker against the number; raw results."""
    if not _ensure_on_path():
        log.warning("ignorant clone not found at %s — skipping.", _IGNORANT_ROOT)
        return []
    return await asyncio.to_thread(_check_phone_sync, country_code, phone)


def _check_phone_sync(country_code: str, phone: str) -> list[dict]:
    import httpx
    import trio

    from ignorant.core import get_functions, import_submodules, launch_module

    out: list[dict] = []

    async def _run() -> None:
        modules = import_submodules("ignorant.modules")
        websites = get_functions(modules)
        async with httpx.AsyncClient(timeout=PER_SITE_TIMEOUT) as client:
            with trio.move_on_after(SCAN_TIMEOUT):
                async with trio.open_nursery() as nursery:
                    for website in websites:
                        nursery.start_soon(launch_module, website, phone, country_code, client, out)

    trio.run(_run)
    return out


# --------------------------------------------------------------------------
# Normalization — raw ignorant finding → slim result dict
# --------------------------------------------------------------------------
def normalize_ignorant_result(raw: dict, country_code: str, phone: str) -> dict:
    """Convert an ignorant finding (a site the number is registered on) to a lean dict.

    Mirrors the holehe provider's result shape. ``method``/``frequent_rate_limit``
    are surfaced as a confidence signal (some checks are self-flagged as prone
    to false positives when silently rate-limited).
    """
    return {
        "platform": raw.get("domain") or raw["name"],
        "phone": f"+{country_code}{phone}",
        "country_code": country_code,
        "exists": True,
        "method": raw.get("method"),
        "frequent_rate_limit": raw.get("frequent_rate_limit", False),
        "rate_limited": raw.get("rateLimit", False),
    }


async def search(phone: str, country_code: str | None = None) -> list[dict]:
    """High-level entry point: parse number + scan + filter to hits + normalize."""
    parts = split_number(phone, country_code)
    if parts is None:
        log.warning("could not resolve phone/country_code from %r / %r", phone, country_code)
        return []
    cc, national = parts
    raw_results = await check_phone(cc, national)
    hits = [r for r in raw_results if r.get("exists")]
    return [normalize_ignorant_result(r, cc, national) for r in hits]
