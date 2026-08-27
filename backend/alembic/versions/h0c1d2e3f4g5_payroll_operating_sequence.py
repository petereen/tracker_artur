"""Add payroll reconciliation, sequential approvals, and publication state."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "h0c1d2e3f4g5"
down_revision: Union[str, Sequence[str], None] = "g0b1c2d3e4f5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("payroll_runs", sa.Column("reconciliation_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.add_column("payroll_runs", sa.Column("approval_workflow", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.add_column("payroll_runs", sa.Column("approved_at", sa.DateTime(timezone=True)))
    op.add_column("payroll_runs", sa.Column("payslips_published_at", sa.DateTime(timezone=True)))
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


def downgrade() -> None:
    op.execute(sa.text("""
        CREATE OR REPLACE FUNCTION payroll_guard_immutable() RETURNS trigger AS $$
        DECLARE run_status text;
        BEGIN
          IF TG_TABLE_NAME = 'payroll_employee_accumulators' THEN
            RAISE EXCEPTION 'Payroll accumulator rows are append-only';
          ELSIF TG_TABLE_NAME = 'payroll_runs' THEN
            run_status := OLD.status;
            IF run_status IN ('posted', 'paid') THEN RAISE EXCEPTION 'Posted payroll runs are immutable'; END IF;
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
    op.drop_column("payroll_runs", "payslips_published_at")
    op.drop_column("payroll_runs", "approved_at")
    op.drop_column("payroll_runs", "approval_workflow")
    op.drop_column("payroll_runs", "reconciliation_snapshot")
