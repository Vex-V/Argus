"""Reddit provider service (port 8023).

Four on-demand fetches via RedScrapsLib: subreddit posts, a user's posts, a
user's comments, and comments on a specific post. Stateless: returns Account
+ Post records, does not persist. Each route returns an empty result set
(HTTP 200) when RedScrapsLib is not installed.
"""
import logging

from fastapi import FastAPI
from pydantic import BaseModel, Field

from shared.cors import add_cors
from shared.evidence import capture_provenance
from shared.schemas import ServiceResponse

from .provider import (
    fetch_post_comments,
    fetch_subreddit_posts,
    fetch_user_comments,
    fetch_user_posts,
)

logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="Argus — Reddit Provider",
    version="0.1.0",
    description="On-demand subreddit/user/comment fetches via RedScrapsLib.",
)

add_cors(app)


class RedditSubredditRequest(BaseModel):
    subreddits: list[str] = Field(default_factory=list)


class RedditUserRequest(BaseModel):
    usernames: list[str] = Field(default_factory=list)


class RedditPostTarget(BaseModel):
    subreddit: str
    post_id: str


class RedditCommentsRequest(BaseModel):
    posts: list[RedditPostTarget] = Field(default_factory=list)


@app.post("/providers/reddit/subreddit", response_model=ServiceResponse, tags=["provider"])
async def reddit_subreddit(request: RedditSubredditRequest) -> ServiceResponse:
    records = await fetch_subreddit_posts(request.subreddits)
    return ServiceResponse(
        results=[r.model_dump(mode="json") for r in records],
        provenance=capture_provenance("reddit_provider"),
    )


@app.post("/providers/reddit/user/posts", response_model=ServiceResponse, tags=["provider"])
async def reddit_user_posts(request: RedditUserRequest) -> ServiceResponse:
    records = await fetch_user_posts(request.usernames)
    return ServiceResponse(
        results=[r.model_dump(mode="json") for r in records],
        provenance=capture_provenance("reddit_provider"),
    )


@app.post("/providers/reddit/user/comments", response_model=ServiceResponse, tags=["provider"])
async def reddit_user_comments(request: RedditUserRequest) -> ServiceResponse:
    records = await fetch_user_comments(request.usernames)
    return ServiceResponse(
        results=[r.model_dump(mode="json") for r in records],
        provenance=capture_provenance("reddit_provider"),
    )


@app.post("/providers/reddit/comments", response_model=ServiceResponse, tags=["provider"])
async def reddit_comments(request: RedditCommentsRequest) -> ServiceResponse:
    records = await fetch_post_comments([p.model_dump() for p in request.posts])
    return ServiceResponse(
        results=[r.model_dump(mode="json") for r in records],
        provenance=capture_provenance("reddit_provider"),
    )


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok", "service": "reddit_provider"}
