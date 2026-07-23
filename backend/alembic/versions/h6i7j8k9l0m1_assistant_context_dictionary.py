"""store unknown-request terms and approved assistant context examples

Revision ID: h6i7j8k9l0m1
Revises: g5h6i7j8k9l0
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "h6i7j8k9l0m1"
down_revision: Union[str, Sequence[str], None] = "g5h6i7j8k9l0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "unknown_assistant_requests",
        sa.Column(
            "terms",
            sa.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
    )
    op.add_column(
        "unknown_assistant_requests",
        sa.Column(
            "reason",
            sa.String(length=80),
            nullable=False,
            server_default="unclassified",
        ),
    )
    op.create_table(
        "assistant_context_examples",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("phrase", sa.Text(), nullable=False),
        sa.Column("phrase_hash", sa.String(length=64), nullable=False),
        sa.Column("intent", sa.String(length=40), nullable=False),
        sa.Column("meaning", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "intent IN ('create_task_draft','get_user_tasks','search_company_knowledge')"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("phrase_hash"),
    )
    op.create_index(
        "ix_assistant_context_examples_phrase_hash",
        "assistant_context_examples",
        ["phrase_hash"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_assistant_context_examples_phrase_hash", table_name="assistant_context_examples")
    op.drop_table("assistant_context_examples")
    op.drop_column("unknown_assistant_requests", "reason")
    op.drop_column("unknown_assistant_requests", "terms")
