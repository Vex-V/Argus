"""Social Analyzer provider — profile discovery across 900+ social sites.

social-analyzer (external/social-analyzer/) is a Python app (qeeqbox) that
finds a username's profiles across hundreds of sites, scoring each candidate
by fetching the page and matching detections rather than trusting the HTTP
status alone (its "rate" is that confidence). Its documented library entry
point is ``SocialAnalyzer().run_as_object(username=..., silent=True,
output="json", ...)``, which does all the work synchronously on an internal
thread pool and returns ``{"detected": [...], "unknown": [...],
"failed": [...]}``.

Rather than pip-install it (its package name has a hyphen and it pulls a
heavier dep set — see requirements.txt), we import its ``app.py`` in-process
from the local clone — but via an explicit file-spec loader keyed to the
clone path, NOT by adding the clone root to ``sys.path``: its module is just
called ``app``, too generic to drop onto the global import path safely (unlike
holehe/ignorant, whose packages are uniquely named). The module is loaded once
and cached; a fresh ``SocialAnalyzer`` instance is created per call because the
class keeps per-run state on ``self`` that concurrent requests would otherwise
clobber. The blocking ``run_as_object`` is run on a background thread.

We ask only for the "detected" profiles (``method="find"``, ``filter="good"``)
and normalize them to the shared ``Account`` schema (same as the maigret /
whatsmyname username-enumeration providers), keeping social-analyzer's own
confidence rate and title in ``raw_data``. Degrades to an empty result set if
the clone or its dependencies (``tld``/``langdetect``/``galeodes``) are absent.
"""
import asyncio
import importlib.util
import logging
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from shared.config import settings
from shared.evidence import entity_hash
from shared.schemas import Account

log = logging.getLogger("providers.socialanalyzer")

_SA_ROOT = Path(
    settings.socialanalyzer_project_path
    or Path(__file__).resolve().parents[3] / "external" / "social-analyzer"
)
_SA_APP = _SA_ROOT / "app.py"

# social-analyzer's `timeout` param is NOT a request timeout — it's an
# artificial politeness sleep it runs *before every single site fetch*
# (app.py: `if self.timeout: sleep(self.timeout)`). The real HTTP timeout is
# hardcoded to 5s inside its fetcher. So any non-zero value here just adds
# `value` seconds of dead sleep per site and makes scans dramatically slower;
# 0 makes it fall back to a tiny random 0.01–0.99s jitter, which is what we
# want. Leave it at 0.
REQUEST_DELAY = 0

_sa_module = None  # cached loaded module (not the instance — that's per-call)


def _load_module():
    """Import social-analyzer's app.py via a file spec (cached), or None if absent."""
    global _sa_module
    if _sa_module is not None:
        return _sa_module
    if not _SA_APP.is_file():
        log.warning("social-analyzer clone not found at %s — skipping.", _SA_APP)
        return None
    try:
        spec = importlib.util.spec_from_file_location("argus_social_analyzer_app", _SA_APP)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001 — missing deps (tld/langdetect/galeodes) etc.
        log.warning("could not import social-analyzer (%s) — skipping.", exc)
        return None
    _sa_module = module
    return _sa_module


def search_username(username: str, top: int = 0, websites: str = "all") -> list[dict]:
    """Run social-analyzer and return its list of detected-profile dicts.

    ``top`` (>0) restricts the scan to the N highest-ranked sites, a big
    speed-up over all 900+; ``websites`` narrows to specific site(s) by name.
    """
    module = _load_module()
    if module is None:
        return []
    try:
        analyzer = module.SocialAnalyzer(silent=True)
        result = analyzer.run_as_object(
            username=username,
            method="find",       # only report detected profiles
            filter="good",       # ... that pass the "good" confidence filter
            profiles="detected",
            output="json",
            mode="fast",
            websites=websites,
            top=str(top) if top else "0",
            timeout=REQUEST_DELAY,
            silent=True,
        )
    except Exception as exc:  # noqa: BLE001 — never let a scraper hiccup crash the provider
        log.error("social-analyzer run failed for %s: %s", username, exc)
        return []
    return (result or {}).get("detected", []) or []


# --------------------------------------------------------------------------
# Normalization — raw social-analyzer profile → standard Account schema
# --------------------------------------------------------------------------
def _platform_from_link(link: str) -> str:
    """Derive a platform name from a profile URL's host (drops a leading www.)."""
    host = urlparse(link).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host or "unknown"


def normalize_socialanalyzer_result(raw: dict, username: str) -> Account:
    """Convert a social-analyzer detected profile to our standard Account schema."""
    link = raw.get("link") or ""
    platform = _platform_from_link(link)
    return Account(
        hash_id=entity_hash(platform, username),
        platform=platform,
        username=username,
        profile_url=link or None,
        last_scraped=datetime.now(timezone.utc),
        raw_data=raw,
    )


async def search(username: str, top: int = 0, websites: str = "all") -> list[Account]:
    """High-level entry point: run (off-thread) + normalize."""
    raw_results = await asyncio.to_thread(search_username, username, top, websites)
    return [normalize_socialanalyzer_result(r, username) for r in raw_results]
