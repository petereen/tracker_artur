"""APScheduler — джобы для каждого сотрудника."""
import logging
from datetime import date, datetime, time, timedelta
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
_DEFAULT_SCHEDULE_WEEKDAYS = (1, 2, 3, 4, 5)
BIRTHDAY_MESSAGE = "🎂 Танд төрсөн өдрийн мэнд хүргэе! 🎉 Ажлын амжилтаар дүүрэн, эрүүл энх, гэр бүл нь аз жаргалаар элбэг байж, сайн сайхан бүхнийг хүсье! 😊"


def _schedule_weekdays(schedule) -> tuple[int, ...]:
    """Return configured ISO weekdays, defaulting to the normal workweek."""
    return tuple((schedule.weekdays if schedule else None) or _DEFAULT_SCHEDULE_WEEKDAYS)


def _birthday_schedule_days(birthday: date) -> tuple[int, ...]:
    """Return cron days for a birthday, including leap-day fallback."""
    return (28, 29) if (birthday.month, birthday.day) == (2, 29) else (birthday.day,)


def _work_time_reminder_dedup_key(employee_id: int, local_day, reminder_type: str, reminder_hour: int | None = None) -> str:
    """Keep separate mirror notifications for the two end-of-day prompts."""
    return f"worktime-reminder:{employee_id}:{local_day}:{reminder_type}:{reminder_hour or 'default'}"


