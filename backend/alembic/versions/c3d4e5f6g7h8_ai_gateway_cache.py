"""add AI gateway semantic response cache

Revision ID: c3d4e5f6g7h8
Revises: z4a5b6c7d8e9
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c3d4e5f6g7h8"
down_revision: Union[str, Sequence[str], None] = "z4a5b6c7d8e9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assistant_semantic_cache",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("prompt_version", sa.String(64), nullable=False),
        sa.Column("language", sa.String(12), nullable=False),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("source_model", sa.String(128), nullable=False),
        sa.Column("usage", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.execute("ALTER TABLE assistant_semantic_cache ADD COLUMN embedding vector(1536) NOT NULL")
    op.create_index("ix_assistant_semantic_cache_expiry", "assistant_semantic_cache", ["expires_at"])
    op.create_index("ix_assistant_semantic_cache_prompt_language", "assistant_semantic_cache", ["prompt_version", "language"])
    op.execute("CREATE INDEX ix_assistant_semantic_cache_embedding_hnsw ON assistant_semantic_cache USING hnsw (embedding vector_cosine_ops)")


def downgrade() -> None:
    op.drop_table("assistant_semantic_cache")
