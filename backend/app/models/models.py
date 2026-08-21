import uuid
from datetime import date, datetime, time

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Float,
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

try:  # Keeps source imports usable before optional production dependencies install.
    from pgvector.sqlalchemy import Vector
except ModuleNotFoundError:  # pragma: no cover - production uses pgvector
    Vector = None


class Employee(Base):
    __tablename__ = "employees"

    id = Column(Integer, primary_key=True)
    name = Column(Text, nullable=False)
    telegram_id = Column(Text, unique=True, nullable=False)
    telegram_username = Column(Text)
    email = Column(Text, unique=True)
    manager_id = Column(Integer, ForeignKey("employees.id", ondelete="SET NULL"))
    job_title = Column(Text)
    phone_number = Column(Text)
    birthday = Column(Date)
    work_direction = Column(Text)
    work_branch = Column(Text)
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
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True)
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
    reviewer_id = Column(Integer, ForeignKey("employees.id", ondelete="SET NULL"))
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
    is_all_day = Column(Boolean, nullable=False, server_default=sa_text("false"), default=False)
    estimate_minutes = Column(Integer)
    work_location_type = Column(String(16))
    work_location = Column(Text)
    sort_position = Column(Numeric(20, 8), nullable=False, server_default="0", default=0)
    version = Column(Integer, nullable=False, server_default="1", default=1)
    is_archived = Column(Boolean, nullable=False, server_default=sa_text("false"), default=False)
    reminder_intervals_min = Column(ARRAY(Integer), default=lambda: list(DEFAULT_REMINDER_INTERVALS_MIN))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True))
    completed_by_id = Column(Integer, ForeignKey("employees.id", ondelete="SET NULL"))
    overdue_pinged_at = Column(DateTime(timezone=True))  # когда был отправлен немедленный пинг о просрочке

    assignee = relationship("Employee", foreign_keys=[assignee_id])
    reviewer = relationship("Employee", foreign_keys=[reviewer_id])
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
    user_notification_id = Column(Integer, ForeignKey("user_notifications.id", ondelete="CASCADE"))
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


DEFAULT_PRIORITY_NOTIFICATION_KINDS = {
    "task_assigned", "task_review_requested", "task_collaboration_updated",
    "task_deadline", "task_overdue", "monthly_report", "report_submitted",
    "project_member_added", "project_request_reviewed", "project_deadline",
    "company_plan_created", "calendar_reminder", "event",
}


class UserNotification(Base):
    __tablename__ = "user_notifications"
    __table_args__ = (
        Index("ix_user_notifications_account_unread", "recipient_account_id", "read_at", "id"),
        UniqueConstraint("dedup_key", name="uq_user_notifications_dedup_key"),
    )

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    recipient_account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False)
    recipient_employee_id = Column(Integer, ForeignKey("employees.id", ondelete="SET NULL"))
    event_id = Column(Integer, ForeignKey("domain_events.id", ondelete="SET NULL"))
    kind = Column(Text, nullable=False)
    title = Column(Text, nullable=False)
    body = Column(Text, nullable=False)
    target_url = Column(Text)
    payload = Column(JSONB, nullable=False, server_default=sa_text("'{}'::jsonb"), default=dict)
    telegram_status = Column(Text, nullable=False, server_default="unavailable", default="unavailable")
    dedup_key = Column(Text, nullable=False)
    is_priority = Column(Boolean, nullable=False, server_default=sa_text("false"), default=False)
    read_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


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


class WorktimeQrKiosk(Base):
    """A provisioned office display that may mint short-lived QR tokens."""

    __tablename__ = "worktime_qr_kiosks"
    __table_args__ = (
        UniqueConstraint("organization_id", "label", name="uq_worktime_qr_kiosk_org_label"),
        Index("ix_worktime_qr_kiosks_org_status", "organization_id", "status"),
        CheckConstraint("status IN ('active','revoked')", name="ck_worktime_qr_kiosk_status"),
    )

    id = Column(Integer, primary_key=True)
    public_id = Column(UUID(as_uuid=True), nullable=False, unique=True, default=uuid.uuid4, server_default=sa_text("gen_random_uuid()"))
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    label = Column(Text, nullable=False)
    location_id = Column(Text, nullable=False, server_default="main_office", default="main_office")
    display_name = Column(Text, nullable=False, server_default="Main office", default="Main office")
    credential_hash = Column(String(64), nullable=False, unique=True)
    pairing_code_hash = Column(String(64), unique=True)
    pairing_expires_at = Column(DateTime(timezone=True))
    status = Column(Text, nullable=False, server_default="active", default="active")
    created_by_account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="SET NULL"))
    paired_at = Column(DateTime(timezone=True))
    last_seen_at = Column(DateTime(timezone=True))
    revoked_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


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
    source_kiosk_id = Column(Integer, ForeignKey("worktime_qr_kiosks.id", ondelete="SET NULL"), index=True)
    work_location_id = Column(Text)
    version = Column(Integer, nullable=False, server_default="1", default=1)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    report = relationship("WorkReport", back_populates="work_time_entries")


# ─── Компаний сарын төлөвлөгөө ─────────────────────────────────────────────

COMPANY_PLAN_HORIZONS = ("long_term", "mid_term", "short_term")
COMPANY_PLAN_STATUSES = ("approved", "archived")


class CompanyPlanItem(Base):
    """An administrator-approved actionable item derived from a worker plan."""

    __tablename__ = "company_plan_items"
    __table_args__ = (
        CheckConstraint(
            "horizon IN ('long_term','mid_term','short_term')",
            name="ck_company_plan_items_horizon",
        ),
        CheckConstraint("status IN ('approved','archived')", name="ck_company_plan_items_status"),
    )

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    plan_month = Column(Date, nullable=False, index=True)
    title = Column(Text, nullable=False)
    content = Column(Text)
    horizon = Column(Text, nullable=False, server_default="short_term", default="short_term")
    position = Column(Integer, nullable=False, server_default="0", default=0)
    status = Column(Text, nullable=False, server_default="approved", default="approved")
    due_date = Column(Date)
    source_employee_id = Column(Integer, ForeignKey("employees.id", ondelete="SET NULL"))
    source_report_id = Column(Integer, ForeignKey("work_reports.id", ondelete="SET NULL"))
    approved_by_account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="SET NULL"))
    approved_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    source_employee = relationship("Employee", foreign_keys=[source_employee_id])
    source_report = relationship("WorkReport", foreign_keys=[source_report_id])


