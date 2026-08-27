"""Add configurable Mongolia payroll domain and immutable calculation snapshots."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "f0a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "v1w2x3y4z5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    json = postgresql.JSONB(astext_type=sa.Text())
    # Payroll postings preserve cost-center attribution on the existing
    # immutable ERP ledger without changing legacy journal rows.
    op.add_column("erp_general_ledger_entries", sa.Column("cost_center_id", sa.Integer(), sa.ForeignKey("erp_cost_centers.id", ondelete="SET NULL")))
    op.create_table(
        "statutory_config_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("jurisdiction", sa.String(8), nullable=False, server_default="MN"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date()),
        sa.Column("tax_point_basis", sa.String(24), nullable=False, server_default="payment_date"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="MNT"),
        sa.Column("minimum_wage", sa.Numeric(20, 4), nullable=False, server_default="0"),
        sa.Column("shi_ceiling_multiplier", sa.Numeric(12, 6), nullable=False, server_default="0"),
        sa.Column("pit_withholding_method", sa.String(24), nullable=False, server_default="ytd_cumulative"),
        sa.Column("rounding_policy", json, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("leave_policy", json, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("source_references", json, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("is_example", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("approved_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("created_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "code", "version", name="uq_payroll_statutory_profile_version"),
    )
    op.create_index("ix_payroll_statutory_profile_effective", "statutory_config_profiles", ["organization_id", "effective_from", "effective_to"])

    op.create_table(
        "shi_rate_tiers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("profile_id", sa.Integer(), sa.ForeignKey("statutory_config_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("payer", sa.String(12), nullable=False),
        sa.Column("insurance_fund", sa.String(32), nullable=False),
        sa.Column("insured_category", sa.String(32), nullable=False, server_default="employee"),
        sa.Column("hazard_class", sa.String(16), nullable=False, server_default="standard"),
        sa.Column("rate", sa.Numeric(12, 8), nullable=False, server_default="0"),
        sa.Column("base_floor", sa.Numeric(20, 4), nullable=False, server_default="0"),
        sa.Column("base_ceiling_policy", sa.String(24), nullable=False, server_default="profile"),
        sa.Column("exemption_code", sa.String(64)),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("profile_id", "payer", "insurance_fund", "insured_category", "hazard_class", name="uq_payroll_shi_rate_tier"),
    )
    op.create_table(
        "pit_bracket_tiers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("profile_id", sa.Integer(), sa.ForeignKey("statutory_config_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("period_basis", sa.String(16), nullable=False, server_default="annual"),
        sa.Column("lower_bound", sa.Numeric(20, 4), nullable=False, server_default="0"),
        sa.Column("upper_bound", sa.Numeric(20, 4)),
        sa.Column("marginal_rate", sa.Numeric(12, 8), nullable=False, server_default="0"),
        sa.Column("base_tax", sa.Numeric(20, 4), nullable=False, server_default="0"),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("profile_id", "period_basis", "position", name="uq_payroll_pit_bracket_position"),
    )
    op.create_table(
        "tax_relief_tiers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("profile_id", sa.Integer(), sa.ForeignKey("statutory_config_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("eligibility_code", sa.String(64), nullable=False),
        sa.Column("lower_bound", sa.Numeric(20, 4), nullable=False, server_default="0"),
        sa.Column("upper_bound", sa.Numeric(20, 4)),
        sa.Column("fixed_amount", sa.Numeric(20, 4), nullable=False, server_default="0"),
        sa.Column("amount_basis", sa.String(16), nullable=False, server_default="annual"),
        sa.Column("formula", sa.Text()),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("profile_id", "eligibility_code", "position", name="uq_payroll_relief_position"),
    )

    op.create_table(
        "salary_structures",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(80), nullable=False), sa.Column("name", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"), sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("effective_from", sa.Date(), nullable=False), sa.Column("effective_to", sa.Date()),
        sa.Column("currency", sa.String(3), nullable=False, server_default="MNT"), sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("created_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("published_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("published_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "code", "version", name="uq_payroll_salary_structure_version"),
    )
    op.create_table(
        "salary_structure_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("salary_structure_id", sa.Integer(), sa.ForeignKey("salary_structures.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date()),
        sa.Column("component_snapshot", json, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("published_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("salary_structure_id", "version", name="uq_payroll_salary_structure_version_snapshot"),
    )
    op.create_index("ix_payroll_salary_structure_version_effective", "salary_structure_versions", ["salary_structure_id", "effective_from", "effective_to"])

    op.create_table(
        "salary_components",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("salary_structure_id", sa.Integer(), sa.ForeignKey("salary_structures.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(80), nullable=False), sa.Column("name", sa.Text(), nullable=False), sa.Column("component_kind", sa.String(24), nullable=False),
        sa.Column("formula", sa.Text(), nullable=False), sa.Column("proration_basis", sa.String(24), nullable=False, server_default="none"),
        sa.Column("is_taxable", sa.Boolean(), nullable=False, server_default=sa.text("true")), sa.Column("is_shi_subject", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_non_taxable_allowance", sa.Boolean(), nullable=False, server_default=sa.text("false")), sa.Column("is_leave_average_eligible", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("payer", sa.String(12), nullable=False, server_default="employee"), sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("erp_accounts.id", ondelete="SET NULL")), sa.Column("cost_center_id", sa.Integer(), sa.ForeignKey("erp_cost_centers.id", ondelete="SET NULL")),
        sa.Column("metadata_json", json, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.UniqueConstraint("salary_structure_id", "code", name="uq_payroll_salary_component_code"),
    )
    op.create_index("ix_payroll_salary_component_order", "salary_components", ["salary_structure_id", "position"])

    op.create_table(
        "employee_payroll_profiles",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False), sa.Column("salary_structure_id", sa.Integer(), sa.ForeignKey("salary_structures.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False), sa.Column("effective_to", sa.Date()), sa.Column("base_salary", sa.Numeric(20, 4), nullable=False, server_default="0"),
        sa.Column("insured_category", sa.String(32), nullable=False, server_default="employee"), sa.Column("hazard_class", sa.String(16), nullable=False, server_default="standard"),
        sa.Column("residency_status", sa.String(24), nullable=False, server_default="resident"), sa.Column("tax_relief_eligibility", json, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("exemption_flags", json, nullable=False, server_default=sa.text("'{}'::jsonb")), sa.Column("taxpayer_number_ciphertext", sa.Text()), sa.Column("social_insurance_number_ciphertext", sa.Text()),
        sa.Column("payment_method", sa.String(16), nullable=False, server_default="bank"), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("employee_id", "effective_from", name="uq_payroll_employee_profile_start"),
    )
    op.create_index("ix_payroll_employee_profile_effective", "employee_payroll_profiles", ["employee_id", "effective_from", "effective_to"])
    op.create_table(
        "employee_bank_accounts",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("employee_payroll_profile_id", sa.Integer(), sa.ForeignKey("employee_payroll_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("bank_code", sa.String(32), nullable=False), sa.Column("account_number_ciphertext", sa.Text(), nullable=False), sa.Column("account_fingerprint", sa.String(64), nullable=False), sa.Column("account_last4", sa.String(4), nullable=False),
        sa.Column("account_holder_ciphertext", sa.Text()), sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("true")), sa.Column("valid_from", sa.Date(), nullable=False), sa.Column("valid_to", sa.Date()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("employee_payroll_profile_id", "account_fingerprint", name="uq_payroll_bank_account_fingerprint"),
    )

    op.create_table(
        "payroll_runs",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_number", sa.String(80), nullable=False), sa.Column("run_type", sa.String(16), nullable=False), sa.Column("period_start", sa.Date(), nullable=False), sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("settlement_key", sa.String(32), nullable=False), sa.Column("tax_point_date", sa.Date(), nullable=False), sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("reversal_of_run_id", sa.Integer(), sa.ForeignKey("payroll_runs.id", ondelete="RESTRICT")), sa.Column("replacement_of_run_id", sa.Integer(), sa.ForeignKey("payroll_runs.id", ondelete="RESTRICT")),
        sa.Column("statutory_profile_id", sa.Integer(), sa.ForeignKey("statutory_config_profiles.id", ondelete="RESTRICT"), nullable=False), sa.Column("input_snapshot", json, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("config_snapshot", json, nullable=False, server_default=sa.text("'{}'::jsonb")), sa.Column("engine_version", sa.String(32), nullable=False, server_default="1"), sa.Column("snapshot_checksum", sa.String(64), nullable=False),
        sa.Column("total_gross", sa.Numeric(20, 4), nullable=False, server_default="0"), sa.Column("total_employee_shi", sa.Numeric(20, 4), nullable=False, server_default="0"), sa.Column("total_employer_shi", sa.Numeric(20, 4), nullable=False, server_default="0"), sa.Column("total_pit", sa.Numeric(20, 4), nullable=False, server_default="0"), sa.Column("total_net", sa.Numeric(20, 4), nullable=False, server_default="0"), sa.Column("posting_profile_id", sa.Integer()),
        sa.Column("erp_document_id", sa.Integer(), sa.ForeignKey("erp_documents.id", ondelete="SET NULL")), sa.Column("created_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")), sa.Column("approved_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")), sa.Column("posted_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "run_number", name="uq_payroll_run_number"),
    )
    op.create_index("ix_payroll_run_period_status", "payroll_runs", ["organization_id", "period_start", "period_end", "status"])
    op.create_table(
        "payslips",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("payroll_run_id", sa.Integer(), sa.ForeignKey("payroll_runs.id", ondelete="CASCADE"), nullable=False), sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False), sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("employee_profile_snapshot", json, nullable=False, server_default=sa.text("'{}'::jsonb")), sa.Column("input_snapshot", json, nullable=False, server_default=sa.text("'{}'::jsonb")), sa.Column("calculation_trace", json, nullable=False, server_default=sa.text("'{}'::jsonb")), sa.Column("ytd_snapshot", json, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("gross", sa.Numeric(20, 4), nullable=False, server_default="0"), sa.Column("taxable_income", sa.Numeric(20, 4), nullable=False, server_default="0"), sa.Column("shi_subject_gross", sa.Numeric(20, 4), nullable=False, server_default="0"), sa.Column("shi_base", sa.Numeric(20, 4), nullable=False, server_default="0"), sa.Column("employee_shi", sa.Numeric(20, 4), nullable=False, server_default="0"), sa.Column("employer_shi", sa.Numeric(20, 4), nullable=False, server_default="0"), sa.Column("pit", sa.Numeric(20, 4), nullable=False, server_default="0"), sa.Column("pit_relief", sa.Numeric(20, 4), nullable=False, server_default="0"), sa.Column("advance_offset", sa.Numeric(20, 4), nullable=False, server_default="0"), sa.Column("net_pay", sa.Numeric(20, 4), nullable=False, server_default="0"), sa.Column("snapshot_checksum", sa.String(64), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("payroll_run_id", "employee_id", name="uq_payroll_payslip_employee"),
    )
    op.create_table(
        "payslip_line_items",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("payslip_id", sa.Integer(), sa.ForeignKey("payslips.id", ondelete="CASCADE"), nullable=False), sa.Column("component_code", sa.String(80), nullable=False), sa.Column("label", sa.Text(), nullable=False), sa.Column("component_kind", sa.String(24), nullable=False), sa.Column("amount", sa.Numeric(20, 4), nullable=False, server_default="0"), sa.Column("taxable", sa.Boolean(), nullable=False, server_default=sa.text("false")), sa.Column("shi_subject", sa.Boolean(), nullable=False, server_default=sa.text("false")), sa.Column("payer", sa.String(12), nullable=False, server_default="employee"), sa.Column("formula_snapshot", sa.Text(), nullable=False), sa.Column("trace", json, nullable=False, server_default=sa.text("'{}'::jsonb")), sa.Column("account_id", sa.Integer(), sa.ForeignKey("erp_accounts.id", ondelete="SET NULL")), sa.Column("cost_center_id", sa.Integer(), sa.ForeignKey("erp_cost_centers.id", ondelete="SET NULL")), sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_payroll_payslip_lines_payslip", "payslip_line_items", ["payslip_id", "position"])
    op.create_table(
        "payroll_employee_accumulators",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False), sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id", ondelete="RESTRICT"), nullable=False), sa.Column("payroll_run_id", sa.Integer(), sa.ForeignKey("payroll_runs.id", ondelete="RESTRICT"), nullable=False), sa.Column("tax_year", sa.Integer(), nullable=False), sa.Column("sequence_no", sa.Integer(), nullable=False), sa.Column("gross_delta", sa.Numeric(20, 4), nullable=False, server_default="0"), sa.Column("taxable_delta", sa.Numeric(20, 4), nullable=False, server_default="0"), sa.Column("shi_base_delta", sa.Numeric(20, 4), nullable=False, server_default="0"), sa.Column("pit_withheld_delta", sa.Numeric(20, 4), nullable=False, server_default="0"), sa.Column("reversal_of_id", sa.Integer(), sa.ForeignKey("payroll_employee_accumulators.id", ondelete="SET NULL")), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.UniqueConstraint("employee_id", "tax_year", "sequence_no", name="uq_payroll_accumulator_sequence"),
    )
    op.create_table(
        "payroll_advances",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False), sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id", ondelete="RESTRICT"), nullable=False), sa.Column("payroll_run_id", sa.Integer(), sa.ForeignKey("payroll_runs.id", ondelete="RESTRICT"), nullable=False), sa.Column("settlement_key", sa.String(32), nullable=False), sa.Column("amount", sa.Numeric(20, 4), nullable=False), sa.Column("applied_amount", sa.Numeric(20, 4), nullable=False, server_default="0"), sa.Column("status", sa.String(16), nullable=False, server_default="approved"), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_payroll_advance_employee_settlement", "payroll_advances", ["employee_id", "settlement_key", "status"])
    op.create_table(
        "payroll_posting_profiles",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False), sa.Column("code", sa.String(80), nullable=False), sa.Column("account_roles", json, nullable=False, server_default=sa.text("'{}'::jsonb")), sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.UniqueConstraint("organization_id", "code", name="uq_payroll_posting_profile_code"),
    )
    op.create_foreign_key("fk_payroll_run_posting_profile", "payroll_runs", "payroll_posting_profiles", ["posting_profile_id"], ["id"], ondelete="RESTRICT")
    op.create_table(
        "payroll_bank_export_profiles",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False), sa.Column("bank_code", sa.String(32), nullable=False), sa.Column("version", sa.Integer(), nullable=False, server_default="1"), sa.Column("status", sa.String(16), nullable=False, server_default="draft"), sa.Column("format", sa.String(8), nullable=False, server_default="csv"), sa.Column("template", json, nullable=False, server_default=sa.text("'{}'::jsonb")), sa.Column("is_provisional", sa.Boolean(), nullable=False, server_default=sa.text("true")), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.UniqueConstraint("organization_id", "bank_code", "version", name="uq_payroll_bank_export_version"),
    )
    op.create_table(
        "payroll_export_artifacts",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False), sa.Column("payroll_run_id", sa.Integer(), sa.ForeignKey("payroll_runs.id", ondelete="RESTRICT"), nullable=False), sa.Column("kind", sa.String(24), nullable=False), sa.Column("format", sa.String(8), nullable=False), sa.Column("template_version", sa.String(80)), sa.Column("storage_key", sa.String(512), nullable=False), sa.Column("filename", sa.String(255), nullable=False, server_default="payroll-export"), sa.Column("content_ciphertext", sa.Text(), nullable=False), sa.Column("checksum", sa.String(64), nullable=False), sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False), sa.Column("downloaded_at", sa.DateTime(timezone=True)), sa.Column("created_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.execute(sa.text("""
        CREATE OR REPLACE FUNCTION payroll_guard_immutable() RETURNS trigger AS $$
        DECLARE run_status text;
        BEGIN
          IF TG_TABLE_NAME = 'payroll_employee_accumulators' THEN
            RAISE EXCEPTION 'Payroll accumulator rows are append-only';
          ELSIF TG_TABLE_NAME = 'payroll_runs' THEN
            run_status := OLD.status;
            -- Approval is still allowed to transition to posted; posted/paid
            -- snapshots require reversal and replacement instead.
            IF run_status IN ('posted', 'paid') THEN
              RAISE EXCEPTION 'Posted payroll runs are immutable';
            END IF;
          ELSIF TG_TABLE_NAME = 'payslip_line_items' THEN
            SELECT r.status INTO run_status FROM payroll_runs r JOIN payslips p ON p.payroll_run_id = r.id WHERE p.id = OLD.payslip_id;
            IF run_status IN ('approved', 'posted', 'paid') THEN
              RAISE EXCEPTION 'Finalized payroll snapshots are immutable';
            END IF;
          ELSIF TG_TABLE_NAME = 'statutory_config_profiles' THEN
            IF OLD.status IN ('published', 'active') THEN
              RAISE EXCEPTION 'Published statutory profiles are immutable';
            END IF;
          ELSIF TG_TABLE_NAME = 'salary_structures' OR TG_TABLE_NAME = 'salary_structure_versions' THEN
            IF OLD.status IN ('published', 'active') THEN
              RAISE EXCEPTION 'Published salary structures are immutable';
            END IF;
          ELSIF TG_TABLE_NAME = 'salary_components' THEN
            SELECT s.status INTO run_status FROM salary_structures s WHERE s.id = OLD.salary_structure_id;
            IF run_status IN ('published', 'active') THEN
              RAISE EXCEPTION 'Published salary components are immutable';
            END IF;
          ELSE
            SELECT status INTO run_status FROM payroll_runs WHERE id = OLD.payroll_run_id;
            IF run_status IN ('approved', 'posted', 'paid') THEN
              RAISE EXCEPTION 'Finalized payroll snapshots are immutable';
            END IF;
          END IF;
          IF TG_OP = 'DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER payroll_run_immutable BEFORE UPDATE OR DELETE ON payroll_runs FOR EACH ROW EXECUTE FUNCTION payroll_guard_immutable();
        CREATE TRIGGER payroll_payslip_immutable BEFORE UPDATE OR DELETE ON payslips FOR EACH ROW EXECUTE FUNCTION payroll_guard_immutable();
        CREATE TRIGGER payroll_payslip_line_immutable BEFORE UPDATE OR DELETE ON payslip_line_items FOR EACH ROW EXECUTE FUNCTION payroll_guard_immutable();
        CREATE TRIGGER payroll_accumulator_immutable BEFORE UPDATE OR DELETE ON payroll_employee_accumulators FOR EACH ROW EXECUTE FUNCTION payroll_guard_immutable();
        CREATE TRIGGER payroll_profile_immutable BEFORE UPDATE OR DELETE ON statutory_config_profiles FOR EACH ROW EXECUTE FUNCTION payroll_guard_immutable();
        CREATE TRIGGER payroll_salary_structure_immutable BEFORE UPDATE OR DELETE ON salary_structures FOR EACH ROW EXECUTE FUNCTION payroll_guard_immutable();
        CREATE TRIGGER payroll_salary_structure_version_immutable BEFORE UPDATE OR DELETE ON salary_structure_versions FOR EACH ROW EXECUTE FUNCTION payroll_guard_immutable();
        CREATE TRIGGER payroll_salary_component_immutable BEFORE UPDATE OR DELETE ON salary_components FOR EACH ROW EXECUTE FUNCTION payroll_guard_immutable();

        CREATE OR REPLACE FUNCTION payroll_prevent_profile_overlap() RETURNS trigger AS $$
        BEGIN
          IF NEW.status IN ('published', 'active') AND EXISTS (
            SELECT 1 FROM statutory_config_profiles p
            WHERE p.organization_id = NEW.organization_id
              AND p.id <> COALESCE(NEW.id, 0)
              AND p.status IN ('published', 'active')
              AND daterange(p.effective_from, p.effective_to, '[]')
                  && daterange(NEW.effective_from, NEW.effective_to, '[]')
          ) THEN
            RAISE EXCEPTION 'Approved statutory profiles may not overlap';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER payroll_profile_no_overlap BEFORE INSERT OR UPDATE ON statutory_config_profiles FOR EACH ROW EXECUTE FUNCTION payroll_prevent_profile_overlap();

        CREATE OR REPLACE FUNCTION payroll_prevent_employee_profile_overlap() RETURNS trigger AS $$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM employee_payroll_profiles p
            WHERE p.organization_id = NEW.organization_id
              AND p.employee_id = NEW.employee_id
              AND p.id <> COALESCE(NEW.id, 0)
              AND daterange(p.effective_from, p.effective_to, '[]')
                  && daterange(NEW.effective_from, NEW.effective_to, '[]')
          ) THEN
            RAISE EXCEPTION 'Employee payroll profiles may not overlap';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER payroll_employee_profile_no_overlap BEFORE INSERT OR UPDATE ON employee_payroll_profiles FOR EACH ROW EXECUTE FUNCTION payroll_prevent_employee_profile_overlap();

        CREATE OR REPLACE FUNCTION payroll_prevent_salary_structure_overlap() RETURNS trigger AS $$
        BEGIN
          IF NEW.status IN ('published', 'active') AND EXISTS (
            SELECT 1 FROM salary_structures s
            WHERE s.organization_id = NEW.organization_id
              AND s.code = NEW.code
              AND s.id <> COALESCE(NEW.id, 0)
              AND s.status IN ('published', 'active')
              AND daterange(s.effective_from, s.effective_to, '[]')
                  && daterange(NEW.effective_from, NEW.effective_to, '[]')
          ) THEN
            RAISE EXCEPTION 'Published salary structures may not overlap';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER payroll_salary_structure_no_overlap BEFORE INSERT OR UPDATE ON salary_structures FOR EACH ROW EXECUTE FUNCTION payroll_prevent_salary_structure_overlap();
    """))

    # Deliberately inactive examples. They are not legal advice and cannot be
    # selected by the calculation service until an administrator publishes them.
    op.execute(sa.text("""
        INSERT INTO statutory_config_profiles
          (organization_id, code, jurisdiction, version, status, effective_from,
           tax_point_basis, currency, minimum_wage, shi_ceiling_multiplier,
           pit_withholding_method, source_references, is_example, checksum)
        SELECT 1, 'MN_EXAMPLE_2026', 'MN', 1, 'draft', DATE '2026-01-01',
          'payment_date', 'MNT', 792000, 10, 'ytd_cumulative',
          '[\"prompt-example-only\", \"https://legalinfo.mn/mn/detail?lawId=14410\", \"https://legalinfo.mn/mn/detail?lawId=16760148379551\", \"https://legalinfo.mn/mn/detail?lawId=17048251350081\", \"https://legalinfo.mn/mn/detail?lawId=16532671533721\"]'::jsonb, true,
          '0000000000000000000000000000000000000000000000000000000000000000'
        WHERE EXISTS (SELECT 1 FROM organizations WHERE id = 1)
          AND NOT EXISTS (SELECT 1 FROM statutory_config_profiles WHERE organization_id = 1 AND code = 'MN_EXAMPLE_2026' AND version = 1)
    """))
    op.execute(sa.text("""
        INSERT INTO pit_bracket_tiers (profile_id, period_basis, lower_bound, upper_bound, marginal_rate, position)
        SELECT p.id, 'monthly', x.lower_bound, x.upper_bound, x.rate, x.position
        FROM statutory_config_profiles p
        CROSS JOIN (VALUES
          (0::numeric, 10000000::numeric, 0.10::numeric, 0),
          (10000000::numeric, 15000000::numeric, 0.15::numeric, 1),
          (15000000::numeric, NULL::numeric, 0.20::numeric, 2)
        ) AS x(lower_bound, upper_bound, rate, position)
        WHERE p.organization_id = 1 AND p.code = 'MN_EXAMPLE_2026' AND p.version = 1
          AND NOT EXISTS (SELECT 1 FROM pit_bracket_tiers b WHERE b.profile_id = p.id)
    """))
    op.execute(sa.text("""
        INSERT INTO shi_rate_tiers (profile_id, payer, insurance_fund, insured_category, hazard_class, rate, position)
        SELECT p.id, x.payer, x.fund, 'employee', x.hazard, x.rate, x.position
        FROM statutory_config_profiles p
        CROSS JOIN (VALUES
          ('employee', 'pension', 'standard', 0.085::numeric, 0),
          ('employee', 'benefit', 'standard', 0.008::numeric, 1),
          ('employee', 'health', 'standard', 0.020::numeric, 2),
          ('employee', 'unemployment', 'standard', 0.002::numeric, 3),
          ('employer', 'pension', 'standard', 0.085::numeric, 4),
          ('employer', 'benefit', 'standard', 0.010::numeric, 5),
          ('employer', 'health', 'standard', 0.020::numeric, 6),
          ('employer', 'unemployment', 'standard', 0.006::numeric, 7),
          ('employer', 'injury', 'standard', 0.004::numeric, 8)
        ) AS x(payer, fund, hazard, rate, position)
        WHERE p.organization_id = 1 AND p.code = 'MN_EXAMPLE_2026' AND p.version = 1
          AND NOT EXISTS (SELECT 1 FROM shi_rate_tiers s WHERE s.profile_id = p.id)
    """))
    op.execute(sa.text("""
        INSERT INTO payroll_bank_export_profiles
          (organization_id, bank_code, version, status, format, template, is_provisional)
        SELECT 1, x.bank_code, 1, 'draft', 'csv',
          '{"columns":[{"key":"batch_reference","header":"Batch reference"},{"key":"sequence","header":"Sequence"},{"key":"execution_date","header":"Execution date"},{"key":"debit_account","header":"Debit account"},{"key":"employee_reference","header":"Employee reference"},{"key":"recipient_name","header":"Recipient name"},{"key":"bank_code","header":"Bank code"},{"key":"bic","header":"BIC"},{"key":"account_number","header":"Account number"},{"key":"amount","header":"Amount"},{"key":"currency","header":"Currency"},{"key":"purpose","header":"Purpose"},{"key":"reference","header":"Reference"}],"include_header":true}'::jsonb,
          true
        FROM (VALUES ('KHAN'), ('GOLOMT'), ('XACBANK')) AS x(bank_code)
        WHERE EXISTS (SELECT 1 FROM organizations WHERE id = 1)
          AND NOT EXISTS (SELECT 1 FROM payroll_bank_export_profiles b WHERE b.organization_id = 1 AND b.bank_code = x.bank_code AND b.version = 1)
    """))


def downgrade() -> None:
    op.execute(sa.text("DROP TRIGGER IF EXISTS payroll_profile_no_overlap ON statutory_config_profiles; DROP TRIGGER IF EXISTS payroll_employee_profile_no_overlap ON employee_payroll_profiles; DROP TRIGGER IF EXISTS payroll_salary_structure_no_overlap ON salary_structures; DROP TRIGGER IF EXISTS payroll_profile_immutable ON statutory_config_profiles; DROP TRIGGER IF EXISTS payroll_run_immutable ON payroll_runs; DROP TRIGGER IF EXISTS payroll_payslip_immutable ON payslips; DROP TRIGGER IF EXISTS payroll_payslip_line_immutable ON payslip_line_items; DROP TRIGGER IF EXISTS payroll_accumulator_immutable ON payroll_employee_accumulators; DROP TRIGGER IF EXISTS payroll_salary_structure_immutable ON salary_structures; DROP TRIGGER IF EXISTS payroll_salary_structure_version_immutable ON salary_structure_versions; DROP TRIGGER IF EXISTS payroll_salary_component_immutable ON salary_components; DROP FUNCTION IF EXISTS payroll_prevent_profile_overlap(); DROP FUNCTION IF EXISTS payroll_prevent_employee_profile_overlap(); DROP FUNCTION IF EXISTS payroll_prevent_salary_structure_overlap(); DROP FUNCTION IF EXISTS payroll_guard_immutable();"))
    for table in (
        "payroll_export_artifacts", "payroll_bank_export_profiles", "payroll_posting_profiles",
        "payroll_advances", "payroll_employee_accumulators", "payslip_line_items", "payslips",
        "payroll_runs", "employee_bank_accounts", "employee_payroll_profiles", "salary_components",
        "salary_structure_versions", "salary_structures", "tax_relief_tiers", "pit_bracket_tiers", "shi_rate_tiers", "statutory_config_profiles",
    ):
        op.drop_table(table)
    op.drop_column("erp_general_ledger_entries", "cost_center_id")
