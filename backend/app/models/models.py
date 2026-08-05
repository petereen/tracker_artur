import uuid
from datetime import date, datetime, time

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func, text as sa_text

from app.core.database import Base


class Employee(Base):
    __tablename__ = "employees"

    id = Column(Integer, primary_key=True)
    name = Column(Text, nullable=False)
    telegram_id = Column(Text, unique=True, nullable=False)
    telegram_username = Column(Text)
    email = Column(Text, unique=True)
    manager_id = Column(Integer, ForeignKey("employees.id", ondelete="SET NULL"))
    job_title = Column(Text)
    primary_language = Column(String(8), nullable=False, server_default="mn", default="mn")
    employment_type = Column(String(24), nullable=False, server_default="member", default="member")
    weekly_capacity_minutes = Column(Integer, nullable=False, server_default="2400", default=2400)
    metadata_json = Column(JSONB, nullable=False, server_default=sa_text("'{}'::jsonb"), default=dict)
    timezone = Column(Text, nullable=False, server_default="Asia/Ulaanbaatar", default="Asia/Ulaanbaatar")
    is_active = Column(Boolean, nullable=False, server_default=sa_text("true"), default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    onboarded_at = Column(DateTime(timezone=True))

    schedules = relationship("Schedule", back_populates="employee", uselist=False)
    streaks = relationship("Streak", back_populates="employee", uselist=False)
    sessions = relationship("SurveySession", back_populates="employee")


class Question(Base):
    __tablename__ = "questions"

    id = Column(Integer, primary_key=True)
    text = Column(Text, nullable=False)
    answer_type = Column(
        Text,
        CheckConstraint("answer_type IN ('integer','decimal','boolean','choice','text')"),
        nullable=False,
    )
    options = Column(JSONB, nullable=False, server_default=sa_text("'[]'::jsonb"), default=list)
    is_required = Column(Boolean, nullable=False, server_default=sa_text("true"), default=True)
    sort_order = Column(Integer, nullable=False, server_default="0", default=0)


class EmployeeQuestion(Base):
    __tablename__ = "employee_questions"
    __table_args__ = (UniqueConstraint("employee_id", "question_id"),)

    id = Column(Integer, primary_key=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="CASCADE"))
    question_id = Column(Integer, ForeignKey("questions.id", ondelete="CASCADE"))


class Schedule(Base):
    __tablename__ = "schedules"

    id = Column(Integer, primary_key=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="CASCADE"), unique=True)
    variant = Column(String(1), nullable=False, server_default="A", default="A")
    evening_time = Column(Time, default=time(17, 30))
    morning_time = Column(Time, default=time(9, 15))
    weekdays = Column(ARRAY(Integer), default=lambda: [1, 2, 3, 4, 5])
    deadline_time = Column(Time, default=time(23, 0))
    reminder_intervals = Column(ARRAY(Integer), default=lambda: [60, 120])

    employee = relationship("Employee", back_populates="schedules")


class SurveySession(Base):
    __tablename__ = "survey_sessions"
    __table_args__ = (UniqueConstraint("employee_id", "date", "type"),)

    id = Column(Integer, primary_key=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="CASCADE"))
    date = Column(Date, nullable=False)
    type = Column(Text, default="evening")
    status = Column(
        Text,
        CheckConstraint("status IN ('pending','completed','partial','missed')"),
        default="pending",
    )
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))

    employee = relationship("Employee", back_populates="sessions")
    answers = relationship("Answer", back_populates="session")


class Answer(Base):
    __tablename__ = "answers"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("survey_sessions.id", ondelete="CASCADE"))
    question_id = Column(Integer, ForeignKey("questions.id", ondelete="CASCADE"))
    value_text = Column(Text)
    value_numeric = Column(Numeric)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    session = relationship("SurveySession", back_populates="answers")
    question = relationship("Question")


class ManagerSettings(Base):
    __tablename__ = "manager_settings"

    id = Column(Integer, primary_key=True)
    telegram_id = Column(Text)
    telegram_username = Column(Text)
    # The original single recipient is kept for backwards compatibility.
    # New notifications are delivered to every distinct ID in this list.
    telegram_admin_ids = Column(JSONB, nullable=False, server_default=sa_text("'[]'::jsonb"), default=list)
    summary_time = Column(Time, default=time(9, 0))
    weekly_summary_time = Column(Time, default=time(17, 0))
    weekly_summary_day = Column(Integer, nullable=False, server_default="5", default=5)
    alerts_enabled = Column(Boolean, nullable=False, server_default=sa_text("true"), default=True)
    gamification_enabled = Column(Boolean, nullable=False, server_default=sa_text("true"), default=True)
    soft_mode_weeks = Column(Integer, nullable=False, server_default="1", default=1)
    onboarding_template = Column(Text, nullable=True)
    # ── Политика уведомлений (тихие часы / дайджесты / эскалация) ──
    quiet_start = Column(Time, default=time(20, 0))            # начало тихих часов (вечер)
    quiet_end = Column(Time, default=time(9, 0))              # конец тихих часов (утро) = начало рабочего окна
    work_weekdays = Column(ARRAY(Integer), default=lambda: [1, 2, 3, 4, 5])  # ISO 1=Пн..7=Вс
    morning_digest_time = Column(Time, default=time(9, 0))
    evening_digest_time = Column(Time, default=time(18, 0))
    overdue_escalation_days = Column(Integer, default=1)      # рабочих дней просрочки до эскалации руководителю
    notifications_enabled = Column(Boolean, default=True)     # глобальный рубильник рутинных пушей
    tts_answers_enabled = Column(Boolean, nullable=False, server_default=sa_text("true"), default=True)


