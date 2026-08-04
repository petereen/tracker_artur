"""add work reports, revisions and Telegram prompts

Revision ID: k9l0m1n2o3p4
Revises: j8k9l0m1n2o3
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "k9l0m1n2o3p4"
down_revision: Union[str, Sequence[str], None] = "j8k9l0m1n2o3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "work_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("report_type", sa.Text(), nullable=False),
        sa.Column("period_date", sa.Date(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="awaiting"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_revision_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("report_type IN ('daily','monthly','next_month_plan')", name="ck_work_reports_type"),
        sa.CheckConstraint("status IN ('awaiting','draft','editing','approved')", name="ck_work_reports_status"),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("employee_id", "report_type", "period_date", name="uq_work_report_period"),
    )
    op.create_index("ix_work_reports_employee_period", "work_reports", ["employee_id", "period_date"])
    op.create_index("ix_work_reports_type_status", "work_reports", ["report_type", "status"])

    op.create_table(
        "work_report_revisions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("report_id", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("status IN ('draft','superseded','deleted','approved')", name="ck_work_report_revisions_status"),
        sa.ForeignKeyConstraint(["report_id"], ["work_reports.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_work_report_revisions_report", "work_report_revisions", ["report_id"])
    op.create_foreign_key(
        "fk_work_reports_approved_revision",
        "work_reports",
        "work_report_revisions",
        ["approved_revision_id"], ["id"], ondelete="SET NULL",
    )

    op.create_table(
        "work_report_prompts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("report_id", sa.Integer(), nullable=False),
        sa.Column("prompt_type", sa.Text(), nullable=False),
        sa.Column("prompt_date", sa.Date(), nullable=False),
        sa.Column("telegram_chat_id", sa.Text(), nullable=False),
        sa.Column("telegram_message_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["report_id"], ["work_reports.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("report_id", "prompt_type", "prompt_date", name="uq_work_report_prompt_day"),
    )
    op.create_index("ix_work_report_prompts_reply", "work_report_prompts", ["telegram_chat_id", "telegram_message_id"])


def downgrade() -> None:
    op.drop_index("ix_work_report_prompts_reply", table_name="work_report_prompts")
    op.drop_table("work_report_prompts")
    op.drop_constraint("fk_work_reports_approved_revision", "work_reports", type_="foreignkey")
    op.drop_index("ix_work_report_revisions_report", table_name="work_report_revisions")
    op.drop_table("work_report_revisions")
    op.drop_index("ix_work_reports_type_status", table_name="work_reports")
    op.drop_index("ix_work_reports_employee_period", table_name="work_reports")
    op.drop_table("work_reports")
