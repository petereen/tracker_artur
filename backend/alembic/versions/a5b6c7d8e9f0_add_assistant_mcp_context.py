"""persist deferred MCP discovery context for assistant conversations

Revision ID: b7c8d9e0f1a2
Revises: f5g6h7i8j9k0
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "b7c8d9e0f1a2"
down_revision: Union[str, Sequence[str], None] = "f5g6h7i8j9k0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # This migration was applied on some installations before the migration
    # graph was repaired. Keep retries safe when the column already exists.
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("assistant_conversations")}
    if "mcp_context" not in columns:
        op.add_column(
            "assistant_conversations",
            sa.Column(
                "mcp_context",
                postgresql.JSONB(),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
        )


def downgrade() -> None:
    op.drop_column("assistant_conversations", "mcp_context")
