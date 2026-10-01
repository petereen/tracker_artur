"""half-yearly reports and platform roles on custom access roles

* ``work_reports.report_type`` accepts ``half_yearly`` (report policy).
* ``erp_access_roles.system_roles``: platform roles (manager, hr, …) that a
  custom access role grants on top of its module capabilities, so an admin
  can build a real role in Settings → Хэрэглэгч ба эрх → Үүрэг ба эрх.

Revision ID: e1f2a3b4c5d6
Revises: d4e8f1a2b3c9
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, Sequence[str], None] = "d4e8f1a2b3c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_TYPES = "report_type IN ('daily','weekly','monthly','quarterly','half_yearly','yearly','custom','next_month_plan','daily_test','monthly_test','next_month_plan_test')"
OLD_TYPES = "report_type IN ('daily','weekly','monthly','quarterly','yearly','custom','next_month_plan','daily_test','monthly_test','next_month_plan_test')"


def upgrade() -> None:
    op.drop_constraint("ck_work_reports_type", "work_reports", type_="check")
    op.create_check_constraint("ck_work_reports_type", "work_reports", NEW_TYPES)
    op.add_column(
        "erp_access_roles",
        sa.Column("system_roles", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )


def downgrade() -> None:
    op.drop_column("erp_access_roles", "system_roles")
    op.execute("DELETE FROM work_reports WHERE report_type = 'half_yearly'")
    op.drop_constraint("ck_work_reports_type", "work_reports", type_="check")
    op.create_check_constraint("ck_work_reports_type", "work_reports", OLD_TYPES)
