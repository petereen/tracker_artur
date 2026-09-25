"""when meal + commute is paid: with the advance or with the remaining pay

ADVANCE adds the month's meal + commute to the advance payment; FINAL pays it
with the remaining (final) payment. Profiles that already used the
WORKED-TO-DATE advance keep their existing behaviour (allowance earned to date
was part of that advance); everything else defaults to FINAL.

Revision ID: a7b8c9d0e1f3
Revises: p1q2r3s4t5u6
Create Date: 2026-09-25 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7b8c9d0e1f3"
down_revision: Union[str, Sequence[str], None] = "p1q2r3s4t5u6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("monthly_payroll_profiles", sa.Column("allowance_payout", sa.String(16), nullable=True))
    op.execute(
        "UPDATE monthly_payroll_profiles SET allowance_payout = "
        "CASE WHEN advance_basis = 'WORKED-TO-DATE' AND allowance_basis <> 'MONTHLY' THEN 'ADVANCE' ELSE 'FINAL' END"
    )
    op.alter_column("monthly_payroll_profiles", "allowance_payout", nullable=False, server_default="FINAL")
    op.create_check_constraint(
        "ck_monthly_payroll_allowance_payout", "monthly_payroll_profiles", "allowance_payout IN ('ADVANCE','FINAL')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_monthly_payroll_allowance_payout", "monthly_payroll_profiles", type_="check")
    op.drop_column("monthly_payroll_profiles", "allowance_payout")