def _missed_job_groups(employees_and_schedules):
    """Group missed-check-in jobs that share a local deadline.

    A group is deliberately scheduled as one job so managers receive one
    consolidated alert instead of one alert per employee.
    """
    groups = {}
    for employee, schedule, tz, deadline, weekdays in employees_and_schedules:
        key = (tz.zone, deadline.hour, deadline.minute, tuple(weekdays))
        groups.setdefault(key, {"timezone": tz, "deadline": deadline, "weekdays": tuple(weekdays), "employee_ids": []})["employee_ids"].append(employee.id)
    return groups.values()


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

    global _last_schedule_fingerprint
    for job in scheduler.get_jobs():
        if any(job.id.startswith(p) for p in
               ("survey_", "reminder1_", "reminder2_", "missed_", "monthly_report_", "birthday_", "task_morning_", "task_evening_", "work_time_")):
            job.remove()

    from app.services.digest_service import send_employee_morning_digest, send_employee_evening_digest
    md, ed = policy.morning_digest, policy.evening_digest

    missed_job_groups = []
    for emp in employees:
        try:
            tz = pytz.timezone(emp.timezone)
        except Exception:
            tz = DEFAULT_TIMEZONE

        sch = get_schedule(emp.id)
        employee_weekdays = _schedule_weekdays(sch)
        employee_dow = ",".join(str(d - 1) for d in employee_weekdays)

        # Evaluate task digests every calendar day. The digest service skips
        # empty non-workdays but still sends when a task is due that day.
        scheduler.add_job(send_employee_morning_digest, "cron",
            hour=md.hour, minute=md.minute, timezone=tz,
            id=f"task_morning_{emp.id}", replace_existing=True, args=[emp.id])
        scheduler.add_job(send_employee_evening_digest, "cron",
            hour=ed.hour, minute=ed.minute, timezone=tz,
            id=f"task_evening_{emp.id}", replace_existing=True, args=[emp.id])

        # Monthly reports apply to every active employee. Employees without a
        # legacy Schedule row use the same default start-of-day time.
        morning: time = sch.morning_time if sch and sch.morning_time else time(9, 15)
        scheduler.add_job(send_monthly_report_prompt, "cron",
            hour=morning.hour, minute=morning.minute, timezone=tz,
            id=f"monthly_report_{emp.id}", replace_existing=True, args=[emp.id])

        if emp.birthday:
            # APScheduler omits an invalid day-of-month in non-leap years. A
            # second job lets February 29 birthdays use February 29 in leap
            # years while the birthday function maps them to February 28 in
            # other years, matching the calendar's recurring birthday rule.
            for birthday_day in _birthday_schedule_days(emp.birthday):
                scheduler.add_job(send_birthday_greeting, "cron",
                    month=emp.birthday.month, day=birthday_day, hour=9, minute=0,
                    timezone=tz, id=f"birthday_{emp.id}_{birthday_day}",
                    replace_existing=True, args=[emp.id])

        weekdays = employee_weekdays
        dow = employee_dow

        # Work-time reminders are fixed local-time guardrails and apply even
        # when an employee has no legacy Schedule row.
        scheduler.add_job(send_work_time_reminder, "cron",
            hour=12, minute=0, day_of_week=dow, timezone=tz,
            id=f"work_time_start_{emp.id}", replace_existing=True,
            args=[emp.id, "start"])
        for hour in (19, 23):
            scheduler.add_job(send_work_time_reminder, "cron",
                hour=hour, minute=0, day_of_week=dow, timezone=tz,
                id=f"work_time_end_{hour}_{emp.id}", replace_existing=True,
                args=[emp.id, "end", hour])

        evening: time = (sch.evening_time if sch else None) or time(17, 30)
        deadline: time = (sch.deadline_time if sch else None) or time(23, 0)
        reminders: list[int] = (sch.reminder_intervals if sch else None) or [60, 120]

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

        missed_job_groups.append((emp, sch, tz, deadline, weekdays))

    for group in _missed_job_groups(missed_job_groups):
        employee_ids = sorted(group["employee_ids"])
        group_key = sha256(
            f"{group['timezone'].zone}:{group['deadline'].isoformat()}:{group['weekdays']}:{employee_ids}".encode()
        ).hexdigest()[:16]
        scheduler.add_job(mark_missed_job, "cron",
            hour=group["deadline"].hour, minute=group["deadline"].minute,
            day_of_week=",".join(str(day - 1) for day in group["weekdays"]), timezone=group["timezone"],
            id=f"missed_{group_key}", replace_existing=True, args=[employee_ids])


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

    # Manager task digest uses the application's default timezone. It runs
    # daily so a task due on a configured non-workday can be an exception;
    # the digest service suppresses empty non-workday messages.
    md = policy.morning_digest
    from app.services.digest_service import send_manager_task_digest
    scheduler.add_job(send_manager_task_digest, "cron",
        hour=md.hour, minute=md.minute,
        timezone=DEFAULT_TIMEZONE,
        id="task_manager_digest", replace_existing=True)

    # Реконсайл напоминаний + дренаж outbox (догоняют задачи/уведомления из веб/Mini App).
    from app.services.reminder_service import reconcile_task_reminders, drain_notification_outbox

    scheduler.add_job(reconcile_task_reminders, "interval", minutes=2,
        id="reconcile_tasks", replace_existing=True)
    scheduler.add_job(drain_notification_outbox, "interval", minutes=1,
        id="drain_outbox", replace_existing=True)

    from app.services.collaboration_reminders import reconcile_calendar_reminders, reconcile_project_deadlines
    scheduler.add_job(reconcile_calendar_reminders, "interval", minutes=1,
        id="reconcile_calendar_reminders", replace_existing=True)
    scheduler.add_job(reconcile_project_deadlines, "interval", minutes=15,
        id="reconcile_project_deadlines", replace_existing=True)

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
    from app.bot.db import canonical_checkin_complete, create_session, get_questions, get_session
    from app.bot.work_report_handlers import send_daily_prompts, send_report_prompt
    from app.services import work_report_service

    bot = _make_bot()
    try:
        with get_session() as s:
            emp = s.get(Employee, employee_id)
            if not emp or not emp.is_active:
                return
            telegram_id = emp.telegram_id
            timezone_name = emp.timezone
            daily_report_reminders_enabled = getattr(get_manager_settings(), "daily_report_reminders_enabled", True)
        local_day = _local_today(timezone_name)
        report = work_report_service.get_or_create_report(employee_id, "daily", local_day)
        if not daily_report_reminders_enabled:
            return
        if not get_questions(employee_id):
            await send_report_prompt(
                bot, report, telegram_chat_id=telegram_id,
                prompt_type="daily_report", local_day=local_day,
            )
            from app.services.user_notifications import mirror_existing_telegram_notification
            mirror_existing_telegram_notification(
                employee_id=employee_id, kind="daily_report", title="Өдрийн тайлан",
                body="Өнөөдрийн ажлын тайлангаа илгээнэ үү.", target_url="/reports",
                dedup_key=f"daily-report:{employee_id}:{local_day}",
            )
            return
        if canonical_checkin_complete(employee_id, local_day):
            await send_report_prompt(
                bot, report, telegram_chat_id=telegram_id,
                prompt_type="daily_report", local_day=local_day,
            )
            from app.services.user_notifications import mirror_existing_telegram_notification
            mirror_existing_telegram_notification(
                employee_id=employee_id, kind="daily_report", title="Өдрийн тайлан",
                body="Өнөөдрийн ажлын тайлангаа илгээнэ үү.", target_url="/reports",
                dedup_key=f"daily-report:{employee_id}:{local_day}",
            )
            return
        session = create_session(employee_id, local_day=local_day)
        if session.status == "completed":
            return
        # Keep the questionnaire, raw-text report, and work-time questions as
        # separate messages, in the same order used by /test_reports.
        await send_daily_prompts(
            bot,
            report,
            telegram_chat_id=telegram_id,
            local_day=local_day,
        )
        from app.services.user_notifications import mirror_existing_telegram_notification
        mirror_existing_telegram_notification(
            employee_id=employee_id, kind="daily_checkin", title="Өдрийн check-in",
            body="Өнөөдрийн check-in болон өдрийн тайлангаа бөглөнө үү.",
            target_url="/", dedup_key=f"daily-checkin:{employee_id}:{local_day}",
        )
    finally:
        await bot.session.close()


