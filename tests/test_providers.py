"""Offline tests for the collection providers.

These exercise the pure/normalization paths and the graceful-degradation
behavior (no network, no credentials, external tool absent).
"""
from datetime import datetime, timezone

import httpx
import pytest

from services.providers.ghunt import provider as ghunt
from services.providers.holehe import provider as holehe
from services.providers.ignorant import provider as ignorant
from services.providers.maigret import provider as maigret
from services.providers.reddit import provider as reddit
from services.providers.socialanalyzer import provider as socialanalyzer
from services.providers.telegram import provider as telegram
from services.providers.whatsapp import provider as whatsapp
from services.providers.whatsmyname import provider as whatsmyname
from services.providers.yandeximage import provider as yandeximage
from shared.evidence import entity_hash
from shared.schemas import Account, Post


# --- maigret normalization -------------------------------------------------
def test_normalize_maigret_result_builds_hash():
    acc = maigret.normalize_maigret_result(
        {"site_name": "GitHub", "username": "fox", "url": "https://github.com/fox"},
        "fox",
    )
    assert isinstance(acc, Account)
    assert acc.platform == "github"
    assert acc.username == "fox"
    assert acc.hash_id == entity_hash("github", "fox")
    assert acc.profile_url == "https://github.com/fox"


def test_normalize_maigret_result_falls_back_to_original_username():
    acc = maigret.normalize_maigret_result({"site_name": "Reddit"}, "fox")
    assert acc.username == "fox"


def test_merge_accounts_dedups_by_hash():
    a = maigret.normalize_maigret_result({"site_name": "GitHub", "username": "fox"}, "fox")
    b = maigret.normalize_maigret_result({"site_name": "GitHub", "username": "fox"}, "fox")
    assert len(maigret.merge_accounts([a], [b])) == 1


@pytest.mark.asyncio
async def test_maigret_search_empty_when_cli_absent(monkeypatch):
    monkeypatch.setattr(maigret, "_find_maigret", lambda: None)
    assert await maigret.search("anyone") == []


@pytest.mark.asyncio
async def test_maigret_search_username_passes_top_sites_override(monkeypatch):
    captured_cmd = {}

    async def fake_run(func, *args, **kwargs):
        captured_cmd["cmd"] = args[0]

    monkeypatch.setattr(maigret, "_find_maigret", lambda: "maigret")
    monkeypatch.setattr(maigret.asyncio, "to_thread", fake_run)
    monkeypatch.setattr(maigret, "_parse_reports", lambda outdir, username: [])
    monkeypatch.setattr(maigret.shutil, "rmtree", lambda *a, **k: None)

    await maigret.search_username("anyone", top_sites=500)
    cmd = captured_cmd["cmd"]
    assert cmd[cmd.index("--top-sites") + 1] == "500"


@pytest.mark.asyncio
async def test_maigret_search_username_defaults_to_configured_top_sites(monkeypatch):
    captured_cmd = {}

    async def fake_run(func, *args, **kwargs):
        captured_cmd["cmd"] = args[0]

    monkeypatch.setattr(maigret, "_find_maigret", lambda: "maigret")
    monkeypatch.setattr(maigret.asyncio, "to_thread", fake_run)
    monkeypatch.setattr(maigret, "_parse_reports", lambda outdir, username: [])
    monkeypatch.setattr(maigret.shutil, "rmtree", lambda *a, **k: None)

    await maigret.search_username("anyone")
    cmd = captured_cmd["cmd"]
    assert cmd[cmd.index("--top-sites") + 1] == str(maigret.settings.maigret_top_sites)


# --- holehe normalization / graceful degradation ----------------------------
def test_normalize_holehe_result_shape():
    hit = holehe.normalize_holehe_result(
        {
            "name": "spotify",
            "domain": "spotify.com",
            "exists": True,
            "method": "register",
            "frequent_rate_limit": True,
            "emailrecovery": None,
            "phoneNumber": None,
            "others": None,
        },
        "target@example.com",
    )
    assert hit == {
        "platform": "spotify.com",
        "email": "target@example.com",
        "exists": True,
        "method": "register",
        "frequent_rate_limit": True,
        "email_recovery": None,
        "phone_number": None,
        "other_data": None,
    }


def test_normalize_holehe_result_falls_back_to_name_when_domain_missing():
    hit = holehe.normalize_holehe_result({"name": "spotify", "exists": True}, "target@example.com")
    assert hit["platform"] == "spotify"