class PlanIdea(Base):
    __tablename__ = "plan_ideas"
    __table_args__ = (
        CheckConstraint("status IN ('pending','approved','rejected','merged')", name="ck_plan_ideas_status"),
        Index("ix_plan_ideas_org_month_status", "organization_id", "plan_month", "status"),
        UniqueConstraint("source_report_id", name="uq_plan_ideas_source_report"),
    )

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    submitted_by_account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False)
    submitted_by_employee_id = Column(Integer, ForeignKey("employees.id", ondelete="SET NULL"))
    plan_month = Column(Date, nullable=False)
    title = Column(Text, nullable=False)
    content = Column(Text)
    suggested_due_date = Column(Date)
    status = Column(Text, nullable=False, server_default="pending", default="pending")
    reviewed_by_account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="SET NULL"))
    merged_into_plan_item_id = Column(Integer, ForeignKey("company_plan_items.id", ondelete="SET NULL"))
    source_report_id = Column(Integer, ForeignKey("work_reports.id", ondelete="SET NULL"))
    reviewed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


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
    telegram_oidc_subject = Column(Text, unique=True)
    password_hash = Column(Text, nullable=False)
    status = Column(Text, nullable=False, server_default="active", default="active")
    locale = Column(String(8), nullable=False, server_default="mn", default="mn")
    preferences = Column(JSONB, nullable=False, server_default=sa_text("'{}'::jsonb"), default=dict)
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
    auth_method = Column(Text, nullable=False, server_default="password", default="password")
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked_at = Column(DateTime(timezone=True))
    last_used_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class MobilePushRegistration(Base):
    __tablename__ = "mobile_push_registrations"
    __table_args__ = (
        CheckConstraint("platform IN ('ios','android')", name="ck_mobile_push_platform"),
        CheckConstraint("provider IN ('apns','fcm')", name="ck_mobile_push_provider"),
        CheckConstraint(
            "(platform = 'ios' AND provider = 'apns') OR (platform = 'android' AND provider = 'fcm')",
            name="ck_mobile_push_platform_provider",
        ),
        Index("ix_mobile_push_account_active", "account_id", "is_active"),
    )

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False)
    platform = Column(String(16), nullable=False)
    provider = Column(String(16), nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True)
    encrypted_token = Column(Text, nullable=False)
    is_active = Column(Boolean, nullable=False, server_default=sa_text("true"), default=True)
    last_registered_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    revoked_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


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
            "role IN ('admin','manager','team_lead','hr','member','contractor','client_auditor')",
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
    archived_at = Column(DateTime(timezone=True))
    archived_by_account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="SET NULL"))
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


class ProjectRequest(Base):
    __tablename__ = "project_requests"
    __table_args__ = (Index("ix_project_requests_org_status", "organization_id", "status"),)

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    requested_by_account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False)
    requested_by_employee_id = Column(Integer, ForeignKey("employees.id", ondelete="SET NULL"))
    payload = Column(JSONB, nullable=False, server_default=sa_text("'{}'::jsonb"), default=dict)
    status = Column(Text, nullable=False, server_default="pending", default="pending")
    reviewer_account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="SET NULL"))
    review_note = Column(Text)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    reviewed_at = Column(DateTime(timezone=True))


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


class TaskReviewer(Base):
    __tablename__ = "task_reviewers"
    __table_args__ = (UniqueConstraint("task_id", "employee_id", name="uq_task_reviewers"),)

    id = Column(Integer, primary_key=True)
    task_id = Column(Integer, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
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


class CompanyLibraryItem(Base):
    __tablename__ = "company_library_items"
    __table_args__ = (
        CheckConstraint("kind IN ('folder','file')", name="ck_company_library_items_kind"),
        CheckConstraint(
            "(kind = 'folder' AND storage_key IS NULL AND content_type IS NULL AND size IS NULL AND checksum IS NULL) "
            "OR (kind = 'file' AND storage_key IS NOT NULL AND content_type IS NOT NULL AND size IS NOT NULL AND checksum IS NOT NULL)",
            name="ck_company_library_items_file_metadata",
        ),
        Index("ix_company_library_items_parent", "organization_id", "parent_id"),
        Index("ix_company_library_items_deleted", "organization_id", "deleted_at"),
    )

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    parent_id = Column(Integer, ForeignKey("company_library_items.id", ondelete="CASCADE"))
    kind = Column(String(12), nullable=False)
    name = Column(Text, nullable=False)
    storage_key = Column(Text, unique=True)
    content_type = Column(Text)
    size = Column(Integer)
    checksum = Column(String(64))
    uploaded_by_account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    deleted_at = Column(DateTime(timezone=True))
    deleted_by_account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="SET NULL"))


RESOURCE_CLASSIFICATIONS = ("public_link_safe", "internal", "confidential", "restricted")


