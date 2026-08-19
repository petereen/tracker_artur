"""persist per-user notification priority overrides

Revision ID: a6b7c8d9e0f1
Revises: z4a5b6c7d8e9
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a6b7c8d9e0f1"
down_revision: Union[str, Sequence[str], None] = "z4a5b6c7d8e9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user_notifications", sa.Column("is_priority", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.execute(
        "UPDATE user_notifications SET is_priority = true WHERE kind IN "
        "('task_assigned', 'task_review_requested', 'task_collaboration_updated', 'task_deadline', "
        "'task_overdue', 'monthly_report', 'report_submitted', 'project_member_added', "
        "'project_request_reviewed', 'project_deadline', 'company_plan_created', 'calendar_reminder', 'event')"
    )


def downgrade() -> None:
    op.drop_column("user_notifications", "is_priority")
