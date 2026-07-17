"""Holehe provider — email registration checks across many sites.

holehe (holehe/) isn't a pip package here — it's a local clone imported
in-process, same approach as the moriarty provider. Its site-checkers are
trio coroutines built around a shared ``httpx.AsyncClient``, not a CLI, so
unlike maigret this can't be shelled out to; instead ``core.import_submodules``
discovers every ``holehe.modules.*`` checker and runs them concurrently in a
trio nursery on a background thread.

holehe's own ``launch_module`` already catches per-module exceptions and
degrades them to a safe ``{"exists": False, "error": True, ...}`` dict, so one
flaky/changed site can't take down the whole scan. ``PER_SITE_TIMEOUT`` bounds
each site's HTTP calls; ``SCAN_TIMEOUT`` is a wall-clock backstop for the scan
as a whole (mirrors the hardcoded subprocess timeout in the maigret provider).

Only sites where the email is found to exist are returned — of ~120+ modules,
the overwhelming majority report "not used" and are noise for a caller that
wants "where is this email registered", not a full negative-result dump.
Holehe's output doesn't fit the shared Account schema well (most fields would
be null — there's no username/bio/avatar, just an existence check), so hits
are normalized to a small purpose-built dict instead.
"""
import asyncio
import logging
import sys
from pathlib import Path

from shared.config import settings

log = logging.getLogger("providers.holehe")

_HOLEHE_ROOT = Path(settings.holehe_project_path or Path(__file__).resolve().parents[3] / "external" / "holehe")

PER_SITE_TIMEOUT = 10   # seconds, per HTTP call (httpx client timeout)
SCAN_TIMEOUT = 60       # seconds, wall-clock cap for the whole scan


def _ensure_on_path() -> bool:
    if not (_HOLEHE_ROOT / "holehe" / "core.py").is_file():
        return False
    root = str(_HOLEHE_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    return True


async def check_email(email: str) -> list[dict]:
    """Run every holehe site-checker module against `email`, raw results."""
    if not _ensure_on_path():
        log.warning("holehe clone not found at %s — skipping.", _HOLEHE_ROOT)
        return []
    return await asyncio.to_thread(_check_email_sync, email)


def _check_email_sync(email: str) -> list[dict]:
    import httpx
    import trio

    from holehe.core import get_functions, import_submodules, launch_module

    out: list[dict] = []

    async def _run() -> None:
        modules = import_submodules("holehe.modules")
        websites = get_functions(modules)
        async with httpx.AsyncClient(timeout=PER_SITE_TIMEOUT) as client:
            with trio.move_on_after(SCAN_TIMEOUT):
                async with trio.open_nursery() as nursery:
                    for website in websites:
                        nursery.start_soon(launch_module, website, email, client, out)

    trio.run(_run)
    return out


# --------------------------------------------------------------------------
# Normalization — raw holehe finding → slim result dict
# --------------------------------------------------------------------------
def normalize_holehe_result(raw: dict, email: str) -> dict:
    """Convert a holehe finding (a site the email is registered on) to a lean dict.

    ``method`` and ``frequent_rate_limit`` are surfaced because they signal
    confidence: some sites' checks are self-flagged by holehe as prone to
    false positives when silently rate-limited (~1 in 4 modules), and
    "password recovery"-method checks are generally noisier than "register"/
    "login" ones.
    """
    return {
        "platform": raw.get("domain") or raw["name"],
        "email": email,
        "exists": True,
        "method": raw.get("method"),
        "frequent_rate_limit": raw.get("frequent_rate_limit", False),
        "email_recovery": raw.get("emailrecovery"),
        "phone_number": raw.get("phoneNumber"),
        "other_data": raw.get("others"),
    }


async def search(email: str) -> list[dict]:
    """High-level entry point: scan + filter to hits + normalize."""
    raw_results = await check_email(email)
    hits = [r for r in raw_results if r.get("exists")]
    return [normalize_holehe_result(r, email) for r in hits]