class ResourcePolicy(Base):
    """Access policy shared by company files and curated knowledge."""

    __tablename__ = "resource_policies"
    __table_args__ = (
        UniqueConstraint("organization_id", "resource_type", "resource_id", name="uq_resource_policy_resource"),
        CheckConstraint("classification IN ('public_link_safe','internal','confidential','restricted')", name="ck_resource_policy_classification"),
    )

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    resource_type = Column(String(32), nullable=False)  # company_file | company_knowledge
    resource_id = Column(Integer, nullable=False)
    classification = Column(String(32), nullable=False, server_default="internal", default="internal")
    inherit_from_parent = Column(Boolean, nullable=False, server_default=sa_text("true"), default=True)
    created_by_account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class ResourceGrant(Base):
    __tablename__ = "resource_grants"
    __table_args__ = (
        CheckConstraint("principal_type IN ('role','team','project','account')", name="ck_resource_grant_principal"),
        UniqueConstraint("policy_id", "principal_type", "principal_key", name="uq_resource_grant_principal"),
    )

    id = Column(Integer, primary_key=True)
    policy_id = Column(Integer, ForeignKey("resource_policies.id", ondelete="CASCADE"), nullable=False, index=True)
    principal_type = Column(String(16), nullable=False)
    principal_key = Column(String(128), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class KnowledgeDocument(Base):
    """Index metadata; source bytes remain in the existing attachment stores."""

    __tablename__ = "knowledge_documents"
    __table_args__ = (
        UniqueConstraint("organization_id", "source_type", "source_id", name="uq_knowledge_document_source"),
        Index("ix_knowledge_documents_index_status", "organization_id", "index_status"),
    )

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    source_type = Column(String(32), nullable=False)  # company_file | company_knowledge
    source_id = Column(Integer, nullable=False)
    title = Column(Text, nullable=False)
    content_type = Column(Text)
    checksum = Column(String(64))
    index_status = Column(String(16), nullable=False, server_default="pending", default="pending")
    indexed_at = Column(DateTime(timezone=True))
    last_error = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (Index("ix_knowledge_chunks_document_position", "document_id", "position"),)

    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False, index=True)
    position = Column(Integer, nullable=False)
    locator = Column(JSONB, nullable=False, server_default=sa_text("'{}'::jsonb"), default=dict)
    content = Column(Text, nullable=False)
    search_vector = Column(Text)
    embedding = Column(Vector(1536) if Vector else ARRAY(Float))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AssistantToolAudit(Base):
    __tablename__ = "assistant_tool_audits"
    __table_args__ = (Index("ix_assistant_tool_audits_expiry", "content_expires_at"),)

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    conversation_id = Column(Integer, ForeignKey("assistant_conversations.id", ondelete="SET NULL"))
    channel = Column(String(16), nullable=False)
    tool_name = Column(String(64), nullable=False)
    status = Column(String(16), nullable=False)
    resource_refs = Column(JSONB, nullable=False, server_default=sa_text("'[]'::jsonb"), default=list)
    # ``metadata`` is reserved by SQLAlchemy's declarative API. Keep the
    # existing database column while exposing it through a safe ORM name.
    audit_metadata = Column("metadata", JSONB, nullable=False, server_default=sa_text("'{}'::jsonb"), default=dict)
    encrypted_payload = Column(Text)
    content_expires_at = Column(DateTime(timezone=True), nullable=False)
    metadata_expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AssistantPendingAction(Base):
    __tablename__ = "assistant_pending_actions"
    __table_args__ = (Index("ix_assistant_pending_actions_expiry", "expires_at"),)

    id = Column(Integer, primary_key=True)
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False)
    action_type = Column(String(32), nullable=False, server_default="update_task", default="update_task")
    task_id = Column(Integer, ForeignKey("tasks.id", ondelete="CASCADE"))
    expected_version = Column(Integer)
    channel = Column(String(16), nullable=False)
    payload = Column(JSONB, nullable=False, server_default=sa_text("'{}'::jsonb"), default=dict)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    consumed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


Index(
    "uq_company_library_items_active_sibling_name",
    CompanyLibraryItem.organization_id,
    func.coalesce(CompanyLibraryItem.parent_id, 0),
    func.lower(CompanyLibraryItem.name),
    unique=True,
    postgresql_where=CompanyLibraryItem.deleted_at.is_(None),
)


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


