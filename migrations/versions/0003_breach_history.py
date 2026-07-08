"""add breach_history JSONB column to accounts

Stores breach exposure + registered-service data (from C5) alongside each
account so the frontend can show breach history per account.

Revision ID: 0003_breach_history
Revises: 0002_nullable_creators
Create Date: 2026-07-03
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0003_breach_history"
down_revision: Union[str, None] = "0002_nullable_creators"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column("breach_history", JSONB(), server_default="[]", nullable=True),
    )


def downgrade() -> None:
    op.drop_column("accounts", "breach_history")