@pytest.mark.asyncio
async def test_holehe_check_email_empty_when_clone_absent(monkeypatch):
    monkeypatch.setattr(holehe, "_ensure_on_path", lambda: False)
    assert await holehe.check_email("target@example.com") == []


@pytest.mark.asyncio
async def test_holehe_search_filters_to_hits_and_normalizes(monkeypatch):
    raw = [
        {"name": "spotify", "domain": "spotify.com", "exists": True},
        {"name": "amazon", "domain": "amazon.com", "exists": False},
    ]

    async def fake_check_email(email):
        return raw

    monkeypatch.setattr(holehe, "check_email", fake_check_email)
    hits = await holehe.search("target@example.com")
    assert len(hits) == 1
    assert hits[0]["platform"] == "spotify.com"
    assert hits[0]["exists"] is True


# --- whatsapp sidecar proxy / graceful degradation --------------------------
class _FakeWhatsAppResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "error", request=httpx.Request("POST", "http://x"), response=self
            )

    def json(self):
        return self._payload


class _FakeWhatsAppClient:
    def __init__(self, response=None, exc=None):
        self._response = response
        self._exc = exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def post(self, url, json=None):
        if self._exc:
            raise self._exc
        return self._response


@pytest.mark.asyncio
async def test_whatsapp_check_number_returns_sidecar_result(monkeypatch):
    fake_response = _FakeWhatsAppResponse(
        200, {"number": "919876543210", "exists": True, "jid": "919876543210@s.whatsapp.net"}
    )
    monkeypatch.setattr(whatsapp.httpx, "AsyncClient", lambda *a, **k: _FakeWhatsAppClient(response=fake_response))

    result = await whatsapp.check_number("919876543210")
    assert result == {"number": "919876543210", "exists": True, "jid": "919876543210@s.whatsapp.net"}


@pytest.mark.asyncio
async def test_whatsapp_check_number_degrades_when_sidecar_unreachable(monkeypatch):
    monkeypatch.setattr(
        whatsapp.httpx, "AsyncClient", lambda *a, **k: _FakeWhatsAppClient(exc=httpx.ConnectError("refused"))
    )

    result = await whatsapp.check_number("919876543210")
    assert result == {"number": "919876543210", "exists": None, "error": "whatsapp sidecar unreachable"}


@pytest.mark.asyncio
async def test_whatsapp_check_number_degrades_when_not_connected(monkeypatch):
    fake_response = _FakeWhatsAppResponse(503, {"error": "not connected"})
    monkeypatch.setattr(whatsapp.httpx, "AsyncClient", lambda *a, **k: _FakeWhatsAppClient(response=fake_response))

    result = await whatsapp.check_number("919876543210")
    assert result == {"number": "919876543210", "exists": None, "error": "whatsapp sidecar not connected"}


# --- yandeximage normalization / graceful degradation -----------------------
def test_yandeximage_normalize_site_builds_absolute_thumbnail_url():
    hit = yandeximage._normalize_site(
        {
            "title": "Some Page",
            "url": "https://example.com/page",
            "domain": "example.com",
            "description": "  a description  ",
            "thumb": {"url": "//avatars.mds.yandex.net/i?id=abc", "width": 148, "height": 90},
        }
    )
    assert hit == {
        "title": "Some Page",
        "url": "https://example.com/page",
        "domain": "example.com",
        "description": "a description",
        "thumbnail_url": "https://avatars.mds.yandex.net/i?id=abc",
    }


def test_yandeximage_normalize_site_handles_missing_thumb_and_description():
    hit = yandeximage._normalize_site({"title": "Some Page", "url": "https://example.com", "domain": "example.com"})
    assert hit["thumbnail_url"] is None
    assert hit["description"] is None