class PersonalTimeBlock(Base):
    __tablename__ = "personal_time_blocks"
    __table_args__ = (
        Index("ix_personal_time_blocks_account_start", "account_id", "starts_at"),
        CheckConstraint("ends_at > starts_at", name="ck_personal_time_blocks_positive_duration"),
    )

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False)
    task_id = Column(Integer, ForeignKey("tasks.id", ondelete="SET NULL"))
    title = Column(Text, nullable=False)
    starts_at = Column(DateTime(timezone=True), nullable=False)
    ends_at = Column(DateTime(timezone=True), nullable=False)
    version = Column(Integer, nullable=False, server_default="1", default=1)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class CalendarEntry(Base):
    __tablename__ = "calendar_entries"
    __table_args__ = (
        Index("ix_calendar_entries_org_period", "organization_id", "starts_at"),
        Index("ix_calendar_entries_account_period", "account_id", "starts_at"),
    )

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=True)
    created_by_account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="SET NULL"))
    kind = Column(Text, nullable=False)  # reminder | event
    visibility = Column(Text, nullable=False, server_default="private", default="private")
    title = Column(Text, nullable=False)
    description = Column(Text)
    starts_at = Column(DateTime(timezone=True), nullable=False)
    ends_at = Column(DateTime(timezone=True), nullable=False)
    is_all_day = Column(Boolean, nullable=False, server_default=sa_text("false"), default=False)
    recurrence_rule = Column(Text)
    recurrence_exceptions = Column(JSONB, nullable=False, server_default=sa_text("'[]'::jsonb"), default=list)
    remind_at = Column(DateTime(timezone=True))
    version = Column(Integer, nullable=False, server_default="1", default=1)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class HolidayRecord(Base):
    __tablename__ = "holiday_records"
    __table_args__ = (UniqueConstraint("organization_id", "country_code", "holiday_date", "name", name="uq_holiday_record"),)

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    country_code = Column(String(2), nullable=False)
    holiday_date = Column(Date, nullable=False)
    name = Column(Text, nullable=False)
    local_name = Column(Text)
    is_active = Column(Boolean, nullable=False, server_default=sa_text("true"), default=True)
    is_override = Column(Boolean, nullable=False, server_default=sa_text("false"), default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AssistantConversation(Base):
    __tablename__ = "assistant_conversations"
    __table_args__ = (Index("ix_assistant_conversations_account_updated", "account_id", "updated_at"),)

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    channel = Column(String(16), nullable=False, server_default="web", default="web")
    external_thread_key = Column(String(128))
    title = Column(Text)
    # The Responses API requires a prior ``mcp_list_tools`` item to be kept in
    # the next turn when deferred MCP discovery is enabled.  This stores only
    # that protocol context, never tool arguments, results, or credentials.
    mcp_context = Column(JSONB, nullable=False, server_default=sa_text("'[]'::jsonb"), default=list)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class AssistantMessage(Base):
    __tablename__ = "assistant_messages"
    __table_args__ = (Index("ix_assistant_messages_conversation_id", "conversation_id", "id"),)

    id = Column(Integer, primary_key=True)
    conversation_id = Column(Integer, ForeignKey("assistant_conversations.id", ondelete="CASCADE"), nullable=False)
    role = Column(Text, nullable=False)
    content = Column(Text, nullable=False)
    action = Column(JSONB)
    sources = Column(JSONB, nullable=False, server_default=sa_text("'[]'::jsonb"), default=list)
    attachments = Column(JSONB, nullable=False, server_default=sa_text("'[]'::jsonb"), default=list)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AssistantSemanticCache(Base):
    """Only stores public, context-independent responses produced by a live model."""

    __tablename__ = "assistant_semantic_cache"
    __table_args__ = (
        Index("ix_assistant_semantic_cache_expiry", "expires_at"),
        Index("ix_assistant_semantic_cache_prompt_language", "prompt_version", "language"),
    )

    id = Column(Integer, primary_key=True)
    prompt_version = Column(String(64), nullable=False)
    language = Column(String(12), nullable=False)
    query_text = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    embedding = Column(Vector(1536) if Vector else ARRAY(Float), nullable=False)
    source_model = Column(String(128), nullable=False)
    usage = Column(JSONB, nullable=False, server_default=sa_text("'{}'::jsonb"), default=dict)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


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


# ─── Configurable ERP foundation ────────────────────────────────────────────
#
# ERP records deliberately use their own tables and are scoped directly to an
# organization.  This keeps the product extractable and avoids changing the
# compatibility contracts used by the original task/report application.


class ERPAccessRole(Base):
    __tablename__ = "erp_access_roles"
    __table_args__ = (UniqueConstraint("organization_id", "code", name="uq_erp_access_roles_org_code"),)

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    name = Column(Text, nullable=False)
    code = Column(String(64), nullable=False)
    description = Column(Text)
    is_system = Column(Boolean, nullable=False, server_default=sa_text("false"), default=False)
    is_active = Column(Boolean, nullable=False, server_default=sa_text("true"), default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class ERPCapability(Base):
    __tablename__ = "erp_capabilities"
    __table_args__ = (UniqueConstraint("access_role_id", "resource", "action", name="uq_erp_capability"),)

    id = Column(Integer, primary_key=True)
    access_role_id = Column(Integer, ForeignKey("erp_access_roles.id", ondelete="CASCADE"), nullable=False)
    resource = Column(String(80), nullable=False)
    action = Column(String(24), nullable=False)


class ERPAccountRole(Base):
    __tablename__ = "erp_account_roles"
    __table_args__ = (UniqueConstraint("account_id", "access_role_id", name="uq_erp_account_role"),)

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False)
    access_role_id = Column(Integer, ForeignKey("erp_access_roles.id", ondelete="CASCADE"), nullable=False)
    scope = Column(JSONB, nullable=False, server_default=sa_text("'{}'::jsonb"), default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ERPTeamRole(Base):
    """A role assignment inherited by active members of an organization team."""
    __tablename__ = "erp_team_roles"
    __table_args__ = (UniqueConstraint("team_id", "access_role_id", name="uq_erp_team_role"),)

    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="CASCADE"), nullable=False)
    access_role_id = Column(Integer, ForeignKey("erp_access_roles.id", ondelete="CASCADE"), nullable=False)
    scope = Column(JSONB, nullable=False, server_default=sa_text("'{}'::jsonb"), default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ERPFormDefinition(Base):
    """Immutable published form/workflow versions; one editable draft per operation."""
    __tablename__ = "erp_form_definitions"
    __table_args__ = (
        UniqueConstraint("organization_id", "operation", "version", name="uq_erp_form_definition_version"),
        Index("ix_erp_form_definitions_org_operation_status", "organization_id", "operation", "status"),
    )

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    operation = Column(String(80), nullable=False)
    version = Column(Integer, nullable=False)
    status = Column(String(24), nullable=False, server_default="draft", default="draft")
    fields = Column(JSONB, nullable=False, server_default=sa_text("'[]'::jsonb"), default=list)
    workflow = Column(JSONB, nullable=False, server_default=sa_text("'{}'::jsonb"), default=dict)
    created_by_account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="SET NULL"))
    published_at = Column(DateTime(timezone=True))
    archived_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class ERPModuleConfig(Base):
    __tablename__ = "erp_module_configs"
    __table_args__ = (
        UniqueConstraint("organization_id", "module", name="uq_erp_module_config_org_module"),
        Index("ix_erp_module_configs_org_enabled", "organization_id", "enabled"),
    )

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    module = Column(String(40), nullable=False)
    enabled = Column(Boolean, nullable=False, server_default=sa_text("false"), default=False)
    updated_by_account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class ERPMasterRequest(Base):
    __tablename__ = "erp_master_requests"
    __table_args__ = (Index("ix_erp_master_requests_org_operation_state", "organization_id", "operation", "workflow_state"),)

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    operation = Column(String(80), nullable=False)
    definition_version = Column(Integer, nullable=False)
    payload = Column(JSONB, nullable=False, server_default=sa_text("'{}'::jsonb"), default=dict)
    workflow_state = Column(String(64), nullable=False, server_default="draft", default="draft")
    scope = Column(JSONB, nullable=False, server_default=sa_text("'{}'::jsonb"), default=dict)
    requested_by_account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="SET NULL"))
    approved_by_account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="SET NULL"))
    approved_at = Column(DateTime(timezone=True))
    materialized_entity_type = Column(String(40))
    materialized_entity_id = Column(Integer)
    version = Column(Integer, nullable=False, server_default="1", default=1)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class ERPWorkflowTransition(Base):
    __tablename__ = "erp_workflow_transitions"
    __table_args__ = (Index("ix_erp_workflow_transition_entity", "organization_id", "entity_type", "entity_id", "created_at"),)

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    entity_type = Column(String(40), nullable=False)
    entity_id = Column(Integer, nullable=False)
    operation = Column(String(80), nullable=False)
    definition_version = Column(Integer, nullable=False)
    from_state = Column(String(64))
    to_state = Column(String(64), nullable=False)
    comment = Column(Text)
    actor_account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ERPCustomField(Base):
    __tablename__ = "erp_custom_fields"
    __table_args__ = (UniqueConstraint("organization_id", "resource", "key", name="uq_erp_custom_field"),)

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    resource = Column(String(80), nullable=False)
    key = Column(String(64), nullable=False)
    label = Column(Text, nullable=False)
    field_type = Column(String(24), nullable=False)
    options = Column(JSONB, nullable=False, server_default=sa_text("'{}'::jsonb"), default=dict)
    required = Column(Boolean, nullable=False, server_default=sa_text("false"), default=False)
    posting_relevant = Column(Boolean, nullable=False, server_default=sa_text("false"), default=False)
    is_active = Column(Boolean, nullable=False, server_default=sa_text("true"), default=True)


