"""GHunt provider — Google account OSINT from an email address.

GHunt (external/GHunt/) is mxrch's offensive Google framework. Unlike holehe /
ignorant (which are trio-based and run on a background thread), GHunt is fully
async on asyncio + httpx — the same stack this FastAPI provider runs on — so
its coroutines are awaited directly in the request handler, no thread needed.
Its package is imported in-process from the local clone (added to ``sys.path``,
same pattern as holehe/ignorant/moriarty), not pip-installed.

Two levels of lookup, degrading independently:

* **Registration check** (``is_email_registered``) — abuses Google's ``gxlu``
  endpoint and needs *no* credentials, so it always runs. It's a plain boolean:
  is any Google account tied to this email.
* **Full profile** (People API ``people_lookup`` with ``max_details``) — returns
  the public Google Account: display name, Gaia ID, profile/cover photo, last
  profile edit, activated Google services, account type. This requires a valid
  GHunt session (cookies + OSIDs + Android master token) generated once with
  ``ghunt login`` and stored at ``~/.malfrats/ghunt/creds.m`` (override with
  ``GHUNT_CREDS_PATH``). When no/invalid session is present the provider still
  returns the registration result and notes the missing profile in ``errors``.

Only a public ``PROFILE`` container is normalized to the ``Account`` schema —
GHunt may also see the target in your own contacts (``CONTACT`` etc.), but that
isn't public OSINT, so it's ignored. Everything degrades to an empty/partial
result (never raises) so the service stays up offline or unauthenticated.
"""
import logging
import sys
from pathlib import Path

from shared.config import settings
from shared.evidence import entity_hash, now_utc

log = logging.getLogger("providers.ghunt")

_GHUNT_ROOT = Path(
    settings.ghunt_project_path
    or Path(__file__).resolve().parents[3] / "external" / "GHunt"
)

HTTP_TIMEOUT = 15  # seconds, per HTTP call


