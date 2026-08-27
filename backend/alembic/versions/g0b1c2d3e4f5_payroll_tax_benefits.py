"""Add Frappe-inspired payroll tax exemption and flexible benefit workflows."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "g0b1c2d3e4f5"
down_revision: Union[str, Sequence[str], None] = "f0a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("salary_components", sa.Column("is_flexible_benefit", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("salary_components", sa.Column("max_benefit_amount_yearly", sa.Numeric(20, 4), nullable=False, server_default="0"))
    op.add_column("salary_components", sa.Column("pay_against_benefit_claim", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("salary_components", sa.Column("only_tax_impact", sa.Boolean(), nullable=False, server_default=sa.text("false")))

    op.create_table(
        "payroll_tax_exemption_categories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("treatment", sa.String(24), nullable=False, server_default="tax_deduction"),
        sa.Column("annual_limit", sa.Numeric(20, 4), nullable=False, server_default="0"),
        sa.Column("requires_proof", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("treatment IN ('tax_deduction', 'tax_credit')", name="ck_payroll_tax_exemption_treatment"),
        sa.UniqueConstraint("organization_id", "code", name="uq_payroll_tax_exemption_category_code"),
    )
    op.create_table(
        "employee_tax_exemption_declarations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category_id", sa.Integer(), sa.ForeignKey("payroll_tax_exemption_categories.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("tax_year", sa.Integer(), nullable=False),
        sa.Column("declared_amount", sa.Numeric(20, 4), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("note", sa.Text()),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("reviewed_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("created_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("declared_amount >= 0", name="ck_payroll_tax_declaration_amount"),
        sa.CheckConstraint("status IN ('draft', 'submitted', 'approved', 'rejected')", name="ck_payroll_tax_declaration_status"),
        sa.UniqueConstraint("employee_id", "tax_year", "category_id", name="uq_payroll_employee_tax_declaration"),
    )
    op.create_index("ix_payroll_tax_declaration_org_year", "employee_tax_exemption_declarations", ["organization_id", "tax_year", "status"])
    op.create_table(
        "employee_tax_exemption_proofs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("declaration_id", sa.Integer(), sa.ForeignKey("employee_tax_exemption_declarations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("amount", sa.Numeric(20, 4), nullable=False),
        sa.Column("reference", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="submitted"),
        sa.Column("reviewed_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("created_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("amount > 0", name="ck_payroll_tax_proof_amount"),
        sa.CheckConstraint("status IN ('submitted', 'approved', 'rejected')", name="ck_payroll_tax_proof_status"),
    )
    op.create_index("ix_payroll_tax_proof_declaration_status", "employee_tax_exemption_proofs", ["declaration_id", "status"])
    op.create_table(
        "employee_benefit_applications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("salary_component_id", sa.Integer(), sa.ForeignKey("salary_components.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("tax_year", sa.Integer(), nullable=False),
        sa.Column("requested_amount", sa.Numeric(20, 4), nullable=False),
        sa.Column("approved_amount", sa.Numeric(20, 4), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("note", sa.Text()),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("reviewed_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("created_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("requested_amount > 0 AND approved_amount >= 0", name="ck_payroll_benefit_application_amount"),
        sa.CheckConstraint("status IN ('draft', 'submitted', 'approved', 'rejected')", name="ck_payroll_benefit_application_status"),
        sa.UniqueConstraint("employee_id", "tax_year", "salary_component_id", name="uq_payroll_employee_benefit_application"),
    )
    op.create_index("ix_payroll_benefit_application_org_year", "employee_benefit_applications", ["organization_id", "tax_year", "status"])
    op.create_table(
        "employee_benefit_claims",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("application_id", sa.Integer(), sa.ForeignKey("employee_benefit_applications.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("claim_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(20, 4), nullable=False),
        sa.Column("reference", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="submitted"),
        sa.Column("payroll_run_id", sa.Integer(), sa.ForeignKey("payroll_runs.id", ondelete="RESTRICT")),
        sa.Column("reviewed_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("created_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("amount > 0", name="ck_payroll_benefit_claim_amount"),
        sa.CheckConstraint("status IN ('submitted', 'approved', 'queued', 'paid', 'rejected')", name="ck_payroll_benefit_claim_status"),
    )
    op.create_index("ix_payroll_benefit_claim_application_status", "employee_benefit_claims", ["application_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_payroll_benefit_claim_application_status", table_name="employee_benefit_claims")
    op.drop_table("employee_benefit_claims")
    op.drop_index("ix_payroll_benefit_application_org_year", table_name="employee_benefit_applications")
    op.drop_table("employee_benefit_applications")
    op.drop_index("ix_payroll_tax_proof_declaration_status", table_name="employee_tax_exemption_proofs")
    op.drop_table("employee_tax_exemption_proofs")
    op.drop_index("ix_payroll_tax_declaration_org_year", table_name="employee_tax_exemption_declarations")
    op.drop_table("employee_tax_exemption_declarations")
    op.drop_table("payroll_tax_exemption_categories")
    op.drop_column("salary_components", "only_tax_impact")
    op.drop_column("salary_components", "pay_against_benefit_claim")
    op.drop_column("salary_components", "max_benefit_amount_yearly")
    op.drop_column("salary_components", "is_flexible_benefit")
