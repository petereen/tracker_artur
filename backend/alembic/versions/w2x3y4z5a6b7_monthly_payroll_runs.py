"""Persist run-based monthly payroll workflow and archive snapshots."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "w2x3y4z5a6b7"
down_revision = "u2v3w4x5y6z7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "monthly_payroll_months",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("rule_set_id", sa.Integer(), sa.ForeignKey("monthly_payroll_rule_sets.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("rule_snapshot", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("calendar_snapshot", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("closed_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("created_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "year", "month", name="uq_monthly_payroll_month"),
        sa.CheckConstraint("month BETWEEN 1 AND 12", name="ck_monthly_payroll_month_number"),
    )
    op.create_index("ix_monthly_payroll_month_org_status", "monthly_payroll_months", ["organization_id", "status", "year", "month"])
    op.create_table(
        "monthly_payroll_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("month_id", sa.Integer(), sa.ForeignKey("monthly_payroll_months.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_type", sa.String(16), nullable=False),
        sa.Column("pay_date", sa.Date(), nullable=False),
        sa.Column("cutoff_date", sa.Date()),
        sa.Column("department_id", sa.Integer(), sa.ForeignKey("departments.id", ondelete="SET NULL")),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("note", sa.Text()),
        sa.Column("advance_snapshot", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("approved_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("paid_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("paid_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("run_type IN ('advance','final')", name="ck_monthly_payroll_run_type"),
        sa.CheckConstraint("status IN ('draft','approved','paid','closed')", name="ck_monthly_payroll_run_status"),
    )
    op.create_index("ix_monthly_payroll_run_month_date", "monthly_payroll_runs", ["month_id", "pay_date", "run_type"])
    op.create_table(
        "monthly_payroll_run_rows",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("monthly_payroll_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("identity_snapshot", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("profile_snapshot", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("inputs", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("result", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("payout_snapshot_ciphertext", sa.Text()),
        sa.Column("warnings", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("approved_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("run_id", "employee_id", name="uq_monthly_payroll_run_employee"),
    )
    op.create_index("ix_monthly_payroll_run_row_org_worker", "monthly_payroll_run_rows", ["organization_id", "employee_id"])
    op.create_table(
        "monthly_payroll_row_audits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("monthly_payroll_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("row_id", sa.Integer(), sa.ForeignKey("monthly_payroll_run_rows.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("field_name", sa.String(80), nullable=False),
        sa.Column("old_value", postgresql.JSONB()),
        sa.Column("new_value", postgresql.JSONB()),
        sa.Column("reason", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "monthly_payroll_archives",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("month_id", sa.Integer(), sa.ForeignKey("monthly_payroll_months.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("closed_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("month_id", "version", name="uq_monthly_payroll_archive_version"),
    )


def downgrade() -> None:
    op.drop_table("monthly_payroll_archives")
    op.drop_table("monthly_payroll_row_audits")
    op.drop_index("ix_monthly_payroll_run_row_org_worker", table_name="monthly_payroll_run_rows")
    op.drop_table("monthly_payroll_run_rows")
    op.drop_index("ix_monthly_payroll_run_month_date", table_name="monthly_payroll_runs")
    op.drop_table("monthly_payroll_runs")
    op.drop_index("ix_monthly_payroll_month_org_status", table_name="monthly_payroll_months")
    op.drop_table("monthly_payroll_months")