class MonthlyReportDigest(Base):
    """One successfully reserved monthly management digest per reporting period."""

    __tablename__ = "monthly_report_digests"
    __table_args__ = (UniqueConstraint("period_date", name="uq_monthly_report_digest_period"),)

    id = Column(Integer, primary_key=True)
    period_date = Column(Date, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CompanyKnowledge(Base):
    """Curated company reference material available to the OYUNS assistant."""

    __tablename__ = "company_knowledge"

    id = Column(Integer, primary_key=True)
    title = Column(Text, nullable=False)
    category = Column(Text)
    content = Column(Text, nullable=False)
    attachment_filename = Column(Text)
    attachment_stored_name = Column(Text)
    attachment_content_type = Column(Text)
    attachment_size = Column(Integer)
    is_active = Column(Boolean, nullable=False, server_default=sa_text("true"), default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class UnknownAssistantRequest(Base):
    """Deduplicated queue of requests that the public router cannot classify."""

    __tablename__ = "unknown_assistant_requests"

    id = Column(Integer, primary_key=True)
    text = Column(Text, nullable=False)
    text_hash = Column(String(64), nullable=False, unique=True, index=True)
    language = Column(String(8), nullable=False)
    channel = Column(String(16), nullable=False)
    terms = Column(ARRAY(Text), nullable=False, server_default=sa_text("'{}'"), default=list)
    reason = Column(String(80), nullable=False, server_default="unclassified", default="unclassified")
    occurrence_count = Column(Integer, nullable=False, server_default="1", default=1)
    status = Column(
        Text,
        CheckConstraint("status IN ('pending','reviewed','dismissed')"),
        nullable=False,
        server_default="pending",
        default="pending",
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_seen_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AssistantContextExample(Base):
    """Administrator-approved wording that teaches the intent router local context."""

    __tablename__ = "assistant_context_examples"

    id = Column(Integer, primary_key=True)
    phrase = Column(Text, nullable=False)
    phrase_hash = Column(String(64), nullable=False, unique=True, index=True)
    intent = Column(
        String(40),
        CheckConstraint(
            "intent IN ('create_task_draft','get_user_tasks','search_company_knowledge')"
        ),
        nullable=False,
    )
    meaning = Column(Text, nullable=False)
    is_active = Column(Boolean, nullable=False, server_default=sa_text("true"), default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class Streak(Base):
    __tablename__ = "streaks"

    id = Column(Integer, primary_key=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="CASCADE"), unique=True)
    current_streak = Column(Integer, default=0)
    longest_streak = Column(Integer, default=0)
    last_filled_date = Column(Date)

    employee = relationship("Employee", back_populates="streaks")


class AdminUser(Base):
    __tablename__ = "admin_users"

    id = Column(Integer, primary_key=True)
    email = Column(Text, unique=True, nullable=False)
    password_hash = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ─── Задачи (task-manager поверх трекера опросов) ──────────────────────────────

TASK_STATUSES = ("open", "in_progress", "done", "overdue", "cancelled")
DEFAULT_REMINDER_INTERVALS_MIN = [1440, 120, 0]  # за сутки, за 2ч, в момент дедлайна


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_project_workflow_position", "project_id", "workflow_status", "sort_position"),
        Index("ix_tasks_owner_workflow_deadline", "assignee_id", "workflow_status", "deadline_at"),
        Index("ix_tasks_parent_position", "parent_task_id", "sort_position"),
    )

    id = Column(Integer, primary_key=True)
    public_id = Column(UUID(as_uuid=True), nullable=False, unique=True, default=uuid.uuid4, server_default=sa_text("gen_random_uuid()"))
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"))
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="SET NULL"))
    parent_task_id = Column(Integer, ForeignKey("tasks.id", ondelete="CASCADE"))
    title = Column(Text, nullable=False)
    description = Column(Text)
    # Постановщик: employee, если зарегистрирован; иначе фиксируем telegram_id
    # (руководитель по MANAGER_TG_ID может не быть в employees).
    created_by_id = Column(Integer, ForeignKey("employees.id", ondelete="SET NULL"))
    created_by_tg = Column(Text)
    assignee_id = Column(Integer, ForeignKey("employees.id", ondelete="SET NULL"))
    deadline_at = Column(DateTime(timezone=True))
    status = Column(
        Text,
        CheckConstraint(
            "status IN ('open','in_progress','done','overdue','cancelled')",
            name="ck_tasks_status",
        ),
        default="open",
        nullable=False,
    )
    priority = Column(Integer, nullable=False, server_default="2", default=2)  # 1=срочно, 2=обычно, 3=низкий
    workflow_status = Column(Text, nullable=False, server_default="to_do", default="to_do")
    start_at = Column(DateTime(timezone=True))
    estimate_minutes = Column(Integer)
    sort_position = Column(Numeric(20, 8), nullable=False, server_default="0", default=0)
    version = Column(Integer, nullable=False, server_default="1", default=1)
    is_archived = Column(Boolean, nullable=False, server_default=sa_text("false"), default=False)
    reminder_intervals_min = Column(ARRAY(Integer), default=lambda: list(DEFAULT_REMINDER_INTERVALS_MIN))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True))
    completed_by_id = Column(Integer, ForeignKey("employees.id", ondelete="SET NULL"))
    overdue_pinged_at = Column(DateTime(timezone=True))  # когда был отправлен немедленный пинг о просрочке

    assignee = relationship("Employee", foreign_keys=[assignee_id])
    creator = relationship("Employee", foreign_keys=[created_by_id])
    comments = relationship("TaskComment", back_populates="task", cascade="all, delete-orphan")


