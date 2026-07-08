"""Argus MCP server — exposes the Argus SOCMINT toolkit to MCP clients.

This is a *pure HTTP client* of the existing Argus API. It imports nothing from
the Argus services and modifies no Argus code: every tool below simply calls a
route (the same ones documented in ENDPOINTS.md / routes.md) over HTTP, exactly
like `curl` would. Point it at a running gateway (`python gateway.py`, all
routes on one port) or at the standalone per-port services — either works,
because the gateway keeps every route's original path.

The MCP client (Claude Desktop / Claude Code) does the multi-step reasoning:
it decides which tools to call and how to chain their outputs. Each tool here
is a thin, well-described wrapper so the model can plan an investigation.

Run (stdio transport, the default for local MCP clients):
    python argus-mcp/server.py

Configuration (environment variables):
    ARGUS_BASE_URL   base URL of the running Argus API   (default http://localhost:8000)
    ARGUS_TIMEOUT    per-request timeout in seconds       (default 180)
"""
from __future__ import annotations

import base64
import json
import mimetypes
import os
from pathlib import Path
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

BASE_URL = os.environ.get("ARGUS_BASE_URL", "http://localhost:8000").rstrip("/")
TIMEOUT = float(os.environ.get("ARGUS_TIMEOUT", "180"))

INSTRUCTIONS = f"""\
Argus is a SOCMINT (social-media intelligence) toolkit: collection *providers*
that fetch records about an identifier, and *analyzers* that score how likely
two things belong to the same person. Use these tools to run a multi-step OSINT
investigation from a seed identifier (a username, email, phone, or image).

Currently targeting: {BASE_URL}
Start any investigation with `argus_health` to see which providers/analyzers
are actually live — many degrade to empty results when their credentials or
external tools are missing, which is expected, not an error.

Suggested chains (pick per the seed you're given):
- USERNAME  -> maigret_search to enumerate accounts across sites. For each
  candidate account on a platform you can fetch (e.g. reddit), pull its posts
  (reddit_user_posts / reddit_user_comments), then corroborate identity with
  analyze_username (handle similarity), analyze_text_similarity (writing style),
  analyze_timing (posting rhythm), and analyze_contacts (shared connections).
- EMAIL     -> holehe_search to find sites the email is registered on.
- PHONE     -> moriarty_lookup for geo / carrier / spam / owner signals;
  whatsapp_check to confirm WhatsApp registration.
- IMAGE / FACE -> face_detect to confirm a face, yandeximage_search or the
  all-in-one face_pipeline to reverse-search it, face_compare to score two
  faces, image_compare for non-face image reuse (banners, memes, reposts).
- CORRELATION -> the analyzers never fetch anything; feed them evidence you
  already collected to get a same-person score with supporting `evidence`.

Every provider response is an envelope: {{results, provenance, errors}}. Treat a
non-empty `errors` list or an empty `results` as "signal absent", and reason
about confidence accordingly. Similarity scores are 0..1; corroborate across
multiple independent signals before concluding two accounts are one person.
"""

mcp = FastMCP("argus", instructions=INSTRUCTIONS)


# ---------------------------------------------------------------------------
# HTTP helpers — one shared async client, opened lazily.
# ---------------------------------------------------------------------------
_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT)
    return _client


def _pretty(data: Any) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False, default=str)


def _render(resp: httpx.Response) -> str:
    """Turn an HTTP response into a string for the model, JSON when possible."""
    ctype = resp.headers.get("content-type", "")
    if "application/json" in ctype:
        body = _pretty(resp.json())
    else:
        body = resp.text
    if resp.status_code >= 400:
        return f"[HTTP {resp.status_code} from {resp.request.url}]\n{body}"
    return body


async def _post_json(path: str, payload: dict) -> str:
    try:
        resp = await _get_client().post(path, json=payload)
    except httpx.HTTPError as e:
        return _unreachable(path, e)
    return _render(resp)


async def _post_multipart(
    path: str,
    files: dict[str, tuple[str, bytes, str]],
    data: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
) -> str:
    try:
        resp = await _get_client().post(path, files=files, data=data or None, params=params or None)
    except httpx.HTTPError as e:
        return _unreachable(path, e)
    return _render(resp)


