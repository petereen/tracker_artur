"""add task location and private planning calendar

Revision ID: u9v0w1x2y3z4
Revises: t8u9v0w1x2y3
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "u9v0w1x2y3z4"
down_revision: Union[str, Sequence[str], None] = "t8u9v0w1x2y3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("work_location_type", sa.String(length=16), nullable=True))
    op.add_column("tasks", sa.Column("work_location", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_tasks_work_location_type",
        "tasks",
        "work_location_type IS NULL OR work_location_type IN ('office','remote','custom')",
    )
    op.create_table(
        "personal_time_blocks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("ends_at > starts_at", name="ck_personal_time_blocks_positive_duration"),
    )
    op.create_index("ix_personal_time_blocks_account_start", "personal_time_blocks", ["account_id", "starts_at"])
    # Seed one canonical daily template per organization from the legacy bank.
    # Existing templates are preserved and no historical answer rows are copied.
    op.execute(sa.text("""
        INSERT INTO checkin_templates (organization_id, name, cadence, is_active)
        SELECT o.id, 'Daily check-in', 'daily', true
        FROM organizations o
        WHERE EXISTS (SELECT 1 FROM questions)
          AND NOT EXISTS (SELECT 1 FROM checkin_templates ct WHERE ct.organization_id = o.id AND ct.is_active = true)
    """))
    op.execute(sa.text("""
        INSERT INTO checkin_questions (template_id, prompt, answer_type, choices, is_required, position)
        SELECT ct.id, jsonb_build_object('mn', q.text), q.answer_type, q.options, q.is_required, q.sort_order
        FROM checkin_templates ct
        JOIN organizations o ON o.id = ct.organization_id
        CROSS JOIN questions q
        WHERE ct.name = 'Daily check-in'
          AND NOT EXISTS (SELECT 1 FROM checkin_questions cq WHERE cq.template_id = ct.id)
    """))
    op.execute(sa.text("""
        INSERT INTO checkins (employee_id, template_id, local_date, status, source, started_at, submitted_at)
        SELECT ss.employee_id, ct.id, ss.date, 'submitted', 'telegram', ss.started_at, ss.completed_at
        FROM survey_sessions ss
        JOIN user_accounts ua ON ua.employee_id = ss.employee_id
        JOIN checkin_templates ct ON ct.organization_id = ua.organization_id AND ct.is_active = true
        WHERE ss.type = 'evening' AND ss.status = 'completed'
        ON CONFLICT ON CONSTRAINT uq_checkins_employee_template_date DO NOTHING
    """))


def downgrade() -> None:
    op.drop_table("personal_time_blocks")
    op.drop_constraint("ck_tasks_work_location_type", "tasks", type_="check")
    op.drop_column("tasks", "work_location")
    op.drop_column("tasks", "work_location_type")