class TaskComment(Base):
    __tablename__ = "task_comments"

    id = Column(Integer, primary_key=True)
    task_id = Column(Integer, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    author_id = Column(Integer, ForeignKey("employees.id", ondelete="SET NULL"))
    author_tg = Column(Text)
    author_account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="SET NULL"))
    text = Column(Text, nullable=False)
    edited_at = Column(DateTime(timezone=True))
    is_resolved = Column(Boolean, nullable=False, server_default=sa_text("false"), default=False)
    mentions = Column(JSONB, nullable=False, server_default=sa_text("'[]'::jsonb"), default=list)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    task = relationship("Task", back_populates="comments")


class NotificationOutbox(Base):
    """Очередь уведомлений — мост между api-процессом (без планировщика) и ботом.
    Бот дренит её (drain_notification_outbox) с учётом тихих часов (not_before)."""
    __tablename__ = "notification_outbox"

    id = Column(Integer, primary_key=True)
    event_id = Column(Integer, ForeignKey("domain_events.id", ondelete="SET NULL"))
    task_id = Column(Integer, ForeignKey("tasks.id", ondelete="CASCADE"))
    recipient_tg = Column(Text, nullable=False)
    kind = Column(Text, nullable=False)  # 'task_assigned' и т.п.
    payload = Column(JSONB)
    not_before = Column(DateTime(timezone=True))
    status = Column(Text, default="pending", nullable=False)  # pending | sent | failed
    attempt_count = Column(Integer, nullable=False, server_default="0", default=0)
    last_error = Column(Text)
    lease_owner = Column(Text)
    lease_expires_at = Column(DateTime(timezone=True))
    next_attempt_at = Column(DateTime(timezone=True))
    dedup_key = Column(Text, unique=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    sent_at = Column(DateTime(timezone=True))


# ─── Ажлын тайлангууд ────────────────────────────────────────────────────────

WORK_REPORT_TYPES = ("daily", "monthly", "next_month_plan", "daily_test", "monthly_test", "next_month_plan_test")
WORK_REPORT_STATUSES = ("awaiting", "draft", "editing", "approved")
WORK_REPORT_REVISION_STATUSES = ("draft", "superseded", "deleted", "approved")


class WorkReport(Base):
    """One report lifecycle for an employee and reporting period.

    ``period_date`` is the local work date for daily reports and the first day
    of the reported month for monthly reports and their following plan.
    """

    __tablename__ = "work_reports"
    __table_args__ = (
        UniqueConstraint("employee_id", "report_type", "period_date", name="uq_work_report_period"),
        CheckConstraint(
            "report_type IN ('daily','monthly','next_month_plan','daily_test','monthly_test','next_month_plan_test')",
            name="ck_work_reports_type",
        ),
        CheckConstraint(
            "status IN ('awaiting','draft','editing','submitted','revision_requested','approved')",
            name="ck_work_reports_status",
        ),
    )

    id = Column(Integer, primary_key=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    report_type = Column(Text, nullable=False)
    period_date = Column(Date, nullable=False)
    status = Column(Text, nullable=False, server_default="awaiting", default="awaiting")
    title = Column(Text)
    submitted_by_account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="SET NULL"))
    reviewer_account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="SET NULL"))
    submitted_at = Column(DateTime(timezone=True))
    reviewed_at = Column(DateTime(timezone=True))
    version = Column(Integer, nullable=False, server_default="1", default=1)
    started_at = Column(DateTime(timezone=True))
    ended_at = Column(DateTime(timezone=True))
    approved_revision_id = Column(Integer, ForeignKey("work_report_revisions.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    employee = relationship("Employee")
    revisions = relationship(
        "WorkReportRevision",
        back_populates="report",
        cascade="all, delete-orphan",
        foreign_keys="WorkReportRevision.report_id",
    )
    prompts = relationship("WorkReportPrompt", back_populates="report", cascade="all, delete-orphan")
    work_time_entries = relationship("WorkTimeEntry", back_populates="report", cascade="all, delete-orphan")


class WorkReportRevision(Base):
    __tablename__ = "work_report_revisions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','superseded','deleted','approved')",
            name="ck_work_report_revisions_status",
        ),
    )

    id = Column(Integer, primary_key=True)
    report_id = Column(Integer, ForeignKey("work_reports.id", ondelete="CASCADE"), nullable=False)
    text = Column(Text, nullable=False)
    author_account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="SET NULL"))
    status = Column(Text, nullable=False, server_default="draft", default="draft")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    report = relationship("WorkReport", back_populates="revisions", foreign_keys=[report_id])


