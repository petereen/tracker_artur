"""Allow payroll component edits and deletion with preserved snapshots."""

from alembic import op
import sqlalchemy as sa


revision = "q7r8s9t0u1v2"
down_revision = "q6r7s8t9u0v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("payroll_additional_salaries", sa.Column("component_code", sa.String(length=80), nullable=True))
    op.add_column("payroll_additional_salaries", sa.Column("component_name", sa.Text(), nullable=True))
    op.execute(sa.text("""
        UPDATE payroll_additional_salaries AS additional
        SET component_code = component.code,
            component_name = component.name
        FROM payroll_salary_component_masters AS component
        WHERE additional.salary_component_id = component.id
    """))
    op.alter_column("payroll_additional_salaries", "component_code", existing_type=sa.String(length=80), nullable=False)
    op.alter_column("payroll_additional_salaries", "component_name", existing_type=sa.Text(), nullable=False)

    op.drop_constraint(
        "employee_compensation_items_component_master_id_fkey",
        "employee_compensation_items",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_employee_compensation_component_master",
        "employee_compensation_items",
        "payroll_salary_component_masters",
        ["component_master_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.drop_constraint(
        "fk_payroll_payslip_line_component_master",
        "payslip_line_items",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_payroll_payslip_line_component_master",
        "payslip_line_items",
        "payroll_salary_component_masters",
        ["component_master_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.drop_constraint(
        "payroll_additional_salaries_salary_component_id_fkey",
        "payroll_additional_salaries",
        type_="foreignkey",
    )
    op.alter_column(
        "payroll_additional_salaries",
        "salary_component_id",
        existing_type=sa.Integer(),
        nullable=True,
    )
    op.create_foreign_key(
        "fk_payroll_additional_salary_component_master",
        "payroll_additional_salaries",
        "payroll_salary_component_masters",
        ["salary_component_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.execute(sa.text("""
        CREATE OR REPLACE FUNCTION payroll_guard_immutable() RETURNS trigger AS $$
        DECLARE run_status text; workflow text;
        BEGIN
          IF TG_OP = 'UPDATE'
            AND TG_TABLE_NAME IN ('payslip_line_items', 'salary_components')
            AND OLD.component_master_id IS NOT NULL
            AND NEW.component_master_id IS NULL
            AND (to_jsonb(NEW) - 'component_master_id') IS NOT DISTINCT FROM (to_jsonb(OLD) - 'component_master_id') THEN
            RETURN NEW;
          END IF;
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
    op.drop_constraint(
        "fk_payroll_additional_salary_component_master",
        "payroll_additional_salaries",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "payroll_additional_salaries_salary_component_id_fkey",
        "payroll_additional_salaries",
        "payroll_salary_component_masters",
        ["salary_component_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.drop_constraint(
        "fk_payroll_payslip_line_component_master",
        "payslip_line_items",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_payroll_payslip_line_component_master",
        "payslip_line_items",
        "payroll_salary_component_masters",
        ["component_master_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.drop_constraint(
        "fk_employee_compensation_component_master",
        "employee_compensation_items",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "employee_compensation_items_component_master_id_fkey",
        "employee_compensation_items",
        "payroll_salary_component_masters",
        ["component_master_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.drop_column("payroll_additional_salaries", "component_name")
    op.drop_column("payroll_additional_salaries", "component_code")
