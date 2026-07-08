"""Maigret provider — username enumeration across many sites.

Wraps the ``maigret`` CLI as a subprocess (installed separately; see README).
Runs it with a JSON report and parses out the sites where the username is
claimed. Maigret's report schema has shifted across versions, so parsing is
defensive. If maigret is not installed the provider returns an empty list
with an explanatory note rather than raising.
"""
import asyncio
import glob
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from shared.config import settings
from shared.evidence import entity_hash
from shared.schemas import Account

log = logging.getLogger("providers.maigret")

_CLAIMED = {"claimed", "found", "true"}


def _find_maigret() -> str | None:
    """Locate the maigret executable.

    ``shutil.which`` only checks PATH, but our services are typically started
    via ``uvicorn ...`` without the venv activated, so its Scripts/bin dir
    (where pip installs the entry-point script) is never on PATH. Fall back
    to looking next to the current interpreter.
    """
    found = shutil.which("maigret")
    if found:
        return found
    ext = ".exe" if sys.platform == "win32" else ""
    candidate = Path(sys.executable).parent / f"maigret{ext}"
    return str(candidate) if candidate.exists() else None


async def search_username(username: str, top_sites: int | None = None) -> list[dict]:
    """Return a list of {site_name, url, username, status} for claimed sites.

    ``top_sites`` overrides the configured default (``settings.maigret_top_sites``)
    for this call only — maigret ranks its site list by popularity, so a
    higher value trades a longer scan for broader coverage (3000+ = full scan).
    """
    maigret_bin = _find_maigret()
    if maigret_bin is None:
        log.warning("maigret CLI not found — skipping username enumeration.")
        return []

    outdir = tempfile.mkdtemp(prefix="maigret_")
    cmd = [
        maigret_bin,
        username,
        "--json", "simple",
        "--top-sites", str(top_sites if top_sites is not None else settings.maigret_top_sites),
        "--timeout", "10",
        "--no-color",
        # aiodns/c-ares frequently can't reach Windows-configured DNS servers
        # (VPN/corporate networks especially), which silently fails most
        # sites as "Connecting failure (DNS)". The threaded resolver uses the
        # system resolver instead and is far more reliable here.
        "--dns-resolver", "threaded",
        "--folderoutput", outdir,
    ]
    # maigret prints unicode (hearts, banners) that crashes on Windows' default
    # cp1252 console/pipe encoding unless both sides are forced to UTF-8: the
    # child via PYTHONIOENCODING, and our own capture via encoding="utf-8"
    # (plain text=True decodes with the parent's locale encoding instead).
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    try:
        await asyncio.to_thread(
            subprocess.run,
            cmd,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            env=env,
        )
        return _parse_reports(outdir, username)
    except subprocess.TimeoutExpired:
        log.warning("maigret timed out for %s", username)
        return []
    except Exception as exc:  # noqa: BLE001
        log.error("maigret failed for %s: %s", username, exc)
        return []
    finally:
        shutil.rmtree(outdir, ignore_errors=True)


def _parse_reports(outdir: str, username: str) -> list[dict]:
    # Maigret writes one report file per identity it investigates: the
    # original username plus any alternate usernames/IDs it extracts along
    # the way (e.g. a Steam ID found on one site, tried against others).
    # Every file can contribute distinct claimed accounts, so all of them
    # must be read — not just the first one glob happens to return.
    files = glob.glob(os.path.join(outdir, "*.json"))
    if not files:
        return []

    seen: set[tuple[str, str]] = set()
    results: list[dict] = []
    for path in sorted(files):
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("could not read maigret report %s: %s", path, exc)
            continue

        for site_name, info in (data.items() if isinstance(data, dict) else []):
            if not isinstance(info, dict):
                continue
            status = _extract_status(info)
            if status not in _CLAIMED:
                continue
            url = info.get("url_user") or info.get("url") or ""
            key = (site_name, url)
            if key in seen:
                continue
            seen.add(key)
            results.append(
                {
                    "site_name": site_name,
                    "url": url,
                    "username": _extract_username(info, username),
                    "status": "Claimed",
                }
            )
    return results


def _extract_status(info: dict) -> str:
    status = info.get("status")
    if isinstance(status, dict):
        status = status.get("status")
    return str(status).lower() if status is not None else ""


def _extract_username(info: dict, fallback: str) -> str:
    ids = info.get("ids") or {}
    if isinstance(ids, dict) and ids.get("username"):
        return ids["username"]
    return info.get("username") or fallback


# --------------------------------------------------------------------------
# Normalization — raw maigret finding → standard Account schema
# --------------------------------------------------------------------------
def normalize_maigret_result(raw: dict, original_username: str) -> Account:
    """Convert a Maigret finding to our standard Account schema."""
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


def merge_accounts(*groups: list[Account]) -> list[Account]:
    """De-duplicate accounts across provider result groups by hash_id."""
    seen: dict[str, Account] = {}
    for group in groups:
        for acc in group:
            seen[acc.hash_id] = acc
    return list(seen.values())


async def search(username: str, top_sites: int | None = None) -> list[Account]:
    """High-level entry point: enumerate + normalize + de-duplicate."""
    raw_results = await search_username(username, top_sites)
    accounts = [normalize_maigret_result(r, username) for r in raw_results]
    return merge_accounts(accounts)