def _ensure_on_path() -> bool:
    """Add the local GHunt clone to sys.path. False if the clone isn't there."""
    if not (_GHUNT_ROOT / "ghunt" / "__init__.py").is_file():
        return False
    root = str(_GHUNT_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    return True


def _load_creds():
    """Return an authenticated-capable GHuntCreds, or None if no valid session.

    Reads GHunt's stored session (``creds.m``). Never raises — a missing or
    corrupt session just means we skip the profile lookup and return the
    registration check alone.
    """
    from ghunt.errors import GHuntInvalidSession
    from ghunt.objects.base import GHuntCreds

    creds_path = settings.ghunt_creds_path or ""
    creds = GHuntCreds(creds_path)
    try:
        creds.load_creds(silent=True)
    except GHuntInvalidSession as exc:
        log.info("no usable GHunt session (%s) — profile lookup skipped.", exc)
        return None
    return creds


async def _authenticate(client) -> tuple[object | None, str | None]:
    """Load + validate a GHunt session for authenticated lookups.

    Returns ``(creds, None)`` on success or ``(None, reason)`` when there's no
    stored session or its cookies can't be refreshed — callers turn ``reason``
    into an ``errors`` entry and degrade. Shared by the gaia and maps routes
    (the email route reuses it too, but still returns its credential-free
    registration result when this fails).
    """
    creds = _load_creds()
    if creds is None:
        return None, "no GHunt session (run `ghunt login`)"
    try:
        from ghunt.helpers.auth import check_and_gen

        await check_and_gen(client, creds)  # validate / refresh cookies
    except Exception as exc:
        log.warning("GHunt authentication failed: %s", exc)
        return None, f"authentication failed: {exc}"
    return creds, None


# --------------------------------------------------------------------------
# Normalization — GHunt People API `Person` → Account-schema dict
# --------------------------------------------------------------------------
def normalize_person(person, email: str | None = None, registered: bool | None = None) -> dict:
    """Convert a GHunt ``Person`` (PROFILE container) to the Account schema.

    Shared by the email and gaia routes. ``email`` is the queried address (email
    route) or ``None`` (gaia route, where it's read from the profile instead);
    ``registered`` is the gxlu result or ``None`` when no check was run.
    Google-specific extras (Gaia ID, activated services, account type, photo
    default-ness, last profile edit) are preserved under ``raw_data``.
    """
    container = "PROFILE"
    gaia_id = person.personId or ""

    # The email route passes the queried address; the gaia route has none, so
    # fall back to the address the profile itself exposes (if any).
    if not email and container in person.emails:
        email = person.emails[container].value or None

    display_name = None
    if container in person.names:
        display_name = person.names[container].fullname or None

    avatar_url = None
    if container in person.profilePhotos and not person.profilePhotos[container].isDefault:
        avatar_url = person.profilePhotos[container].url

    cover_url = None
    if container in person.coverPhotos and not person.coverPhotos[container].isDefault:
        cover_url = person.coverPhotos[container].url

    last_edit = None
    if container in person.sourceIds and person.sourceIds[container].lastUpdated:
        last_edit = person.sourceIds[container].lastUpdated.isoformat()

    user_types = []
    if container in person.profileInfos:
        user_types = list(person.profileInfos[container].userTypes)

    activated_services = []
    if container in person.inAppReachability:
        activated_services = list(person.inAppReachability[container].apps)

    raw_data = {
        "gaia_id": gaia_id,
        "custom_profile_picture": avatar_url is not None,
        "cover_photo_url": cover_url,
        "last_profile_edit": last_edit,
        "user_types": user_types,
        "activated_google_services": activated_services,
        "entity_type": person.extendedData.dynamiteData.entityType,
        "customer_id": person.extendedData.dynamiteData.customerId or None,
        "is_enterprise_user": person.extendedData.gplusData.isEntrepriseUser,
    }
    # Only the email route runs the gxlu registration check; omit the field when
    # there's nothing to report (e.g. the gaia route) rather than lie with False.
    if registered is not None:
        raw_data["registered_on_google"] = registered

    return {
        "hash_id": entity_hash("google", gaia_id or email or ""),
        "platform": "google",
        "username": email or gaia_id,
        "display_name": display_name,
        "bio": None,
        "avatar_url": avatar_url,
        "profile_url": None,
        "email": email,
        "last_scraped": now_utc().isoformat(),
        "raw_data": raw_data,
        "breach_history": [],
    }


async def search(email: str) -> tuple[list[dict], list[str]]:
    """Look up a Google account by email.

    Returns ``(results, errors)``. ``results`` is at most one Account dict for a
    public Google profile; ``errors`` carries non-fatal notes (clone missing, no
    session, target not found) so the caller can surface them without a failure.
    """
    if not _ensure_on_path():
        msg = f"GHunt clone not found at {_GHUNT_ROOT}"
        log.warning("%s — skipping.", msg)
        return [], [msg]

    import httpx

    from ghunt.helpers.gmail import is_email_registered

    errors: list[str] = []

    async with httpx.AsyncClient(http2=True, timeout=HTTP_TIMEOUT) as client:
        # Level 1 — registration check (no credentials required).
        try:
            registered = await is_email_registered(client, email)
        except Exception as exc:  # gxlu is flaky / rate-limited upstream
            log.warning("registration check failed for %s: %s", email, exc)
            registered = None
            errors.append(f"registration check failed: {exc}")

        # Level 2 — full profile via the People API (needs a GHunt session).
        creds, auth_err = await _authenticate(client)
        if creds is None:
            errors.append(f"{auth_err} — profile lookup skipped, registration check only")
            return _registration_only(email, registered), errors

        try:
            from ghunt.apis.peoplepa import PeoplePaHttp

            people_api = PeoplePaHttp(creds)
            found, person = await people_api.people_lookup(
                client, email, params_template="max_details"
            )
        except Exception as exc:
            log.warning("GHunt profile lookup failed for %s: %s", email, exc)
            errors.append(f"profile lookup failed: {exc}")
            return _registration_only(email, registered), errors

        if not found or "PROFILE" not in person.sourceIds:
            errors.append("no public Google Account matched this email")
            return _registration_only(email, registered), errors

        return [normalize_person(person, email, bool(registered))], errors


def _registration_only(email: str, registered) -> list[dict]:
    """Minimal result when we only have the registration boolean, no profile.

    Returned only when Google says the email *is* registered but we couldn't (or
    weren't authorized to) pull the profile — so a caller still learns a Google
    account exists. If it's not registered (or unknown), return nothing.
    """
    if not registered:
        return []
    return [
        {
            "hash_id": entity_hash("google", email),
            "platform": "google",
            "username": email,
            "email": email,
            "last_scraped": now_utc().isoformat(),
            "raw_data": {
                "registered_on_google": True,
                "profile_available": False,
            },
            "breach_history": [],
        }
    ]


async def lookup_gaia(gaia_id: str) -> tuple[list[dict], list[str]]:
    """Look up a Google account by Gaia ID (the reverse of the email route).

    Uses the People API ``people`` endpoint (keyed by Gaia ID instead of email)
    and normalizes the same ``Person`` to the Account schema — so this is the way
    to pivot from a Gaia ID found elsewhere back to a profile. Needs a GHunt
    session (there's no credential-free fallback here, unlike the email route).
    Returns ``(results, errors)``; ``results`` is at most one Account dict.
    """
    if not _ensure_on_path():
        msg = f"GHunt clone not found at {_GHUNT_ROOT}"
        log.warning("%s — skipping.", msg)
        return [], [msg]

    import httpx

    async with httpx.AsyncClient(http2=True, timeout=HTTP_TIMEOUT) as client:
        creds, auth_err = await _authenticate(client)
        if creds is None:
            return [], [auth_err]

        try:
            from ghunt.apis.peoplepa import PeoplePaHttp

            people_api = PeoplePaHttp(creds)
            found, person = await people_api.people(
                client, gaia_id, params_template="max_details"
            )
        except Exception as exc:
            log.warning("GHunt gaia lookup failed for %s: %s", gaia_id, exc)
            return [], [f"gaia lookup failed: {exc}"]

        if not found or "PROFILE" not in person.sourceIds:
            return [], ["no public Google Account matched this Gaia ID"]

        return [normalize_person(person)], []


# err strings returned by gmaps.get_reviews → stable status values we expose
_MAPS_STATUS = {
    "": "ok",
    "failed": "ip_blocked",
    "empty": "no_public_reviews",
    "private": "private",
}


async def maps_reviews(gaia_id: str) -> tuple[list[dict], list[str]]:
    """Fetch a Gaia ID's Google Maps contribution statistics.

    This GHunt version exposes only the aggregate counts (reviews / ratings /
    photos) and the public contributor page — individual review contents are
    disabled upstream — so that's what's returned, plus a ``status`` describing
    the outcome. Needs a GHunt session. Returns ``(results, errors)`` with a
    single result dict carrying the stats and status.
    """
    if not _ensure_on_path():
        msg = f"GHunt clone not found at {_GHUNT_ROOT}"
        log.warning("%s — skipping.", msg)
        return [], [msg]

    import httpx

    async with httpx.AsyncClient(http2=True, timeout=HTTP_TIMEOUT) as client:
        creds, auth_err = await _authenticate(client)
        if creds is None:
            return [], [auth_err]

        try:
            from ghunt.helpers import gmaps

            err, stats = await gmaps.get_reviews(client, gaia_id)
        except Exception as exc:
            log.warning("GHunt maps reviews lookup failed for %s: %s", gaia_id, exc)
            return [], [f"maps reviews lookup failed: {exc}"]

        result = {
            "gaia_id": gaia_id,
            "profile_url": f"https://www.google.com/maps/contrib/{gaia_id}/reviews",
            "status": _MAPS_STATUS.get(err, err or "ok"),
            "stats": stats or {},
        }
        errors: list[str] = []
        if err == "failed":
            errors.append("Google IP-blocked the Maps request — try again later")
        return [result], errors


async def maps_contributions(gaia_id: str, max_items: int = 50) -> tuple[list[dict], list[str]]:
    """Scrape a Gaia ID's *actual* public Maps contributions (not just counts).

    Companion to ``maps_reviews`` (which only has aggregate counts, because
    Google stripped the items from the API GHunt used). This drives a headless
    browser over the public contributor page instead — so it needs **no GHunt
    session**, but is CSS-selector-fragile (see ``maps_scraper``). Each result is
    one contribution: place, address, star rating, relative date, the review
    text (when the entry has any beyond a bare star rating), and the owner's
    reply if present. Returns ``(results, errors)``; empty results + a note when
    the profile is private/empty or the scrape fails.
    """
    from .maps_scraper import scrape_contributions

    items = await scrape_contributions(gaia_id, max_items=max_items)
    if not items:
        return [], ["no public Maps contributions found (private/empty profile, "
                    "or the Maps page layout changed — see maps_scraper)"]
    return items, []