async def send_reminder(employee_id: int, num: int):
    from datetime import date as d
    from sqlalchemy import select
    from app.models.models import Employee, SurveySession
    from app.bot.db import canonical_checkin_complete, get_session
    from app.services import work_report_service

    bot = _make_bot()
    try:
        with get_session() as s:
            emp = s.get(Employee, employee_id)
            if not emp:
                return
            local_day = _local_today(emp.timezone)
            sess = s.execute(
                select(SurveySession).where(
                    SurveySession.employee_id == employee_id,
                    SurveySession.date == local_day,
                    SurveySession.type == "evening",
                    SurveySession.status == "pending",
                )
            ).scalars().first()
            telegram_id = emp.telegram_id
            timezone_name = emp.timezone
        checkin_complete = canonical_checkin_complete(employee_id, local_day) or sess is None
        report_complete = not work_report_service.report_needs_submission(employee_id, "daily", local_day)
        missing = []
        if not checkin_complete:
            missing.append("чек-ин (/today)")
        if not report_complete:
            missing.append("өдрийн тайлан")
        if missing:
            reminder_text = f"⚠️ Сануулга #{num}: " + " болон ".join(missing) + "-аа бөглөхөө мартав аа!"
            await bot.send_message(telegram_id, reminder_text)
            from app.services.user_notifications import mirror_existing_telegram_notification
            mirror_existing_telegram_notification(
                employee_id=employee_id, kind="daily_reminder", title="Өдрийн сануулга",
                body=" болон ".join(missing) + "-аа бөглөнө үү.", target_url="/",
                dedup_key=f"daily-reminder:{employee_id}:{local_day}:{num}",
            )
    finally:
        await bot.session.close()


async def send_work_time_reminder(employee_id: int, reminder_type: str, reminder_hour: int | None = None):
    """Nudge a worker only when today's work interval needs attention."""
    from app.bot.db import get_session
    from app.models.models import Employee, Schedule
    from app.services import work_report_service

    bot = _make_bot()
    try:
        with get_session() as s:
            emp = s.get(Employee, employee_id)
            if not emp or not emp.is_active or not emp.telegram_id:
                return
            telegram_id = emp.telegram_id
            timezone_name = emp.timezone
            schedule = s.query(Schedule).filter(Schedule.employee_id == employee_id).one_or_none()

        local_day = _local_today(timezone_name)
        active_weekdays = set(_schedule_weekdays(schedule))
        if local_day.isoweekday() not in active_weekdays:
            return
        state = work_report_service.work_time_status(employee_id, local_day)
        if reminder_type == "start":
            if state["started"]:
                return
            message = (
                "🕛 Цагаа бүртгэхээ мартсан юм биш биз? 🙂\n\n"
                "Өнөөдрийн ажлаа эхлүүлсэн бол эхэлсэн цагаа бүртгэнэ үү:\n"
                "🏢 Оффис: <b>/daystart</b>\n"
                "🏠 Remote: <b>/remotestart</b>"
            )
        else:
            if not state["active"]:
                return
            end_command = "/dayend" if state["mode"] == "in_person" else "/remoteend"
            mode_label = "оффисын" if state["mode"] == "in_person" else "remote"
            message = (
                "🌙 Ажлаа дуусгахаа мартсан юм биш биз? 🙂\n\n"
                f"Таны {mode_label} ажлын цаг одоогоор нээлттэй байна. "
                f"Дуусгахдаа <b>{end_command}</b> командыг ашиглана уу."
            )
        await bot.send_message(telegram_id, message, parse_mode="HTML")
        from app.services.user_notifications import mirror_existing_telegram_notification
        mirror_existing_telegram_notification(
            employee_id=employee_id, kind="worktime_reminder", title="Ажлын цагийн сануулга",
            body="Ажлын цагаа эхлүүлэх эсвэл дуусгахаа мартсан эсэхээ шалгана уу.", target_url="/",
            dedup_key=_work_time_reminder_dedup_key(employee_id, local_day, reminder_type, reminder_hour),
        )
    finally:
        await bot.session.close()


