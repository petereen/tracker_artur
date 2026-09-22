"""Add unified payroll v2 guardrails and reversal audit records."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "h3i4j5k6l7m8"
down_revision = "g2h3i4j5k6l7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table, column in (
        ("statutory_config_profiles", sa.Column("superseded_on", sa.Date(), nullable=True)),
        ("salary_structures", sa.Column("superseded_on", sa.Date(), nullable=True)),
    ):
        op.add_column(table, column)

    op.add_column("statutory_config_profiles", sa.Column("superseded_by_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_payroll_profile_superseded_by",
        "statutory_config_profiles",
        "statutory_config_profiles",
        ["superseded_by_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column("salary_structures", sa.Column("superseded_by_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_payroll_structure_superseded_by",
        "salary_structures",
        "salary_structures",
        ["superseded_by_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column("payroll_salary_component_masters", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("payroll_salary_component_masters", sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False))
    op.add_column("payroll_salary_component_masters", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(sa.text("UPDATE payroll_salary_component_masters SET is_active = (status IN ('active', 'published'))"))
    op.create_index(
        "ix_payroll_component_master_org_active",
        "payroll_salary_component_masters",
        ["organization_id", "is_active", "archived_at"],
    )

    op.add_column("payslip_line_items", sa.Column("component_master_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_payroll_payslip_line_component_master",
        "payslip_line_items",
        "payroll_salary_component_masters",
        ["component_master_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.execute(sa.text("""
        UPDATE payslip_line_items li
        SET component_master_id = cm.id
        FROM payslips p
        JOIN payroll_runs r ON r.id = p.payroll_run_id
        JOIN payroll_salary_component_masters cm ON cm.organization_id = p.organization_id
        WHERE li.payslip_id = p.id AND r.organization_id = p.organization_id
          AND cm.code = li.component_code
    """))
    op.create_index("ix_payroll_payslip_line_component_master", "payslip_line_items", ["component_master_id"])

    op.add_column("payroll_runs", sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("payroll_runs", sa.Column("rejected_by_account_id", sa.Integer(), nullable=True))
    op.add_column("payroll_runs", sa.Column("rejection_reason", sa.Text(), nullable=True))
    op.add_column("payroll_runs", sa.Column("reversed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("payroll_runs", sa.Column("reversed_by_account_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_payroll_run_rejected_by", "payroll_runs", "user_accounts", ["rejected_by_account_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_payroll_run_reversed_by", "payroll_runs", "user_accounts", ["reversed_by_account_id"], ["id"], ondelete="SET NULL")

    op.add_column("payroll_payment_allocations", sa.Column("reversed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("payroll_payment_allocations", sa.Column("reversed_by_account_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_payroll_payment_reversed_by", "payroll_payment_allocations", "user_accounts", ["reversed_by_account_id"], ["id"], ondelete="SET NULL")

    op.create_table(
        "payroll_payment_reversals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("payment_allocation_id", sa.Integer(), sa.ForeignKey("payroll_payment_allocations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("original_erp_document_id", sa.Integer(), sa.ForeignKey("erp_documents.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("reversal_erp_document_id", sa.Integer(), sa.ForeignKey("erp_documents.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("transaction_reference", sa.String(160), nullable=False),
        sa.Column("evidence", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("payment_allocation_id", name="uq_payroll_payment_reversal_allocation"),
    )

    # Replace the old terminal-state comparison with the complete v2 state
    # set. Financial payloads remain immutable; workflow metadata can advance.
    op.execute(sa.text("""
        CREATE OR REPLACE FUNCTION payroll_guard_immutable() RETURNS trigger AS $$
        DECLARE run_status text; workflow text;
        BEGIN
          IF TG_TABLE_NAME = 'payroll_employee_accumulators' THEN
            RAISE EXCEPTION 'Payroll accumulator rows are append-only';
          ELSIF TG_TABLE_NAME = 'payroll_runs' THEN
            run_status := OLD.status; workflow := OLD.workflow_version;
            IF workflow = 'unified_v2' AND run_status IN ('calculated','in_review','approved','posted','payment_prepared','partially_settled','settled','payslips_released','rejected','reversed') THEN
              IF (to_jsonb(NEW) - 'status' - 'payment_status' - 'payslips_published_at' - 'approval_workflow' - 'reconciliation_snapshot' - 'rejected_at' - 'rejected_by_account_id' - 'rejection_reason' - 'reversed_at' - 'reversed_by_account_id' - 'erp_document_id' - 'posting_profile_id' - 'posted_at' - 'posting_date' - 'approved_by_account_id' - 'approved_at' - 'document_status' - 'bank_entry_id' - 'updated_at')
                IS DISTINCT FROM (to_jsonb(OLD) - 'status' - 'payment_status' - 'payslips_published_at' - 'approval_workflow' - 'reconciliation_snapshot' - 'rejected_at' - 'rejected_by_account_id' - 'rejection_reason' - 'reversed_at' - 'reversed_by_account_id' - 'erp_document_id' - 'posting_profile_id' - 'posted_at' - 'posting_date' - 'approved_by_account_id' - 'approved_at' - 'document_status' - 'bank_entry_id' - 'updated_at') THEN
                RAISE EXCEPTION 'Finalized unified payroll snapshots are immutable';
              END IF;
            ELSIF run_status IN ('posted','paid') AND (to_jsonb(NEW) - 'payslips_published_at' - 'updated_at' - 'status' - 'document_status' - 'bank_entry_id' - 'payment_status') IS DISTINCT FROM (to_jsonb(OLD) - 'payslips_published_at' - 'updated_at' - 'status' - 'document_status' - 'bank_entry_id' - 'payment_status') THEN
              RAISE EXCEPTION 'Finalized Frappe payroll snapshots are immutable';
            END IF;
          ELSIF TG_TABLE_NAME = 'payslips' THEN
            SELECT r.status, r.workflow_version INTO run_status, workflow FROM payroll_runs r WHERE r.id = OLD.payroll_run_id;
            IF workflow = 'unified_v2' AND run_status IN ('calculated','in_review','approved','posted','payment_prepared','partially_settled','settled','payslips_released','rejected','reversed') THEN
              RAISE EXCEPTION 'Finalized unified payslip snapshots are immutable';
            ELSIF run_status IN ('approved','posted','paid') THEN
              RAISE EXCEPTION 'Finalized payroll snapshots are immutable';
            END IF;
          ELSIF TG_TABLE_NAME = 'payslip_line_items' THEN
            SELECT r.status INTO run_status FROM payroll_runs r JOIN payslips p ON p.payroll_run_id = r.id WHERE p.id = OLD.payslip_id;
            IF run_status IN ('calculated','in_review','approved','posted','payment_prepared','partially_settled','settled','payslips_released','rejected','reversed') THEN RAISE EXCEPTION 'Finalized payroll line items are immutable'; END IF;
          ELSIF TG_TABLE_NAME = 'statutory_config_profiles' THEN
            IF OLD.status IN ('published','active') AND (to_jsonb(NEW) - 'superseded_on' - 'superseded_by_id') IS DISTINCT FROM (to_jsonb(OLD) - 'superseded_on' - 'superseded_by_id') THEN RAISE EXCEPTION 'Published statutory profiles are immutable'; END IF;
          ELSIF TG_TABLE_NAME = 'salary_structures' OR TG_TABLE_NAME = 'salary_structure_versions' THEN
            IF OLD.status IN ('published','active') AND (to_jsonb(NEW) - 'superseded_on' - 'superseded_by_id') IS DISTINCT FROM (to_jsonb(OLD) - 'superseded_on' - 'superseded_by_id') THEN RAISE EXCEPTION 'Published salary structures are immutable'; END IF;
          ELSIF TG_TABLE_NAME = 'salary_components' THEN
            SELECT s.status INTO run_status FROM salary_structures s WHERE s.id = OLD.salary_structure_id;
            IF run_status IN ('published','active') THEN RAISE EXCEPTION 'Published salary components are immutable'; END IF;
          END IF;
          IF TG_OP = 'DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
        END;
        $$ LANGUAGE plpgsql;
    """))


def downgrade() -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS payroll_payment_reversals"))
    op.drop_index("ix_payroll_component_master_org_active", table_name="payroll_salary_component_masters")
    op.drop_index("ix_payroll_payslip_line_component_master", table_name="payslip_line_items")
    for name, table in (
        ("fk_payroll_payment_reversed_by", "payroll_payment_allocations"),
        ("fk_payroll_run_reversed_by", "payroll_runs"),
        ("fk_payroll_run_rejected_by", "payroll_runs"),
        ("fk_payroll_payslip_line_component_master", "payslip_line_items"),
        ("fk_payroll_structure_superseded_by", "salary_structures"),
        ("fk_payroll_profile_superseded_by", "statutory_config_profiles"),
    ):
        op.drop_constraint(name, table, type_="foreignkey")
    for table, column in (
        ("payroll_payment_allocations", "reversed_by_account_id"),
        ("payroll_payment_allocations", "reversed_at"),
        ("payroll_runs", "reversed_by_account_id"),
        ("payroll_runs", "reversed_at"),
        ("payroll_runs", "rejection_reason"),
        ("payroll_runs", "rejected_by_account_id"),
        ("payroll_runs", "rejected_at"),
        ("payslip_line_items", "component_master_id"),
        ("payroll_salary_component_masters", "archived_at"),
        ("payroll_salary_component_masters", "is_active"),
        ("payroll_salary_component_masters", "description"),
        ("salary_structures", "superseded_by_id"),
        ("salary_structures", "superseded_on"),
        ("statutory_config_profiles", "superseded_by_id"),
        ("statutory_config_profiles", "superseded_on"),
    ):
        op.drop_column(table, column)
