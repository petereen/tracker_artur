"""add organization workspace chat

Revision ID: s8t9u0v1w2x3
Revises: r7s8t9u0v1w2
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "s8t9u0v1w2x3"
down_revision: Union[str, Sequence[str], None] = "r7s8t9u0v1w2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_conversations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(length=12), nullable=False),
        sa.Column("title", sa.Text()),
        sa.Column("direct_key", sa.Text()),
        sa.Column("created_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("kind IN ('direct','group')", name="ck_chat_conversations_kind"),
        sa.CheckConstraint("(kind = 'direct' AND direct_key IS NOT NULL AND title IS NULL) OR (kind = 'group' AND direct_key IS NULL AND title IS NOT NULL)", name="ck_chat_conversations_shape"),
        sa.UniqueConstraint("organization_id", "direct_key", name="uq_chat_conversations_direct_key"),
    )
    op.create_index("ix_chat_conversations_org_updated", "chat_conversations", ["organization_id", "updated_at", "id"])
    op.create_table(
        "chat_participants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("chat_conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(length=12), nullable=False, server_default="member"),
        sa.Column("visible_after_message_id", sa.Integer()),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("left_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("role IN ('owner','member')", name="ck_chat_participants_role"),
        sa.UniqueConstraint("conversation_id", "account_id", name="uq_chat_participants_conversation_account"),
    )
    op.create_index("ix_chat_participants_account_active", "chat_participants", ["account_id", "left_at", "conversation_id"])
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("chat_conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sender_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("client_nonce", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("char_length(body) BETWEEN 1 AND 4000", name="ck_chat_messages_body_length"),
        sa.UniqueConstraint("conversation_id", "sender_account_id", "client_nonce", name="uq_chat_messages_client_nonce"),
    )
    op.create_index("ix_chat_messages_conversation_id", "chat_messages", ["conversation_id", "id"])
    op.create_table(
        "chat_message_receipts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("message_id", sa.Integer(), sa.ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("read_at IS NULL OR delivered_at IS NOT NULL", name="ck_chat_message_receipts_read_delivered"),
        sa.UniqueConstraint("message_id", "account_id", name="uq_chat_message_receipts_message_account"),
    )
    op.create_index("ix_chat_receipts_account_unread", "chat_message_receipts", ["account_id", "read_at", "message_id"])
    op.create_table(
        "workspace_presence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_workspace_presence_org_seen", "workspace_presence", ["organization_id", "last_seen_at"])


def downgrade() -> None:
    op.drop_table("workspace_presence")
    op.drop_table("chat_message_receipts")
    op.drop_table("chat_messages")
    op.drop_table("chat_participants")
    op.drop_table("chat_conversations")
