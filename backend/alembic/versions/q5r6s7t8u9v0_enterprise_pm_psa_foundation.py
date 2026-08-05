"""enterprise PM/PSA foundation

Revision ID: q5r6s7t8u9v0
Revises: p4q5r6s7t8u9
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.models.models import Base


revision: str = "q5r6s7t8u9v0"
down_revision: Union[str, Sequence[str], None] = "p4q5r6s7t8u9"
branch_labels = None
depends_on = None


NEW_TABLES = [
    "organizations", "user_accounts", "refresh_sessions", "teams", "team_members",
    "skills", "employee_skills", "clients", "projects", "project_members",
    "project_rates", "exchange_rate_snapshots", "role_assignments", "shift_schedules",
    "time_off", "resource_allocations", "task_assignees", "task_dependencies",
    "task_check_items", "attachments", "saved_views", "checkin_templates",
    "checkin_questions", "checkins", "checkin_answers", "report_comments",
    "objectives", "key_results", "milestones", "goal_links", "audit_logs",
    "domain_events", "job_queue", "idempotency_records", "calendar_connections",
    "calendar_event_links",
]


def _create(name: str) -> None:
    Base.metadata.tables[name].create(bind=op.get_bind(), checkfirst=True)


def _add_columns(table: str, columns: list[sa.Column]) -> None:
    for column in columns:
        op.add_column(table, column)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    _create("organizations")
    op.execute(
        "INSERT INTO organizations (id,name,timezone,base_currency,settings) "
        "VALUES (1,'OYUNS','Asia/Ulaanbaatar','MNT','{}'::jsonb) ON CONFLICT (id) DO NOTHING"
    )

    _add_columns("employees", [
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("manager_id", sa.Integer(), nullable=True),
        sa.Column("job_title", sa.Text(), nullable=True),
        sa.Column("primary_language", sa.String(8), nullable=False, server_default="mn"),
        sa.Column("employment_type", sa.String(24), nullable=False, server_default="member"),
        sa.Column("weekly_capacity_minutes", sa.Integer(), nullable=False, server_default="2400"),
        sa.Column("metadata_json", sa.dialects.postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    ])
    op.create_unique_constraint("uq_employees_email", "employees", ["email"])
    op.create_foreign_key("fk_employees_manager", "employees", "employees", ["manager_id"], ["id"], ondelete="SET NULL")

    _create("user_accounts")
    op.execute(
        """
        INSERT INTO user_accounts
            (organization_id,legacy_admin_id,email,password_hash,status,locale,must_change_password,created_at,updated_at)
        SELECT 1,id,lower(email),password_hash,'active','mn',false,COALESCE(created_at,now()),now()
        FROM admin_users ON CONFLICT (email) DO NOTHING
        """
    )

    for name in ("teams", "skills", "clients", "projects"):
        _create(name)
    for name in (
        "refresh_sessions", "team_members", "employee_skills", "project_members",
        "project_rates", "exchange_rate_snapshots", "role_assignments", "shift_schedules",
        "time_off", "resource_allocations",
    ):
        _create(name)
    op.execute(
        """
        INSERT INTO role_assignments (account_id,role)
        SELECT a.id,'admin' FROM user_accounts a
        WHERE a.legacy_admin_id IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM role_assignments r WHERE r.account_id=a.id AND r.role='admin')
        """
    )

    _add_columns("tasks", [
        sa.Column("public_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("parent_task_id", sa.Integer(), nullable=True),
        sa.Column("workflow_status", sa.Text(), nullable=False, server_default="to_do"),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("estimate_minutes", sa.Integer(), nullable=True),
        sa.Column("sort_position", sa.Numeric(20, 8), nullable=False, server_default="0"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    ])
    op.create_unique_constraint("uq_tasks_public_id", "tasks", ["public_id"])
    op.create_foreign_key("fk_tasks_organization", "tasks", "organizations", ["organization_id"], ["id"], ondelete="CASCADE")
    op.create_foreign_key("fk_tasks_project", "tasks", "projects", ["project_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_tasks_parent", "tasks", "tasks", ["parent_task_id"], ["id"], ondelete="CASCADE")
    op.create_check_constraint("ck_tasks_workflow_status", "tasks", "workflow_status IN ('backlog','to_do','in_progress','review','done','cancelled')")
    op.execute(
        """
        UPDATE tasks SET organization_id=1,
          workflow_status=CASE status WHEN 'in_progress' THEN 'in_progress' WHEN 'done' THEN 'done'
            WHEN 'cancelled' THEN 'cancelled' ELSE 'to_do' END,
          sort_position=id
        """
    )
    op.create_index("ix_tasks_project_workflow_position", "tasks", ["project_id", "workflow_status", "sort_position"])
    op.create_index("ix_tasks_owner_workflow_deadline", "tasks", ["assignee_id", "workflow_status", "deadline_at"])
    op.create_index("ix_tasks_parent_position", "tasks", ["parent_task_id", "sort_position"])

    _add_columns("task_comments", [
        sa.Column("author_account_id", sa.Integer(), nullable=True),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_resolved", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("mentions", sa.dialects.postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    ])
    op.create_foreign_key("fk_task_comments_author_account", "task_comments", "user_accounts", ["author_account_id"], ["id"], ondelete="SET NULL")
    for name in ("task_assignees", "task_dependencies", "task_check_items", "attachments", "saved_views"):
        _create(name)

    op.drop_constraint("ck_work_reports_status", "work_reports", type_="check")
    _add_columns("work_reports", [
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("submitted_by_account_id", sa.Integer(), nullable=True),
        sa.Column("reviewer_account_id", sa.Integer(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    ])
    op.create_check_constraint("ck_work_reports_status", "work_reports", "status IN ('awaiting','draft','editing','submitted','revision_requested','approved')")
    op.create_foreign_key("fk_work_reports_submitter", "work_reports", "user_accounts", ["submitted_by_account_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_work_reports_reviewer", "work_reports", "user_accounts", ["reviewer_account_id"], ["id"], ondelete="SET NULL")
    op.add_column("work_report_revisions", sa.Column("author_account_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_work_report_revisions_author", "work_report_revisions", "user_accounts", ["author_account_id"], ["id"], ondelete="SET NULL")

    op.drop_constraint("ck_work_time_entries_mode", "work_time_entries", type_="check")
    op.alter_column("work_time_entries", "mode", existing_type=sa.Text(), nullable=True)
    _add_columns("work_time_entries", [
        sa.Column("employee_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("local_work_date", sa.Date(), nullable=True),
        sa.Column("timezone", sa.Text(), nullable=False, server_default="Asia/Ulaanbaatar"),
        sa.Column("entry_type", sa.Text(), nullable=False, server_default="work"),
        sa.Column("source_channel", sa.Text(), nullable=False, server_default="telegram"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_billable", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("approval_status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("approved_by_account_id", sa.Integer(), nullable=True),
        sa.Column("hourly_rate_snapshot", sa.Numeric(18, 4), nullable=True),
        sa.Column("rate_currency", sa.String(3), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    ])
    op.execute(
        """
        UPDATE work_time_entries e SET employee_id=r.employee_id, local_work_date=r.period_date,
          timezone=COALESCE(emp.timezone,'Asia/Ulaanbaatar')
        FROM work_reports r JOIN employees emp ON emp.id=r.employee_id WHERE r.id=e.report_id
        """
    )
    op.create_check_constraint("ck_work_time_entries_mode", "work_time_entries", "mode IS NULL OR mode IN ('in_person','remote')")
    op.create_check_constraint("ck_work_time_entries_type", "work_time_entries", "entry_type IN ('work','break')")
    op.create_foreign_key("fk_work_time_entries_employee", "work_time_entries", "employees", ["employee_id"], ["id"], ondelete="CASCADE")
    op.create_foreign_key("fk_work_time_entries_project", "work_time_entries", "projects", ["project_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_work_time_entries_task", "work_time_entries", "tasks", ["task_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_work_time_entries_approver", "work_time_entries", "user_accounts", ["approved_by_account_id"], ["id"], ondelete="SET NULL")
    for column in ("employee_id", "project_id", "task_id", "local_work_date"):
        op.create_index(f"ix_work_time_entries_{column}", "work_time_entries", [column])
    op.create_index("uq_work_time_entries_open_employee", "work_time_entries", ["employee_id"], unique=True, postgresql_where=sa.text("ended_at IS NULL AND employee_id IS NOT NULL"))

    for name in ("checkin_templates", "checkin_questions", "checkins", "checkin_answers", "report_comments"):
        _create(name)
    for name in ("objectives", "key_results", "milestones", "goal_links"):
        _create(name)
    for name in ("audit_logs", "domain_events", "job_queue", "idempotency_records", "calendar_connections", "calendar_event_links"):
        _create(name)

    _add_columns("notification_outbox", [
        sa.Column("event_id", sa.Integer(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("lease_owner", sa.Text(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
    ])
    op.create_foreign_key("fk_notification_outbox_event", "notification_outbox", "domain_events", ["event_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    op.drop_constraint("fk_notification_outbox_event", "notification_outbox", type_="foreignkey")
    for column in ("next_attempt_at", "lease_expires_at", "lease_owner", "last_error", "attempt_count", "event_id"):
        op.drop_column("notification_outbox", column)

    for name in (
        "calendar_event_links", "calendar_connections", "idempotency_records", "job_queue", "domain_events",
        "audit_logs", "goal_links", "milestones", "key_results", "objectives", "report_comments",
        "checkin_answers", "checkins", "checkin_questions", "checkin_templates", "saved_views", "attachments",
        "task_check_items", "task_dependencies", "task_assignees", "resource_allocations", "time_off",
        "shift_schedules", "role_assignments", "exchange_rate_snapshots", "project_rates", "project_members",
        "employee_skills", "team_members", "refresh_sessions",
    ):
        op.drop_table(name)

    for index in ("uq_work_time_entries_open_employee", "ix_work_time_entries_local_work_date", "ix_work_time_entries_task_id", "ix_work_time_entries_project_id", "ix_work_time_entries_employee_id"):
        op.drop_index(index, table_name="work_time_entries")
    for constraint in ("fk_work_time_entries_approver", "fk_work_time_entries_task", "fk_work_time_entries_project", "fk_work_time_entries_employee"):
        op.drop_constraint(constraint, "work_time_entries", type_="foreignkey")
    op.drop_constraint("ck_work_time_entries_type", "work_time_entries", type_="check")
    op.drop_constraint("ck_work_time_entries_mode", "work_time_entries", type_="check")
    op.execute("DELETE FROM work_time_entries WHERE entry_type='break'")
    for column in ("version", "rate_currency", "hourly_rate_snapshot", "approved_by_account_id", "approval_status", "is_billable", "notes", "source_channel", "entry_type", "timezone", "local_work_date", "task_id", "project_id", "employee_id"):
        op.drop_column("work_time_entries", column)
    op.alter_column("work_time_entries", "mode", existing_type=sa.Text(), nullable=False)
    op.create_check_constraint("ck_work_time_entries_mode", "work_time_entries", "mode IN ('in_person','remote')")

    op.drop_constraint("fk_work_report_revisions_author", "work_report_revisions", type_="foreignkey")
    op.drop_column("work_report_revisions", "author_account_id")
    op.drop_constraint("fk_work_reports_reviewer", "work_reports", type_="foreignkey")
    op.drop_constraint("fk_work_reports_submitter", "work_reports", type_="foreignkey")
    op.drop_constraint("ck_work_reports_status", "work_reports", type_="check")
    op.execute("UPDATE work_reports SET status='draft' WHERE status='submitted'")
    op.execute("UPDATE work_reports SET status='editing' WHERE status='revision_requested'")
    for column in ("version", "reviewed_at", "submitted_at", "reviewer_account_id", "submitted_by_account_id", "title"):
        op.drop_column("work_reports", column)
    op.create_check_constraint("ck_work_reports_status", "work_reports", "status IN ('awaiting','draft','editing','approved')")

    op.drop_constraint("fk_task_comments_author_account", "task_comments", type_="foreignkey")
    for column in ("mentions", "is_resolved", "edited_at", "author_account_id"):
        op.drop_column("task_comments", column)
    for index in ("ix_tasks_parent_position", "ix_tasks_owner_workflow_deadline", "ix_tasks_project_workflow_position"):
        op.drop_index(index, table_name="tasks")
    op.drop_constraint("ck_tasks_workflow_status", "tasks", type_="check")
    op.drop_constraint("fk_tasks_parent", "tasks", type_="foreignkey")
    op.drop_constraint("fk_tasks_project", "tasks", type_="foreignkey")
    op.drop_constraint("fk_tasks_organization", "tasks", type_="foreignkey")
    op.drop_constraint("uq_tasks_public_id", "tasks", type_="unique")
    for column in ("is_archived", "version", "sort_position", "estimate_minutes", "start_at", "workflow_status", "parent_task_id", "project_id", "organization_id", "public_id"):
        op.drop_column("tasks", column)

    for name in ("projects", "clients", "skills", "teams"):
        op.drop_table(name)
    op.drop_table("user_accounts")
    op.drop_constraint("fk_employees_manager", "employees", type_="foreignkey")
    op.drop_constraint("uq_employees_email", "employees", type_="unique")
    for column in ("metadata_json", "weekly_capacity_minutes", "employment_type", "primary_language", "job_title", "manager_id", "email"):
        op.drop_column("employees", column)
    op.drop_table("organizations")
