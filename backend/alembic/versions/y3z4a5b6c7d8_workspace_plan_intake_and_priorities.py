"""add Telegram plan intake idempotency and normalize task priorities

Revision ID: y3z4a5b6c7d8
Revises: x2y3z4a5b6c7
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "y3z4a5b6c7d8"
down_revision: Union[str, Sequence[str], None] = "x2y3z4a5b6c7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE tasks SET priority = 3 WHERE priority = 4")
    op.add_column("plan_ideas", sa.Column("source_report_id", sa.Integer(), sa.ForeignKey("work_reports.id", ondelete="SET NULL")))
    op.create_unique_constraint("uq_plan_ideas_source_report", "plan_ideas", ["source_report_id"])


def downgrade() -> None:
    op.drop_constraint("uq_plan_ideas_source_report", "plan_ideas", type_="unique")
    op.drop_column("plan_ideas", "source_report_id")