class WorkReportPrompt(Base):
    __tablename__ = "work_report_prompts"
    __table_args__ = (
        UniqueConstraint("report_id", "prompt_type", "prompt_date", name="uq_work_report_prompt_day"),
    )

    id = Column(Integer, primary_key=True)
    report_id = Column(Integer, ForeignKey("work_reports.id", ondelete="CASCADE"), nullable=False)
    prompt_type = Column(Text, nullable=False)
    prompt_date = Column(Date, nullable=False)
    telegram_chat_id = Column(Text, nullable=False)
    telegram_message_id = Column(Integer)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    report = relationship("WorkReport", back_populates="prompts")


class WorkTimeEntry(Base):
    """One non-overlapping in-person or remote work interval for a day."""

    __tablename__ = "work_time_entries"
    __table_args__ = (
        CheckConstraint("mode IS NULL OR mode IN ('in_person','remote')", name="ck_work_time_entries_mode"),
        CheckConstraint("entry_type IN ('work','break')", name="ck_work_time_entries_type"),
        CheckConstraint("ended_at IS NULL OR ended_at >= started_at", name="ck_work_time_entries_range"),
    )

    id = Column(Integer, primary_key=True)
    report_id = Column(Integer, ForeignKey("work_reports.id", ondelete="CASCADE"), nullable=False, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="CASCADE"), index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    task_id = Column(Integer, ForeignKey("tasks.id", ondelete="SET NULL"), index=True)
    local_work_date = Column(Date, index=True)
    timezone = Column(Text, nullable=False, server_default="Asia/Ulaanbaatar", default="Asia/Ulaanbaatar")
    entry_type = Column(Text, nullable=False, server_default="work", default="work")
    mode = Column(Text)
    started_at = Column(DateTime(timezone=True), nullable=False)
    ended_at = Column(DateTime(timezone=True))
    source_channel = Column(Text, nullable=False, server_default="telegram", default="telegram")
    notes = Column(Text)
    is_billable = Column(Boolean, nullable=False, server_default=sa_text("false"), default=False)
    approval_status = Column(Text, nullable=False, server_default="pending", default="pending")
    approved_by_account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="SET NULL"))
    hourly_rate_snapshot = Column(Numeric(18, 4))
    rate_currency = Column(String(3))
    exchange_rate_snapshot_id = Column(Integer, ForeignKey("exchange_rate_snapshots.id", ondelete="SET NULL"))
    version = Column(Integer, nullable=False, server_default="1", default=1)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    report = relationship("WorkReport", back_populates="work_time_entries")


# ─── Компанийн сарын төлөвлөгөө ─────────────────────────────────────────────

COMPANY_PLAN_HORIZONS = ("long_term", "mid_term", "short_term")
COMPANY_PLAN_STATUSES = ("approved",)


class CompanyPlanItem(Base):
    """An administrator-approved actionable item derived from a worker plan."""

    __tablename__ = "company_plan_items"
    __table_args__ = (
        CheckConstraint(
            "horizon IN ('long_term','mid_term','short_term')",
            name="ck_company_plan_items_horizon",
        ),
        CheckConstraint("status IN ('approved')", name="ck_company_plan_items_status"),
    )

    id = Column(Integer, primary_key=True)
    plan_month = Column(Date, nullable=False, index=True)
    title = Column(Text, nullable=False)
    content = Column(Text)
    horizon = Column(Text, nullable=False, server_default="short_term", default="short_term")
    position = Column(Integer, nullable=False, server_default="0", default=0)
    status = Column(Text, nullable=False, server_default="approved", default="approved")
    source_employee_id = Column(Integer, ForeignKey("employees.id", ondelete="SET NULL"))
    source_report_id = Column(Integer, ForeignKey("work_reports.id", ondelete="SET NULL"))
    approved_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    source_employee = relationship("Employee", foreign_keys=[source_employee_id])
    source_report = relationship("WorkReport", foreign_keys=[source_report_id])


# ─── Enterprise PM / PSA foundation ─────────────────────────────────────────


