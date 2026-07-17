"""WhatsMyName provider — username enumeration from a JSON detection dataset.

WhatsMyName (external/WhatsMyName/) isn't a tool we shell out to — it's a
community-curated JSON file (``wmn-data.json``) of detection rules for ~700
sites. Each entry gives a profile-URL template plus what an "account exists"
vs. "account missing" response looks like (status code + body substring), so
the whole check is just: fill in the username, fetch each URL, and compare the
response against the rule. That's the same job maigret does, but self-contained
here (no external CLI, no separate install) — so the results are normalized to
the same ``Account`` schema the maigret provider returns.

Detection follows the dataset's own semantics (mirrors the reference checker in
wmn.md): a hit needs the status code to equal ``e_code`` AND the "exists"
substring ``e_string`` to be present AND the "missing" substring ``m_string``
to be absent — the last of these is what filters out sites that return 200 with
a "user not found" page. Checks run concurrently under a bounded semaphore
against a shared ``httpx.AsyncClient``; per-site failures are swallowed so one
dead/blocked site can't sink the scan, and ``SCAN_TIMEOUT`` is a wall-clock cap
for the run as a whole. Degrades to an empty result set if the dataset clone
isn't present.
"""
import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import httpx

from shared.config import settings
from shared.evidence import entity_hash
from shared.schemas import Account

log = logging.getLogger("providers.whatsmyname")

_WMN_ROOT = Path(
    settings.whatsmyname_project_path
    or Path(__file__).resolve().parents[3] / "external" / "WhatsMyName"
)
_WMN_DATA = _WMN_ROOT / "wmn-data.json"

PER_SITE_TIMEOUT = 10   # seconds, per HTTP request
SCAN_TIMEOUT = 90       # seconds, wall-clock cap for the whole scan
CONCURRENCY = 50        # simultaneous in-flight requests

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# The dataset is a few hundred KB and never changes at runtime — load it once.
_sites_cache: list[dict] | None = None


def _load_sites() -> list[dict]:
    """Load and cache the WhatsMyName site list, or [] if the clone is absent."""
    global _sites_cache
    if _sites_cache is not None:
        return _sites_cache
    if not _WMN_DATA.is_file():
        log.warning("WhatsMyName dataset not found at %s — skipping.", _WMN_DATA)
        _sites_cache = []
        return _sites_cache
    try:
        with open(_WMN_DATA, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        log.error("could not read WhatsMyName dataset %s: %s", _WMN_DATA, exc)
        _sites_cache = []
        return _sites_cache
    # Entries can be flagged invalid; the field is usually absent (= valid).
    _sites_cache = [s for s in data.get("sites", []) if s.get("valid", True) and s.get("uri_check")]
    return _sites_cache


def _is_hit(site: dict, status_code: int, body: str) -> bool:
    """Apply the dataset's exists/missing rule to one response."""
    if status_code != site.get("e_code", 200):
        return False
    body_lower = body.lower()
    e_string = site.get("e_string") or ""
    if e_string and e_string.lower() not in body_lower:
        return False
    # If the "missing" marker is present, it's a false positive regardless of code.
    m_string = site.get("m_string") or ""
    if m_string and m_string.lower() in body_lower:
        return False
    return True


async def _check_site(
    client: httpx.AsyncClient, sem: asyncio.Semaphore, site: dict, username: str, out: list[dict]
) -> None:
    """Check a single site, appending a raw hit dict to `out` if it matches."""
    url = site["uri_check"].replace("{account}", username)
    async with sem:
        try:
            resp = await client.get(url, follow_redirects=True)
        except Exception:  # noqa: BLE001 — network/DNS/TLS/etc; a dead site is not a scan failure
            return
    if _is_hit(site, resp.status_code, resp.text):
        out.append({
            "site_name": site["name"],
            "url": url,
            "username": username,
            "category": site.get("cat", "unknown"),
            "http_code": resp.status_code,
        })


async def check_username(username: str) -> list[dict]:
    """Run every WhatsMyName rule against `username`; return raw hit dicts.

    Results accumulate into `out` as each check completes, so if the scan hits
    ``SCAN_TIMEOUT`` we still return the hits found so far (mirrors holehe's
    ``move_on_after``) rather than discarding the whole run.
    """
    sites = _load_sites()
    if not sites:
        return []
    sem = asyncio.Semaphore(CONCURRENCY)
    headers = {"User-Agent": _UA}
    out: list[dict] = []
    async with httpx.AsyncClient(timeout=PER_SITE_TIMEOUT, headers=headers) as client:
        tasks = [asyncio.create_task(_check_site(client, sem, site, username, out)) for site in sites]
        try:
            await asyncio.wait_for(asyncio.gather(*tasks), timeout=SCAN_TIMEOUT)
        except asyncio.TimeoutError:
            log.warning(
                "WhatsMyName scan for %s exceeded %ss cap — returning %d partial hit(s)",
                username, SCAN_TIMEOUT, len(out),
            )
            for t in tasks:
                t.cancel()
    return out


# --------------------------------------------------------------------------
# Normalization — raw WhatsMyName finding → standard Account schema
# --------------------------------------------------------------------------
def normalize_wmn_result(raw: dict, original_username: str) -> Account:
    """Convert a WhatsMyName finding to our standard Account schema."""
    platform = raw["site_name"].lower()
    username = raw.get("username") or original_username
    return Account(
        hash_id=entity_hash(platform, username),
        platform=platform,
        username=username,
        profile_url=raw.get("url") or None,
        last_scraped=datetime.now(timezone.utc),
        raw_data=raw,
    )


async def search(username: str) -> list[Account]:
    """High-level entry point: enumerate + normalize."""
    raw_results = await check_username(username)
    return [normalize_wmn_result(r, username) for r in raw_results]
