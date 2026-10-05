"""APScheduler — джобы для каждого сотрудника."""
import logging
from contextlib import asynccontextmanager
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


def _employee_language(employee_id: int, primary_language: str | None = None) -> str:
    from app.bot.db import get_session
    from app.core.localization import resolve_language
    from app.core.tenancy import system_scope
    from app.models.models import UserAccount

    with system_scope(), get_session() as db:
        account = db.query(UserAccount).filter(UserAccount.employee_id == employee_id, UserAccount.status == "active").one_or_none()
        return resolve_language(account.locale if account else None, primary_language)


def _telegram_language(telegram_id: str, organization_id: int | None = None) -> str:
    from app.bot.db import get_session
    from app.core.tenancy import system_scope
    from app.models.models import Employee

    with system_scope(), get_session() as db:
        query = db.query(Employee).filter(Employee.telegram_id == str(telegram_id), Employee.is_active.is_(True))
        if organization_id is not None:
            query = query.filter(Employee.organization_id == organization_id)
        employee = query.order_by(Employee.id).first()
        employee_id = employee.id if employee else None
        primary_language = employee.primary_language if employee else None
    return _employee_language(employee_id, primary_language) if employee_id is not None else "mn"


def _birthday_message(language: str) -> str:
    return {
        "en": "🎂 Happy birthday! 🎉 Wishing you success at work, good health, and a year filled with happiness and wonderful moments! 😊",
        "ru": "🎂 Поздравляем с днём рождения! 🎉 Желаем успехов в работе, крепкого здоровья, счастья и всего самого доброго! 😊",
    }.get(language, BIRTHDAY_MESSAGE)


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


