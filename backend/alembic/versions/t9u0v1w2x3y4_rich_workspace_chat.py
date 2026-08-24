"""add rich workspace chat capabilities

Revision ID: t9u0v1w2x3y4
Revises: s8t9u0v1w2x3
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "t9u0v1w2x3y4"
down_revision: Union[str, Sequence[str], None] = "s8t9u0v1w2x3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chat_participants", sa.Column("pinned_at", sa.DateTime(timezone=True)))
    op.add_column("chat_participants", sa.Column("archived_at", sa.DateTime(timezone=True)))
    op.add_column("chat_participants", sa.Column("muted_until", sa.DateTime(timezone=True)))

    op.alter_column("chat_messages", "body", existing_type=sa.Text(), nullable=True)
    op.drop_constraint("ck_chat_messages_body_length", "chat_messages", type_="check")
    op.create_check_constraint("ck_chat_messages_body_length", "chat_messages", "body IS NULL OR char_length(body) BETWEEN 1 AND 4000")
    op.add_column("chat_messages", sa.Column("reply_to_message_id", sa.Integer()))
    op.add_column("chat_messages", sa.Column("thread_root_message_id", sa.Integer()))
    op.add_column("chat_messages", sa.Column("forwarded_from_message_id", sa.Integer()))
    op.add_column("chat_messages", sa.Column("forwarded_sender_name", sa.Text()))
    op.add_column("chat_messages", sa.Column("edited_at", sa.DateTime(timezone=True)))
    op.add_column("chat_messages", sa.Column("deleted_at", sa.DateTime(timezone=True)))
    op.add_column("chat_messages", sa.Column("deleted_by_account_id", sa.Integer()))
    op.create_foreign_key("fk_chat_messages_reply_to", "chat_messages", "chat_messages", ["reply_to_message_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_chat_messages_thread_root", "chat_messages", "chat_messages", ["thread_root_message_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_chat_messages_forwarded_from", "chat_messages", "chat_messages", ["forwarded_from_message_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_chat_messages_deleted_by", "chat_messages", "user_accounts", ["deleted_by_account_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_chat_messages_thread_root", "chat_messages", ["thread_root_message_id", "id"])
    op.execute("CREATE INDEX ix_chat_messages_search ON chat_messages USING gin (to_tsvector('simple', COALESCE(body, ''))) WHERE deleted_at IS NULL")

    op.create_table(
        "chat_attachments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("chat_conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("message_id", sa.Integer(), sa.ForeignKey("chat_messages.id", ondelete="CASCADE")),
        sa.Column("staged_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False, unique=True),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("media_kind", sa.String(length=12), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("duration_seconds", sa.Float()),
        sa.Column("scan_status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("media_kind IN ('image','video','audio','document')", name="ck_chat_attachments_media_kind"),
        sa.CheckConstraint("size > 0", name="ck_chat_attachments_positive_size"),
    )
    op.create_index("ix_chat_attachments_message", "chat_attachments", ["message_id", "id"])
    op.create_index("ix_chat_attachments_staged_expiry", "chat_attachments", ["message_id", "expires_at"])
    op.execute("CREATE INDEX ix_chat_attachments_filename_search ON chat_attachments USING gin (to_tsvector('simple', filename))")

    op.create_table(
        "chat_message_reactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("message_id", sa.Integer(), sa.ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("emoji", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("message_id", "account_id", "emoji", name="uq_chat_message_reaction_actor"),
    )
    op.create_index("ix_chat_message_reactions_message", "chat_message_reactions", ["message_id", "emoji"])
    op.create_table(
        "chat_message_stars",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("message_id", sa.Integer(), sa.ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("message_id", "account_id", name="uq_chat_message_star_actor"),
    )
    op.create_table(
        "chat_message_pins",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("chat_conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("message_id", sa.Integer(), sa.ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("pinned_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("message_id", name="uq_chat_message_pin"),
    )
    op.create_index("ix_chat_message_pins_conversation", "chat_message_pins", ["conversation_id", "created_at"])
    op.create_table(
        "chat_message_hidden",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("message_id", sa.Integer(), sa.ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("hidden_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("message_id", "account_id", name="uq_chat_message_hidden_actor"),
    )


def downgrade() -> None:
    op.drop_table("chat_message_hidden")
    op.drop_index("ix_chat_message_pins_conversation", table_name="chat_message_pins")
    op.drop_table("chat_message_pins")
    op.drop_table("chat_message_stars")
    op.drop_index("ix_chat_message_reactions_message", table_name="chat_message_reactions")
    op.drop_table("chat_message_reactions")
    op.execute("DROP INDEX IF EXISTS ix_chat_attachments_filename_search")
    op.drop_index("ix_chat_attachments_staged_expiry", table_name="chat_attachments")
    op.drop_index("ix_chat_attachments_message", table_name="chat_attachments")
    op.drop_table("chat_attachments")
    op.execute("DROP INDEX IF EXISTS ix_chat_messages_search")
    op.drop_index("ix_chat_messages_thread_root", table_name="chat_messages")
    op.drop_constraint("fk_chat_messages_deleted_by", "chat_messages", type_="foreignkey")
    op.drop_constraint("fk_chat_messages_forwarded_from", "chat_messages", type_="foreignkey")
    op.drop_constraint("fk_chat_messages_thread_root", "chat_messages", type_="foreignkey")
    op.drop_constraint("fk_chat_messages_reply_to", "chat_messages", type_="foreignkey")
    for column in ("deleted_by_account_id", "deleted_at", "edited_at", "forwarded_sender_name", "forwarded_from_message_id", "thread_root_message_id", "reply_to_message_id"):
        op.drop_column("chat_messages", column)
    op.drop_constraint("ck_chat_messages_body_length", "chat_messages", type_="check")
    op.execute("UPDATE chat_messages SET body = '[attachment]' WHERE body IS NULL")
    op.alter_column("chat_messages", "body", existing_type=sa.Text(), nullable=False)
    op.create_check_constraint("ck_chat_messages_body_length", "chat_messages", "char_length(body) BETWEEN 1 AND 4000")
    op.drop_column("chat_participants", "muted_until")
    op.drop_column("chat_participants", "archived_at")
    op.drop_column("chat_participants", "pinned_at")