class ERPSequence(Base):
    __tablename__ = "erp_sequences"
    __table_args__ = (UniqueConstraint("organization_id", "key", name="uq_erp_sequence"),)

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    key = Column(String(80), nullable=False)
    prefix = Column(String(40), nullable=False, server_default="", default="")
    next_number = Column(Integer, nullable=False, server_default="1", default=1)
    padding = Column(Integer, nullable=False, server_default="5", default=5)


class ERPParty(Base):
    __tablename__ = "erp_parties"
    __table_args__ = (
        UniqueConstraint("organization_id", "code", name="uq_erp_party_org_code"),
        Index("ix_erp_parties_org_type", "organization_id", "party_type"),
    )

    id = Column(Integer, primary_key=True)
    public_id = Column(UUID(as_uuid=True), nullable=False, unique=True, default=uuid.uuid4, server_default=sa_text("gen_random_uuid()"))
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    legacy_client_id = Column(Integer, ForeignKey("clients.id", ondelete="SET NULL"), unique=True)
    party_type = Column(String(24), nullable=False)
    code = Column(String(64), nullable=False)
    name = Column(Text, nullable=False)
    email = Column(Text)
    phone = Column(Text)
    tax_id = Column(Text)
    credit_limit = Column(Numeric(18, 4))
    currency = Column(String(3), nullable=False, server_default="MNT", default="MNT")
    status = Column(String(24), nullable=False, server_default="active", default="active")
    contacts = Column(JSONB, nullable=False, server_default=sa_text("'[]'::jsonb"), default=list)
    addresses = Column(JSONB, nullable=False, server_default=sa_text("'[]'::jsonb"), default=list)
    custom = Column(JSONB, nullable=False, server_default=sa_text("'{}'::jsonb"), default=dict)
    definition_version = Column(Integer, nullable=False, server_default="1", default=1)
    workflow_state = Column(String(64), nullable=False, server_default="draft", default="draft")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class ERPItem(Base):
    __tablename__ = "erp_items"
    __table_args__ = (UniqueConstraint("organization_id", "code", name="uq_erp_item_org_code"),)

    id = Column(Integer, primary_key=True)
    public_id = Column(UUID(as_uuid=True), nullable=False, unique=True, default=uuid.uuid4, server_default=sa_text("gen_random_uuid()"))
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    code = Column(String(64), nullable=False)
    name = Column(Text, nullable=False)
    item_type = Column(String(24), nullable=False, server_default="product", default="product")
    item_group = Column(Text)
    unit = Column(String(24), nullable=False, server_default="Nos", default="Nos")
    valuation_method = Column(String(24), nullable=False, server_default="moving_average", default="moving_average")
    standard_cost = Column(Numeric(18, 4), nullable=False, server_default="0", default=0)
    reorder_level = Column(Numeric(18, 4))
    is_stock_item = Column(Boolean, nullable=False, server_default=sa_text("true"), default=True)
    is_active = Column(Boolean, nullable=False, server_default=sa_text("true"), default=True)
    custom = Column(JSONB, nullable=False, server_default=sa_text("'{}'::jsonb"), default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class ERPWarehouse(Base):
    __tablename__ = "erp_warehouses"
    __table_args__ = (UniqueConstraint("organization_id", "code", name="uq_erp_warehouse_org_code"),)

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    code = Column(String(64), nullable=False)
    name = Column(Text, nullable=False)
    parent_id = Column(Integer, ForeignKey("erp_warehouses.id", ondelete="SET NULL"))
    is_active = Column(Boolean, nullable=False, server_default=sa_text("true"), default=True)


class ERPUnitOfMeasure(Base):
    __tablename__ = "erp_units_of_measure"
    __table_args__ = (UniqueConstraint("organization_id", "code", name="uq_erp_uom_org_code"),)

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    code = Column(String(32), nullable=False)
    name = Column(Text, nullable=False)
    symbol = Column(String(16))
    decimal_places = Column(Integer, nullable=False, server_default="2", default=2)
    is_active = Column(Boolean, nullable=False, server_default=sa_text("true"), default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ERPPriceList(Base):
    __tablename__ = "erp_price_lists"
    __table_args__ = (UniqueConstraint("organization_id", "code", name="uq_erp_price_list_org_code"),)

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    code = Column(String(64), nullable=False)
    name = Column(Text, nullable=False)
    party_id = Column(Integer, ForeignKey("erp_parties.id", ondelete="SET NULL"))
    price_list_type = Column(String(24), nullable=False, server_default="supplier", default="supplier")
    currency = Column(String(3), nullable=False, server_default="MNT", default="MNT")
    valid_from = Column(Date)
    valid_to = Column(Date)
    is_active = Column(Boolean, nullable=False, server_default=sa_text("true"), default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ERPPriceListEntry(Base):
    __tablename__ = "erp_price_list_entries"
    __table_args__ = (UniqueConstraint("price_list_id", "item_id", name="uq_erp_price_list_entry_item"),)

    id = Column(Integer, primary_key=True)
    price_list_id = Column(Integer, ForeignKey("erp_price_lists.id", ondelete="CASCADE"), nullable=False)
    item_id = Column(Integer, ForeignKey("erp_items.id", ondelete="CASCADE"), nullable=False)
    uom_id = Column(Integer, ForeignKey("erp_units_of_measure.id", ondelete="SET NULL"))
    minimum_quantity = Column(Numeric(18, 6), nullable=False, server_default="1", default=1)
    rate = Column(Numeric(18, 4), nullable=False, server_default="0", default=0)


class ERPDiscountTier(Base):
    __tablename__ = "erp_discount_tiers"
    __table_args__ = (UniqueConstraint("organization_id", "code", name="uq_erp_discount_tier_org_code"),)

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    code = Column(String(64), nullable=False)
    name = Column(Text, nullable=False)
    minimum_spend = Column(Numeric(18, 4), nullable=False, server_default="0", default=0)
    discount_percent = Column(Numeric(9, 4), nullable=False, server_default="0", default=0)
    is_active = Column(Boolean, nullable=False, server_default=sa_text("true"), default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ERPReorderRule(Base):
    __tablename__ = "erp_reorder_rules"
    __table_args__ = (UniqueConstraint("organization_id", "item_id", "warehouse_id", name="uq_erp_reorder_rule_item_warehouse"),)

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    item_id = Column(Integer, ForeignKey("erp_items.id", ondelete="CASCADE"), nullable=False)
    warehouse_id = Column(Integer, ForeignKey("erp_warehouses.id", ondelete="CASCADE"), nullable=False)
    reorder_level = Column(Numeric(18, 6), nullable=False, server_default="0", default=0)
    reorder_quantity = Column(Numeric(18, 6), nullable=False, server_default="0", default=0)
    maximum_level = Column(Numeric(18, 6))
    is_active = Column(Boolean, nullable=False, server_default=sa_text("true"), default=True)


class ERPCostCenter(Base):
    __tablename__ = "erp_cost_centers"
    __table_args__ = (UniqueConstraint("organization_id", "code", name="uq_erp_cost_center_org_code"),)

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    parent_id = Column(Integer, ForeignKey("erp_cost_centers.id", ondelete="SET NULL"))
    code = Column(String(64), nullable=False)
    name = Column(Text, nullable=False)
    is_active = Column(Boolean, nullable=False, server_default=sa_text("true"), default=True)


class ERPTaxTemplate(Base):
    __tablename__ = "erp_tax_templates"
    __table_args__ = (UniqueConstraint("organization_id", "code", name="uq_erp_tax_template_org_code"),)

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    code = Column(String(64), nullable=False)
    name = Column(Text, nullable=False)
    direction = Column(String(16), nullable=False, server_default="sales", default="sales")
    is_active = Column(Boolean, nullable=False, server_default=sa_text("true"), default=True)


class ERPTaxTemplateRate(Base):
    __tablename__ = "erp_tax_template_rates"

    id = Column(Integer, primary_key=True)
    tax_template_id = Column(Integer, ForeignKey("erp_tax_templates.id", ondelete="CASCADE"), nullable=False)
    name = Column(Text, nullable=False)
    rate = Column(Numeric(9, 4), nullable=False, server_default="0", default=0)
    account_id = Column(Integer, ForeignKey("erp_accounts.id", ondelete="SET NULL"))


class ERPInventoryLevel(Base):
    __tablename__ = "erp_inventory_levels"
    __table_args__ = (
        UniqueConstraint("organization_id", "item_id", "warehouse_id", name="uq_erp_inventory_level_item_warehouse"),
        Index("ix_erp_inventory_levels_org_warehouse", "organization_id", "warehouse_id"),
    )

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    item_id = Column(Integer, ForeignKey("erp_items.id", ondelete="CASCADE"), nullable=False)
    warehouse_id = Column(Integer, ForeignKey("erp_warehouses.id", ondelete="CASCADE"), nullable=False)
    quantity = Column(Numeric(18, 6), nullable=False, server_default="0", default=0)
    valuation_rate = Column(Numeric(18, 4), nullable=False, server_default="0", default=0)
    inventory_value = Column(Numeric(18, 4), nullable=False, server_default="0", default=0)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class ERPAccount(Base):
    __tablename__ = "erp_accounts"
    __table_args__ = (UniqueConstraint("organization_id", "code", name="uq_erp_account_org_code"),)

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    parent_id = Column(Integer, ForeignKey("erp_accounts.id", ondelete="SET NULL"))
    code = Column(String(64), nullable=False)
    name = Column(Text, nullable=False)
    account_type = Column(String(32), nullable=False)
    is_group = Column(Boolean, nullable=False, server_default=sa_text("false"), default=False)
    is_active = Column(Boolean, nullable=False, server_default=sa_text("true"), default=True)


class ERPDocument(Base):
    __tablename__ = "erp_documents"
    __table_args__ = (
        UniqueConstraint("organization_id", "document_type", "number", name="uq_erp_document_number"),
        Index("ix_erp_documents_org_type_status", "organization_id", "document_type", "status"),
        Index("ix_erp_documents_party", "organization_id", "party_id", "posting_date"),
        Index("ix_erp_documents_org_archive", "organization_id", "archived_at"),
    )

    id = Column(Integer, primary_key=True)
    public_id = Column(UUID(as_uuid=True), nullable=False, unique=True, default=uuid.uuid4, server_default=sa_text("gen_random_uuid()"))
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    document_type = Column(String(64), nullable=False)
    number = Column(String(80), nullable=False)
    status = Column(String(24), nullable=False, server_default="draft", default="draft")
    party_id = Column(Integer, ForeignKey("erp_parties.id", ondelete="SET NULL"))
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="SET NULL"))
    source_document_id = Column(Integer, ForeignKey("erp_documents.id", ondelete="SET NULL"))
    amended_from_id = Column(Integer, ForeignKey("erp_documents.id", ondelete="SET NULL"))
    currency = Column(String(3), nullable=False, server_default="MNT", default="MNT")
    exchange_rate = Column(Numeric(24, 10), nullable=False, server_default="1", default=1)
    posting_date = Column(Date, nullable=False, server_default=func.current_date())
    due_date = Column(Date)
    net_total = Column(Numeric(18, 4), nullable=False, server_default="0", default=0)
    tax_total = Column(Numeric(18, 4), nullable=False, server_default="0", default=0)
    grand_total = Column(Numeric(18, 4), nullable=False, server_default="0", default=0)
    outstanding_amount = Column(Numeric(18, 4), nullable=False, server_default="0", default=0)
    payload = Column(JSONB, nullable=False, server_default=sa_text("'{}'::jsonb"), default=dict)
    custom = Column(JSONB, nullable=False, server_default=sa_text("'{}'::jsonb"), default=dict)
    submitted_at = Column(DateTime(timezone=True))
    submitted_by_account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="SET NULL"))
    cancelled_at = Column(DateTime(timezone=True))
    archived_at = Column(DateTime(timezone=True))
    archived_by_account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="SET NULL"))
    version = Column(Integer, nullable=False, server_default="1", default=1)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class ERPDocumentLine(Base):
    __tablename__ = "erp_document_lines"
    __table_args__ = (Index("ix_erp_document_lines_document", "document_id", "position"),)

    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey("erp_documents.id", ondelete="CASCADE"), nullable=False)
    item_id = Column(Integer, ForeignKey("erp_items.id", ondelete="SET NULL"))
    warehouse_id = Column(Integer, ForeignKey("erp_warehouses.id", ondelete="SET NULL"))
    account_id = Column(Integer, ForeignKey("erp_accounts.id", ondelete="SET NULL"))
    description = Column(Text, nullable=False)
    quantity = Column(Numeric(18, 6), nullable=False, server_default="1", default=1)
    rate = Column(Numeric(18, 4), nullable=False, server_default="0", default=0)
    discount_percent = Column(Numeric(9, 4), nullable=False, server_default="0", default=0)
    discount_amount = Column(Numeric(18, 4), nullable=False, server_default="0", default=0)
    amount = Column(Numeric(18, 4), nullable=False, server_default="0", default=0)
    tax_rate = Column(Numeric(9, 4), nullable=False, server_default="0", default=0)
    tax_amount = Column(Numeric(18, 4), nullable=False, server_default="0", default=0)
    position = Column(Integer, nullable=False, server_default="0", default=0)
    data = Column(JSONB, nullable=False, server_default=sa_text("'{}'::jsonb"), default=dict)


