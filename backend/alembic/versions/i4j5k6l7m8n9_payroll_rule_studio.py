"""Add configurable payroll rule studio, work policies, and statutory traces."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "i4j5k6l7m8n9"
down_revision = "h3i4j5k6l7m8"
branch_labels = None
depends_on = None


def _json_default(value: str) -> sa.TextClause:
    return sa.text(value)


def upgrade() -> None:
    op.add_column("statutory_config_profiles", sa.Column("pit_calculation_mode", sa.String(24), server_default="marginal_tiers", nullable=False))
    op.add_column("statutory_config_profiles", sa.Column("pit_formula", sa.Text(), nullable=True))
    op.add_column("statutory_config_profiles", sa.Column("standard_daily_hours", sa.Numeric(8, 4), server_default="8", nullable=False))
    op.add_column("statutory_config_profiles", sa.Column("standard_weekly_hours", sa.Numeric(8, 4), server_default="40", nullable=False))
    op.add_column("statutory_config_profiles", sa.Column("standard_workweek", postgresql.JSONB(), server_default=_json_default("'[1,2,3,4,5]'::jsonb"), nullable=False))

    for column in (
        sa.Column("lower_bound", sa.Numeric(20, 4), server_default="0", nullable=False),
        sa.Column("upper_bound", sa.Numeric(20, 4), nullable=True),
        sa.Column("calculation_mode", sa.String(24), server_default="flat_percent", nullable=False),
        sa.Column("fixed_amount", sa.Numeric(20, 4), server_default="0", nullable=False),
        sa.Column("base_tax", sa.Numeric(20, 4), server_default="0", nullable=False),
        sa.Column("formula", sa.Text(), nullable=True),
    ):
        op.add_column("shi_rate_tiers", column)

    op.add_column("salary_components", sa.Column("amount_mode", sa.String(16), server_default="formula", nullable=False))
    op.add_column("salary_components", sa.Column("percentage_basis", sa.String(80), nullable=True))
    op.add_column("payroll_salary_component_masters", sa.Column("amount_mode", sa.String(16), server_default="formula", nullable=False))
    op.add_column("payroll_salary_component_masters", sa.Column("percentage_basis", sa.String(80), nullable=True))

    op.drop_constraint("uq_payroll_shi_rate_tier", "shi_rate_tiers", type_="unique")
    op.create_unique_constraint(
        "uq_payroll_shi_rate_tier_position",
        "shi_rate_tiers",
        ["profile_id", "payer", "insurance_fund", "insured_category", "hazard_class", "position"],
    )

    op.create_table(
        "payroll_social_insurance_contributor_types",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date()),
        sa.Column("source_references", postgresql.JSONB(), server_default=_json_default("'[]'::jsonb"), nullable=False),
        sa.Column("status", sa.String(16), server_default="draft", nullable=False),
        sa.Column("created_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("organization_id", "code", "effective_from", name="uq_payroll_contributor_type_effective"),
    )
    op.create_index("ix_payroll_contributor_type_effective", "payroll_social_insurance_contributor_types", ["organization_id", "code", "effective_from", "effective_to"])

    op.create_table(
        "payroll_work_policies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("scope_type", sa.String(16), server_default="organization", nullable=False),
        sa.Column("scope_key", sa.String(160), server_default="*", nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date()),
        sa.Column("daily_hours", sa.Numeric(8, 4), server_default="8", nullable=False),
        sa.Column("weekly_hours", sa.Numeric(8, 4), server_default="40", nullable=False),
        sa.Column("workweek", postgresql.JSONB(), server_default=_json_default("'[1,2,3,4,5]'::jsonb"), nullable=False),
        sa.Column("overtime_rules", postgresql.JSONB(), server_default=_json_default("'{}'::jsonb"), nullable=False),
        sa.Column("stacking_policy", sa.String(24), server_default="exclusive", nullable=False),
        sa.Column("status", sa.String(16), server_default="draft", nullable=False),
        sa.Column("source_references", postgresql.JSONB(), server_default=_json_default("'[]'::jsonb"), nullable=False),
        sa.Column("created_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("organization_id", "scope_type", "scope_key", "effective_from", name="uq_payroll_work_policy_effective"),
    )
    op.create_index("ix_payroll_work_policy_effective", "payroll_work_policies", ["organization_id", "scope_type", "scope_key", "effective_from", "effective_to"])

    op.create_table(
        "payroll_formula_variables",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("data_type", sa.String(16), server_default="decimal", nullable=False),
        sa.Column("default_value", sa.Text()),
        sa.Column("source", sa.String(24), server_default="manual", nullable=False),
        sa.Column("required", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("minimum", sa.Numeric(20, 4)),
        sa.Column("maximum", sa.Numeric(20, 4)),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("organization_id", "code", name="uq_payroll_formula_variable_code"),
    )

    op.create_table(
        "payroll_report_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("status", sa.String(16), server_default="draft", nullable=False),
        sa.Column("template", postgresql.JSONB(), server_default=_json_default("'{}'::jsonb"), nullable=False),
        sa.Column("required_keys", postgresql.JSONB(), server_default=_json_default("'[]'::jsonb"), nullable=False),
        sa.Column("source_references", postgresql.JSONB(), server_default=_json_default("'[]'::jsonb"), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("created_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("published_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("organization_id", "kind", "version", name="uq_payroll_report_template_version"),
    )

    op.create_table(
        "payslip_statutory_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("payslip_id", sa.Integer(), sa.ForeignKey("payslips.id", ondelete="CASCADE"), nullable=False),
        sa.Column("contributor_code", sa.String(32), nullable=False),
        sa.Column("payer", sa.String(12), nullable=False),
        sa.Column("insurance_fund", sa.String(32), nullable=False),
        sa.Column("hazard_class", sa.String(32), server_default="standard", nullable=False),
        sa.Column("calculation_mode", sa.String(24), nullable=False),
        sa.Column("base", sa.Numeric(20, 4), server_default="0", nullable=False),
        sa.Column("lower_bound", sa.Numeric(20, 4), server_default="0", nullable=False),
        sa.Column("upper_bound", sa.Numeric(20, 4)),
        sa.Column("rate", sa.Numeric(12, 8), server_default="0", nullable=False),
        sa.Column("amount", sa.Numeric(20, 4), server_default="0", nullable=False),
        sa.Column("formula_snapshot", sa.Text()),
        sa.Column("trace", postgresql.JSONB(), server_default=_json_default("'{}'::jsonb"), nullable=False),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_index("ix_payroll_payslip_statutory_lines", "payslip_statutory_lines", ["payslip_id", "position"])


def downgrade() -> None:
    op.drop_index("ix_payroll_payslip_statutory_lines", table_name="payslip_statutory_lines")
    op.drop_table("payslip_statutory_lines")
    op.drop_table("payroll_report_templates")
    op.drop_table("payroll_formula_variables")
    op.drop_index("ix_payroll_work_policy_effective", table_name="payroll_work_policies")
    op.drop_table("payroll_work_policies")
    op.drop_index("ix_payroll_contributor_type_effective", table_name="payroll_social_insurance_contributor_types")
    op.drop_table("payroll_social_insurance_contributor_types")
    op.drop_constraint("uq_payroll_shi_rate_tier_position", "shi_rate_tiers", type_="unique")
    op.create_unique_constraint("uq_payroll_shi_rate_tier", "shi_rate_tiers", ["profile_id", "payer", "insurance_fund", "insured_category", "hazard_class"])
    for column in ("formula", "base_tax", "fixed_amount", "calculation_mode", "upper_bound", "lower_bound"):
        op.drop_column("shi_rate_tiers", column)
    op.drop_column("salary_components", "percentage_basis")
    op.drop_column("salary_components", "amount_mode")
    op.drop_column("payroll_salary_component_masters", "percentage_basis")
    op.drop_column("payroll_salary_component_masters", "amount_mode")
    for column in ("standard_workweek", "standard_weekly_hours", "standard_daily_hours", "pit_formula", "pit_calculation_mode"):
        op.drop_column("statutory_config_profiles", column)
