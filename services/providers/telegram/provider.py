"""Telegram provider — on-demand channel fetch via Telethon.

Reads the most recent messages from the public channels named in the request
and turns them into Account (author) + Post records. Unlike the old passive
worker, this is a one-shot request/response fetch: it grabs a fixed recent
window each call (no Redis cursor, no scheduler). Telethon is imported lazily
so the service starts without the package or credentials configured, and
returns an empty list when Telegram credentials are missing.
"""
import logging
from datetime import datetime, timezone

from shared.config import settings
from shared.evidence import entity_hash
from shared.schemas import Account, Post

log = logging.getLogger("providers.telegram")

PLATFORM = "telegram"
MAX_MESSAGES_PER_CHANNEL = 100


def _make_account(username: str, display_name: str | None = None) -> Account:
    return Account(
        hash_id=entity_hash(PLATFORM, username),
        platform=PLATFORM,
        username=username,
        display_name=display_name,
        last_scraped=datetime.now(timezone.utc),
    )


async def fetch(channels: list[str]) -> list[Account | Post]:
    """Fetch recent messages from the given public channels."""
    if not settings.telegram_api_id or not settings.telegram_api_hash:
        log.warning("Telegram credentials not configured — skipping.")
        return []
    if not channels:
        return []

    # Lazy import: keeps the service importable without telethon installed.
    from telethon import TelegramClient

    records: list[Account | Post] = []
    seen_authors: set[str] = set()

    client = TelegramClient(
        settings.telegram_session_name,
        int(settings.telegram_api_id),
        settings.telegram_api_hash,
    )
    await client.start()
    try:
        for channel in channels:
            async for msg in client.iter_messages(
                channel, limit=MAX_MESSAGES_PER_CHANNEL
            ):
                if not (msg.message or msg.media):
                    continue

                sender = await _safe_sender(msg)
                author_username = sender or channel
                if author_username not in seen_authors:
                    seen_authors.add(author_username)
                    records.append(_make_account(author_username))

                records.append(_message_to_post(channel, msg, author_username))
    finally:
        await client.disconnect()

    return records


async def _safe_sender(msg) -> str | None:
    try:
        sender = await msg.get_sender()
        return getattr(sender, "username", None) or (
            str(sender.id) if sender else None
        )
    except Exception:  # noqa: BLE001
        return None


def _message_to_post(channel: str, msg, author_username: str) -> Post:
    raw = {
        "channel": channel,
        "message_id": msg.id,
        "forwarded_from": str(msg.forward.from_name)
        if getattr(msg, "forward", None)
        else None,
    }
    media_urls: list[str] = []
    if msg.media:
        media_urls.append(f"telegram://{channel}/{msg.id}")

    geo_lat = geo_lng = None
    geo = getattr(msg, "geo", None)
    if geo is not None:
        geo_lat = getattr(geo, "lat", None)
        geo_lng = getattr(geo, "long", None)

    ts = msg.date
    if ts is not None and ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)

    return Post(
        hash_id=entity_hash(PLATFORM, f"{channel}:{msg.id}"),
        platform=PLATFORM,
        author_hash_id=entity_hash(PLATFORM, author_username),
        content=msg.message or "",
        timestamp=ts,
        geo_lat=geo_lat,
        geo_lng=geo_lng,
        media_urls=media_urls,
        raw_data=raw,
    )