def _unreachable(path: str, err: Exception) -> str:
    return (
        f"[Could not reach Argus at {BASE_URL}{path}: {err}]\n"
        f"Is the Argus API running? Start it with `python gateway.py` "
        f"(or the standalone services) and/or set ARGUS_BASE_URL correctly."
    )


def _load_image(image_path: str) -> tuple[str, bytes, str]:
    """Read a local image into an httpx `files` tuple (name, bytes, content-type)."""
    p = Path(image_path).expanduser()
    if not p.is_file():
        raise FileNotFoundError(f"image not found: {p}")
    ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    return (p.name, p.read_bytes(), ctype)


# ===========================================================================
# Meta
# ===========================================================================
@mcp.tool()
async def argus_health() -> str:
    """Aggregate health of every mounted Argus provider/analyzer.

    Call this first. Services degrade gracefully when a credential or external
    tool is missing, so this shows which signals are actually available before
    you plan an investigation.
    """
    try:
        resp = await _get_client().get("/health")
    except httpx.HTTPError as e:
        return _unreachable("/health", e)
    return _render(resp)


# ===========================================================================
# Providers — collection
# ===========================================================================
@mcp.tool()
async def maigret_search(username: str, top_sites: int | None = None) -> str:
    """Enumerate accounts for a USERNAME across many sites (via the maigret CLI).

    `top_sites` (optional) overrides how many of maigret's popularity-ranked
    sites to scan for this call only; higher = broader but slower (3000+ = full
    scan). Returns one Account per site where the username appears claimed.
    Degrades to empty results if the maigret CLI isn't installed.
    """
    payload: dict[str, Any] = {"username": username}
    if top_sites is not None:
        payload["top_sites"] = top_sites
    return await _post_json("/providers/maigret/search", payload)


@mcp.tool()
async def moriarty_lookup(phone: str) -> str:
    """Phone-number OSINT for a PHONE (e.g. "+919876543210").

    Returns geo/carrier/timezone, spam reports/risk, web search links and
    mentions. Includes a Truecaller-style owner name only if the server has
    Google credentials configured. Accepts international format with +.
    """
    return await _post_json("/providers/moriarty/lookup", {"phone": phone})


@mcp.tool()
async def holehe_search(email: str) -> str:
    """Check which sites an EMAIL is registered on (~120 sites, ~20-60s).

    Returns one entry per site where the email is found to exist. `method` /
    `frequent_rate_limit` are a confidence signal — some checks are prone to
    false positives when silently rate-limited.
    """
    return await _post_json("/providers/holehe/search", {"email": email})


@mcp.tool()
async def whatsapp_check(number: str) -> str:
    """Check whether a PHONE number is registered on WhatsApp (passive lookup only).

    Accepts +, spaces, dashes (normalized to digits). Only ever performs a
    passive registration lookup — never sends a message. Requires the Baileys
    sidecar to be running and logged in; otherwise returns exists=null with an
    error explaining the sidecar is unreachable / not connected.
    """
    return await _post_json("/providers/whatsapp/check", {"number": number})


@mcp.tool()
async def reddit_subreddit(subreddits: list[str]) -> str:
    """Fetch recent posts from one or more SUBREDDITS.

    Returns a mixed list of Account (authors) then Post entries. Note: this
    route reports collection time as the post `timestamp`, not the true posting
    time. Empty if RedScrapsLib isn't installed/authenticated.
    """
    return await _post_json("/providers/reddit/subreddit", {"subreddits": subreddits})


@mcp.tool()
async def reddit_user_posts(usernames: list[str]) -> str:
    """Fetch the post submissions of one or more reddit USERNAMES.

    Returns one Account per username followed by their Post submissions, with
    real `CreatedUtc` timestamps and engagement (upvotes, comment_count). Good
    for building a text/timing corpus to correlate against another account.
    """
    return await _post_json("/providers/reddit/user/posts", {"usernames": usernames})


