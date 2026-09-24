"""Add the monthly run based payroll foundation."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "u2v3w4x5y6z7"
down_revision: Union[str, Sequence[str], None] = "s0t1u2v3w4x5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "monthly_payroll_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("salary_type", sa.String(16), nullable=False, server_default="PRORATION"),
        sa.Column("meal_allowance", sa.Numeric(20, 4), nullable=False, server_default="0"),
        sa.Column("commute_allowance", sa.Numeric(20, 4), nullable=False, server_default="0"),
        sa.Column("payment_frequency", sa.String(16), nullable=False, server_default="MONTHLY"),
        sa.Column("pay_days", postgresql.JSONB(), nullable=False, server_default=sa.text("'[25]'::jsonb")),
        sa.Column("advance_basis", sa.String(24), nullable=False, server_default="FIXED"),
        sa.Column("advance_amount", sa.Numeric(20, 4), nullable=False, server_default="0"),
        sa.Column("advance_percent", sa.Numeric(8, 4), nullable=False, server_default="40"),
        sa.Column("advance_values", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("daily_norm_hours", sa.Numeric(8, 4), nullable=False, server_default="8"),
        sa.Column("insured_type", sa.String(32), nullable=False, server_default="01001"),
        sa.Column("tax_relief_eligible", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "employee_id", name="uq_monthly_payroll_profile_employee"),
        sa.CheckConstraint("salary_type IN ('PRORATION','FIXED')", name="ck_monthly_payroll_salary_type"),
        sa.CheckConstraint("payment_frequency IN ('MONTHLY','BIWEEKLY','WEEKLY')", name="ck_monthly_payroll_frequency"),
        sa.CheckConstraint("advance_basis IN ('FIXED','PERCENT','WORKED-TO-DATE')", name="ck_monthly_payroll_advance_basis"),
    )
    op.create_index("ix_monthly_payroll_profiles_organization_id", "monthly_payroll_profiles", ["organization_id"])
    op.create_index("ix_monthly_payroll_profiles_employee_id", "monthly_payroll_profiles", ["employee_id"])

    op.create_table(
        "monthly_payroll_salary_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("profile_id", sa.Integer(), sa.ForeignKey("monthly_payroll_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("monthly_salary", sa.Numeric(20, 4), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("created_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("profile_id", "valid_from", name="uq_monthly_payroll_salary_start"),
    )
    op.create_index("ix_monthly_payroll_salary_effective", "monthly_payroll_salary_history", ["profile_id", "valid_from"])

    op.create_table(
        "monthly_payroll_company_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("legal_company_name", sa.Text()),
        sa.Column("daily_norm_hours", sa.Numeric(8, 4), nullable=False, server_default="8"),
        sa.Column("employer_injury_rate", sa.Numeric(8, 6), nullable=False, server_default="0.005"),
        sa.Column("weekday_overtime_multiplier", sa.Numeric(8, 4), nullable=False, server_default="1.5"),
        sa.Column("rest_day_overtime_multiplier", sa.Numeric(8, 4), nullable=False, server_default="1.5"),
        sa.Column("public_holiday_overtime_multiplier", sa.Numeric(8, 4), nullable=False, server_default="2"),
        sa.Column("default_advance_basis", sa.String(24), nullable=False, server_default="FIXED"),
        sa.Column("default_advance_percent", sa.Numeric(8, 4), nullable=False, server_default="40"),
        sa.Column("deduction_types", postgresql.JSONB(), nullable=False, server_default=sa.text("'[\"Торгууль / сахилгын шийтгэл\", \"Хохирол / ажилтнаас авах авлага\", \"Бусад\"]'::jsonb")),
        sa.Column("salary_expense_account_id", sa.Integer(), sa.ForeignKey("erp_accounts.id", ondelete="SET NULL")),
        sa.Column("employer_shi_account_id", sa.Integer(), sa.ForeignKey("erp_accounts.id", ondelete="SET NULL")),
        sa.Column("advance_clearing_account_id", sa.Integer(), sa.ForeignKey("erp_accounts.id", ondelete="SET NULL")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("employer_injury_rate >= 0.005 AND employer_injury_rate <= 0.025", name="ck_monthly_payroll_injury_rate"),
    )

    op.create_table(
        "monthly_payroll_rule_sets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(16), nullable=False, server_default="published"),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date()),
        sa.Column("minimum_wage", sa.Numeric(20, 4), nullable=False),
        sa.Column("shi_cap_multiplier", sa.Numeric(12, 6), nullable=False, server_default="10"),
        sa.Column("employee_rates", postgresql.JSONB(), nullable=False),
        sa.Column("employer_rates", postgresql.JSONB(), nullable=False),
        sa.Column("pit_brackets", postgresql.JSONB(), nullable=False),
        sa.Column("relief_tiers", postgresql.JSONB(), nullable=False),
        sa.Column("overtime_multipliers", postgresql.JSONB(), nullable=False),
        sa.Column("source_references", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "version", name="uq_monthly_payroll_rule_version"),
    )
    op.create_index("ix_monthly_payroll_rule_effective", "monthly_payroll_rule_sets", ["organization_id", "valid_from", "valid_to"])

    op.create_table(
        "monthly_payroll_calendar_days",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("calendar_date", sa.Date(), nullable=False),
        sa.Column("day_type", sa.String(24), nullable=False),
        sa.Column("holiday_name", sa.Text()),
        sa.Column("is_override", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "calendar_date", name="uq_monthly_payroll_calendar_date"),
        sa.CheckConstraint("day_type IN ('working','weekly_rest','public_holiday')", name="ck_monthly_payroll_calendar_type"),
    )
    op.create_index("ix_monthly_payroll_calendar_org_date", "monthly_payroll_calendar_days", ["organization_id", "calendar_date"])

    op.execute(sa.text("""
        INSERT INTO monthly_payroll_company_settings (organization_id)
        SELECT id FROM organizations
        ON CONFLICT (organization_id) DO NOTHING
    """))
    # Preserve existing worker salary assignments in the new monthly profile
    # without carrying the salary-structure/formula dependency into the new flow.
    op.execute(sa.text("""
        INSERT INTO monthly_payroll_profiles
          (organization_id, employee_id, insured_type, tax_relief_eligible)
        SELECT DISTINCT ON (organization_id, employee_id)
          organization_id, employee_id, insured_category,
          jsonb_array_length(COALESCE(tax_relief_eligibility, '[]'::jsonb)) > 0
        FROM employee_payroll_profiles
        ORDER BY organization_id, employee_id, effective_from DESC, id DESC
        ON CONFLICT (organization_id, employee_id) DO NOTHING
    """))
    op.execute(sa.text("""
        INSERT INTO monthly_payroll_salary_history (profile_id, monthly_salary, valid_from, created_by_account_id)
        SELECT monthly.id, legacy.base_salary, legacy.effective_from, legacy.created_by_account_id
        FROM employee_payroll_profiles AS legacy
        JOIN monthly_payroll_profiles AS monthly
          ON monthly.organization_id = legacy.organization_id
         AND monthly.employee_id = legacy.employee_id
        ON CONFLICT (profile_id, valid_from) DO NOTHING
    """))
    op.execute(sa.text("""
        INSERT INTO monthly_payroll_rule_sets
          (organization_id, version, status, valid_from, minimum_wage, shi_cap_multiplier,
           employee_rates, employer_rates, pit_brackets, relief_tiers, overtime_multipliers, source_references)
        SELECT id, 1, 'published', DATE '2026-01-01', 792000, 10,
          '{"pension":0.085,"benefit":0.008,"unemployment":0.002,"health":0.02}'::jsonb,
          '{"pension":0.085,"benefit":0.01,"unemployment":0.005,"injury":0.005,"health":0.02}'::jsonb,
          '[{"lower":0,"upper":10000000,"rate":0.10,"base_tax":0},{"lower":10000000,"upper":15000000,"rate":0.15,"base_tax":1000000},{"lower":15000000,"upper":null,"rate":0.20,"base_tax":1750000}]'::jsonb,
          '[{"lower":0,"upper":500000,"amount":20000},{"lower":500000,"upper":1000000,"amount":18000},{"lower":1000000,"upper":1500000,"amount":16000},{"lower":1500000,"upper":2000000,"amount":14000},{"lower":2000000,"upper":2500000,"amount":12000},{"lower":2500000,"upper":3000000,"amount":10000}]'::jsonb,
          '{"weekday":1.5,"rest_day":1.5,"public_holiday":2.0}'::jsonb,
          '["https://legalinfo.mn/mn/detail?lawId=14410","https://legalinfo.mn/mn/detail?lawId=16760148379551"]'::jsonb
        FROM organizations
        ON CONFLICT (organization_id, version) DO NOTHING
    """))


def downgrade() -> None:
    op.drop_index("ix_monthly_payroll_calendar_org_date", table_name="monthly_payroll_calendar_days")
    op.drop_table("monthly_payroll_calendar_days")
    op.drop_index("ix_monthly_payroll_rule_effective", table_name="monthly_payroll_rule_sets")
    op.drop_table("monthly_payroll_rule_sets")
    op.drop_table("monthly_payroll_company_settings")
    op.drop_index("ix_monthly_payroll_salary_effective", table_name="monthly_payroll_salary_history")
    op.drop_table("monthly_payroll_salary_history")
    op.drop_index("ix_monthly_payroll_profiles_employee_id", table_name="monthly_payroll_profiles")
    op.drop_index("ix_monthly_payroll_profiles_organization_id", table_name="monthly_payroll_profiles")
    op.drop_table("monthly_payroll_profiles")