class Organization(Base):
    __tablename__ = "organizations"

    id = Column(Integer, primary_key=True)
    public_id = Column(UUID(as_uuid=True), nullable=False, unique=True, default=uuid.uuid4, server_default=sa_text("gen_random_uuid()"))
    name = Column(Text, nullable=False)
    timezone = Column(Text, nullable=False, server_default="Asia/Ulaanbaatar", default="Asia/Ulaanbaatar")
    base_currency = Column(String(3), nullable=False, server_default="MNT", default="MNT")
    settings = Column(JSONB, nullable=False, server_default=sa_text("'{}'::jsonb"), default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class UserAccount(Base):
    __tablename__ = "user_accounts"
    __table_args__ = (
        CheckConstraint("status IN ('invited','active','locked','disabled')", name="ck_user_accounts_status"),
    )

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="SET NULL"), unique=True)
    legacy_admin_id = Column(Integer, ForeignKey("admin_users.id", ondelete="SET NULL"), unique=True)
    email = Column(Text, nullable=False, unique=True)
    password_hash = Column(Text, nullable=False)
    status = Column(Text, nullable=False, server_default="active", default="active")
    locale = Column(String(8), nullable=False, server_default="mn", default="mn")
    must_change_password = Column(Boolean, nullable=False, server_default=sa_text("false"), default=False)
    failed_login_count = Column(Integer, nullable=False, server_default="0", default=0)
    locked_until = Column(DateTime(timezone=True))
    last_login_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class RefreshSession(Base):
    __tablename__ = "refresh_sessions"
    __table_args__ = (Index("ix_refresh_sessions_account_expiry", "account_id", "expires_at"),)

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True)
    device_label = Column(Text)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked_at = Column(DateTime(timezone=True))
    last_used_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"
    __table_args__ = (
        Index("ix_password_reset_tokens_account_expiry", "account_id", "expires_at"),
        CheckConstraint("purpose IN ('password_reset','invitation')", name="ck_password_reset_tokens_purpose"),
    )

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True)
    purpose = Column(Text, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class RoleAssignment(Base):
    __tablename__ = "role_assignments"
    __table_args__ = (
        CheckConstraint(
            "role IN ('admin','manager','team_lead','member','contractor','client_auditor')",
            name="ck_role_assignments_role",
        ),
        Index("ix_role_assignments_account_role", "account_id", "role"),
    )

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False)
    role = Column(Text, nullable=False)
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="CASCADE"))
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"))
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="CASCADE"))
    valid_from = Column(Date)
    valid_until = Column(Date)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Team(Base):
    __tablename__ = "teams"
    __table_args__ = (UniqueConstraint("organization_id", "code", name="uq_teams_org_code"),)

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    parent_team_id = Column(Integer, ForeignKey("teams.id", ondelete="SET NULL"))
    manager_id = Column(Integer, ForeignKey("employees.id", ondelete="SET NULL"))
    name = Column(Text, nullable=False)
    code = Column(String(40), nullable=False)
    timezone = Column(Text, nullable=False, server_default="Asia/Ulaanbaatar", default="Asia/Ulaanbaatar")
    is_active = Column(Boolean, nullable=False, server_default=sa_text("true"), default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class TeamMember(Base):
    __tablename__ = "team_members"
    __table_args__ = (
        UniqueConstraint("team_id", "employee_id", name="uq_team_members_team_employee"),
        CheckConstraint("allocation_percent >= 0 AND allocation_percent <= 100", name="ck_team_members_allocation"),
    )

    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="CASCADE"), nullable=False)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    team_role = Column(Text, nullable=False, server_default="member", default="member")
    allocation_percent = Column(Numeric(5, 2), nullable=False, server_default="100", default=100)
    starts_on = Column(Date)
    ends_on = Column(Date)


class Skill(Base):
    __tablename__ = "skills"
    __table_args__ = (UniqueConstraint("organization_id", "normalized_name", name="uq_skills_org_name"),)

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    name = Column(Text, nullable=False)
    normalized_name = Column(Text, nullable=False)


class EmployeeSkill(Base):
    __tablename__ = "employee_skills"
    __table_args__ = (UniqueConstraint("employee_id", "skill_id", name="uq_employee_skills"),)

    id = Column(Integer, primary_key=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    skill_id = Column(Integer, ForeignKey("skills.id", ondelete="CASCADE"), nullable=False)
    proficiency = Column(Integer, nullable=False, server_default="1", default=1)
    is_verified = Column(Boolean, nullable=False, server_default=sa_text("false"), default=False)
    last_used_on = Column(Date)


class Client(Base):
    __tablename__ = "clients"
    __table_args__ = (UniqueConstraint("organization_id", "code", name="uq_clients_org_code"),)

    id = Column(Integer, primary_key=True)
    public_id = Column(UUID(as_uuid=True), nullable=False, unique=True, default=uuid.uuid4, server_default=sa_text("gen_random_uuid()"))
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    code = Column(String(40), nullable=False)
    name = Column(Text, nullable=False)
    status = Column(Text, nullable=False, server_default="active", default="active")
    default_currency = Column(String(3), nullable=False, server_default="MNT", default="MNT")
    contacts = Column(JSONB, nullable=False, server_default=sa_text("'[]'::jsonb"), default=list)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("organization_id", "code", name="uq_projects_org_code"),
        Index("ix_projects_org_status", "organization_id", "status"),
        Index("ix_projects_client_status", "client_id", "status"),
        Index("ix_projects_manager_status", "manager_id", "status"),
    )

    id = Column(Integer, primary_key=True)
    public_id = Column(UUID(as_uuid=True), nullable=False, unique=True, default=uuid.uuid4, server_default=sa_text("gen_random_uuid()"))
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="SET NULL"))
    manager_id = Column(Integer, ForeignKey("employees.id", ondelete="SET NULL"))
    code = Column(String(40), nullable=False)
    name = Column(Text, nullable=False)
    description = Column(Text)
    status = Column(Text, nullable=False, server_default="draft", default="draft")
    starts_on = Column(Date)
    ends_on = Column(Date)
    budget_minutes = Column(Integer)
    budget_amount = Column(Numeric(18, 4))
    currency = Column(String(3), nullable=False, server_default="MNT", default="MNT")
    default_billable = Column(Boolean, nullable=False, server_default=sa_text("false"), default=False)
    version = Column(Integer, nullable=False, server_default="1", default=1)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class ProjectMember(Base):
    __tablename__ = "project_members"
    __table_args__ = (UniqueConstraint("project_id", "employee_id", name="uq_project_members"),)

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    project_role = Column(Text)
    allocation_percent = Column(Numeric(5, 2), nullable=False, server_default="0", default=0)
    is_billable = Column(Boolean, nullable=False, server_default=sa_text("false"), default=False)
    starts_on = Column(Date)
    ends_on = Column(Date)