@mcp.tool()
async def reddit_user_comments(usernames: list[str]) -> str:
    """Fetch the comments authored by one or more reddit USERNAMES.

    Returns one Account per username followed by their comments (real, distinct
    comment/parent IDs and timestamps). Useful writing-style + timing corpus.
    """
    return await _post_json("/providers/reddit/user/comments", {"usernames": usernames})


@mcp.tool()
async def reddit_comments(posts: list[dict]) -> str:
    """Fetch comments on specific reddit posts.

    `posts` is a list of {"subreddit": "...", "post_id": "..."}. Returns one
    Account per unique commenter then their comments. Caveat: this route does
    not report per-comment timestamps or reliable comment IDs (RedScrapsLib
    limitation) — dedupe on `hash_id`, not `raw_data.comment_id`.
    """
    return await _post_json("/providers/reddit/comments", {"posts": posts})


@mcp.tool()
async def yandeximage_search(image_path: str, top_n: int = 10) -> str:
    """Reverse-image-search a local IMAGE via Yandex Images.

    `image_path` is a path on the machine running this MCP server. Returns up to
    `top_n` source pages that contain the image, most-relevant first. Degrades
    to empty results if the headless browser is unavailable.
    """
    try:
        img = _load_image(image_path)
    except FileNotFoundError as e:
        return f"[{e}]"
    return await _post_multipart(
        "/providers/yandeximage/search", files={"file": img}, params={"top_n": top_n}
    )


# ===========================================================================
# Analyzers — scoring (feed them evidence you already collected)
# ===========================================================================
@mcp.tool()
async def analyze_username(username_a: str, username_b: str) -> str:
    """Score how similar two usernames are (0..1) with supporting evidence.

    Jaro-Winkler + normalized Levenshtein + leet/separator normalization +
    substring containment. Pure Python; always available.
    """
    return await _post_json(
        "/analyze/username", {"username_a": username_a, "username_b": username_b}
    )


@mcp.tool()
async def analyze_text_similarity(texts_a: list[str], texts_b: list[str]) -> str:
    """Score writing-style similarity (0..1) between two sets of texts.

    Combines semantic (sentence-transformers, if installed) and stylometric
    signals 60/40. Feed each account's posts/comments as `texts_a` / `texts_b`.
    `semantic_similarity` is 0.0 if sentence-transformers isn't installed
    (stylometry still contributes).
    """
    return await _post_json(
        "/analyze/text-similarity", {"texts_a": texts_a, "texts_b": texts_b}
    )


@mcp.tool()
async def analyze_timing(timestamps_a: list[float], timestamps_b: list[float]) -> str:
    """Score posting-rhythm similarity (0..1) between two accounts.

    `timestamps_*` are unix seconds; needs 5+ per side or it returns a low-info
    fallback. Compares hour-of-day and day-of-week histograms and reports the
    shared peak hours as evidence.
    """
    return await _post_json(
        "/analyze/timing", {"timestamps_a": timestamps_a, "timestamps_b": timestamps_b}
    )


@mcp.tool()
async def analyze_contacts(contacts_a: list[dict], contacts_b: list[dict]) -> str:
    """Score follower/contact-set overlap (0..1) between two accounts.

    Each contact is {"id": str, "weight": float=1.0} — weight interaction
    strength higher than plain follows. Returns Jaccard + weighted overlap and
    the list of mutual contacts.
    """
    return await _post_json(
        "/analyze/contacts", {"contacts_a": contacts_a, "contacts_b": contacts_b}
    )


@mcp.tool()
async def analyze_profile_content(posts: list[str], platform: str = "") -> str:
    """Profile a single account's content: keywords, hashtags, sentiment, tone.

    Feed one account's posts. Returns TF-IDF top keywords, hashtag frequencies,
    VADER sentiment, and an Ollama-classified tone (falls back to "unknown"
    when Ollama is unreachable). Each signal degrades independently.
    """
    return await _post_json(
        "/analyze/profile-content", {"posts": posts, "platform": platform}
    )