async def mark_missed_job(employee_ids: list[int]):
    """Mark and report missed check-ins as a single manager notification."""
    from sqlalchemy import select
    from app.bot.db import canonical_checkin_complete, get_manager_settings, get_questions, get_session, mark_session_missed
    from app.models.models import Employee, SurveySession
    from app.services.manager_recipients import manager_telegram_ids

    missing_names = []
    with get_session() as s:
        employees = [s.get(Employee, employee_id) for employee_id in employee_ids]

    for employee in employees:
        if not employee or not employee.is_active or not get_questions(employee.id):
            continue
        local_day = _local_today(employee.timezone)
        if canonical_checkin_complete(employee.id, local_day):
            continue
        with get_session() as s:
            completed_session = s.execute(
                select(SurveySession.id).where(
                    SurveySession.employee_id == employee.id,
                    SurveySession.date == local_day,
                    SurveySession.status == "completed",
                )
            ).scalar_one_or_none()
        if completed_session:
            continue
        mark_session_missed(employee.id)
        missing_names.append(employee.name)

    if not missing_names:
        return

    ms = get_manager_settings()
    recipients = manager_telegram_ids(ms)
    if not ms or not ms.alerts_enabled or not recipients:
        return

    bot = _make_bot()
    try:
        message = "Өнөөдөр чек-ин бөглөөгүй ажилтан: " + ", ".join(missing_names)
        for recipient in recipients:
            await bot.send_message(recipient, message)
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
        from app.services.user_notifications import mirror_existing_telegram_notification
        mirror_existing_telegram_notification(
            employee_id=employee_id, kind="monthly_report", title="Сарын тайлан",
            body="Энэ сарын тайлангаа илгээнэ үү.", target_url="/reports",
            dedup_key=f"monthly-report:{employee_id}:{local_day.strftime('%Y-%m')}",
        )
    finally:
        await bot.session.close()


def _birthday_occurs_on_day(birthday: date, local_day: date) -> bool:
    """Match the calendar's February 29 fallback behavior."""
    try:
        return birthday.replace(year=local_day.year) == local_day
    except ValueError:
        return local_day.month == 2 and local_day.day == 28


async def send_birthday_greeting(employee_id: int):
    """Send the worker's birthday greeting at 09:00 in their local timezone."""
    from app.bot.db import get_session
    from app.models.models import Employee

    with get_session() as s:
        emp = s.get(Employee, employee_id)
        if not emp or not emp.is_active or not emp.birthday:
            return
        birthday = emp.birthday
        telegram_id = emp.telegram_id
        timezone_name = emp.timezone
        employee_name = emp.name

    local_day = _local_today(timezone_name)
    if not _birthday_occurs_on_day(birthday, local_day):
        return

    telegram_status = "unavailable"
    if telegram_id:
        bot = _make_bot()
        try:
            await bot.send_message(str(telegram_id), BIRTHDAY_MESSAGE)
            telegram_status = "sent"
        except Exception:  # noqa: BLE001
            telegram_status = "failed"
            log.exception("Birthday greeting Telegram delivery failed employee=%s", employee_id)
        finally:
            await bot.session.close()

    from app.services.user_notifications import mirror_existing_telegram_notification
    mirror_existing_telegram_notification(
        employee_id=employee_id,
        kind="birthday",
        title="Төрсөн өдрийн мэндчилгээ",
        body=BIRTHDAY_MESSAGE,
        target_url="/profile",
        dedup_key=f"birthday:{employee_id}:{local_day.year}",
        telegram_status=telegram_status,
    )
    log.info("Birthday greeting delivered employee=%s name=%s day=%s", employee_id, employee_name, local_day)


def _schedule_fingerprint() -> str:
    """Hash only the values that determine employee-specific scheduler jobs."""
    from app.bot.db import get_all_active_employees, get_schedule

    values: list[str] = []
    for emp in get_all_active_employees():
        sch = get_schedule(emp.id)
        values.append(repr((
            emp.id, emp.timezone, emp.is_active,
            emp.birthday,
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