class ProjectRate(Base):
    __tablename__ = "project_rates"
    __table_args__ = (Index("ix_project_rates_scope_dates", "project_id", "employee_id", "role_name", "effective_from"),)

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="CASCADE"))
    role_name = Column(Text)
    hourly_amount = Column(Numeric(18, 4), nullable=False)
    currency = Column(String(3), nullable=False)
    effective_from = Column(Date, nullable=False)
    effective_until = Column(Date)


class ExchangeRateSnapshot(Base):
    __tablename__ = "exchange_rate_snapshots"
    __table_args__ = (Index("ix_exchange_rates_pair_fetched", "base_currency", "quote_currency", "fetched_at"),)

    id = Column(Integer, primary_key=True)
    provider = Column(Text, nullable=False)
    base_currency = Column(String(3), nullable=False)
    quote_currency = Column(String(3), nullable=False)
    rate = Column(Numeric(24, 10), nullable=False)
    fetched_at = Column(DateTime(timezone=True), nullable=False)
    source_payload_hash = Column(String(64), nullable=False)


class ShiftSchedule(Base):
    __tablename__ = "shift_schedules"
    __table_args__ = (Index("ix_shift_schedules_employee_weekday", "employee_id", "weekday"),)

    id = Column(Integer, primary_key=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="CASCADE"))
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="CASCADE"))
    weekday = Column(Integer, nullable=False)
    starts_at = Column(Time, nullable=False)
    ends_at = Column(Time, nullable=False)
    break_minutes = Column(Integer, nullable=False, server_default="60", default=60)
    timezone = Column(Text, nullable=False, server_default="Asia/Ulaanbaatar", default="Asia/Ulaanbaatar")
    effective_from = Column(Date)
    effective_until = Column(Date)


