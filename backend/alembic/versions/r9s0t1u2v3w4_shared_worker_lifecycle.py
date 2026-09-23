"""unify worker active state and preserve archived payroll identities

Revision ID: r9s0t1u2v3w4
Revises: r8s9t0u1v2w3
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op


revision: str = "r9s0t1u2v3w4"
down_revision: Union[str, Sequence[str], None] = "r8s9t0u1v2w3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("employees", sa.Column("deleted_at", sa.DateTime(timezone=True)))
    op.add_column("employees", sa.Column("deleted_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")))
    op.create_index("ix_employees_deleted_at", "employees", ["deleted_at"])
    op.add_column("employee_payroll_profiles", sa.Column("component_overrides", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.add_column("payslips", sa.Column("payout_snapshot_ciphertext", sa.Text()))
    # HR's old employment status was independently editable. Preserve the
    # conservative interpretation of any inactive/terminated worker.
    op.execute(sa.text("""
        UPDATE employees AS e
        SET is_active = false
        FROM employee_details AS d
        WHERE d.employee_id = e.id
          AND d.organization_id = e.organization_id
          AND d.employment_status <> 'active'
    """))
    op.execute(sa.text("""
        UPDATE user_accounts AS ua
        SET status = 'disabled'
        FROM employees AS e
        WHERE ua.employee_id = e.id
          AND ua.organization_id = e.organization_id
          AND e.is_active = false
          AND ua.status = 'active'
    """))


def downgrade() -> None:
    op.drop_column("payslips", "payout_snapshot_ciphertext")
    op.drop_column("employee_payroll_profiles", "component_overrides")
    op.drop_index("ix_employees_deleted_at", table_name="employees")
    op.drop_column("employees", "deleted_by_account_id")
    op.drop_column("employees", "deleted_at")
