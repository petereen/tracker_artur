"""add persistent user notifications

Revision ID: x2y3z4a5b6c7
Revises: w1x2y3z4a5b6
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "x2y3z4a5b6c7"
down_revision: Union[str, Sequence[str], None] = "w1x2y3z4a5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("recipient_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("recipient_employee_id", sa.Integer(), sa.ForeignKey("employees.id", ondelete="SET NULL")),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("domain_events.id", ondelete="SET NULL")),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("target_url", sa.Text()),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("telegram_status", sa.Text(), nullable=False, server_default="unavailable"),
        sa.Column("dedup_key", sa.Text(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("dedup_key", name="uq_user_notifications_dedup_key"),
    )
    op.create_index("ix_user_notifications_account_unread", "user_notifications", ["recipient_account_id", "read_at", "id"])
    op.add_column("notification_outbox", sa.Column("user_notification_id", sa.Integer(), sa.ForeignKey("user_notifications.id", ondelete="CASCADE")))


def downgrade() -> None:
    op.drop_column("notification_outbox", "user_notification_id")
    op.drop_index("ix_user_notifications_account_unread", table_name="user_notifications")
    op.drop_table("user_notifications")
