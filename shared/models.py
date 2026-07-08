"""SQLAlchemy ORM models — the PostgreSQL storage contract.

pgvector columns hold face (512-dim ArcFace) and text (384-dim MiniLM)
embeddings. All JSON payloads use JSONB. UUID primary keys are generated
application-side so records can be referenced before they hit the DB.
"""
import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


# --------------------------------------------------------------------------
# Auth & cases
# --------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="investigator")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    warrant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    created_by: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")


# --------------------------------------------------------------------------
# Core data entities
# --------------------------------------------------------------------------
class Account(Base):
    __tablename__ = "accounts"

    hash_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    platform: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    username: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    display_name: Mapped[str | None] = mapped_column(String(255))
    bio: Mapped[str | None] = mapped_column(Text)
    avatar_url: Mapped[str | None] = mapped_column(Text)
    profile_url: Mapped[str | None] = mapped_column(Text)
    follower_count: Mapped[int | None] = mapped_column(BigInteger)
    following_count: Mapped[int | None] = mapped_column(BigInteger)
    email: Mapped[str | None] = mapped_column(String(320), index=True)
    phone: Mapped[str | None] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_scraped: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_data: Mapped[dict] = mapped_column(JSONB, default=dict)
    breach_history: Mapped[list] = mapped_column(JSONB, default=list)
    face_embedding: Mapped[list[float] | None] = mapped_column(Vector(512))
    text_embedding: Mapped[list[float] | None] = mapped_column(Vector(384))


class Post(Base):
    __tablename__ = "posts"

    hash_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    platform: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    author_hash_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("accounts.hash_id"), nullable=False, index=True
    )
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    translated_content: Mapped[str | None] = mapped_column(Text)
    detected_language: Mapped[str | None] = mapped_column(String(16))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    geo_lat: Mapped[float | None] = mapped_column(Float)
    geo_lng: Mapped[float | None] = mapped_column(Float)
    media_urls: Mapped[list] = mapped_column(JSONB, default=list)
    hashtags: Mapped[list] = mapped_column(JSONB, default=list)
    engagement: Mapped[dict] = mapped_column(JSONB, default=dict)
    raw_data: Mapped[dict] = mapped_column(JSONB, default=dict)
    text_embedding: Mapped[list[float] | None] = mapped_column(Vector(384))


class Image(Base):
    __tablename__ = "images"

    hash_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_url: Mapped[str | None] = mapped_column(Text)
    source_entity_id: Mapped[str | None] = mapped_column(String(64), index=True)
    image_type: Mapped[str] = mapped_column(String(32), default="avatar", nullable=False)
    face_detected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    face_embedding: Mapped[list[float] | None] = mapped_column(Vector(512))
    phash: Mapped[str | None] = mapped_column(Text)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Finding(Base):
    __tablename__ = "findings"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    entity_a_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_b_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    match_score: Mapped[float] = mapped_column(Float, nullable=False)
    analyzer_scores: Mapped[dict] = mapped_column(JSONB, default=dict)
    evidence: Mapped[list] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    case_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("cases.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# --------------------------------------------------------------------------
# Collection / watchlist (tables created now; used from Phase 1 onward)
# --------------------------------------------------------------------------
class CollectionJob(Base):
    __tablename__ = "collection_jobs"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    platform: Mapped[str] = mapped_column(String(64), nullable=False)
    region: Mapped[dict] = mapped_column(JSONB, default=dict)
    keywords: Mapped[list] = mapped_column(JSONB, default=list)
    hashtags: Mapped[list] = mapped_column(JSONB, default=list)
    languages: Mapped[list] = mapped_column(JSONB, default=list)
    telegram_channels: Mapped[list] = mapped_column(JSONB, default=list)
    subreddits: Mapped[list] = mapped_column(JSONB, default=list)
    interval_minutes: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Watchlist(Base):
    __tablename__ = "watchlist"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    entity_hash_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    case_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("cases.id"), nullable=False, index=True
    )
    added_by: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id"), nullable=True
    )
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# --------------------------------------------------------------------------
# Compliance — hash-chained, append-only audit trail
# --------------------------------------------------------------------------
class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    actor_id: Mapped[str | None] = mapped_column(String(64), index=True)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    target: Mapped[str | None] = mapped_column(Text)
    justification: Mapped[str | None] = mapped_column(Text)
    case_id: Mapped[str | None] = mapped_column(String(64), index=True)
    warrant_id: Mapped[str | None] = mapped_column(String(128))
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    content_hash: Mapped[str | None] = mapped_column(String(64))
    prev_hash: Mapped[str | None] = mapped_column(String(64))
