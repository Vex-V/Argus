"""Reddit provider — on-demand fetches via RedScrapsLib.

Reddit's official API now gates key issuance for new apps, so this provider
scrapes via RedScrapsLib — a cookie-authenticated scraper (backed by a bundled
.NET assembly, self-throttling at ~429/Retry-After) — instead of asyncpraw.
Cookies are pulled from a real logged-in browser session via browser_cookie3.
RedScrapsLib is rate-limited to ~100 calls/hour, and each fetch below makes
exactly one RedScrapsLib call per requested subreddit/username/post, so keep
requests modest.

Four independent lookups, mirroring RedScrapsLib's four fetch functions:
  - fetch_subreddit_posts — recent posts from one or more subreddits
  - fetch_user_posts      — a user's own post submissions
  - fetch_user_comments   — a user's own comments
  - fetch_post_comments   — comments on a specific post (subreddit + post_id)

RedScrapsLib and browser_cookie3 are imported lazily so the service starts
without them installed or without a logged-in browser profile.
"""
import asyncio
import logging
from datetime import datetime, timezone

from shared.config import settings
from shared.evidence import entity_hash
from shared.schemas import Account, Post

log = logging.getLogger("providers.reddit")

PLATFORM = "reddit"
POSTS_PER_SUBREDDIT = 50
POSTS_PER_USER = 50
COMMENTS_PER_USER = 50
COMMENTS_PER_POST = 100

_initialized = False
_init_lock = asyncio.Lock()


async def _get_client():
    """Import + initialize RedScrapsLib, or None if it isn't installed."""
    try:
        import RedScrapsLib as rs
    except ImportError:
        log.warning("RedScrapsLib not installed — skipping reddit fetch.")
        return None
    await _ensure_initialized(rs)
    return rs


async def _ensure_initialized(rs) -> None:
    global _initialized
    if _initialized:
        return
    async with _init_lock:
        if _initialized:
            return
        cookies = None
        try:
            import browser_cookie3

            loader = getattr(browser_cookie3, settings.reddit_cookie_browser)
            cookies = await asyncio.to_thread(loader, domain_name=".reddit.com")
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "Could not load reddit.com cookies from %s (%s) — "
                "continuing unauthenticated, expect heavier rate limiting.",
                settings.reddit_cookie_browser,
                exc,
            )
        await asyncio.to_thread(rs.init, settings.reddit_user_agent, False, cookies)
        _initialized = True


def _make_account(username: str) -> Account:
    return Account(
        hash_id=entity_hash(PLATFORM, username),
        platform=PLATFORM,
        username=username,
        profile_url=f"https://reddit.com/user/{username}",
        last_scraped=datetime.now(timezone.utc),
    )


