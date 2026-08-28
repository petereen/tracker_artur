"""Add Frappe-style payroll documents and preserve legacy runs."""

from __future__ import annotations

from datetime import date
import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "i0j1k2l3m4n5"
down_revision: Union[str, Sequence[str], None] = "h0c1d2e3f4g5"
branch_labels = None
depends_on = None


def _next_code(bind, organization_id: int, base: str, suffix: str) -> str:
    candidate = base
    index = 1
    while bind.execute(
        sa.text("SELECT 1 FROM payroll_salary_component_masters WHERE organization_id = :organization_id AND code = :code"),
        {"organization_id": organization_id, "code": candidate},
    ).first():
        candidate = f"{base}__legacy_{suffix}_{index}"
        index += 1
    return candidate


def upgrade() -> None:
    json_type = postgresql.JSONB(astext_type=sa.Text())

    op.create_table(
        "payroll_periods",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("tax_year", sa.Integer(), nullable=False),
        sa.Column("payroll_frequency", sa.String(16), nullable=False, server_default="monthly"),
        sa.Column("statutory_profile_id", sa.Integer(), sa.ForeignKey("statutory_config_profiles.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("created_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "code", name="uq_payroll_period_org_code"),
        sa.CheckConstraint("end_date >= start_date", name="ck_payroll_period_date_order"),
        sa.CheckConstraint("status IN ('open', 'closed')", name="ck_payroll_period_status"),
    )
    op.create_index("ix_payroll_period_org_dates", "payroll_periods", ["organization_id", "start_date", "end_date", "status"])

    op.create_table(
        "payroll_salary_component_masters",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("component_kind", sa.String(24), nullable=False),
        sa.Column("formula", sa.Text(), nullable=False),
        sa.Column("proration_basis", sa.String(24), nullable=False, server_default="none"),
        sa.Column("is_taxable", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_shi_subject", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_non_taxable_allowance", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_leave_average_eligible", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_flexible_benefit", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("max_benefit_amount_yearly", sa.Numeric(20, 4), nullable=False, server_default="0"),
        sa.Column("pay_against_benefit_claim", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("only_tax_impact", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("payer", sa.String(12), nullable=False, server_default="employee"),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("erp_accounts.id", ondelete="SET NULL")),
        sa.Column("cost_center_id", sa.Integer(), sa.ForeignKey("erp_cost_centers.id", ondelete="SET NULL")),
        sa.Column("metadata_json", json_type, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("source_salary_component_id", sa.Integer(), sa.ForeignKey("salary_components.id", ondelete="SET NULL")),
        sa.Column("created_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "code", name="uq_payroll_component_master_org_code"),
    )
    op.create_index("ix_payroll_component_master_org_status", "payroll_salary_component_masters", ["organization_id", "status"])

    op.create_table(
        "payroll_additional_salaries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("number", sa.String(80), nullable=False),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("salary_component_id", sa.Integer(), sa.ForeignKey("payroll_salary_component_masters.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("payroll_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(20, 4), nullable=False),
        sa.Column("component_kind", sa.String(16), nullable=False, server_default="earning"),
        sa.Column("taxable", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("shi_subject", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("source", sa.String(24), nullable=False, server_default="manual"),
        sa.Column("reference", sa.Text()),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("payroll_run_id", sa.Integer(), sa.ForeignKey("payroll_runs.id", ondelete="SET NULL")),
        sa.Column("submitted_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("created_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "number", name="uq_payroll_additional_salary_number"),
        sa.CheckConstraint("amount > 0", name="ck_payroll_additional_salary_amount"),
        sa.CheckConstraint("status IN ('draft', 'submitted', 'cancelled')", name="ck_payroll_additional_salary_status"),
    )
    op.create_index("ix_payroll_additional_salary_employee_date", "payroll_additional_salaries", ["organization_id", "employee_id", "payroll_date", "status"])

    op.create_table(
        "payroll_bank_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("number", sa.String(80), nullable=False),
        sa.Column("payroll_run_id", sa.Integer(), sa.ForeignKey("payroll_runs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("payment_account_id", sa.Integer(), sa.ForeignKey("erp_accounts.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("posting_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(20, 4), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="MNT"),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("erp_document_id", sa.Integer(), sa.ForeignKey("erp_documents.id", ondelete="SET NULL")),
        sa.Column("submitted_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("created_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "number", name="uq_payroll_bank_entry_number"),
        sa.CheckConstraint("status IN ('draft', 'submitted', 'cancelled')", name="ck_payroll_bank_entry_status"),
    )
    op.create_index("ix_payroll_bank_entry_org_status", "payroll_bank_entries", ["organization_id", "status", "posting_date"])

    # Existing records keep their old status and immutable snapshots.  New
    # API-created documents explicitly opt into workflow_version=frappe_v1.
    op.add_column("salary_components", sa.Column("component_master_id", sa.Integer(), sa.ForeignKey("payroll_salary_component_masters.id", ondelete="SET NULL")))
    op.add_column("employee_payroll_profiles", sa.Column("document_status", sa.String(16), nullable=False, server_default="submitted"))
    op.add_column("payroll_runs", sa.Column("workflow_version", sa.String(16), nullable=False, server_default="legacy"))
    op.add_column("payroll_runs", sa.Column("document_status", sa.String(16), nullable=False, server_default="draft"))
    op.add_column("payroll_runs", sa.Column("payroll_frequency", sa.String(16), nullable=False, server_default="monthly"))
    op.add_column("payroll_runs", sa.Column("posting_date", sa.Date()))
    op.add_column("payroll_runs", sa.Column("employee_filter", json_type, nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.add_column("payroll_runs", sa.Column("salary_slips_created", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("payroll_runs", sa.Column("salary_slips_submitted", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("payroll_runs", sa.Column("payment_status", sa.String(16), nullable=False, server_default="unpaid"))
    op.add_column("payroll_runs", sa.Column("payment_account_id", sa.Integer(), sa.ForeignKey("erp_accounts.id", ondelete="SET NULL")))
    op.add_column("payroll_runs", sa.Column("cost_center_id", sa.Integer(), sa.ForeignKey("erp_cost_centers.id", ondelete="SET NULL")))
    op.add_column("payroll_runs", sa.Column("payroll_period_id", sa.Integer(), sa.ForeignKey("payroll_periods.id", ondelete="SET NULL")))
    op.add_column("payroll_runs", sa.Column("bank_entry_id", sa.Integer(), sa.ForeignKey("payroll_bank_entries.id", ondelete="SET NULL")))
    op.add_column("payslips", sa.Column("document_status", sa.String(16), nullable=False, server_default="draft"))
    op.add_column("payslips", sa.Column("submitted_at", sa.DateTime(timezone=True)))
    op.add_column("payslips", sa.Column("published_at", sa.DateTime(timezone=True)))
    op.add_column("payslips", sa.Column("cancelled_at", sa.DateTime(timezone=True)))
    op.create_index("ix_payroll_run_org_workflow_status", "payroll_runs", ["organization_id", "workflow_version", "document_status", "posting_date"])

    bind = op.get_bind()
    # The preceding Mongolia payroll migration protects finalized snapshots
    # with triggers.  This migration only adds workflow metadata and master
    # links; temporarily suspending those guards lets the non-destructive
    # backfill complete without changing any historical payroll values.  The
    # guards are restored before upgrade returns (and PostgreSQL rolls back
    # the disable statements automatically if the migration fails).
    bind.execute(sa.text("""
        CREATE OR REPLACE FUNCTION payroll_guard_immutable() RETURNS trigger AS $$
        DECLARE run_status text; workflow text;
        BEGIN
          IF TG_TABLE_NAME = 'payroll_employee_accumulators' THEN
            RAISE EXCEPTION 'Payroll accumulator rows are append-only';
          ELSIF TG_TABLE_NAME = 'payroll_runs' THEN
            run_status := OLD.status;
            workflow := OLD.workflow_version;
            IF run_status IN ('posted', 'paid') THEN
              IF workflow = 'frappe_v1' THEN
                -- Frappe documents may advance their document/payment state
                -- after accrual, but their frozen inputs and totals remain
                -- immutable and require cancel/amendment for correction.
                IF (to_jsonb(NEW) - 'payslips_published_at' - 'updated_at' - 'status' - 'document_status' - 'bank_entry_id' - 'payment_status')
                  IS DISTINCT FROM (to_jsonb(OLD) - 'payslips_published_at' - 'updated_at' - 'status' - 'document_status' - 'bank_entry_id' - 'payment_status') THEN
                  RAISE EXCEPTION 'Finalized Frappe payroll snapshots are immutable';
                END IF;
              ELSIF (to_jsonb(NEW) - 'payslips_published_at' - 'updated_at')
                IS DISTINCT FROM (to_jsonb(OLD) - 'payslips_published_at' - 'updated_at') THEN
                RAISE EXCEPTION 'Posted payroll runs are immutable';
              END IF;
            END IF;
          ELSIF TG_TABLE_NAME = 'payslips' THEN
            SELECT r.status, r.workflow_version INTO run_status, workflow FROM payroll_runs r WHERE r.id = OLD.payroll_run_id;
            IF run_status IN ('approved', 'posted', 'paid') THEN
              IF workflow = 'frappe_v1' THEN
                IF (to_jsonb(NEW) - 'document_status' - 'submitted_at' - 'published_at' - 'cancelled_at')
                  IS DISTINCT FROM (to_jsonb(OLD) - 'document_status' - 'submitted_at' - 'published_at' - 'cancelled_at') THEN
                  RAISE EXCEPTION 'Finalized Frappe payslip snapshots are immutable';
                END IF;
              ELSE
                RAISE EXCEPTION 'Finalized payroll snapshots are immutable';
              END IF;
            END IF;
          ELSIF TG_TABLE_NAME = 'payslip_line_items' THEN
            SELECT r.status INTO run_status FROM payroll_runs r JOIN payslips p ON p.payroll_run_id = r.id WHERE p.id = OLD.payslip_id;
            IF run_status IN ('approved', 'posted', 'paid') THEN RAISE EXCEPTION 'Finalized payroll snapshots are immutable'; END IF;
          ELSIF TG_TABLE_NAME = 'statutory_config_profiles' THEN
            IF OLD.status IN ('published', 'active') THEN RAISE EXCEPTION 'Published statutory profiles are immutable'; END IF;
          ELSIF TG_TABLE_NAME = 'salary_structures' OR TG_TABLE_NAME = 'salary_structure_versions' THEN
            IF OLD.status IN ('published', 'active') THEN RAISE EXCEPTION 'Published salary structures are immutable'; END IF;
          ELSIF TG_TABLE_NAME = 'salary_components' THEN
            SELECT s.status INTO run_status FROM salary_structures s WHERE s.id = OLD.salary_structure_id;
            IF run_status IN ('published', 'active') THEN RAISE EXCEPTION 'Published salary components are immutable'; END IF;
          ELSE
            SELECT status INTO run_status FROM payroll_runs WHERE id = OLD.payroll_run_id;
            IF run_status IN ('approved', 'posted', 'paid') THEN RAISE EXCEPTION 'Finalized payroll snapshots are immutable'; END IF;
          END IF;
          IF TG_OP = 'DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
        END;
        $$ LANGUAGE plpgsql;
    """))
    bind.execute(sa.text("ALTER TABLE payroll_runs DISABLE TRIGGER payroll_run_immutable; ALTER TABLE payslips DISABLE TRIGGER payroll_payslip_immutable; ALTER TABLE salary_components DISABLE TRIGGER payroll_salary_component_immutable"))
    bind.execute(sa.text("UPDATE payroll_runs SET workflow_version = 'legacy', document_status = CASE WHEN status IN ('approved', 'posted', 'paid') THEN 'submitted' ELSE 'draft' END, salary_slips_created = status <> 'draft', salary_slips_submitted = status IN ('approved', 'posted', 'paid'), posting_date = period_end"))
    bind.execute(sa.text("UPDATE payslips SET document_status = CASE WHEN EXISTS (SELECT 1 FROM payroll_runs r WHERE r.id = payslips.payroll_run_id AND r.status IN ('approved', 'posted', 'paid')) THEN 'submitted' ELSE 'draft' END, submitted_at = CASE WHEN EXISTS (SELECT 1 FROM payroll_runs r WHERE r.id = payslips.payroll_run_id AND r.status IN ('approved', 'posted', 'paid')) THEN payslips.created_at ELSE NULL END"))

    # Backfill periods from legacy runs, retaining one period per distinct
    # organization/date window and linking every run to its period.
    period_ids: dict[tuple[int, date, date], int] = {}
    period_rows = bind.execute(sa.text("SELECT DISTINCT ON (organization_id, period_start, period_end) organization_id, period_start, period_end, tax_point_date, statutory_profile_id FROM payroll_runs ORDER BY organization_id, period_start, period_end, id"))
    for row in period_rows:
        key = (row.organization_id, row.period_start, row.period_end)
        if key in period_ids:
            continue
        base_code = f"{row.period_start:%Y-%m}"
        code = base_code
        suffix = 1
        while bind.execute(sa.text("SELECT 1 FROM payroll_periods WHERE organization_id = :organization_id AND code = :code"), {"organization_id": row.organization_id, "code": code}).first():
            suffix += 1
            code = f"{base_code}-{suffix}"
        result = bind.execute(sa.text("INSERT INTO payroll_periods (organization_id, code, name, start_date, end_date, tax_year, payroll_frequency, statutory_profile_id, status) VALUES (:organization_id, :code, :name, :start_date, :end_date, :tax_year, 'monthly', :statutory_profile_id, 'closed') RETURNING id"), {"organization_id": row.organization_id, "code": code, "name": f"Payroll {row.period_start:%Y-%m-%d} – {row.period_end:%Y-%m-%d}", "start_date": row.period_start, "end_date": row.period_end, "tax_year": row.tax_point_date.year, "statutory_profile_id": row.statutory_profile_id})
        period_ids[key] = result.scalar_one()
    for (organization_id, period_start, period_end), period_id in period_ids.items():
        bind.execute(sa.text("UPDATE payroll_runs SET payroll_period_id = :period_id WHERE organization_id = :organization_id AND period_start = :period_start AND period_end = :period_end"), {"period_id": period_id, "organization_id": organization_id, "period_start": period_start, "period_end": period_end})

    # Create one reusable master for identical legacy definitions.  If the
    # same code has conflicting definitions, preserve each structure line with
    # a deterministic legacy suffix instead of changing historical formulas.
    master_by_definition: dict[tuple[int, str, str], int] = {}
    component_rows = bind.execute(sa.text("SELECT sc.id, ss.organization_id, ss.id AS structure_id, sc.code, sc.name, sc.component_kind, sc.formula, sc.proration_basis, sc.is_taxable, sc.is_shi_subject, sc.is_non_taxable_allowance, sc.is_leave_average_eligible, sc.is_flexible_benefit, sc.max_benefit_amount_yearly, sc.pay_against_benefit_claim, sc.only_tax_impact, sc.payer, sc.account_id, sc.cost_center_id, sc.metadata_json FROM salary_components sc JOIN salary_structures ss ON ss.id = sc.salary_structure_id ORDER BY ss.organization_id, sc.code, sc.id"))
    for row in component_rows:
        fingerprint = repr((row.name, row.component_kind, row.formula, row.proration_basis, row.is_taxable, row.is_shi_subject, row.is_non_taxable_allowance, row.is_leave_average_eligible, row.is_flexible_benefit, str(row.max_benefit_amount_yearly), row.pay_against_benefit_claim, row.only_tax_impact, row.payer, row.account_id, row.cost_center_id, row.metadata_json))
        definition_key = (row.organization_id, row.code, fingerprint)
        master_id = master_by_definition.get(definition_key)
        if master_id is None:
            existing_code = bind.execute(sa.text("SELECT code FROM payroll_salary_component_masters WHERE organization_id = :organization_id AND source_salary_component_id IS NOT NULL AND code = :code"), {"organization_id": row.organization_id, "code": row.code}).first()
            code = row.code if existing_code is None else _next_code(bind, row.organization_id, row.code, str(row.structure_id))
            params = {**row._mapping, "code": code, "metadata_json": json.dumps(row.metadata_json or {})}
            master_id = bind.execute(sa.text("INSERT INTO payroll_salary_component_masters (organization_id, code, name, component_kind, formula, proration_basis, is_taxable, is_shi_subject, is_non_taxable_allowance, is_leave_average_eligible, is_flexible_benefit, max_benefit_amount_yearly, pay_against_benefit_claim, only_tax_impact, payer, account_id, cost_center_id, metadata_json, source_salary_component_id) VALUES (:organization_id, :code, :name, :component_kind, :formula, :proration_basis, :is_taxable, :is_shi_subject, :is_non_taxable_allowance, :is_leave_average_eligible, :is_flexible_benefit, :max_benefit_amount_yearly, :pay_against_benefit_claim, :only_tax_impact, :payer, :account_id, :cost_center_id, CAST(:metadata_json AS jsonb), :source_salary_component_id) RETURNING id"), params).scalar_one()
            master_by_definition[definition_key] = master_id
        bind.execute(sa.text("UPDATE salary_components SET component_master_id = :master_id WHERE id = :id"), {"master_id": master_id, "id": row.id})
    bind.execute(sa.text("ALTER TABLE salary_components ENABLE TRIGGER payroll_salary_component_immutable; ALTER TABLE payslips ENABLE TRIGGER payroll_payslip_immutable; ALTER TABLE payroll_runs ENABLE TRIGGER payroll_run_immutable"))


def downgrade() -> None:
    # Restore the pre-Frappe trigger body before removing the columns it
    # references.  This keeps a downgrade deployable and preserves the
    # original legacy immutability semantics for the remaining tables.
    op.execute(sa.text("""
        CREATE OR REPLACE FUNCTION payroll_guard_immutable() RETURNS trigger AS $$
        DECLARE run_status text;
        BEGIN
          IF TG_TABLE_NAME = 'payroll_employee_accumulators' THEN
            RAISE EXCEPTION 'Payroll accumulator rows are append-only';
          ELSIF TG_TABLE_NAME = 'payroll_runs' THEN
            run_status := OLD.status;
            IF run_status IN ('posted', 'paid')
              AND (to_jsonb(NEW) - 'payslips_published_at' - 'updated_at')
                IS DISTINCT FROM (to_jsonb(OLD) - 'payslips_published_at' - 'updated_at') THEN
              RAISE EXCEPTION 'Posted payroll runs are immutable';
            END IF;
          ELSIF TG_TABLE_NAME = 'payslip_line_items' THEN
            SELECT r.status INTO run_status FROM payroll_runs r JOIN payslips p ON p.payroll_run_id = r.id WHERE p.id = OLD.payslip_id;
            IF run_status IN ('approved', 'posted', 'paid') THEN RAISE EXCEPTION 'Finalized payroll snapshots are immutable'; END IF;
          ELSIF TG_TABLE_NAME = 'statutory_config_profiles' THEN
            IF OLD.status IN ('published', 'active') THEN RAISE EXCEPTION 'Published statutory profiles are immutable'; END IF;
          ELSIF TG_TABLE_NAME = 'salary_structures' OR TG_TABLE_NAME = 'salary_structure_versions' THEN
            IF OLD.status IN ('published', 'active') THEN RAISE EXCEPTION 'Published salary structures are immutable'; END IF;
          ELSIF TG_TABLE_NAME = 'salary_components' THEN
            SELECT s.status INTO run_status FROM salary_structures s WHERE s.id = OLD.salary_structure_id;
            IF run_status IN ('published', 'active') THEN RAISE EXCEPTION 'Published salary components are immutable'; END IF;
          ELSE
            SELECT status INTO run_status FROM payroll_runs WHERE id = OLD.payroll_run_id;
            IF run_status IN ('approved', 'posted', 'paid') THEN RAISE EXCEPTION 'Finalized payroll snapshots are immutable'; END IF;
          END IF;
          IF TG_OP = 'DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
        END;
        $$ LANGUAGE plpgsql;
    """))
    op.drop_index("ix_payroll_run_org_workflow_status", table_name="payroll_runs")
    op.drop_column("payslips", "cancelled_at")
    op.drop_column("payslips", "published_at")
    op.drop_column("payslips", "submitted_at")
    op.drop_column("payslips", "document_status")
    op.drop_column("payroll_runs", "bank_entry_id")
    op.drop_column("payroll_runs", "payroll_period_id")
    op.drop_column("payroll_runs", "cost_center_id")
    op.drop_column("payroll_runs", "payment_account_id")
    op.drop_column("payroll_runs", "payment_status")
    op.drop_column("payroll_runs", "salary_slips_submitted")
    op.drop_column("payroll_runs", "salary_slips_created")
    op.drop_column("payroll_runs", "employee_filter")
    op.drop_column("payroll_runs", "posting_date")
    op.drop_column("payroll_runs", "payroll_frequency")
    op.drop_column("payroll_runs", "document_status")
    op.drop_column("payroll_runs", "workflow_version")
    op.drop_column("employee_payroll_profiles", "document_status")
    op.drop_column("salary_components", "component_master_id")
    op.drop_index("ix_payroll_bank_entry_org_status", table_name="payroll_bank_entries")
    op.drop_table("payroll_bank_entries")
    op.drop_index("ix_payroll_additional_salary_employee_date", table_name="payroll_additional_salaries")
    op.drop_table("payroll_additional_salaries")
    op.drop_index("ix_payroll_component_master_org_status", table_name="payroll_salary_component_masters")
    op.drop_table("payroll_salary_component_masters")
    op.drop_index("ix_payroll_period_org_dates", table_name="payroll_periods")
    op.drop_table("payroll_periods")
