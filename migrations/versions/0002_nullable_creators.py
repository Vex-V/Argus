"""make collection_jobs.created_by and watchlist.added_by nullable

Phase 1 lets internal services (and the demo verification flow) create
collection jobs and watchlist entries without an authenticated user. The
actor is still recorded when a JWT is supplied.

Revision ID: 0002_nullable_creators
Revises: 0001_initial
Create Date: 2026-07-03
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0002_nullable_creators"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("collection_jobs", "created_by", nullable=True)
    op.alter_column("watchlist", "added_by", nullable=True)


def downgrade() -> None:
    op.alter_column("collection_jobs", "created_by", nullable=False)
    op.alter_column("watchlist", "added_by", nullable=False)
