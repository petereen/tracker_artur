"""add durable one-to-one chat calls

Revision ID: v1w2x3y4z5a6
Revises: u0v1w2x3y4z5
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "v1w2x3y4z5a6"
down_revision: Union[str, Sequence[str], None] = "u0v1w2x3y4z5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_calls",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("chat_conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("caller_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("callee_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("call_type", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False, server_default="ringing"),
        sa.Column("outcome", sa.String(length=12)),
        sa.Column("end_reason", sa.Text()),
        sa.Column("initiated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column("connected_at", sa.DateTime(timezone=True)),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("duration_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint("call_type IN ('audio','video')", name="ck_chat_calls_type"),
        sa.CheckConstraint("status IN ('ringing','accepted','connected','ended')", name="ck_chat_calls_status"),
        sa.CheckConstraint("outcome IS NULL OR outcome IN ('completed','missed','declined','canceled','failed')", name="ck_chat_calls_outcome"),
        sa.CheckConstraint("caller_account_id <> callee_account_id", name="ck_chat_calls_distinct_peers"),
    )
    op.create_index("ix_chat_calls_conversation_started", "chat_calls", ["conversation_id", "initiated_at"])
    op.add_column("chat_messages", sa.Column("kind", sa.String(length=12), nullable=False, server_default="text"))
    op.add_column("chat_messages", sa.Column("call_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_chat_messages_call_id", "chat_messages", "chat_calls", ["call_id"], ["id"], ondelete="CASCADE")
    op.create_unique_constraint("uq_chat_messages_call_id", "chat_messages", ["call_id"])
    op.create_check_constraint("ck_chat_messages_kind_shape", "chat_messages", "(kind = 'text' AND call_id IS NULL) OR (kind = 'call' AND call_id IS NOT NULL AND sender_account_id IS NULL AND body IS NULL)")


def downgrade() -> None:
    op.drop_constraint("ck_chat_messages_kind_shape", "chat_messages", type_="check")
    op.drop_constraint("uq_chat_messages_call_id", "chat_messages", type_="unique")
    op.drop_constraint("fk_chat_messages_call_id", "chat_messages", type_="foreignkey")
    op.drop_column("chat_messages", "call_id")
    op.drop_column("chat_messages", "kind")
    op.drop_index("ix_chat_calls_conversation_started", table_name="chat_calls")
    op.drop_table("chat_calls")