@pytest.mark.asyncio
async def test_yandeximage_search_respects_top_n(monkeypatch):
    fake_state = {
        "initialState": {
            "cbirSites": {
                "sites": [
                    {"title": "A", "url": "https://a.com", "domain": "a.com"},
                    {"title": "B", "url": "https://b.com", "domain": "b.com"},
                    {"title": "C", "url": "https://c.com", "domain": "c.com"},
                ]
            }
        }
    }

    async def fake_run_search(browser, image_bytes, filename, content_type):
        return fake_state

    monkeypatch.setattr(yandeximage, "_run_search", fake_run_search)

    class _FakeBrowser:
        async def close(self):
            pass

    class _FakeChromium:
        async def launch(self, headless=True):
            return _FakeBrowser()

    class _FakePlaywrightCtx:
        async def __aenter__(self):
            return type("P", (), {"chromium": _FakeChromium()})()

        async def __aexit__(self, *exc_info):
            return False

    monkeypatch.setattr(yandeximage, "async_playwright", lambda: _FakePlaywrightCtx())

    results = await yandeximage.reverse_image_search(b"fake-bytes", top_n=2)
    assert [r["domain"] for r in results] == ["a.com", "b.com"]


@pytest.mark.asyncio
async def test_yandeximage_search_degrades_to_empty_on_failure(monkeypatch):
    def boom():
        raise RuntimeError("no browser available")

    monkeypatch.setattr(yandeximage, "async_playwright", boom)

    assert await yandeximage.reverse_image_search(b"fake-bytes") == []


# --- telegram / reddit graceful degradation --------------------------------
@pytest.mark.asyncio
async def test_telegram_fetch_no_channels_returns_empty():
    # Short-circuits before any network/telethon import.
    assert await telegram.fetch([]) == []


@pytest.mark.asyncio
async def test_telegram_fetch_no_credentials_returns_empty(monkeypatch):
    monkeypatch.setattr(telegram.settings, "telegram_api_id", None)
    monkeypatch.setattr(telegram.settings, "telegram_api_hash", None)
    assert await telegram.fetch(["somechannel"]) == []


@pytest.mark.asyncio
async def test_reddit_fetch_subreddit_posts_no_subreddits_returns_empty():
    assert await reddit.fetch_subreddit_posts([]) == []


@pytest.mark.asyncio
async def test_reddit_fetch_user_posts_no_usernames_returns_empty():
    assert await reddit.fetch_user_posts([]) == []


@pytest.mark.asyncio
async def test_reddit_fetch_user_comments_no_usernames_returns_empty():
    assert await reddit.fetch_user_comments([]) == []


@pytest.mark.asyncio
async def test_reddit_fetch_post_comments_no_targets_returns_empty():
    assert await reddit.fetch_post_comments([]) == []


def test_reddit_created_utc_to_datetime_falls_back_to_now():
    assert reddit._created_utc_to_datetime(None).tzinfo is not None


def test_reddit_created_utc_to_datetime_converts_float():
    dt = reddit._created_utc_to_datetime(1735689600.0)
    assert dt.year == 2025 and dt.tzinfo is not None


def test_reddit_user_post_builder_links_author():
    class FakePost:
        PostID = "abc123"
        Title = "Hello"
        SelfText = "World"
        Subreddit = "python"
        Link = "https://reddit.com/r/python/abc123"
        Upvotes = 42
        CommentCount = 3
        CreatedUtc = 1735689600.0

    post = reddit._user_post_to_post("alice", FakePost())
    assert isinstance(post, Post)
    assert post.author_hash_id == entity_hash("reddit", "alice")
    assert post.content == "Hello\n\nWorld"
    assert post.engagement == {"upvotes": 42, "comment_count": 3}
    assert post.raw_data["kind"] == "post"


def test_reddit_user_comment_builder_links_author():
    class FakeComment:
        CommentID = "c1"
        Author = "alice"
        Subreddit = "python"
        Body = "nice post"
        ParentID = "abc123"
        PostID = "abc123"
        PostTitle = "Hello"
        Link = "https://reddit.com/r/python/abc123/c1"
        Upvotes = 5
        CreatedUtc = 1735689600.0

    post = reddit._user_comment_to_post("alice", FakeComment())
    assert isinstance(post, Post)
    assert post.author_hash_id == entity_hash("reddit", "alice")
    assert post.content == "nice post"
    assert post.raw_data["kind"] == "comment"
    assert post.raw_data["comment_id"] == "c1"


def test_reddit_post_comment_builder_links_author():
    class FakeComment:
        # RedScrapsLib's get_comments reports these equal to the post ID for
        # every comment (upstream quirk) — the builder must not rely on them
        # for hash uniqueness.
        CommentID = "abc123"
        Author = "bob"
        ParentID = "abc123"
        Body = "me too"

    post = reddit._post_comment_to_post("python", "abc123", 0, FakeComment(), "bob")
    assert isinstance(post, Post)
    assert post.author_hash_id == entity_hash("reddit", "bob")
    assert post.content == "me too"
    assert post.raw_data == {
        "kind": "comment",
        "subreddit": "python",
        "post_id": "abc123",
        "comment_id": "abc123",
        "parent_id": "abc123",
    }


