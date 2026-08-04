"""add isolated report types for the Telegram test command

Revision ID: l0m1n2o3p4q5
Revises: k9l0m1n2o3p4
"""

from typing import Sequence, Union

from alembic import op


revision: str = "l0m1n2o3p4q5"
down_revision: Union[str, Sequence[str], None] = "k9l0m1n2o3p4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("ck_work_reports_type", "work_reports", type_="check")
    op.create_check_constraint(
        "ck_work_reports_type",
        "work_reports",
        "report_type IN ('daily','monthly','next_month_plan','daily_test','monthly_test','next_month_plan_test')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_work_reports_type", "work_reports", type_="check")
    op.create_check_constraint(
        "ck_work_reports_type",
        "work_reports",
        "report_type IN ('daily','monthly','next_month_plan')",
    )