def _created_utc_to_datetime(value: float | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromtimestamp(value, tz=timezone.utc)


# --------------------------------------------------------------------------
# 1. Subreddit posts
# --------------------------------------------------------------------------
async def fetch_subreddit_posts(subreddits: list[str]) -> list[Account | Post]:
    """Fetch recent posts from the given subreddits."""
    if not subreddits:
        return []
    rs = await _get_client()
    if rs is None:
        return []

    records: list[Account | Post] = []
    seen_authors: set[str] = set()

    for sub_name in subreddits:
        home = await asyncio.to_thread(rs.get_home, sub_name, "new", POSTS_PER_SUBREDDIT)
        if home is None or not home.Posts:
            continue

        for post in home.Posts:
            author_name = post.Author or "[deleted]"
            if author_name != "[deleted]" and author_name not in seen_authors:
                seen_authors.add(author_name)
                records.append(_make_account(author_name))
            records.append(_home_post_to_post(sub_name, post, author_name))

    return records


def _home_post_to_post(sub_name: str, post, author_name: str) -> Post:
    content = post.Title or ""
    if post.SelfText:
        content = f"{content}\n\n{post.SelfText}"

    return Post(
        hash_id=entity_hash(PLATFORM, f"reddit:{post.PostID}"),
        platform=PLATFORM,
        author_hash_id=entity_hash(PLATFORM, author_name),
        content=content,
        # RedScrapsLib's get_home doesn't return the original post time, so
        # this reflects collection time, not the true posting time.
        timestamp=datetime.now(timezone.utc),
        raw_data={"kind": "post", "subreddit": sub_name, "post_id": post.PostID, "link": post.Link},
    )


# --------------------------------------------------------------------------
# 2. A user's own post submissions
# --------------------------------------------------------------------------
async def fetch_user_posts(usernames: list[str]) -> list[Account | Post]:
    """Fetch each given user's own post submissions."""
    if not usernames:
        return []
    rs = await _get_client()
    if rs is None:
        return []

    records: list[Account | Post] = []
    for username in usernames:
        records.append(_make_account(username))

        submitted = await asyncio.to_thread(rs.get_user_posts, username, "new", POSTS_PER_USER)
        if submitted is None or not submitted.Posts:
            continue
        for post in submitted.Posts:
            records.append(_user_post_to_post(username, post))

    return records


def _user_post_to_post(username: str, post) -> Post:
    content = post.Title or ""
    if post.SelfText:
        content = f"{content}\n\n{post.SelfText}"

    engagement = {}
    if post.Upvotes is not None:
        engagement["upvotes"] = post.Upvotes
    if post.CommentCount is not None:
        engagement["comment_count"] = post.CommentCount

    return Post(
        hash_id=entity_hash(PLATFORM, f"reddit:{post.PostID}"),
        platform=PLATFORM,
        author_hash_id=entity_hash(PLATFORM, username),
        content=content,
        timestamp=_created_utc_to_datetime(post.CreatedUtc),
        engagement=engagement,
        raw_data={"kind": "post", "subreddit": post.Subreddit, "post_id": post.PostID, "link": post.Link},
    )


# --------------------------------------------------------------------------
# 3. A user's own comments
# --------------------------------------------------------------------------
async def fetch_user_comments(usernames: list[str]) -> list[Account | Post]:
    """Fetch each given user's own comments."""
    if not usernames:
        return []
    rs = await _get_client()
    if rs is None:
        return []

    records: list[Account | Post] = []
    for username in usernames:
        records.append(_make_account(username))

        commented = await asyncio.to_thread(rs.get_user_comments, username, "new", COMMENTS_PER_USER)
        if commented is None or not commented.Comments:
            continue
        for comment in commented.Comments:
            records.append(_user_comment_to_post(username, comment))

    return records


def _user_comment_to_post(username: str, comment) -> Post:
    engagement = {}
    if comment.Upvotes is not None:
        engagement["upvotes"] = comment.Upvotes

    return Post(
        hash_id=entity_hash(PLATFORM, f"reddit_comment:{comment.CommentID}"),
        platform=PLATFORM,
        author_hash_id=entity_hash(PLATFORM, username),
        content=comment.Body or "",
        timestamp=_created_utc_to_datetime(comment.CreatedUtc),
        engagement=engagement,
        raw_data={
            "kind": "comment",
            "subreddit": comment.Subreddit,
            "post_id": comment.PostID,
            "post_title": comment.PostTitle,
            "comment_id": comment.CommentID,
            "parent_id": comment.ParentID,
            "link": comment.Link,
        },
    )


# --------------------------------------------------------------------------
# 4. Comments on a specific post
# --------------------------------------------------------------------------
async def fetch_post_comments(targets: list[dict]) -> list[Account | Post]:
    """Fetch comments on specific posts.

    Each target is ``{"subreddit": str, "post_id": str}``.
    """
    if not targets:
        return []
    rs = await _get_client()
    if rs is None:
        return []

    records: list[Account | Post] = []
    seen_authors: set[str] = set()

    for target in targets:
        subreddit = target.get("subreddit", "")
        post_id = target.get("post_id", "")
        if not subreddit or not post_id:
            continue

        thread = await asyncio.to_thread(
            rs.get_comments, subreddit, post_id, "confidence", COMMENTS_PER_POST
        )
        if thread is None or not thread.Comments:
            continue

        for index, comment in enumerate(thread.Comments):
            author_name = comment.Author or "[deleted]"
            if author_name != "[deleted]" and author_name not in seen_authors:
                seen_authors.add(author_name)
                records.append(_make_account(author_name))
            records.append(_post_comment_to_post(subreddit, post_id, index, comment, author_name))

    return records


def _post_comment_to_post(subreddit: str, post_id: str, index: int, comment, author_name: str) -> Post:
    return Post(
        # RedScrapsLib's get_comments reports CommentID/ParentID equal to the
        # post's own ID for every comment in the thread (an upstream bug —
        # verified live), so they can't disambiguate distinct comments here;
        # the hash_id is keyed on thread position instead.
        hash_id=entity_hash(PLATFORM, f"reddit_comment:{post_id}:{index}"),
        platform=PLATFORM,
        author_hash_id=entity_hash(PLATFORM, author_name),
        content=comment.Body or "",
        # get_comments's Comment type carries no timestamp, so this reflects
        # collection time, not the true comment time (same caveat as
        # _home_post_to_post above).
        timestamp=datetime.now(timezone.utc),
        raw_data={
            "kind": "comment",
            "subreddit": subreddit,
            "post_id": post_id,
            # As reported by RedScrapsLib — unreliable, see note above.
            "comment_id": comment.CommentID,
            "parent_id": comment.ParentID,
        },
    )