def test_reddit_post_comment_hash_ids_differ_by_thread_position():
    class FakeComment:
        CommentID = "abc123"
        ParentID = "abc123"
        Body = "text"

    a = reddit._post_comment_to_post("python", "abc123", 0, FakeComment(), "bob")
    b = reddit._post_comment_to_post("python", "abc123", 1, FakeComment(), "bob")
    assert a.hash_id != b.hash_id


def test_telegram_post_builder_links_author():
    class FakeMsg:
        id = 7
        message = "hello"
        media = None
        date = datetime(2026, 1, 1, tzinfo=timezone.utc)
        forward = None
        geo = None

    post = telegram._message_to_post("chan", FakeMsg(), "alice")
    assert isinstance(post, Post)
    assert post.author_hash_id == entity_hash("telegram", "alice")
    assert post.hash_id == entity_hash("telegram", "chan:7")
    assert post.content == "hello"


# --- whatsmyname detection / normalization / graceful degradation -----------
def test_whatsmyname_is_hit_requires_code_and_estring():
    site = {"e_code": 200, "e_string": "profile", "m_string": "not found"}
    assert whatsmyname._is_hit(site, 200, "<h1>profile page</h1>") is True
    assert whatsmyname._is_hit(site, 404, "profile") is False          # wrong code
    assert whatsmyname._is_hit(site, 200, "<h1>welcome</h1>") is False  # e_string absent


def test_whatsmyname_is_hit_rejects_when_missing_string_present():
    # A 200 with the "missing" marker is a false positive, not a hit.
    site = {"e_code": 200, "e_string": "profile", "m_string": "user not found"}
    assert whatsmyname._is_hit(site, 200, "profile ... user not found") is False


def test_whatsmyname_is_hit_code_only_when_no_estring():
    site = {"e_code": 200, "e_string": "", "m_string": ""}
    assert whatsmyname._is_hit(site, 200, "anything") is True
    assert whatsmyname._is_hit(site, 301, "anything") is False


def test_normalize_wmn_result_builds_account():
    acc = whatsmyname.normalize_wmn_result(
        {"site_name": "GitHub", "username": "fox", "url": "https://github.com/fox", "category": "coding"},
        "fox",
    )
    assert isinstance(acc, Account)
    assert acc.platform == "github"
    assert acc.username == "fox"
    assert acc.hash_id == entity_hash("github", "fox")
    assert acc.profile_url == "https://github.com/fox"
    assert acc.raw_data["category"] == "coding"


@pytest.mark.asyncio
async def test_whatsmyname_check_empty_when_dataset_absent(monkeypatch):
    monkeypatch.setattr(whatsmyname, "_load_sites", lambda: [])
    assert await whatsmyname.check_username("anyone") == []


@pytest.mark.asyncio
async def test_whatsmyname_search_normalizes_hits(monkeypatch):
    async def fake_check(username):
        return [{"site_name": "GitHub", "username": username, "url": "https://github.com/fox"}]

    monkeypatch.setattr(whatsmyname, "check_username", fake_check)
    accounts = await whatsmyname.search("fox")
    assert len(accounts) == 1
    assert accounts[0].platform == "github"


# --- ignorant number parsing / normalization / graceful degradation ---------
def test_ignorant_split_number_with_explicit_country_code():
    assert ignorant.split_number("98765 43210", "91") == ("91", "9876543210")
    assert ignorant.split_number("9876543210", "+91") == ("91", "9876543210")


def test_ignorant_split_number_parses_full_international():
    # +1 202-555-0143 (US)
    assert ignorant.split_number("+12025550143", None) == ("1", "2025550143")


def test_ignorant_split_number_returns_none_when_unresolvable():
    assert ignorant.split_number("not-a-number", None) is None


def test_normalize_ignorant_result_shape():
    hit = ignorant.normalize_ignorant_result(
        {"name": "instagram", "domain": "instagram.com", "method": "register",
         "frequent_rate_limit": False, "rateLimit": False, "exists": True},
        "91", "9876543210",
    )
    assert hit == {
        "platform": "instagram.com",
        "phone": "+919876543210",
        "country_code": "91",
        "exists": True,
        "method": "register",
        "frequent_rate_limit": False,
        "rate_limited": False,
    }


