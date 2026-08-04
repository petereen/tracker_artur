from datetime import date, datetime, time

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func, text as sa_text

from app.core.database import Base


class Employee(Base):
    __tablename__ = "employees"

    id = Column(Integer, primary_key=True)
    name = Column(Text, nullable=False)
    telegram_id = Column(Text, unique=True, nullable=False)
    telegram_username = Column(Text)
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

    id = Column(Integer, primary_key=True)
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
    text = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    task = relationship("Task", back_populates="comments")


class NotificationOutbox(Base):
    """Очередь уведомлений — мост между api-процессом (без планировщика) и ботом.
    Бот дренит её (drain_notification_outbox) с учётом тихих часов (not_before)."""
    __tablename__ = "notification_outbox"

    id = Column(Integer, primary_key=True)
    task_id = Column(Integer, ForeignKey("tasks.id", ondelete="CASCADE"))
    recipient_tg = Column(Text, nullable=False)
    kind = Column(Text, nullable=False)  # 'task_assigned' и т.п.
    payload = Column(JSONB)
    not_before = Column(DateTime(timezone=True))
    status = Column(Text, default="pending", nullable=False)  # pending | sent | failed
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
            "status IN ('awaiting','draft','editing','approved')",
            name="ck_work_reports_status",
        ),
    )

    id = Column(Integer, primary_key=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    report_type = Column(Text, nullable=False)
    period_date = Column(Date, nullable=False)
    status = Column(Text, nullable=False, server_default="awaiting", default="awaiting")
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
