"""add multiple remote and in-person work-time intervals

Revision ID: p4q5r6s7t8u9
Revises: o3p4q5r6s7
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "p4q5r6s7t8u9"
down_revision: Union[str, Sequence[str], None] = "o3p4q5r6s7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "work_time_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("report_id", sa.Integer(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("mode IN ('in_person','remote')", name="ck_work_time_entries_mode"),
        sa.CheckConstraint("ended_at IS NULL OR ended_at >= started_at", name="ck_work_time_entries_range"),
        sa.ForeignKeyConstraint(["report_id"], ["work_reports.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_work_time_entries_report_id", "work_time_entries", ["report_id"])
    # Preserve legacy one-pair records as in-person intervals.
    op.execute(
        """
        INSERT INTO work_time_entries (report_id, mode, started_at, ended_at)
        SELECT id, 'in_person', COALESCE(started_at, ended_at), ended_at
        FROM work_reports
        WHERE report_type = 'daily' AND (started_at IS NOT NULL OR ended_at IS NOT NULL)
        """
    )


def downgrade() -> None:
    op.drop_index("ix_work_time_entries_report_id", table_name="work_time_entries")
    op.drop_table("work_time_entries")