def _make_bot(organization_id: int | None = None):
    """A fresh client for the tenant's own (handshaken) bot, or ``None``.

    Tenants without a connected bot get no Telegram messages; ``None`` means
    the primary tenant (platform ``BOT_TOKEN`` fallback)."""
    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode
    from app.bot.db import primary_tenant_id
    from app.services.telegram_bots import registry

    tenant_bot = registry.for_organization_sync(organization_id if organization_id is not None else primary_tenant_id())
    if tenant_bot is None:
        return None
    return Bot(token=tenant_bot.token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


@asynccontextmanager
async def tenant_bot(organization_id: int | None):
    """``async with tenant_bot(org) as bot`` — closes the client afterwards."""
    bot = _make_bot(organization_id)
    try:
        yield bot
    finally:
        if bot is not None:
            await bot.session.close()


def organization_for_telegram_id(telegram_id: str | None) -> int | None:
    """Tenant of a Telegram recipient (worker ids are unique platform-wide)."""
    from sqlalchemy import select
    from app.bot.db import get_session
    from app.core.tenancy import system_scope
    from app.models.models import Employee

    if not telegram_id:
        return None
    with system_scope(), get_session() as s:
        return s.execute(select(Employee.organization_id).where(Employee.telegram_id == str(telegram_id))).scalar_one_or_none()


async def send_telegram(recipient_tg: str | None, text: str, *, organization_id: int | None = None, **kwargs) -> bool:
    """Send through the recipient tenant's bot; ``False`` when it has none."""
    if not recipient_tg or not text:
        return False
    organization_id = organization_id or organization_for_telegram_id(recipient_tg)
    async with tenant_bot(organization_id) as bot:
        if bot is None:
            return False
        await bot.send_message(recipient_tg, text, **kwargs)
        return True


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

    # Digest times follow each worker's tenant settings.
    tenant_policies = {}

    def policy_for(organization_id):
        if organization_id not in tenant_policies:
            tenant_policies[organization_id] = load_policy(get_manager_settings(organization_id))
        return tenant_policies[organization_id]

    missed_job_groups = []
    for emp in employees:
        tenant_policy = policy_for(emp.organization_id)
        md, ed = tenant_policy.morning_digest, tenant_policy.evening_digest
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

        # Periodic (weekly/monthly/quarterly/half-yearly/yearly/custom) and
        # department reports follow the admin report policy. The job runs
        # hourly at the worker's start-of-day minute; each frequency fires in
        # its configured reminder hour (default: the morning check-in hour)
        # while its reminder or submission-grace window is open.
        morning: time = sch.morning_time if sch and sch.morning_time else time(9, 15)
        scheduler.add_job(send_periodic_report_prompts, "cron",
            minute=morning.minute, timezone=tz,
            id=f"monthly_report_{emp.id}", replace_existing=True, args=[emp.id, morning.hour])

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

    from app.services.contract_expiry_reminders import reconcile_contract_expiry_reminders
    scheduler.add_job(reconcile_contract_expiry_reminders, "interval", minutes=30,
        id="contract_expiry_reminders", replace_existing=True)

    from app.services.crm_reminders import reconcile_crm_activity_reminders
    scheduler.add_job(reconcile_crm_activity_reminders, "interval", minutes=15,
        id="crm_activity_reminders", replace_existing=True)

    # Cloudflare custom hostnames waiting for the customer's DNS/certificate.
    from app.services.custom_domains import refresh_pending_domains
    scheduler.add_job(refresh_pending_domains, "interval", minutes=5,
        id="refresh_custom_domains", replace_existing=True)

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
    from app.bot.db import canonical_checkin_complete, create_session, get_manager_settings, get_questions, get_session
    from app.bot.work_report_handlers import send_daily_prompts, send_report_prompt
    from app.services import work_report_service

    with get_session() as s:
        emp = s.get(Employee, employee_id)
        if not emp or not emp.is_active:
            return
        telegram_id = emp.telegram_id
        timezone_name = emp.timezone
        organization_id = emp.organization_id
    from app.services.notification_preferences import delivery_for_employee_sync

    daily_report_reminders_enabled = getattr(get_manager_settings(organization_id), "daily_report_reminders_enabled", True)
    local_day = _local_today(timezone_name)
    report = work_report_service.get_or_create_report(employee_id, "daily", local_day)
    if not daily_report_reminders_enabled or not telegram_id:
        return
    report_delivery = delivery_for_employee_sync(employee_id, "daily_report")
    # The legacy check-in questionnaire is its own (default-off) category.
    checkin_enabled = delivery_for_employee_sync(employee_id, "daily_checkin").telegram
    if not report_delivery.telegram and not checkin_enabled:
        return
    bot = _make_bot(organization_id)
    if bot is None:
        return
    try:
        # The report policy may drop daily reports for this worker; the
        # check-in questionnaire itself is independent of the policy.
        daily_reports = work_report_service.daily_reports_enabled(employee_id) and report_delivery.telegram
        if not checkin_enabled or not get_questions(employee_id):
            if not daily_reports:
                return
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
            if not daily_reports:
                return
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
    from sqlalchemy import select
    from app.models.models import Employee, SurveySession
    from app.bot.db import canonical_checkin_complete, get_manager_settings, get_session
    from app.services import work_report_service

    with get_session() as s:
        emp = s.get(Employee, employee_id)
        organization_id = emp.organization_id if emp else None
        primary_language = emp.primary_language if emp else None
    language = _employee_language(employee_id, primary_language) if emp else "mn"
    bot = _make_bot(organization_id) if emp and emp.telegram_id else None
    if bot is None:
        return
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
        daily_report_reminders_enabled = getattr(get_manager_settings(organization_id), "daily_report_reminders_enabled", True)
        if not daily_report_reminders_enabled:
            return
        from app.services.notification_preferences import delivery_for_employee_sync

        if not delivery_for_employee_sync(employee_id, "daily_reminder").telegram:
            return
        checkin_enabled = delivery_for_employee_sync(employee_id, "daily_checkin").telegram
        checkin_complete = not checkin_enabled or canonical_checkin_complete(employee_id, local_day) or sess is None
        report_complete = (
            not work_report_service.daily_reports_enabled(employee_id)
            or not work_report_service.report_needs_submission(employee_id, "daily", local_day)
        )
        missing = []
        if not checkin_complete:
            missing.append("чек-ин (/today)")
        if not report_complete:
            missing.append("өдрийн тайлан")
        if missing:
            missing_labels = {
                "en": {"чек-ин (/today)": "check-in (/today)", "өдрийн тайлан": "daily report"},
                "ru": {"чек-ин (/today)": "опрос (/today)", "өдрийн тайлан": "ежедневный отчёт"},
            }.get(language, {})
            items = [missing_labels.get(item, item) for item in missing]
            if language == "en":
                reminder_text = f"⚠️ Reminder #{num}: Please remember to complete your " + " and ".join(items) + "."
            elif language == "ru":
                reminder_text = f"⚠️ Напоминание №{num}: Заполните " + " и ".join(items) + "."
            else:
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

    with get_session() as s:
        emp = s.get(Employee, employee_id)
        if not emp or not emp.is_active or not emp.telegram_id:
            return
        telegram_id = emp.telegram_id
        timezone_name = emp.timezone
        organization_id = emp.organization_id
        primary_language = emp.primary_language
        schedule = s.query(Schedule).filter(Schedule.employee_id == employee_id).one_or_none()
    from app.services.notification_preferences import delivery_for_employee_sync

    if not delivery_for_employee_sync(employee_id, "worktime_reminder").telegram:
        return
    bot = _make_bot(organization_id)
    if bot is None:
        return
    try:

        local_day = _local_today(timezone_name)
        active_weekdays = set(_schedule_weekdays(schedule))
        if local_day.isoweekday() not in active_weekdays:
            return
        state = work_report_service.work_time_status(employee_id, local_day)
        language = _employee_language(employee_id, primary_language)
        if reminder_type == "start":
            if state["started"]:
                return
            message = ({
                "en": "🕛 <b>Remember to track your work time</b>\n\nIf you have started work today, record your start time:\n🏢 Office: <b>/daystart</b>\n🏠 Remote: <b>/remotestart</b>",
                "ru": "🕛 <b>Не забудьте учесть рабочее время</b>\n\nЕсли вы уже начали работу сегодня, отметьте время начала:\n🏢 Офис: <b>/daystart</b>\n🏠 Удалённо: <b>/remotestart</b>",
            }.get(language) or (
                "🕛 <b>Ажлын цагаа бүртгээрэй</b>\n\n"
                "Өнөөдөр ажлаа эхлүүлсэн бол эхэлсэн цагаа бүртгэнэ үү:\n"
                "🏢 Оффис: <b>/daystart</b>\n"
                "🏠 Remote: <b>/remotestart</b>"
            ))
        else:
            if not state["active"]:
                return
            end_command = "/dayend" if state["mode"] == "in_person" else "/remoteend"
            mode_label = ("office" if state["mode"] == "in_person" else "remote") if language == "en" else ("офисный" if state["mode"] == "in_person" else "удалённый") if language == "ru" else ("оффисын" if state["mode"] == "in_person" else "remote")
            message = ({
                "en": f"🌙 <b>Your work session is still open</b>\n\nYour {mode_label} work session is still open. Use <b>{end_command}</b> when you finish.",
                "ru": f"🌙 <b>Рабочая сессия не завершена</b>\n\nВаша {mode_label} рабочая сессия всё ещё активна. Завершите её командой <b>{end_command}</b>.",
            }.get(language) or (
                "🌙 <b>Ажлын цаг нээлттэй байна</b>\n\n"
                f"Таны {mode_label} ажлын цаг одоогоор нээлттэй байна. "
                f"Дуусгахдаа <b>{end_command}</b> командыг ашиглана уу."
            ))
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

    missing_by_tenant: dict[int, list[str]] = {}
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
        missing_by_tenant.setdefault(employee.organization_id, []).append(employee.name)

    from app.bot.db import is_primary_tenant

    # One alert per tenant, to that tenant's managers through its own bot.
    from app.services.notification_preferences import tenant_category_enabled_sync

    for organization_id, missing_names in missing_by_tenant.items():
        if not tenant_category_enabled_sync(organization_id, "checkin"):
            continue
        ms = get_manager_settings(organization_id)
        recipients = manager_telegram_ids(ms, primary=is_primary_tenant(organization_id))
        if not ms or not ms.alerts_enabled or not recipients:
            continue
        async with tenant_bot(organization_id) as bot:
            if bot is None:
                continue
            for recipient in recipients:
                language = _telegram_language(recipient, organization_id)
                heading = {"en": "Employees who have not completed today's check-in: ", "ru": "Сотрудники, не прошедшие сегодняшний опрос: "}.get(language, "Өнөөдөр чек-ин бөглөөгүй ажилтан: ")
                message = heading + ", ".join(missing_names)
                await bot.send_message(recipient, message)


def _local_now(timezone_name: str | None) -> datetime:
    try:
        zone = pytz.timezone(timezone_name or "Asia/Ulaanbaatar")
    except Exception:
        zone = DEFAULT_TIMEZONE
    return datetime.now(zone)


def _local_today(timezone_name: str | None):
    return _local_now(timezone_name).date()


def due_report_periods(scope: dict, local_day: date, local_hour: int | None = None, default_hour: int | None = None) -> list[tuple[object, int | None]]:
    """Report periods to remind about now.

    Returns ``(period, department_id)`` pairs: personal periods from the
    worker's frequencies (daily stays with the evening check-in flow) and
    department periods for departments the worker heads. A period is due in
    its end-of-period reminder window and, when the policy grants submission
    grace days, the previous period until its deadline. With ``local_hour``
    only frequencies whose reminder hour (``default_hour`` when unset) is now
    are returned.
    """
    from app.services.report_policy import open_report_periods, settings_for

    policy = scope["policy"]
    due: list[tuple[object, int | None]] = []
    candidates = [(frequency, None) for frequency in scope["frequencies"] if frequency != "daily"]
    for department_id, frequencies in scope["led_departments"].items():
        candidates.extend((frequency, department_id) for frequency in frequencies)
    for frequency, department_id in candidates:
        if local_hour is not None:
            hour = settings_for(policy, frequency).get("reminder_hour")
            if (default_hour if hour is None else hour) != local_hour:
                continue
        for period, _phase in open_report_periods(policy, frequency, local_day):
            due.append((period, department_id))
    return due


async def send_periodic_report_prompts(employee_id: int, default_hour: int | None = None):
    """Prompt for every enabled report period in its end-of-period window.

    Each prompt is sent at most once per report and day (``reserve_prompt``)
    and stops as soon as the report is submitted or approved.
    """
    from app.bot.db import get_session
    from app.bot.work_report_handlers import send_report_prompt
    from app.models.models import Department, Employee
    from app.services import work_report_service
    from app.services.notification_preferences import delivery_for_employee_sync
    from app.services.user_notifications import mirror_existing_telegram_notification

    with get_session() as s:
        emp = s.get(Employee, employee_id)
        if not emp or not emp.is_active:
            return
        telegram_id = emp.telegram_id
        timezone_name = emp.timezone
        organization_id = emp.organization_id
        primary_language = emp.primary_language
    local_now = _local_now(timezone_name)
    local_day = local_now.date()
    scope = work_report_service.employee_report_scope(employee_id)
    # Jobs persisted before the hourly schedule pass no hour: run as before.
    due = due_report_periods(scope, local_day, local_now.hour if default_hour is not None else None, default_hour)
    if not due:
        return
    bot = _make_bot(organization_id) if telegram_id else None
    try:
        for period, department_id in due:
            if not work_report_service.period_report_needs_submission(employee_id, period, department_id=department_id):
                continue
            if period.report_type == "monthly" and department_id is None:
                # The policy period (company month may not start on the 1st).
                report = work_report_service.get_or_create_period_report(employee_id, period)
                prompt_type = "monthly_report"
            else:
                report = work_report_service.get_or_create_period_report(employee_id, period, department_id=department_id)
                prompt_type = "periodic_report"
            department_name = None
            if department_id is not None:
                with get_session() as s:
                    department = s.get(Department, department_id)
                    department_name = department.name if department else None
            telegram_status = "unavailable"
            kind = "monthly_report" if prompt_type == "monthly_report" else "periodic_report"
            if bot is not None and delivery_for_employee_sync(employee_id, kind).telegram:
                try:
                    await send_report_prompt(bot, report, telegram_chat_id=telegram_id, prompt_type=prompt_type, local_day=local_day)
                    telegram_status = "sent"
                except Exception:  # noqa: BLE001 - one failed prompt must not block the others
                    telegram_status = "failed"
                    log.exception("Periodic report prompt failed employee=%s report=%s", employee_id, report.id)
            title = f"{department_name} · {period.label}" if department_name else period.label
            mirror_existing_telegram_notification(
                employee_id=employee_id,
                kind="monthly_report" if prompt_type == "monthly_report" else "periodic_report",
                title=title,
                body=f"{period.start.isoformat()} – {period.end.isoformat()} хугацааны тайлангаа илгээнэ үү.",
                target_url=f"/reports?report={report.id}",
                dedup_key=(
                    f"monthly-report:{employee_id}:{period.start.isoformat()}" if prompt_type == "monthly_report"
                    else f"periodic-report:{report.id}:{local_day.isoformat()}"
                ),
                telegram_status=telegram_status,
            )
    finally:
        if bot is not None:
            await bot.session.close()


# Persisted APScheduler jobs created before the report policy reference this name.
send_monthly_report_prompt = send_periodic_report_prompts


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
        organization_id = emp.organization_id
        primary_language = emp.primary_language

    local_day = _local_today(timezone_name)
    if not _birthday_occurs_on_day(birthday, local_day):
        return

    from app.services.notification_preferences import delivery_for_employee_sync

    telegram_status = "unavailable"
    bot = _make_bot(organization_id) if telegram_id and delivery_for_employee_sync(employee_id, "birthday").telegram else None
    if bot is not None:
        try:
            await bot.send_message(str(telegram_id), _birthday_message(_employee_language(employee_id, primary_language)))
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

    from app.bot.db import primary_tenant_id
    from app.services.notification_preferences import tenant_category_enabled_sync

    # Yesterday's check-in answers: part of the legacy check-in category.
    if not tenant_category_enabled_sync(primary_tenant_id(), "checkin"):
        return
    ms = get_manager_settings()
    recipients = manager_telegram_ids(ms)
    if not ms or not recipients:
        return

    data = get_yesterday_summary()
    # Check-in summaries are a primary-tenant (legacy) feature.
    async with tenant_bot(None) as bot:
        if bot is None:
            return
        for recipient in recipients:
            language = _telegram_language(recipient)
            heading = {"en": "summary", "ru": "сводка"}.get(language, "хураангуй")
            lines = [f"📊 <b>{data['date']} {heading}</b>\n"]
            for q_text, val in data["totals"].items():
                lines.append(f"• {q_text[:40]}: <b>{val}</b>")
            if data["missed"]:
                missing_label = {"en": "Not completed", "ru": "Не заполнено"}.get(language, "Бөглөөгүй")
                lines.append(f"\n⚠️ {missing_label}: {', '.join(data['missed'])}")
            await bot.send_message(recipient, "\n".join(lines), parse_mode="HTML")
