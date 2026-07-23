"""add unknown assistant request review queue

Revision ID: g5h6i7j8k9l0
Revises: f4a5b6c7d8e9
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "g5h6i7j8k9l0"
down_revision: Union[str, Sequence[str], None] = "f4a5b6c7d8e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "unknown_assistant_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("text_hash", sa.String(length=64), nullable=False),
        sa.Column("language", sa.String(length=8), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), server_default="1", nullable=False),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('pending','reviewed','dismissed')"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("text_hash"),
    )
    op.create_index(
        "ix_unknown_assistant_requests_status",
        "unknown_assistant_requests",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_unknown_assistant_requests_status", table_name="unknown_assistant_requests")
    op.drop_table("unknown_assistant_requests")
