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
from sqlalchemy.sql import func

from app.core.database import Base


class Employee(Base):
    __tablename__ = "employees"

    id = Column(Integer, primary_key=True)
    name = Column(Text, nullable=False)
    telegram_id = Column(Text, unique=True, nullable=False)
    telegram_username = Column(Text)
    timezone = Column(Text, default="Europe/Moscow")
    is_active = Column(Boolean, default=True)
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
    options = Column(JSONB, default=list)
    is_required = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)


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
    variant = Column(String(1), default="A")
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
    weekly_summary_day = Column(Integer, default=5)
    alerts_enabled = Column(Boolean, default=True)
    gamification_enabled = Column(Boolean, default=True)
    soft_mode_weeks = Column(Integer, default=1)
    onboarding_template = Column(Text, nullable=True)


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
    priority = Column(Integer, default=2)  # 1=срочно, 2=обычно, 3=низкий
    reminder_intervals_min = Column(ARRAY(Integer), default=lambda: list(DEFAULT_REMINDER_INTERVALS_MIN))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True))
    completed_by_id = Column(Integer, ForeignKey("employees.id", ondelete="SET NULL"))

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
