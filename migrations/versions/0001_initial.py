"""initial schema — pgvector extension + all Phase 0 tables

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-03
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # pgvector extension (image ships it pre-installed; this enables it).
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("role", sa.String(32), nullable=False, server_default="investigator"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "cases",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("warrant_id", sa.String(128), nullable=False),
        sa.Column("created_by", UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="open"),
    )
    op.create_index("ix_cases_warrant_id", "cases", ["warrant_id"])
    op.create_index("ix_cases_created_by", "cases", ["created_by"])

    op.create_table(
        "accounts",
        sa.Column("hash_id", sa.String(64), primary_key=True),
        sa.Column("platform", sa.String(64), nullable=False),
        sa.Column("username", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255)),
        sa.Column("bio", sa.Text()),
        sa.Column("avatar_url", sa.Text()),
        sa.Column("profile_url", sa.Text()),
        sa.Column("follower_count", sa.BigInteger()),
        sa.Column("following_count", sa.BigInteger()),
        sa.Column("email", sa.String(320)),
        sa.Column("phone", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("last_scraped", sa.DateTime(timezone=True)),
        sa.Column("raw_data", JSONB()),
        sa.Column("face_embedding", Vector(512)),
        sa.Column("text_embedding", Vector(384)),
    )
    op.create_index("ix_accounts_platform", "accounts", ["platform"])
    op.create_index("ix_accounts_username", "accounts", ["username"])
    op.create_index("ix_accounts_email", "accounts", ["email"])
    op.create_index("ix_accounts_phone", "accounts", ["phone"])

    op.create_table(
        "posts",
        sa.Column("hash_id", sa.String(64), primary_key=True),
        sa.Column("platform", sa.String(64), nullable=False),
        sa.Column("author_hash_id", sa.String(64), sa.ForeignKey("accounts.hash_id"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("translated_content", sa.Text()),
        sa.Column("detected_language", sa.String(16)),
        sa.Column("timestamp", sa.DateTime(timezone=True)),
        sa.Column("geo_lat", sa.Float()),
        sa.Column("geo_lng", sa.Float()),
        sa.Column("media_urls", JSONB()),
        sa.Column("hashtags", JSONB()),
        sa.Column("engagement", JSONB()),
        sa.Column("raw_data", JSONB()),
        sa.Column("text_embedding", Vector(384)),
    )
    op.create_index("ix_posts_platform", "posts", ["platform"])
    op.create_index("ix_posts_author_hash_id", "posts", ["author_hash_id"])
    op.create_index("ix_posts_timestamp", "posts", ["timestamp"])

    op.create_table(
        "images",
        sa.Column("hash_id", sa.String(64), primary_key=True),
        sa.Column("source_url", sa.Text()),
        sa.Column("source_entity_id", sa.String(64)),
        sa.Column("image_type", sa.String(32), nullable=False, server_default="avatar"),
        sa.Column("face_detected", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("face_embedding", Vector(512)),
        sa.Column("phash", sa.Text()),
        sa.Column("captured_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_images_source_entity_id", "images", ["source_entity_id"])

    op.create_table(
        "findings",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("entity_a_id", sa.String(64), nullable=False),
        sa.Column("entity_b_id", sa.String(64), nullable=False),
        sa.Column("match_score", sa.Float(), nullable=False),
        sa.Column("analyzer_scores", JSONB()),
        sa.Column("evidence", JSONB()),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("case_id", UUID(as_uuid=False), sa.ForeignKey("cases.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_findings_entity_a_id", "findings", ["entity_a_id"])
    op.create_index("ix_findings_entity_b_id", "findings", ["entity_b_id"])
    op.create_index("ix_findings_case_id", "findings", ["case_id"])

    op.create_table(
        "collection_jobs",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("platform", sa.String(64), nullable=False),
        sa.Column("region", JSONB()),
        sa.Column("keywords", JSONB()),
        sa.Column("hashtags", JSONB()),
        sa.Column("languages", JSONB()),
        sa.Column("telegram_channels", JSONB()),
        sa.Column("subreddits", JSONB()),
        sa.Column("interval_minutes", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_by", UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "watchlist",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("entity_hash_id", sa.String(64), nullable=False),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("case_id", UUID(as_uuid=False), sa.ForeignKey("cases.id"), nullable=False),
        sa.Column("added_by", UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_watchlist_entity_hash_id", "watchlist", ["entity_hash_id"])
    op.create_index("ix_watchlist_case_id", "watchlist", ["case_id"])

    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("actor_id", sa.String(64)),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("target", sa.Text()),
        sa.Column("justification", sa.Text()),
        sa.Column("case_id", sa.String(64)),
        sa.Column("warrant_id", sa.String(128)),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("content_hash", sa.String(64)),
        sa.Column("prev_hash", sa.String(64)),
    )
    op.create_index("ix_audit_log_actor_id", "audit_log", ["actor_id"])
    op.create_index("ix_audit_log_case_id", "audit_log", ["case_id"])


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("watchlist")
    op.drop_table("collection_jobs")
    op.drop_table("findings")
    op.drop_table("images")
    op.drop_table("posts")
    op.drop_table("accounts")
    op.drop_table("cases")
    op.drop_table("users")
    op.execute("DROP EXTENSION IF EXISTS vector;")
