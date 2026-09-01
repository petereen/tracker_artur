"""Add tenant-safe HR profiles, Telegram invites, leave, attendance, and recurring compensation."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "j0k1l2m3n4o5"
down_revision: Union[str, Sequence[str], None] = "i0j1k2l3m4n5"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    employee_columns = {row["name"] for row in inspector.get_columns("employees")}
    if "organization_id" not in employee_columns:
        op.add_column("employees", sa.Column("organization_id", sa.Integer(), nullable=True))
        op.create_index("ix_employees_organization_id", "employees", ["organization_id"])
        op.create_foreign_key("fk_employees_organization", "employees", "organizations", ["organization_id"], ["id"], ondelete="CASCADE")
        op.execute(sa.text("""
            UPDATE employees e
            SET organization_id = COALESCE((
                SELECT ua.organization_id FROM user_accounts ua
                WHERE ua.employee_id = e.id ORDER BY ua.id LIMIT 1
            ), 1)
            WHERE e.organization_id IS NULL
        """))
        op.alter_column("employees", "organization_id", nullable=False)
    for name, column in (
        ("first_name", sa.Column("first_name", sa.Text(), nullable=True)),
        ("last_name", sa.Column("last_name", sa.Text(), nullable=True)),
        ("photo_url", sa.Column("photo_url", sa.Text(), nullable=True)),
    ):
        if name not in employee_columns:
            op.add_column("employees", column)
    if "telegram_id" in employee_columns:
        op.alter_column("employees", "telegram_id", nullable=True)
    payroll_columns = {row["name"] for row in sa.inspect(op.get_bind()).get_columns("payroll_runs")}
    if "hr_generation_key" not in payroll_columns:
        op.add_column("payroll_runs", sa.Column("hr_generation_key", sa.String(255), nullable=True, unique=True))

    if _has_table("time_off") and not _has_table("leave_requests"):
        op.rename_table("time_off", "leave_requests")
    leave_columns = {row["name"] for row in sa.inspect(op.get_bind()).get_columns("leave_requests")}
    if "organization_id" not in leave_columns:
        op.add_column("leave_requests", sa.Column("organization_id", sa.Integer(), nullable=True))
        op.create_index("ix_leave_requests_organization_id", "leave_requests", ["organization_id"])
        op.create_foreign_key("fk_leave_requests_organization", "leave_requests", "organizations", ["organization_id"], ["id"], ondelete="CASCADE")
        op.execute(sa.text("UPDATE leave_requests l SET organization_id = e.organization_id FROM employees e WHERE e.id = l.employee_id"))
        op.alter_column("leave_requests", "organization_id", nullable=False)
    for name, column in (
        ("reason", sa.Column("reason", sa.Text(), nullable=True)),
        ("working_days", sa.Column("working_days", sa.Numeric(8, 2), nullable=True)),
        ("reviewed_by_account_id", sa.Column("reviewed_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL"), nullable=True)),
        ("reviewer_feedback", sa.Column("reviewer_feedback", sa.Text(), nullable=True)),
        ("reviewed_at", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True)),
        ("version", sa.Column("version", sa.Integer(), nullable=False, server_default="1")),
    ):
        if name not in leave_columns:
            op.add_column("leave_requests", column)
    op.execute(sa.text("UPDATE leave_requests SET time_off_type = 'annual' WHERE time_off_type = 'vacation'"))
    op.execute(sa.text("UPDATE leave_requests SET version = 1 WHERE version IS NULL"))

    op.create_table(
        "departments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("manager_employee_id", sa.Integer(), sa.ForeignKey("employees.id", ondelete="SET NULL")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "code", name="uq_departments_org_code"),
    )
    op.create_index("ix_departments_org_active", "departments", ["organization_id", "is_active"])
    op.create_table(
        "employee_details",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("department_id", sa.Integer(), sa.ForeignKey("departments.id", ondelete="SET NULL")),
        sa.Column("manager_id", sa.Integer(), sa.ForeignKey("employees.id", ondelete="SET NULL")),
        sa.Column("job_title", sa.Text()),
        sa.Column("employment_role", sa.Text()),
        sa.Column("start_date", sa.Date()),
        sa.Column("end_date", sa.Date()),
        sa.Column("employment_status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "employee_id", name="uq_employee_details_org_employee"),
        sa.UniqueConstraint("employee_id", name="uq_employee_details_employee"),
    )
    op.create_index("ix_employee_details_org_department", "employee_details", ["organization_id", "department_id"])
    op.create_table(
        "worker_invites",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("bound_telegram_id", sa.Text()),
        sa.Column("created_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_worker_invites_employee_active", "worker_invites", ["employee_id", "used_at", "revoked_at", "expires_at"])
    op.create_index("uq_worker_invites_employee_open", "worker_invites", ["employee_id"], unique=True, postgresql_where=sa.text("used_at IS NULL AND revoked_at IS NULL"))
    op.create_table(
        "leave_balances",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("leave_type", sa.String(20), nullable=False),
        sa.Column("entitled_days", sa.Numeric(8, 2), nullable=False, server_default="0"),
        sa.Column("carried_days", sa.Numeric(8, 2), nullable=False, server_default="0"),
        sa.Column("adjustment_days", sa.Numeric(8, 2), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "employee_id", "year", "leave_type", name="uq_leave_balances_employee_year_type"),
    )
    op.create_index("ix_leave_balances_org_year", "leave_balances", ["organization_id", "year", "leave_type"])
    op.create_table(
        "attendance_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("attendance_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("source", sa.String(16), nullable=False, server_default="manual"),
        sa.Column("worked_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("first_started_at", sa.DateTime(timezone=True)),
        sa.Column("last_ended_at", sa.DateTime(timezone=True)),
        sa.Column("confirmed_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("note", sa.Text()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "employee_id", "attendance_date", name="uq_attendance_logs_employee_date"),
    )
    op.create_index("ix_attendance_logs_org_date", "attendance_logs", ["organization_id", "attendance_date"])
    op.create_table(
        "employee_compensation_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("component_master_id", sa.Integer(), sa.ForeignKey("payroll_salary_component_masters.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("amount", sa.Numeric(20, 4), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_employee_compensation_org_employee_dates", "employee_compensation_items", ["organization_id", "employee_id", "effective_from", "effective_to"])

    # Populate the one-to-one employment record and department master without
    # guessing personal names or assigning project Teams as HR departments.
    op.execute(sa.text("""
        INSERT INTO departments (organization_id, code, name)
        SELECT e.organization_id,
               'legacy-' || md5(lower(trim(COALESCE(NULLIF(e.work_direction, ''), NULLIF(e.work_branch, ''))))),
               trim(COALESCE(NULLIF(e.work_direction, ''), NULLIF(e.work_branch, '')))
        FROM employees e
        WHERE COALESCE(NULLIF(trim(e.work_direction), ''), NULLIF(trim(e.work_branch), '')) IS NOT NULL
        GROUP BY e.organization_id, trim(COALESCE(NULLIF(e.work_direction, ''), NULLIF(e.work_branch, '')))
        ON CONFLICT (organization_id, code) DO NOTHING
    """))
    op.execute(sa.text("""
        INSERT INTO employee_details (organization_id, employee_id, department_id, manager_id, job_title, employment_status, start_date)
        SELECT e.organization_id, e.id, d.id, e.manager_id, e.job_title,
               CASE WHEN e.is_active THEN 'active' ELSE 'inactive' END,
               CASE WHEN e.onboarded_at IS NOT NULL THEN e.onboarded_at::date ELSE NULL END
        FROM employees e
        LEFT JOIN departments d ON d.organization_id = e.organization_id
          AND d.name = trim(COALESCE(NULLIF(e.work_direction, ''), NULLIF(e.work_branch, '')))
        ON CONFLICT (employee_id) DO NOTHING
    """))


def downgrade() -> None:
    op.drop_column("payroll_runs", "hr_generation_key")
    op.drop_index("ix_employee_compensation_org_employee_dates", table_name="employee_compensation_items")
    op.drop_table("employee_compensation_items")
    op.drop_index("ix_attendance_logs_org_date", table_name="attendance_logs")
    op.drop_table("attendance_logs")
    op.drop_index("ix_leave_balances_org_year", table_name="leave_balances")
    op.drop_table("leave_balances")
    op.drop_index("uq_worker_invites_employee_open", table_name="worker_invites")
    op.drop_index("ix_worker_invites_employee_active", table_name="worker_invites")
    op.drop_table("worker_invites")
    op.drop_index("ix_employee_details_org_department", table_name="employee_details")
    op.drop_table("employee_details")
    op.drop_index("ix_departments_org_active", table_name="departments")
    op.drop_table("departments")
    for name in ("version", "reviewed_at", "reviewer_feedback", "reviewed_by_account_id", "working_days", "reason", "organization_id"):
        op.drop_column("leave_requests", name)
    if _has_table("leave_requests") and not _has_table("time_off"):
        op.rename_table("leave_requests", "time_off")
    op.drop_column("employees", "photo_url")
    op.drop_column("employees", "last_name")
    op.drop_column("employees", "first_name")
    # Keep the column nullable on rollback: a pending HR invite may have no
    # Telegram identity, and restoring NOT NULL would make a data-preserving
    # downgrade fail. The legacy application can continue reading nullable
    # values via its compatibility response model.
    op.drop_constraint("fk_employees_organization", "employees", type_="foreignkey")
    op.drop_index("ix_employees_organization_id", table_name="employees")
    op.drop_column("employees", "organization_id")