class TimeOff(Base):
    __tablename__ = "time_off"
    __table_args__ = (Index("ix_time_off_employee_dates", "employee_id", "starts_on", "ends_on"),)

    id = Column(Integer, primary_key=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    time_off_type = Column(Text, nullable=False)
    starts_on = Column(Date, nullable=False)
    ends_on = Column(Date, nullable=False)
    partial_day_minutes = Column(Integer)
    status = Column(Text, nullable=False, server_default="pending", default="pending")
    approved_by_account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ResourceAllocation(Base):
    __tablename__ = "resource_allocations"
    __table_args__ = (Index("ix_resource_allocations_employee_dates", "employee_id", "starts_on", "ends_on"),)

    id = Column(Integer, primary_key=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    starts_on = Column(Date, nullable=False)
    ends_on = Column(Date, nullable=False)
    planned_minutes = Column(Integer)
    allocation_percent = Column(Numeric(5, 2))
    source = Column(Text, nullable=False, server_default="manual", default="manual")
    status = Column(Text, nullable=False, server_default="planned", default="planned")


class TaskAssignee(Base):
    __tablename__ = "task_assignees"
    __table_args__ = (UniqueConstraint("task_id", "employee_id", name="uq_task_assignees"),)

    id = Column(Integer, primary_key=True)
    task_id = Column(Integer, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    assignment_role = Column(Text, nullable=False, server_default="contributor", default="contributor")
    assigned_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class TaskDependency(Base):
    __tablename__ = "task_dependencies"
    __table_args__ = (
        UniqueConstraint("predecessor_task_id", "successor_task_id", name="uq_task_dependencies"),
        CheckConstraint("predecessor_task_id <> successor_task_id", name="ck_task_dependencies_not_self"),
    )

    id = Column(Integer, primary_key=True)
    predecessor_task_id = Column(Integer, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    successor_task_id = Column(Integer, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    dependency_type = Column(Text, nullable=False, server_default="blocks", default="blocks")


class TaskCheckItem(Base):
    __tablename__ = "task_check_items"
    __table_args__ = (Index("ix_task_check_items_task_position", "task_id", "position"),)

    id = Column(Integer, primary_key=True)
    task_id = Column(Integer, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    text = Column(Text, nullable=False)
    is_completed = Column(Boolean, nullable=False, server_default=sa_text("false"), default=False)
    assignee_id = Column(Integer, ForeignKey("employees.id", ondelete="SET NULL"))
    position = Column(Numeric(20, 8), nullable=False, server_default="0", default=0)
    completed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Attachment(Base):
    __tablename__ = "attachments"
    __table_args__ = (Index("ix_attachments_object", "object_type", "object_id"),)

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    object_type = Column(Text, nullable=False)
    object_id = Column(Integer, nullable=False)
    storage_key = Column(Text, nullable=False, unique=True)
    filename = Column(Text, nullable=False)
    content_type = Column(Text, nullable=False)
    size = Column(Integer, nullable=False)
    checksum = Column(String(64), nullable=False)
    uploaded_by_account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="SET NULL"))
    scan_status = Column(Text, nullable=False, server_default="pending", default="pending")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SavedView(Base):
    __tablename__ = "saved_views"

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False)
    module = Column(Text, nullable=False)
    name = Column(Text, nullable=False)
    view_type = Column(Text, nullable=False)
    filters = Column(JSONB, nullable=False, server_default=sa_text("'{}'::jsonb"), default=dict)
    grouping = Column(JSONB, nullable=False, server_default=sa_text("'{}'::jsonb"), default=dict)
    visible_columns = Column(JSONB, nullable=False, server_default=sa_text("'[]'::jsonb"), default=list)
    sort = Column(JSONB, nullable=False, server_default=sa_text("'[]'::jsonb"), default=list)
    is_shared = Column(Boolean, nullable=False, server_default=sa_text("false"), default=False)


class CheckinTemplate(Base):
    __tablename__ = "checkin_templates"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="CASCADE"))
    name = Column(Text, nullable=False)
    cadence = Column(Text, nullable=False, server_default="daily", default="daily")
    is_active = Column(Boolean, nullable=False, server_default=sa_text("true"), default=True)


class CheckinQuestion(Base):
    __tablename__ = "checkin_questions"
    __table_args__ = (Index("ix_checkin_questions_template_position", "template_id", "position"),)

    id = Column(Integer, primary_key=True)
    template_id = Column(Integer, ForeignKey("checkin_templates.id", ondelete="CASCADE"), nullable=False)
    prompt = Column(JSONB, nullable=False)
    answer_type = Column(Text, nullable=False)
    choices = Column(JSONB, nullable=False, server_default=sa_text("'[]'::jsonb"), default=list)
    is_required = Column(Boolean, nullable=False, server_default=sa_text("true"), default=True)
    position = Column(Integer, nullable=False, server_default="0", default=0)


class Checkin(Base):
    __tablename__ = "checkins"
    __table_args__ = (
        UniqueConstraint("employee_id", "template_id", "local_date", name="uq_checkins_employee_template_date"),
        Index("ix_checkins_status_date", "status", "local_date"),
    )

    id = Column(Integer, primary_key=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    template_id = Column(Integer, ForeignKey("checkin_templates.id", ondelete="CASCADE"), nullable=False)
    local_date = Column(Date, nullable=False)
    status = Column(Text, nullable=False, server_default="scheduled", default="scheduled")
    source = Column(Text, nullable=False, server_default="web", default="web")
    started_at = Column(DateTime(timezone=True))
    submitted_at = Column(DateTime(timezone=True))


class CheckinAnswer(Base):
    __tablename__ = "checkin_answers"
    __table_args__ = (UniqueConstraint("checkin_id", "question_id", name="uq_checkin_answers"),)

    id = Column(Integer, primary_key=True)
    checkin_id = Column(Integer, ForeignKey("checkins.id", ondelete="CASCADE"), nullable=False)
    question_id = Column(Integer, ForeignKey("checkin_questions.id", ondelete="CASCADE"), nullable=False)
    value_text = Column(Text)
    value_numeric = Column(Numeric)
    value_json = Column(JSONB)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ReportComment(Base):
    __tablename__ = "report_comments"
    __table_args__ = (Index("ix_report_comments_report_created", "report_id", "created_at"),)

    id = Column(Integer, primary_key=True)
    report_id = Column(Integer, ForeignKey("work_reports.id", ondelete="CASCADE"), nullable=False)
    revision_id = Column(Integer, ForeignKey("work_report_revisions.id", ondelete="SET NULL"))
    author_account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="SET NULL"))
    text = Column(Text, nullable=False)
    range_metadata = Column(JSONB)
    is_resolved = Column(Boolean, nullable=False, server_default=sa_text("false"), default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Objective(Base):
    __tablename__ = "objectives"
    __table_args__ = (Index("ix_objectives_period_level_status", "period_start", "level", "status"),)

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    parent_objective_id = Column(Integer, ForeignKey("objectives.id", ondelete="SET NULL"))
    owner_team_id = Column(Integer, ForeignKey("teams.id", ondelete="SET NULL"))
    owner_employee_id = Column(Integer, ForeignKey("employees.id", ondelete="SET NULL"))
    level = Column(Text, nullable=False)
    title = Column(Text, nullable=False)
    description = Column(Text)
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    status = Column(Text, nullable=False, server_default="draft", default="draft")
    progress_method = Column(Text, nullable=False, server_default="key_results", default="key_results")
    version = Column(Integer, nullable=False, server_default="1", default=1)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class KeyResult(Base):
    __tablename__ = "key_results"

    id = Column(Integer, primary_key=True)
    objective_id = Column(Integer, ForeignKey("objectives.id", ondelete="CASCADE"), nullable=False)
    owner_employee_id = Column(Integer, ForeignKey("employees.id", ondelete="SET NULL"))
    title = Column(Text, nullable=False)
    metric_type = Column(Text, nullable=False)
    start_value = Column(Numeric(18, 4), nullable=False, server_default="0", default=0)
    target_value = Column(Numeric(18, 4), nullable=False)
    current_value = Column(Numeric(18, 4), nullable=False, server_default="0", default=0)
    unit = Column(Text)
    confidence = Column(Numeric(5, 2))
    due_date = Column(Date)
    status = Column(Text, nullable=False, server_default="active", default="active")


class Milestone(Base):
    __tablename__ = "milestones"
    __table_args__ = (Index("ix_milestones_project_due", "project_id", "due_date"),)

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"))
    owner_employee_id = Column(Integer, ForeignKey("employees.id", ondelete="SET NULL"))
    title = Column(Text, nullable=False)
    due_date = Column(Date)
    status = Column(Text, nullable=False, server_default="planned", default="planned")
    progress = Column(Numeric(5, 2), nullable=False, server_default="0", default=0)


class GoalLink(Base):
    __tablename__ = "goal_links"

    id = Column(Integer, primary_key=True)
    objective_id = Column(Integer, ForeignKey("objectives.id", ondelete="CASCADE"))
    key_result_id = Column(Integer, ForeignKey("key_results.id", ondelete="CASCADE"))
    milestone_id = Column(Integer, ForeignKey("milestones.id", ondelete="CASCADE"))
    linked_type = Column(Text, nullable=False)
    linked_id = Column(Integer, nullable=False)
    contribution_weight = Column(Numeric(5, 2), nullable=False, server_default="100", default=100)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_entity", "entity_type", "entity_id", "created_at"),
        Index("ix_audit_logs_actor", "actor_account_id", "created_at"),
    )

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    actor_account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="SET NULL"))
    actor_employee_id = Column(Integer, ForeignKey("employees.id", ondelete="SET NULL"))
    channel = Column(Text, nullable=False)
    action = Column(Text, nullable=False)
    entity_type = Column(Text, nullable=False)
    entity_id = Column(Integer)
    before_data = Column(JSONB)
    after_data = Column(JSONB)
    request_id = Column(Text)
    ip_address = Column(Text)
    user_agent = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class DomainEvent(Base):
    __tablename__ = "domain_events"
    __table_args__ = (Index("ix_domain_events_org_id", "organization_id", "id"),)

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    topic = Column(Text, nullable=False)
    aggregate_type = Column(Text, nullable=False)
    aggregate_id = Column(Integer, nullable=False)
    aggregate_version = Column(Integer, nullable=False, server_default="1", default=1)
    operation = Column(Text, nullable=False)
    payload = Column(JSONB, nullable=False, server_default=sa_text("'{}'::jsonb"), default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class JobQueue(Base):
    __tablename__ = "job_queue"
    __table_args__ = (Index("ix_job_queue_claim", "state", "run_at", "lease_expires_at"),)

    id = Column(Integer, primary_key=True)
    job_type = Column(Text, nullable=False)
    payload = Column(JSONB, nullable=False, server_default=sa_text("'{}'::jsonb"), default=dict)
    state = Column(Text, nullable=False, server_default="pending", default="pending")
    run_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    lease_owner = Column(Text)
    lease_expires_at = Column(DateTime(timezone=True))
    attempts = Column(Integer, nullable=False, server_default="0", default=0)
    max_attempts = Column(Integer, nullable=False, server_default="5", default=5)
    dedup_key = Column(Text, unique=True)
    last_error = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (UniqueConstraint("account_id", "operation", "key", name="uq_idempotency_scope"),)

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False)
    operation = Column(Text, nullable=False)
    key = Column(Text, nullable=False)
    request_hash = Column(String(64), nullable=False)
    response_status = Column(Integer)
    response_body = Column(JSONB)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CalendarConnection(Base):
    __tablename__ = "calendar_connections"
    __table_args__ = (UniqueConstraint("account_id", "provider", name="uq_calendar_connections_account_provider"),)

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False)
    provider = Column(Text, nullable=False, server_default="google", default="google")
    encrypted_access_token = Column(Text)
    encrypted_refresh_token = Column(Text)
    token_expires_at = Column(DateTime(timezone=True))
    scopes = Column(JSONB, nullable=False, server_default=sa_text("'[]'::jsonb"), default=list)
    sync_cursor = Column(Text)
    sync_mode = Column(Text, nullable=False, server_default="outbound", default="outbound")
    status = Column(Text, nullable=False, server_default="pending", default="pending")
    last_synced_at = Column(DateTime(timezone=True))
    last_error = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class CalendarEventLink(Base):
    __tablename__ = "calendar_event_links"
    __table_args__ = (UniqueConstraint("connection_id", "task_id", name="uq_calendar_event_links_task"),)

    id = Column(Integer, primary_key=True)
    connection_id = Column(Integer, ForeignKey("calendar_connections.id", ondelete="CASCADE"), nullable=False)
    task_id = Column(Integer, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    external_event_id = Column(Text, nullable=False)
    external_etag = Column(Text)
    sync_state = Column(Text, nullable=False, server_default="synced", default="synced")
    last_error = Column(Text)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