class ERPGeneralLedgerEntry(Base):
    __tablename__ = "erp_general_ledger_entries"
    __table_args__ = (Index("ix_erp_gl_org_account_date", "organization_id", "account_id", "posting_date"),)

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    document_id = Column(Integer, ForeignKey("erp_documents.id", ondelete="RESTRICT"), nullable=False)
    account_id = Column(Integer, ForeignKey("erp_accounts.id", ondelete="RESTRICT"), nullable=False)
    party_id = Column(Integer, ForeignKey("erp_parties.id", ondelete="SET NULL"))
    posting_date = Column(Date, nullable=False)
    debit = Column(Numeric(18, 4), nullable=False, server_default="0", default=0)
    credit = Column(Numeric(18, 4), nullable=False, server_default="0", default=0)
    memo = Column(Text)
    reversal_of_id = Column(Integer, ForeignKey("erp_general_ledger_entries.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ERPStockLedgerEntry(Base):
    __tablename__ = "erp_stock_ledger_entries"
    __table_args__ = (Index("ix_erp_stock_org_item_warehouse_date", "organization_id", "item_id", "warehouse_id", "posting_date"),)

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    document_id = Column(Integer, ForeignKey("erp_documents.id", ondelete="RESTRICT"), nullable=False)
    item_id = Column(Integer, ForeignKey("erp_items.id", ondelete="RESTRICT"), nullable=False)
    warehouse_id = Column(Integer, ForeignKey("erp_warehouses.id", ondelete="RESTRICT"), nullable=False)
    posting_date = Column(Date, nullable=False)
    quantity_delta = Column(Numeric(18, 6), nullable=False)
    value_delta = Column(Numeric(18, 4), nullable=False)
    valuation_rate = Column(Numeric(18, 4), nullable=False, server_default="0", default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ERPPostingPeriod(Base):
    __tablename__ = "erp_posting_periods"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_erp_posting_period_name"),
        Index("ix_erp_posting_period_dates", "organization_id", "starts_on", "ends_on"),
    )

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(80), nullable=False)
    starts_on = Column(Date, nullable=False)
    ends_on = Column(Date, nullable=False)
    status = Column(String(24), nullable=False, server_default="open", default="open")
    closed_by_account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="SET NULL"))
    closed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ERPApprovalRule(Base):
    __tablename__ = "erp_approval_rules"
    __table_args__ = (UniqueConstraint("organization_id", "resource", "priority", name="uq_erp_approval_rule_priority"),)

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    resource = Column(String(80), nullable=False)
    minimum_amount = Column(Numeric(18, 4), nullable=False, server_default="0", default=0)
    required_access_role_id = Column(Integer, ForeignKey("erp_access_roles.id", ondelete="SET NULL"))
    priority = Column(Integer, nullable=False, server_default="100", default=100)
    is_active = Column(Boolean, nullable=False, server_default=sa_text("true"), default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ERPPaymentAllocation(Base):
    __tablename__ = "erp_payment_allocations"
    __table_args__ = (UniqueConstraint("payment_document_id", "invoice_document_id", name="uq_erp_payment_allocation"),)

    id = Column(Integer, primary_key=True)
    payment_document_id = Column(Integer, ForeignKey("erp_documents.id", ondelete="CASCADE"), nullable=False)
    invoice_document_id = Column(Integer, ForeignKey("erp_documents.id", ondelete="RESTRICT"), nullable=False)
    amount = Column(Numeric(18, 4), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ERPImportBatch(Base):
    __tablename__ = "erp_import_batches"
    __table_args__ = (Index("ix_erp_import_batches_org_state", "organization_id", "state", "created_at"),)

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    created_by_account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="SET NULL"))
    entity = Column(String(40), nullable=False)
    source_format = Column(String(32), nullable=False, server_default="generic", default="generic")
    state = Column(String(24), nullable=False, server_default="draft", default="draft")
    rows = Column(JSONB, nullable=False, server_default=sa_text("'[]'::jsonb"), default=list)
    validation_errors = Column(JSONB, nullable=False, server_default=sa_text("'[]'::jsonb"), default=list)
    committed_at = Column(DateTime(timezone=True))
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
    calendar_id = Column(Text, nullable=False, server_default="primary", default="primary")
    google_account_email = Column(Text)
    calendar_name = Column(Text)
    calendar_timezone = Column(Text)
    webhook_channel_id = Column(Text, unique=True)
    webhook_resource_id = Column(Text)
    encrypted_channel_token = Column(Text)
    channel_expires_at = Column(DateTime(timezone=True))
    last_webhook_message_number = Column(String(32))
    sync_failure_count = Column(Integer, nullable=False, server_default="0", default=0)
    sync_mode = Column(Text, nullable=False, server_default="outbound", default="outbound")
    status = Column(Text, nullable=False, server_default="pending", default="pending")
    last_synced_at = Column(DateTime(timezone=True))
    last_error = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class CalendarEventLink(Base):
    __tablename__ = "calendar_event_links"
    __table_args__ = (
        UniqueConstraint("connection_id", "task_id", name="uq_calendar_event_links_task"),
        UniqueConstraint("connection_id", "calendar_entry_id", name="uq_calendar_event_links_entry"),
        CheckConstraint("task_id IS NOT NULL OR calendar_entry_id IS NOT NULL", name="ck_calendar_event_links_entity"),
    )

    id = Column(Integer, primary_key=True)
    connection_id = Column(Integer, ForeignKey("calendar_connections.id", ondelete="CASCADE"), nullable=False)
    task_id = Column(Integer, ForeignKey("tasks.id", ondelete="CASCADE"))
    calendar_entry_id = Column(Integer, ForeignKey("calendar_entries.id", ondelete="CASCADE"))
    external_event_id = Column(Text, nullable=False)
    external_recurring_event_id = Column(Text)
    external_etag = Column(Text)
    external_updated_at = Column(DateTime(timezone=True))
    source = Column(Text, nullable=False, server_default="platform", default="platform")
    platform_version = Column(Integer)
    platform_fingerprint = Column(String(64))
    conflict_state = Column(Text, nullable=False, server_default="none", default="none")
    sync_state = Column(Text, nullable=False, server_default="synced", default="synced")
    last_error = Column(Text)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class GoogleCalendarOAuthState(Base):
    __tablename__ = "google_calendar_oauth_states"
    __table_args__ = (Index("ix_google_calendar_oauth_states_expiry", "expires_at"),)

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False)
    nonce_hash = Column(String(64), nullable=False, unique=True)
    encrypted_code_verifier = Column(Text, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class TelegramOAuthState(Base):
    __tablename__ = "telegram_oauth_states"
    __table_args__ = (Index("ix_telegram_oauth_states_expiry", "expires_at"),)

    id = Column(Integer, primary_key=True)
    state_hash = Column(String(64), nullable=False, unique=True)
    nonce_hash = Column(String(64), nullable=False, unique=True)
    encrypted_nonce = Column(Text, nullable=False)
    encrypted_code_verifier = Column(Text, nullable=False)
    platform = Column(String(16), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class MobileUpdateBundle(Base):
    """Immutable web bundle metadata for the self-hosted native updater."""

    __tablename__ = "mobile_update_bundles"
    __table_args__ = (
        UniqueConstraint("app_id", "version", name="uq_mobile_update_bundle_app_version"),
        Index("ix_mobile_update_bundles_app_created", "app_id", "created_at"),
    )

    id = Column(Integer, primary_key=True)
    app_id = Column(String(128), nullable=False)
    version = Column(String(64), nullable=False)
    storage_key = Column(String(512), nullable=False, unique=True)
    checksum = Column(String(64), nullable=False)
    size = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class MobileUpdateChannel(Base):
    """Mutable channel pointer; promotion is an atomic metadata-only change."""

    __tablename__ = "mobile_update_channels"
    __table_args__ = (UniqueConstraint("app_id", "name", name="uq_mobile_update_channel_app_name"),)

    id = Column(Integer, primary_key=True)
    app_id = Column(String(128), nullable=False)
    name = Column(String(64), nullable=False)
    active_bundle_id = Column(Integer, ForeignKey("mobile_update_bundles.id", ondelete="SET NULL"))
    previous_bundle_id = Column(Integer, ForeignKey("mobile_update_bundles.id", ondelete="SET NULL"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