@pytest.mark.asyncio
async def test_ignorant_check_empty_when_clone_absent(monkeypatch):
    monkeypatch.setattr(ignorant, "_ensure_on_path", lambda: False)
    assert await ignorant.check_phone("91", "9876543210") == []


@pytest.mark.asyncio
async def test_ignorant_search_filters_to_hits_and_normalizes(monkeypatch):
    async def fake_check_phone(cc, national):
        return [
            {"name": "instagram", "domain": "instagram.com", "exists": True},
            {"name": "amazon", "domain": "amazon.com", "exists": False},
        ]

    monkeypatch.setattr(ignorant, "check_phone", fake_check_phone)
    hits = await ignorant.search("+919876543210")
    assert len(hits) == 1
    assert hits[0]["platform"] == "instagram.com"
    assert hits[0]["exists"] is True


@pytest.mark.asyncio
async def test_ignorant_search_empty_when_number_unresolvable(monkeypatch):
    assert await ignorant.search("garbage", None) == []


# --- social-analyzer normalization / graceful degradation -------------------
def test_socialanalyzer_platform_from_link_strips_www():
    assert socialanalyzer._platform_from_link("https://www.github.com/fox") == "github.com"
    assert socialanalyzer._platform_from_link("https://twitter.com/fox") == "twitter.com"
    assert socialanalyzer._platform_from_link("") == "unknown"


def test_normalize_socialanalyzer_result_builds_account():
    acc = socialanalyzer.normalize_socialanalyzer_result(
        {"link": "https://github.com/fox", "rate": "%100", "title": "fox (GitHub)"},
        "fox",
    )
    assert isinstance(acc, Account)
    assert acc.platform == "github.com"
    assert acc.username == "fox"
    assert acc.hash_id == entity_hash("github.com", "fox")
    assert acc.profile_url == "https://github.com/fox"
    assert acc.raw_data["rate"] == "%100"


def test_socialanalyzer_search_username_empty_when_module_absent(monkeypatch):
    monkeypatch.setattr(socialanalyzer, "_load_module", lambda: None)
    assert socialanalyzer.search_username("anyone") == []


@pytest.mark.asyncio
async def test_socialanalyzer_search_normalizes_detected(monkeypatch):
    def fake_run(username, top=0, websites="all"):
        return [{"link": "https://github.com/fox", "rate": "%100"}]

    monkeypatch.setattr(socialanalyzer, "search_username", fake_run)
    accounts = await socialanalyzer.search("fox")
    assert len(accounts) == 1
    assert accounts[0].platform == "github.com"


# --- GHunt normalization / graceful degradation -----------------------------
class _FakeContainer(dict):
    """Mirrors GHunt's PersonContainers: dict keyed by container name."""


def _fake_person():
    """A minimal stand-in for GHunt's People API `Person` (PROFILE container)."""
    from types import SimpleNamespace as NS

    return NS(
        personId="123456789",
        emails=_FakeContainer({"PROFILE": NS(value="jane@gmail.com")}),
        names=_FakeContainer({"PROFILE": NS(fullname="Jane Doe")}),
        profilePhotos=_FakeContainer({"PROFILE": NS(isDefault=False, url="https://pic/jane.jpg")}),
        coverPhotos=_FakeContainer({"PROFILE": NS(isDefault=True, url="https://cover")}),
        sourceIds=_FakeContainer({"PROFILE": NS(lastUpdated=datetime(2025, 1, 2, tzinfo=timezone.utc))}),
        profileInfos=_FakeContainer({"PROFILE": NS(userTypes=["GOOGLE_USER"])}),
        inAppReachability=_FakeContainer({"PROFILE": NS(apps=["Maps", "Photos"])}),
        extendedData=NS(
            dynamiteData=NS(entityType="PERSON", customerId=""),
            gplusData=NS(isEntrepriseUser=False),
        ),
    )


