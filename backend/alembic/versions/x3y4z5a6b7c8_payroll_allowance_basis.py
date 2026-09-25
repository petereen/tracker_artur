"""meal + commute allowance basis on monthly payroll profiles

Meal and commute become daily rates: FIXED pays them for every planned
workday, WORKED_DAYS for every day actually worked. Existing profiles hold
monthly amounts, so they keep the legacy MONTHLY behaviour until HR re-saves
them with a daily basis.

Revision ID: x3y4z5a6b7c8
Revises: 92b736716ad1
Create Date: 2026-09-25 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "x3y4z5a6b7c8"
down_revision: Union[str, Sequence[str], None] = "92b736716ad1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("monthly_payroll_profiles", sa.Column("allowance_basis", sa.String(16), nullable=True))
    op.execute("UPDATE monthly_payroll_profiles SET allowance_basis = 'MONTHLY'")
    op.alter_column("monthly_payroll_profiles", "allowance_basis", nullable=False, server_default="FIXED")
    op.create_check_constraint(
        "ck_monthly_payroll_allowance_basis", "monthly_payroll_profiles",
        "allowance_basis IN ('MONTHLY','FIXED','WORKED_DAYS')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_monthly_payroll_allowance_basis", "monthly_payroll_profiles", type_="check")
    op.drop_column("monthly_payroll_profiles", "allowance_basis")
