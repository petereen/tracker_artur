"""policy-driven report periods and department reports

Adds weekly/quarterly/yearly/custom report types, the period end and custom
period key, and department-level reports. The single per-employee uniqueness
rule becomes two partial unique indexes (personal vs department reports).

Revision ID: e5f6a7b8c9d0
Revises: d1e2f3a4b5c6
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_TYPES = "report_type IN ('daily','weekly','monthly','quarterly','yearly','custom','next_month_plan','daily_test','monthly_test','next_month_plan_test')"
OLD_TYPES = "report_type IN ('daily','monthly','next_month_plan','daily_test','monthly_test','next_month_plan_test')"


def upgrade() -> None:
    op.add_column("work_reports", sa.Column("period_end", sa.Date(), nullable=True))
    op.add_column("work_reports", sa.Column("period_key", sa.Text(), nullable=False, server_default=""))
    op.add_column("work_reports", sa.Column("department_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_work_reports_department", "work_reports", "departments", ["department_id"], ["id"], ondelete="CASCADE",
    )
    op.drop_constraint("ck_work_reports_type", "work_reports", type_="check")
    op.create_check_constraint("ck_work_reports_type", "work_reports", NEW_TYPES)
    op.drop_constraint("uq_work_report_period", "work_reports", type_="unique")
    op.create_index(
        "uq_work_report_personal_period", "work_reports", ["employee_id", "report_type", "period_key", "period_date"],
        unique=True, postgresql_where=sa.text("department_id IS NULL"),
    )
    op.create_index(
        "uq_work_report_department_period", "work_reports", ["department_id", "report_type", "period_key", "period_date"],
        unique=True, postgresql_where=sa.text("department_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.execute("DELETE FROM work_reports WHERE department_id IS NOT NULL OR report_type IN ('weekly','quarterly','yearly','custom')")
    op.drop_index("uq_work_report_department_period", table_name="work_reports")
    op.drop_index("uq_work_report_personal_period", table_name="work_reports")
    op.create_unique_constraint("uq_work_report_period", "work_reports", ["employee_id", "report_type", "period_date"])
    op.drop_constraint("ck_work_reports_type", "work_reports", type_="check")
    op.create_check_constraint("ck_work_reports_type", "work_reports", OLD_TYPES)
    op.drop_constraint("fk_work_reports_department", "work_reports", type_="foreignkey")
    op.drop_column("work_reports", "department_id")
    op.drop_column("work_reports", "period_key")
    op.drop_column("work_reports", "period_end")
