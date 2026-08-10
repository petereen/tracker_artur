"""add multiple task reviewers

Revision ID: c1d2e3f4g5h6
Revises: z4a5b6c7d8e9
"""
from alembic import op
import sqlalchemy as sa

revision = "c1d2e3f4g5h6"
down_revision = "z4a5b6c7d8e9"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        "task_reviewers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("task_id", "employee_id", name="uq_task_reviewers"),
    )
    op.create_index("ix_task_reviewers_employee_workflow", "task_reviewers", ["employee_id", "task_id"])
    op.execute("INSERT INTO task_reviewers (task_id, employee_id) SELECT id, reviewer_id FROM tasks WHERE reviewer_id IS NOT NULL")

def downgrade() -> None:
    op.drop_index("ix_task_reviewers_employee_workflow", table_name="task_reviewers")
    op.drop_table("task_reviewers")