@mcp.tool()
async def face_compare(image_a_path: str, image_b_path: str) -> str:
    """Score facial similarity (0..1) between two local face IMAGES.

    Stateless; nothing is stored. Reads both files and sends them base64-encoded.
    Degrades to score 0.0 with evidence explaining if the face model is
    unavailable or no face was found in one of the images.
    """
    try:
        a = _load_image(image_a_path)
        b = _load_image(image_b_path)
    except FileNotFoundError as e:
        return f"[{e}]"
    payload = {
        "image_a": base64.b64encode(a[1]).decode(),
        "image_b": base64.b64encode(b[1]).decode(),
    }
    return await _post_json("/face/compare", payload)


@mcp.tool()
async def face_detect(image_path: str) -> str:
    """Detect the largest face in a local IMAGE.

    Returns detection confidence, bounding box, an annotated image and the
    extracted face crop (base64), plus a saved-crop path on the server. Use
    before reverse-searching to confirm the image actually contains a face.
    """
    try:
        img = _load_image(image_path)
    except FileNotFoundError as e:
        return f"[{e}]"
    return await _post_multipart("/face/detect", files={"file": img})


@mcp.tool()
async def face_embed(
    image_path: str,
    source_url: str | None = None,
    source_entity_id: str | None = None,
    image_type: str = "avatar",
) -> str:
    """Store a face embedding from a local IMAGE into the Argus search index.

    Writes a 512-dim embedding to PostgreSQL (upsert by content hash) when a
    face is detected, so later `face_search` calls can match against it. This is
    one of the only two endpoints that persist anything. Requires the DB to be
    up and migrated.
    """
    try:
        img = _load_image(image_path)
    except FileNotFoundError as e:
        return f"[{e}]"
    data: dict[str, str] = {"image_type": image_type}
    if source_url is not None:
        data["source_url"] = source_url
    if source_entity_id is not None:
        data["source_entity_id"] = source_entity_id
    return await _post_multipart("/face/embed", files={"file": img}, data=data)


@mcp.tool()
async def face_search(image_path: str, limit: int = 10) -> str:
    """Find the nearest stored faces to a local query IMAGE (pgvector cosine).

    Searches the `images` table populated by `face_embed`. Returns up to `limit`
    nearest neighbours with similarity scores. Empty if nothing has been
    embedded yet or the DB isn't available.
    """
    try:
        img = _load_image(image_path)
    except FileNotFoundError as e:
        return f"[{e}]"
    return await _post_multipart("/face/search", files={"file": img}, params={"limit": limit})


@mcp.tool()
async def image_compare(image_a_path: str, image_b_path: str) -> str:
    """Score non-face image reuse (0..1) between two local IMAGES via perceptual hash.

    For banners, memes, reposted photos — not faces (use face_compare for those).
    Returns pHash Hamming distance, similarity and a likely_match flag. Stateless.
    """
    try:
        a = _load_image(image_a_path)
        b = _load_image(image_b_path)
    except FileNotFoundError as e:
        return f"[{e}]"
    return await _post_multipart(
        "/image/compare", files={"image_a": a, "image_b": b}
    )


@mcp.tool()
async def image_search(image_path: str, limit: int = 10) -> str:
    """Find the nearest stored images to a local query IMAGE (pHash Hamming distance).

    Upserts the query image's pHash into the `images` table, then searches it —
    so this endpoint persists. Returns up to `limit` nearest images. Requires
    the DB to be up and migrated.
    """
    try:
        img = _load_image(image_path)
    except FileNotFoundError as e:
        return f"[{e}]"
    return await _post_multipart("/image/search", files={"file": img}, params={"limit": limit})


@mcp.tool()
async def face_pipeline(image_path: str, top_n: int = 10) -> str:
    """All-in-one: detect a face in a local IMAGE, reverse-search it, score each match.

    Chains face detection + Yandex reverse image search + facial similarity and
    returns a plain-text ranked summary with download URLs for each matched
    image (not JSON). Needs the facial model + headless browser on the server to
    produce real results. Best single call for "who is this person in the photo".
    """
    try:
        img = _load_image(image_path)
    except FileNotFoundError as e:
        return f"[{e}]"
    return await _post_multipart(
        "/analyze/face-pipeline", files={"file": img}, params={"top_n": top_n}
    )


if __name__ == "__main__":
    mcp.run()
