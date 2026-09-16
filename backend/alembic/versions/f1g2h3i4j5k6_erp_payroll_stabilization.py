"""Add explicit accounting controls and granular payroll treasury records."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "f1g2h3i4j5k6"
# Continue from the repository's current single deployable head so this
# feature does not introduce a second migration branch.
down_revision: Union[str, Sequence[str], None] = "n1o2p3q4r5s6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("erp_accounts", sa.Column("classification", sa.String(24), nullable=False, server_default="asset"))
    op.add_column("erp_accounts", sa.Column("purpose", sa.String(32), nullable=False, server_default="general"))
    op.add_column("erp_accounts", sa.Column("currency", sa.String(3), nullable=False, server_default="MNT"))
    op.add_column("salary_structures", sa.Column("source_structure_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_salary_structure_source", "salary_structures", "salary_structures", ["source_structure_id"], ["id"], ondelete="SET NULL")
    op.execute(sa.text("""
        UPDATE erp_accounts
        SET classification = CASE
          WHEN account_type IN ('cash','receivable','inventory','fixed_asset','wip') THEN 'asset'
          WHEN account_type IN ('payable','tax_payable','payroll_payable') THEN 'liability'
          WHEN account_type IN ('income') THEN 'income'
          WHEN account_type IN ('expense','payroll_expense') THEN 'expense'
          ELSE 'asset' END,
          purpose = CASE
          WHEN account_type = 'cash' THEN 'cash'
          WHEN account_type = 'receivable' THEN 'receivable'
          WHEN account_type IN ('payable','payroll_payable') THEN 'payable'
          WHEN account_type IN ('tax_payable','tax_receivable') THEN 'tax'
          WHEN account_type = 'inventory' THEN 'inventory'
          WHEN account_type = 'fixed_asset' THEN 'fixed_asset'
          WHEN account_type = 'payroll_expense' THEN 'salary_expense'
          WHEN account_type = 'income' THEN 'revenue'
          ELSE 'general' END
    """))

    op.add_column("employee_bank_accounts", sa.Column("employee_id", sa.Integer(), nullable=True))
    op.alter_column("employee_bank_accounts", "employee_payroll_profile_id", nullable=True)
    op.create_foreign_key("fk_employee_bank_account_employee", "employee_bank_accounts", "employees", ["employee_id"], ["id"], ondelete="RESTRICT")
    op.execute(sa.text("""
        UPDATE employee_bank_accounts a
        SET employee_id = p.employee_id
        FROM employee_payroll_profiles p
        WHERE p.id = a.employee_payroll_profile_id
    """))

    op.create_table(
        "erp_accounting_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("base_currency", sa.String(3), nullable=False, server_default="MNT"),
        sa.Column("fiscal_year_start_month", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("default_cost_center_id", sa.Integer(), sa.ForeignKey("erp_cost_centers.id", ondelete="SET NULL")),
        sa.Column("default_bank_account_id", sa.Integer(), sa.ForeignKey("erp_accounts.id", ondelete="SET NULL")),
        sa.Column("conversion_date", sa.Date()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", name="uq_erp_accounting_settings_org"),
    )

    op.create_table(
        "payroll_payment_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("payroll_run_id", sa.Integer(), sa.ForeignKey("payroll_runs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("batch_reference", sa.String(120), nullable=False),
        sa.Column("payment_account_id", sa.Integer(), sa.ForeignKey("erp_accounts.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("payable_account_id", sa.Integer(), sa.ForeignKey("erp_accounts.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("posting_date", sa.Date(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="MNT"),
        sa.Column("status", sa.String(24), nullable=False, server_default="prepared"),
        sa.Column("retry_of_batch_id", sa.Integer(), sa.ForeignKey("payroll_payment_batches.id", ondelete="RESTRICT")),
        sa.Column("export_artifact_id", sa.Integer(), sa.ForeignKey("payroll_export_artifacts.id", ondelete="SET NULL")),
        sa.Column("bank_reference", sa.String(160)),
        sa.Column("bank_confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("total_amount", sa.Numeric(20, 4), nullable=False, server_default="0"),
        sa.Column("created_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "batch_reference", name="uq_payroll_payment_batch_reference"),
    )
    op.create_index("ix_payroll_payment_batch_run_status", "payroll_payment_batches", ["payroll_run_id", "status"])

    op.create_table(
        "payroll_payment_allocations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("payment_batch_id", sa.Integer(), sa.ForeignKey("payroll_payment_batches.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("payslip_id", sa.Integer(), sa.ForeignKey("payslips.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("amount", sa.Numeric(20, 4), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("transaction_reference", sa.String(160)),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("settled_at", sa.DateTime(timezone=True)),
        sa.Column("rejected_at", sa.DateTime(timezone=True)),
        sa.Column("rejection_reason", sa.Text()),
        sa.Column("settlement_evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("erp_document_id", sa.Integer(), sa.ForeignKey("erp_documents.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("payment_batch_id", "payslip_id", name="uq_payroll_payment_allocation_slip"),
    )
    op.create_index("ix_payroll_payment_allocation_status", "payroll_payment_allocations", ["payment_batch_id", "status"])

    op.create_table(
        "payroll_statement_imports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("payment_account_id", sa.Integer(), sa.ForeignKey("erp_accounts.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_checksum", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="imported"),
        sa.Column("statement_start", sa.Date()),
        sa.Column("statement_end", sa.Date()),
        sa.Column("created_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "source_checksum", name="uq_payroll_statement_import_checksum"),
    )
    op.create_table(
        "payroll_statement_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("statement_import_id", sa.Integer(), sa.ForeignKey("payroll_statement_imports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("line_fingerprint", sa.String(64), nullable=False),
        sa.Column("transaction_reference", sa.String(160)),
        sa.Column("transaction_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(20, 4), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="MNT"),
        sa.Column("description", sa.Text()),
        sa.Column("match_status", sa.String(24), nullable=False, server_default="unmatched"),
        sa.Column("matched_allocation_id", sa.Integer(), sa.ForeignKey("payroll_payment_allocations.id", ondelete="SET NULL")),
        sa.Column("fee_amount", sa.Numeric(20, 4), nullable=False, server_default="0"),
        sa.Column("matched_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("statement_import_id", "line_fingerprint", name="uq_payroll_statement_line_fingerprint"),
    )
    op.create_index("ix_payroll_statement_line_match", "payroll_statement_lines", ["statement_import_id", "match_status"])

    op.execute(sa.text("""
        CREATE OR REPLACE FUNCTION erp_ledger_immutable() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'Posted ledger entries are immutable'; END;
        $$ LANGUAGE plpgsql;
        DROP TRIGGER IF EXISTS erp_gl_immutable ON erp_general_ledger_entries;
        CREATE TRIGGER erp_gl_immutable BEFORE UPDATE OR DELETE ON erp_general_ledger_entries
          FOR EACH ROW EXECUTE FUNCTION erp_ledger_immutable();
        DROP TRIGGER IF EXISTS erp_stock_immutable ON erp_stock_ledger_entries;
        CREATE TRIGGER erp_stock_immutable BEFORE UPDATE OR DELETE ON erp_stock_ledger_entries
          FOR EACH ROW EXECUTE FUNCTION erp_ledger_immutable();
    """))


def downgrade() -> None:
    op.execute(sa.text("DROP TRIGGER IF EXISTS erp_gl_immutable ON erp_general_ledger_entries; DROP TRIGGER IF EXISTS erp_stock_immutable ON erp_stock_ledger_entries; DROP FUNCTION IF EXISTS erp_ledger_immutable();"))
    op.drop_index("ix_payroll_statement_line_match", table_name="payroll_statement_lines")
    op.drop_table("payroll_statement_lines")
    op.drop_table("payroll_statement_imports")
    op.drop_index("ix_payroll_payment_allocation_status", table_name="payroll_payment_allocations")
    op.drop_table("payroll_payment_allocations")
    op.drop_index("ix_payroll_payment_batch_run_status", table_name="payroll_payment_batches")
    op.drop_table("payroll_payment_batches")
    op.drop_table("erp_accounting_settings")
    op.drop_constraint("fk_employee_bank_account_employee", "employee_bank_accounts", type_="foreignkey")
    op.drop_column("employee_bank_accounts", "employee_id")
    op.drop_column("erp_accounts", "currency")
    op.drop_column("erp_accounts", "purpose")
    op.drop_column("erp_accounts", "classification")
    op.drop_constraint("fk_salary_structure_source", "salary_structures", type_="foreignkey")
    op.drop_column("salary_structures", "source_structure_id")
