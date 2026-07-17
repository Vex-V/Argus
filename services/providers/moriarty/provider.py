"""Moriarty provider — phone number OSINT via the local Moriarty-Project clone.

Moriarty-Project (Moriarty-Project/) isn't a pip package — it's a Flask app
whose Investigation/ modules do the actual lookups. Rather than driving its
browser UI, we import those modules directly and call them in-process.

The modules that are plain HTTP scraping (requests/bs4, no credentials, no
browser) are wired in directly: phone geocoding, spam-report lookups, and web
mentions. FindOwner (Truecaller via Google login) is wired in too, via
findowner.find_owner — see that module for why it's a separate, optional,
credential-gated path. socialMedia1-5
(Facebook/Instagram/Twitter/Google/Microsoft account-enumeration via
automated login attempts) are deliberately NOT wired in — they need
pyvirtualdisplay/Xvfb (Linux-only, not available on this Windows box), and the
login-probing approach risks tripping those platforms' abuse detection and
account lockouts. Revisit if there's a specific need.

Investigation/*.py store their results in bare module-level globals (no
returned value from the setter), so concurrent calls would clobber each
other; _lock serializes access and _lookup_sync does a full request/response
cycle before releasing it.
"""
import asyncio
import logging
import sys
from pathlib import Path

from shared.config import settings

log = logging.getLogger("providers.moriarty")

# Moriarty-Project lives at external/Moriarty-Project; this module is at
# services/providers/moriarty/provider.py, so the repo root is three parents up.
_MORIARTY_ROOT = Path(
    settings.moriarty_project_path
    or Path(__file__).resolve().parents[3] / "external" / "Moriarty-Project"
)
_lock = asyncio.Lock()


async def moriarty_lookup(phone_number: str) -> dict:
    if not (_MORIARTY_ROOT / "Investigation").is_dir():
        return {"error": f"Moriarty-Project not found at {_MORIARTY_ROOT}", "phone_number": phone_number}

    async with _lock:
        result = await asyncio.to_thread(_lookup_sync, phone_number)

    if settings.moriarty_google_email and settings.moriarty_google_password:
        from . import findowner

        result["truecaller_owner"] = await findowner.find_owner(phone_number)

    return result


def _lookup_sync(phone_number: str) -> dict:
    root = str(_MORIARTY_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)

    from Investigation import general, getComments, getComments2, getLinks, spamControl, spamControl2

    result: dict = {"phone_number": phone_number}

    try:
        general.location(phone_number)
        result["geo"] = {
            "valid": general.return_errNumber_() == "True",
            "country": general.returnCountry(),
            "operator": general.returnOperator(),
            "timezone": general.returnTimeZone(),
            "local_time": general.returnCurrentTime(),
        }
    except Exception as exc:  # noqa: BLE001
        log.warning("moriarty geo lookup failed: %s", exc)
        result["geo"] = {}

    try:
        spamControl2.getSpam(phone_number)
        spam_reports = spamControl2.returnValue()
    except Exception:  # noqa: BLE001
        spam_reports = "No spam info found"

    try:
        spamControl.spamMain(phone_number)
        risk_level, explanation, number_type = spamControl.printAll()
    except Exception:  # noqa: BLE001
        risk_level, explanation, number_type = "unknown", "unknown", "unknown"

    result["spam"] = {
        "reports": spam_reports,
        "risk_level": risk_level,
        "explanation": explanation,
        "number_type": number_type,
    }

    try:
        getLinks.getLinks_(phone_number)
        result["search_links"] = [u for u in getLinks.printAll() if u and u != "not found"]
    except Exception:  # noqa: BLE001
        result["search_links"] = []

    comments: list[str] = []
    try:
        getComments.getComments_(phone_number)
        comments.extend(getComments.printAll())
    except Exception:  # noqa: BLE001
        pass
    try:
        getComments2._getComments2_(phone_number)
        comments.extend(getComments2.printAll())
    except Exception:  # noqa: BLE001
        pass
    result["comments"] = [c for c in dict.fromkeys(comments) if c and "No comment" not in c]

    return result