def test_normalize_person_builds_account_with_google_extras():
    acc = ghunt.normalize_person(_fake_person(), "jane@gmail.com", registered=True)
    assert acc["platform"] == "google"
    assert acc["username"] == "jane@gmail.com"
    assert acc["email"] == "jane@gmail.com"
    assert acc["display_name"] == "Jane Doe"
    assert acc["hash_id"] == entity_hash("google", "123456789")
    assert acc["avatar_url"] == "https://pic/jane.jpg"
    rd = acc["raw_data"]
    assert rd["gaia_id"] == "123456789"
    assert rd["registered_on_google"] is True
    assert rd["custom_profile_picture"] is True
    assert rd["cover_photo_url"] is None            # default cover → dropped
    assert rd["last_profile_edit"] == "2025-01-02T00:00:00+00:00"
    assert rd["activated_google_services"] == ["Maps", "Photos"]
    assert rd["user_types"] == ["GOOGLE_USER"]


def test_ghunt_registration_only_returns_stub_when_registered():
    out = ghunt._registration_only("jane@gmail.com", registered=True)
    assert len(out) == 1
    assert out[0]["platform"] == "google"
    assert out[0]["raw_data"] == {"registered_on_google": True, "profile_available": False}


def test_ghunt_registration_only_empty_when_not_registered():
    assert ghunt._registration_only("nobody@gmail.com", registered=False) == []
    assert ghunt._registration_only("nobody@gmail.com", registered=None) == []


@pytest.mark.asyncio
async def test_ghunt_search_reports_error_when_clone_absent(monkeypatch):
    monkeypatch.setattr(ghunt, "_ensure_on_path", lambda: False)
    results, errors = await ghunt.search("jane@gmail.com")
    assert results == []
    assert errors and "clone not found" in errors[0]


def test_normalize_person_gaia_route_derives_email_and_omits_registered():
    # gaia route passes no email/registered: email comes from the profile,
    # and the registration field is omitted rather than reported as False.
    acc = ghunt.normalize_person(_fake_person())
    assert acc["email"] == "jane@gmail.com"          # pulled from PROFILE container
    assert acc["username"] == "jane@gmail.com"
    assert acc["hash_id"] == entity_hash("google", "123456789")
    assert "registered_on_google" not in acc["raw_data"]


@pytest.mark.asyncio
async def test_ghunt_lookup_gaia_reports_error_when_clone_absent(monkeypatch):
    monkeypatch.setattr(ghunt, "_ensure_on_path", lambda: False)
    results, errors = await ghunt.lookup_gaia("123456789")
    assert results == []
    assert errors and "clone not found" in errors[0]


def test_ghunt_maps_status_map_covers_gmaps_err_strings():
    # every err string gmaps.get_reviews can return maps to a stable status
    assert ghunt._MAPS_STATUS[""] == "ok"
    assert ghunt._MAPS_STATUS["failed"] == "ip_blocked"
    assert ghunt._MAPS_STATUS["empty"] == "no_public_reviews"
    assert ghunt._MAPS_STATUS["private"] == "private"


@pytest.mark.asyncio
async def test_ghunt_maps_reviews_reports_error_when_clone_absent(monkeypatch):
    monkeypatch.setattr(ghunt, "_ensure_on_path", lambda: False)
    results, errors = await ghunt.maps_reviews("123456789")
    assert results == []
    assert errors and "clone not found" in errors[0]


@pytest.mark.asyncio
async def test_ghunt_maps_contributions_passes_scraped_items_through(monkeypatch):
    scraped = [
        {"review_id": "r1", "place": "Taco Bell", "address": "…", "rating": 5,
         "date": "a year ago", "review_text": "great", "owner_response": "thanks"},
    ]

    async def fake_scrape(gaia_id, max_items=50):
        return scraped

    # scrape_contributions is imported inside maps_contributions from the
    # maps_scraper module, so patch it at the source.
    from services.providers.ghunt import maps_scraper
    monkeypatch.setattr(maps_scraper, "scrape_contributions", fake_scrape)

    results, errors = await ghunt.maps_contributions("123456789")
    assert results == scraped
    assert errors == []


@pytest.mark.asyncio
async def test_ghunt_maps_contributions_errors_when_nothing_scraped(monkeypatch):
    async def fake_scrape(gaia_id, max_items=50):
        return []

    from services.providers.ghunt import maps_scraper
    monkeypatch.setattr(maps_scraper, "scrape_contributions", fake_scrape)

    results, errors = await ghunt.maps_contributions("123456789")
    assert results == []
    assert errors and "no public Maps contributions" in errors[0]
