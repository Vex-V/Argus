"""Pydantic schemas — the wire contracts the Argus services speak.

Kept intentionally simple. The entity types mirror the ORM models in
``models.py`` but are the shapes that cross the network, not the DB rows.
"""
from datetime import datetime

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------
# Generic envelope every service returns
# --------------------------------------------------------------------------
class ServiceResponse(BaseModel):
    results: list[dict] = Field(default_factory=list)
    provenance: dict = Field(default_factory=dict)  # source_service, timestamp, etc.
    errors: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Core entity types (produced by the providers)
# --------------------------------------------------------------------------
class Account(BaseModel):
    hash_id: str                       # SHA-256 of (platform + username)
    platform: str                      # "telegram", "reddit", etc.
    username: str
    display_name: str | None = None
    bio: str | None = None
    avatar_url: str | None = None
    profile_url: str | None = None
    follower_count: int | None = None
    following_count: int | None = None
    email: str | None = None
    phone: str | None = None
    created_at: datetime | None = None
    last_scraped: datetime | None = None
    raw_data: dict = Field(default_factory=dict)  # platform-specific fields
    breach_history: list = Field(default_factory=list)


class Post(BaseModel):
    hash_id: str                       # SHA-256 of (platform + post_id)
    platform: str
    author_hash_id: str                # links to Account
    content: str
    translated_content: str | None = None
    detected_language: str | None = None
    timestamp: datetime
    geo_lat: float | None = None
    geo_lng: float | None = None
    media_urls: list[str] = Field(default_factory=list)
    hashtags: list[str] = Field(default_factory=list)
    engagement: dict = Field(default_factory=dict)  # likes, comments, shares, etc.
    raw_data: dict = Field(default_factory=dict)


# --------------------------------------------------------------------------
# Analyzer request bodies
# --------------------------------------------------------------------------
class UsernameCompareRequest(BaseModel):
    username_a: str
    username_b: str


class TextSimilarityRequest(BaseModel):
    texts_a: list[str] = Field(default_factory=list)
    texts_b: list[str] = Field(default_factory=list)


class TimingRequest(BaseModel):
    timestamps_a: list[float] = Field(default_factory=list)  # unix seconds
    timestamps_b: list[float] = Field(default_factory=list)


class Contact(BaseModel):
    id: str
    weight: float = 1.0                 # interaction strength (comments/mentions > follows)


class ContactsRequest(BaseModel):
    contacts_a: list[Contact] = Field(default_factory=list)
    contacts_b: list[Contact] = Field(default_factory=list)


class FaceCompareRequest(BaseModel):
    image_a: str                        # base64-encoded image bytes
    image_b: str


class ContentProfileRequest(BaseModel):
    posts: list[str] = Field(default_factory=list)
    platform: str = ""
