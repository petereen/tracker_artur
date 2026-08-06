"""add ERP reliability workspace entities

Revision ID: v0w1x2y3z4a5
Revises: u9v0w1x2y3z4
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "v0w1x2y3z4a5"
down_revision: Union[str, Sequence[str], None] = "u9v0w1x2y3z4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("employees", sa.Column("phone_number", sa.Text(), nullable=True))
    op.add_column("employees", sa.Column("birthday", sa.Date(), nullable=True))
    op.add_column("employees", sa.Column("work_direction", sa.Text(), nullable=True))
    op.add_column("employees", sa.Column("work_branch", sa.Text(), nullable=True))
    op.create_table(
        "project_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("requested_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("requested_by_employee_id", sa.Integer(), sa.ForeignKey("employees.id", ondelete="SET NULL")),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("reviewer_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("review_note", sa.Text()),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_project_requests_org_status", "project_requests", ["organization_id", "status"])
    op.create_table(
        "calendar_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="CASCADE")),
        sa.Column("created_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("visibility", sa.Text(), nullable=False, server_default="private"),
        sa.Column("title", sa.Text(), nullable=False), sa.Column("description", sa.Text()),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False), sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("remind_at", sa.DateTime(timezone=True)), sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_calendar_entries_org_period", "calendar_entries", ["organization_id", "starts_at"])
    op.create_index("ix_calendar_entries_account_period", "calendar_entries", ["account_id", "starts_at"])
    op.create_table(
        "holiday_records",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=False), sa.Column("holiday_date", sa.Date(), nullable=False), sa.Column("name", sa.Text(), nullable=False), sa.Column("local_name", sa.Text()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")), sa.Column("is_override", sa.Boolean(), nullable=False, server_default=sa.text("false")), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "country_code", "holiday_date", "name", name="uq_holiday_record"),
    )
    op.create_table(
        "assistant_conversations",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False), sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False), sa.Column("title", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_assistant_conversations_account_updated", "assistant_conversations", ["account_id", "updated_at"])
    op.create_table(
        "assistant_messages",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("assistant_conversations.id", ondelete="CASCADE"), nullable=False), sa.Column("role", sa.Text(), nullable=False), sa.Column("content", sa.Text(), nullable=False), sa.Column("action", postgresql.JSONB()), sa.Column("sources", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_assistant_messages_conversation_id", "assistant_messages", ["conversation_id", "id"])


def downgrade() -> None:
    op.drop_table("assistant_messages"); op.drop_table("assistant_conversations")
    op.drop_table("holiday_records"); op.drop_table("calendar_entries"); op.drop_table("project_requests")
    for column in ("work_branch", "work_direction", "birthday", "phone_number"):
        op.drop_column("employees", column)
