"""APScheduler — джобы для каждого сотрудника."""
import logging
from datetime import datetime, time, timedelta
from hashlib import sha256

import pytz
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import text

from app.core.config import settings

log = logging.getLogger(__name__)

DEFAULT_TIMEZONE = pytz.timezone("Asia/Ulaanbaatar")
jobstores = {"default": SQLAlchemyJobStore(url=settings.SYNC_DATABASE_URL)}
scheduler = AsyncIOScheduler(jobstores=jobstores, timezone=DEFAULT_TIMEZONE)
_last_schedule_fingerprint: str | None = None
_REBUILD_LOCK_KEY = 67129841


def _make_bot():
    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode
    return Bot(token=settings.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


def _rebuild_jobs_unlocked():
    from app.bot.db import get_all_active_employees, get_manager_settings, get_schedule
    from app.services.notification_policy import load_policy

    employees = get_all_active_employees()
    manager_settings = get_manager_settings()
    policy = load_policy(manager_settings)
    digest_dow = ",".join(str(d - 1) for d in sorted(policy.work_weekdays)) or "0,1,2,3,4"

    global _last_schedule_fingerprint
    for job in scheduler.get_jobs():
        if any(job.id.startswith(p) for p in
               ("survey_", "reminder1_", "reminder2_", "missed_", "monthly_report_", "task_morning_", "task_evening_")):
            job.remove()

    from app.services.digest_service import send_employee_morning_digest, send_employee_evening_digest
    md, ed = policy.morning_digest, policy.evening_digest

    for emp in employees:
        try:
            tz = pytz.timezone(emp.timezone)
        except Exception:
            tz = DEFAULT_TIMEZONE

        # Дайджесты по задачам — для ВСЕХ активных сотрудников (не зависят от опросов).
        scheduler.add_job(send_employee_morning_digest, "cron",
            hour=md.hour, minute=md.minute, day_of_week=digest_dow, timezone=tz,
            id=f"task_morning_{emp.id}", replace_existing=True, args=[emp.id])
        scheduler.add_job(send_employee_evening_digest, "cron",
            hour=ed.hour, minute=ed.minute, day_of_week=digest_dow, timezone=tz,
            id=f"task_evening_{emp.id}", replace_existing=True, args=[emp.id])

        sch = get_schedule(emp.id)
        # Monthly reports apply to every active employee. Employees without a
        # legacy Schedule row use the same default start-of-day time.
        morning: time = sch.morning_time if sch and sch.morning_time else time(9, 15)
        scheduler.add_job(send_monthly_report_prompt, "cron",
            hour=morning.hour, minute=morning.minute, timezone=tz,
            id=f"monthly_report_{emp.id}", replace_existing=True, args=[emp.id])
        if not sch:
            continue

        weekdays = sch.weekdays or [1, 2, 3, 4, 5]
        dow = ",".join(str(d - 1) for d in weekdays)

        evening: time = sch.evening_time or time(17, 30)
        deadline: time = sch.deadline_time or time(23, 0)
        reminders: list[int] = sch.reminder_intervals or [60, 120]

        scheduler.add_job(send_survey, "cron",
            hour=evening.hour, minute=evening.minute, day_of_week=dow, timezone=tz,
            id=f"survey_{emp.id}", replace_existing=True, args=[emp.id])

        r1 = (datetime.combine(datetime.today(), evening) + timedelta(minutes=reminders[0])).time()
        scheduler.add_job(send_reminder, "cron",
            hour=r1.hour, minute=r1.minute, day_of_week=dow, timezone=tz,
            id=f"reminder1_{emp.id}", replace_existing=True, args=[emp.id, 1])

        r2 = (datetime.combine(datetime.today(), evening) + timedelta(minutes=reminders[1] if len(reminders) > 1 else 120)).time()
        scheduler.add_job(send_reminder, "cron",
            hour=r2.hour, minute=r2.minute, day_of_week=dow, timezone=tz,
            id=f"reminder2_{emp.id}", replace_existing=True, args=[emp.id, 2])

        scheduler.add_job(mark_missed_job, "cron",
            hour=deadline.hour, minute=deadline.minute, day_of_week=dow, timezone=tz,
            id=f"missed_{emp.id}", replace_existing=True, args=[emp.id])


    if manager_settings:
        st: time = manager_settings.summary_time or time(9, 0)
        scheduler.add_job(morning_summary, "cron",
            hour=st.hour, minute=st.minute,
            timezone=DEFAULT_TIMEZONE,
            id="morning_summary", replace_existing=True)

        wt: time = manager_settings.weekly_summary_time or time(17, 0)
        wd = manager_settings.weekly_summary_day or 5
        scheduler.add_job(morning_summary, "cron",
            day_of_week=wd - 1, hour=wt.hour, minute=wt.minute,
            timezone=DEFAULT_TIMEZONE,
            id="weekly_summary", replace_existing=True)

    # Manager task digest uses the application's default timezone.
    md = policy.morning_digest
    from app.services.digest_service import send_manager_task_digest
    scheduler.add_job(send_manager_task_digest, "cron",
        hour=md.hour, minute=md.minute, day_of_week=digest_dow,
        timezone=DEFAULT_TIMEZONE,
        id="task_manager_digest", replace_existing=True)

    # Реконсайл напоминаний + дренаж outbox (догоняют задачи/уведомления из веб/Mini App).
    from app.services.reminder_service import reconcile_task_reminders, drain_notification_outbox

    scheduler.add_job(reconcile_task_reminders, "interval", minutes=2,
        id="reconcile_tasks", replace_existing=True)
    scheduler.add_job(drain_notification_outbox, "interval", minutes=1,
        id="drain_outbox", replace_existing=True)

    # The job checks completion rather than assuming a fixed submission day;
    # it therefore sends as soon as the final previous-month report is approved.
    from app.services.monthly_report_digest_service import try_send_monthly_report_digest
    scheduler.add_job(try_send_monthly_report_digest, "interval", minutes=15,
        id="monthly_report_digest", replace_existing=True)

    _last_schedule_fingerprint = _schedule_fingerprint()
    scheduler.add_job(reconcile_schedule_jobs, "interval", minutes=1,
        id="reconcile_schedules", replace_existing=True)

    log.info("Scheduler rebuilt for %d employees", len(employees))


def rebuild_jobs():
    """Rebuild persistent jobs with a cross-process PostgreSQL lock.

    APScheduler's ``replace_existing`` prevents duplicates within one
    scheduler, but two bot replicas can still race on the same job store.
    PostgreSQL advisory locks make deployment restarts and overlapping
    replicas harmless while retaining the existing SQLite-compatible
    behavior for local/test configurations.
    """
    jobstore = jobstores["default"]
    engine = getattr(jobstore, "engine", None)
    if engine is None or engine.dialect.name != "postgresql":
        _rebuild_jobs_unlocked()
        return

    with engine.connect() as connection:
        acquired = connection.execute(
            text("SELECT pg_try_advisory_lock(:lock_key)"),
            {"lock_key": _REBUILD_LOCK_KEY},
        ).scalar()
        if not acquired:
            log.warning("Another scheduler is rebuilding jobs; skipping this rebuild")
            return
        try:
            _rebuild_jobs_unlocked()
        finally:
            connection.execute(
                text("SELECT pg_advisory_unlock(:lock_key)"),
                {"lock_key": _REBUILD_LOCK_KEY},
            )
            connection.commit()


async def send_survey(employee_id: int):
    from app.models.models import Employee
    from app.bot.db import create_session, get_session
    from app.bot.work_report_handlers import send_daily_prompts
    from app.services import work_report_service

    bot = _make_bot()
    try:
        with get_session() as s:
            emp = s.get(Employee, employee_id)
            if not emp or not emp.is_active:
                return
            telegram_id = emp.telegram_id
            timezone_name = emp.timezone
        create_session(employee_id)
        local_day = _local_today(timezone_name)
        report = work_report_service.get_or_create_report(employee_id, "daily", local_day)
        # Keep the questionnaire, raw-text report, and work-time questions as
        # separate messages, in the same order used by /test_reports.
        await send_daily_prompts(
            bot,
            report,
            telegram_chat_id=telegram_id,
            local_day=local_day,
        )
    finally:
        await bot.session.close()


async def send_reminder(employee_id: int, num: int):
    from datetime import date as d
    from sqlalchemy import select
    from app.models.models import Employee, SurveySession
    from app.bot.db import get_session
    from app.services import work_report_service

    bot = _make_bot()
    try:
        with get_session() as s:
            emp = s.get(Employee, employee_id)
            if not emp:
                return
            sess = s.execute(
                select(SurveySession).where(
                    SurveySession.employee_id == employee_id,
                    SurveySession.date == d.today(),
                    SurveySession.status == "pending",
                )
            ).scalar_one_or_none()
            telegram_id = emp.telegram_id
            timezone_name = emp.timezone
        report_complete = work_report_service.report_is_approved(employee_id, "daily", _local_today(timezone_name))
        if sess or not report_complete:
            await bot.send_message(telegram_id, f"⚠️ Сануулга #{num}: чек-ин болон өдрийн тайлангаа бөглөхөө бүү мартаарай! /today")
    finally:
        await bot.session.close()


async def mark_missed_job(employee_id: int):
    from app.bot.db import mark_session_missed, get_manager_settings, get_session
    from app.models.models import Employee
    from app.services.manager_recipients import manager_telegram_ids

    mark_session_missed(employee_id)
    ms = get_manager_settings()
    recipients = manager_telegram_ids(ms)
    if not ms or not ms.alerts_enabled or not recipients:
        return

    bot = _make_bot()
    try:
        with get_session() as s:
            emp = s.get(Employee, employee_id)
            emp_name = emp.name if emp else None
        if emp_name:
            for recipient in recipients:
                await bot.send_message(recipient, f"🚨 {emp_name} өнөөдөр чек-ин бөглөөгүй байна.")
    finally:
        await bot.session.close()


def _local_today(timezone_name: str | None):
    try:
        zone = pytz.timezone(timezone_name or "Asia/Ulaanbaatar")
    except Exception:
        zone = DEFAULT_TIMEZONE
    return datetime.now(zone).date()


async def send_monthly_report_prompt(employee_id: int):
    """Prompt on each of a month's last three local calendar days until approved."""
    from app.bot.db import get_session
    from app.bot.work_report_handlers import send_report_prompt
    from app.models.models import Employee
    from app.services import work_report_service

    bot = _make_bot()
    try:
        with get_session() as s:
            emp = s.get(Employee, employee_id)
            if not emp or not emp.is_active:
                return
            telegram_id = emp.telegram_id
            timezone_name = emp.timezone
        local_day = _local_today(timezone_name)
        if not work_report_service.is_last_three_days(local_day):
            return
        if work_report_service.report_is_approved(employee_id, "monthly", local_day):
            return
        report = work_report_service.get_or_create_report(employee_id, "monthly", local_day)
        await send_report_prompt(
            bot,
            report,
            telegram_chat_id=telegram_id,
            prompt_type="monthly_report",
            local_day=local_day,
        )
    finally:
        await bot.session.close()


def _schedule_fingerprint() -> str:
    """Hash only the values that determine employee-specific scheduler jobs."""
    from app.bot.db import get_all_active_employees, get_schedule

    values: list[str] = []
    for emp in get_all_active_employees():
        sch = get_schedule(emp.id)
        values.append(repr((
            emp.id, emp.timezone, emp.is_active,
            sch.evening_time if sch else None,
            sch.morning_time if sch else None,
            tuple(sch.weekdays or []) if sch else (),
            sch.deadline_time if sch else None,
            tuple(sch.reminder_intervals or []) if sch else (),
        )))
    return sha256("|".join(values).encode()).hexdigest()


async def reconcile_schedule_jobs():
    """Apply admin schedule changes without requiring a bot restart."""
    global _last_schedule_fingerprint
    current = _schedule_fingerprint()
    if current != _last_schedule_fingerprint:
        log.info("Schedule configuration changed; rebuilding jobs")
        rebuild_jobs()


async def morning_summary():
    from app.bot.db import get_manager_settings, get_yesterday_summary
    from app.services.manager_recipients import manager_telegram_ids

    ms = get_manager_settings()
    recipients = manager_telegram_ids(ms)
    if not ms or not recipients:
        return

    data = get_yesterday_summary()
    lines = [f"📊 <b>{data['date']}-ны хураангуй</b>\n"]
    for q_text, val in data["totals"].items():
        lines.append(f"• {q_text[:40]}: <b>{val}</b>")
    if data["missed"]:
        lines.append(f"\n⚠️ Бөглөөгүй: {', '.join(data['missed'])}")

    bot = _make_bot()
    try:
        for recipient in recipients:
            await bot.send_message(recipient, "\n".join(lines), parse_mode="HTML")
    finally:
        await bot.session.close()
