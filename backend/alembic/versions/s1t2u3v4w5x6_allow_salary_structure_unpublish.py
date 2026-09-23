"""Allow published salary structures to be returned to draft."""

from alembic import op
import sqlalchemy as sa


revision = "s1t2u3v4w5x6"
down_revision = "r1s2t3u4v5w6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("""
        CREATE OR REPLACE FUNCTION payroll_guard_immutable() RETURNS trigger AS $$
        DECLARE run_status text;
        BEGIN
          IF TG_TABLE_NAME = 'payroll_employee_accumulators' THEN
            RAISE EXCEPTION 'Payroll accumulator rows are append-only';
          ELSIF TG_TABLE_NAME = 'payroll_runs' THEN
            run_status := OLD.status;
            IF TG_OP = 'UPDATE' AND run_status IN ('posted', 'paid')
              AND (to_jsonb(NEW) - 'payslips_published_at' - 'updated_at')
                IS DISTINCT FROM (to_jsonb(OLD) - 'payslips_published_at' - 'updated_at') THEN
              RAISE EXCEPTION 'Posted payroll runs are immutable';
            END IF;
          ELSIF TG_TABLE_NAME = 'payslip_line_items' THEN
            SELECT r.status INTO run_status FROM payroll_runs r JOIN payslips p ON p.payroll_run_id = r.id WHERE p.id = OLD.payslip_id;
            IF run_status IN ('approved', 'posted', 'paid') THEN RAISE EXCEPTION 'Finalized payroll snapshots are immutable'; END IF;
          ELSIF TG_TABLE_NAME = 'statutory_config_profiles' THEN
            IF TG_OP = 'UPDATE' AND OLD.status IN ('published', 'active') THEN RAISE EXCEPTION 'Published statutory profiles are immutable'; END IF;
          ELSIF TG_TABLE_NAME = 'salary_structures' OR TG_TABLE_NAME = 'salary_structure_versions' THEN
            IF TG_OP = 'UPDATE' AND OLD.status IN ('published', 'active')
              AND NOT (NEW.status = 'draft'
                AND (to_jsonb(NEW) - 'status' - 'published_by_account_id' - 'published_at')
                  IS NOT DISTINCT FROM (to_jsonb(OLD) - 'status' - 'published_by_account_id' - 'published_at')) THEN
              RAISE EXCEPTION 'Published salary structures are immutable';
            END IF;
          ELSIF TG_TABLE_NAME = 'salary_components' THEN
            SELECT s.status INTO run_status FROM salary_structures s WHERE s.id = OLD.salary_structure_id;
            IF TG_OP = 'UPDATE' AND run_status IN ('published', 'active') THEN RAISE EXCEPTION 'Published salary components are immutable'; END IF;
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
          IF TG_TABLE_NAME = 'payroll_employee_accumulators' THEN RAISE EXCEPTION 'Payroll accumulator rows are append-only';
          ELSIF TG_TABLE_NAME = 'payroll_runs' THEN
            run_status := OLD.status;
            IF TG_OP = 'UPDATE' AND run_status IN ('posted', 'paid')
              AND (to_jsonb(NEW) - 'payslips_published_at' - 'updated_at') IS DISTINCT FROM (to_jsonb(OLD) - 'payslips_published_at' - 'updated_at') THEN RAISE EXCEPTION 'Posted payroll runs are immutable'; END IF;
          ELSIF TG_TABLE_NAME = 'payslip_line_items' THEN
            SELECT r.status INTO run_status FROM payroll_runs r JOIN payslips p ON p.payroll_run_id = r.id WHERE p.id = OLD.payslip_id;
            IF run_status IN ('approved', 'posted', 'paid') THEN RAISE EXCEPTION 'Finalized payroll snapshots are immutable'; END IF;
          ELSIF TG_TABLE_NAME = 'statutory_config_profiles' THEN
            IF TG_OP = 'UPDATE' AND OLD.status IN ('published', 'active') THEN RAISE EXCEPTION 'Published statutory profiles are immutable'; END IF;
          ELSIF TG_TABLE_NAME = 'salary_structures' OR TG_TABLE_NAME = 'salary_structure_versions' THEN
            IF TG_OP = 'UPDATE' AND OLD.status IN ('published', 'active') THEN RAISE EXCEPTION 'Published salary structures are immutable'; END IF;
          ELSIF TG_TABLE_NAME = 'salary_components' THEN
            SELECT s.status INTO run_status FROM salary_structures s WHERE s.id = OLD.salary_structure_id;
            IF TG_OP = 'UPDATE' AND run_status IN ('published', 'active') THEN RAISE EXCEPTION 'Published salary components are immutable'; END IF;
          ELSE
            SELECT status INTO run_status FROM payroll_runs WHERE id = OLD.payroll_run_id;
            IF run_status IN ('approved', 'posted', 'paid') THEN RAISE EXCEPTION 'Finalized payroll snapshots are immutable'; END IF;
          END IF;
          IF TG_OP = 'DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
        END;
        $$ LANGUAGE plpgsql;
    """))
