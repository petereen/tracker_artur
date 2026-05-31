"""APScheduler — джобы для каждого сотрудника."""
import logging
from datetime import datetime, time, timedelta

import pytz
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import settings

log = logging.getLogger(__name__)

jobstores = {"default": SQLAlchemyJobStore(url=settings.SYNC_DATABASE_URL)}
scheduler = AsyncIOScheduler(jobstores=jobstores)


def _make_bot():
    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode
    return Bot(token=settings.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


def rebuild_jobs():
    from app.bot.db import get_all_active_employees, get_manager_settings, get_schedule

    employees = get_all_active_employees()
    manager_settings = get_manager_settings()

    for job in scheduler.get_jobs():
        if any(job.id.startswith(p) for p in ("survey_", "reminder1_", "reminder2_", "missed_")):
            job.remove()

    for emp in employees:
        sch = get_schedule(emp.id)
        if not sch:
            continue
        try:
            tz = pytz.timezone(emp.timezone)
        except Exception:
            tz = pytz.timezone("Europe/Moscow")

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
            id="morning_summary", replace_existing=True)

        wt: time = manager_settings.weekly_summary_time or time(17, 0)
        wd = manager_settings.weekly_summary_day or 5
        scheduler.add_job(morning_summary, "cron",
            day_of_week=wd - 1, hour=wt.hour, minute=wt.minute,
            id="weekly_summary", replace_existing=True)

    # Реконсайл напоминаний по задачам (догоняет задачи, созданные из веб/Mini App,
    # где планировщик не запущен). Идемпотентно.
    from app.services.reminder_service import reconcile_task_reminders

    scheduler.add_job(
        reconcile_task_reminders, "interval", minutes=2,
        id="reconcile_tasks", replace_existing=True,
    )

    log.info("Scheduler rebuilt for %d employees", len(employees))


async def send_survey(employee_id: int):
    from app.models.models import Employee
    from app.bot.db import create_session, get_session

    bot = _make_bot()
    try:
        with get_session() as s:
            emp = s.get(Employee, employee_id)
            if not emp or not emp.is_active:
                return
            telegram_id = emp.telegram_id
        create_session(employee_id)
        await bot.send_message(telegram_id, "⏰ Время для вечернего чек-ина!\nНапиши /today чтобы начать.")
    finally:
        await bot.session.close()


async def send_reminder(employee_id: int, num: int):
    from datetime import date as d
    from sqlalchemy import select
    from app.models.models import Employee, SurveySession
    from app.bot.db import get_session

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
        if sess:
            await bot.send_message(telegram_id, f"⚠️ Напоминание #{num}: не забудь заполнить чек-ин! /today")
    finally:
        await bot.session.close()


async def mark_missed_job(employee_id: int):
    from app.bot.db import mark_session_missed, get_manager_settings, get_session
    from app.models.models import Employee

    mark_session_missed(employee_id)
    ms = get_manager_settings()
    if not ms or not ms.alerts_enabled or not ms.telegram_id:
        return

    bot = _make_bot()
    try:
        with get_session() as s:
            emp = s.get(Employee, employee_id)
            emp_name = emp.name if emp else None
        if emp_name:
            await bot.send_message(ms.telegram_id, f"🚨 {emp_name} не заполнил чек-ин сегодня.")
    finally:
        await bot.session.close()


async def morning_summary():
    from app.bot.db import get_manager_settings, get_yesterday_summary

    ms = get_manager_settings()
    if not ms or not ms.telegram_id:
        return

    data = get_yesterday_summary()
    lines = [f"📊 <b>Сводка за {data['date']}</b>\n"]
    for q_text, val in data["totals"].items():
        lines.append(f"• {q_text[:40]}: <b>{val}</b>")
    if data["missed"]:
        lines.append(f"\n⚠️ Не заполнили: {', '.join(data['missed'])}")

    bot = _make_bot()
    try:
        await bot.send_message(ms.telegram_id, "\n".join(lines), parse_mode="HTML")
    finally:
        await bot.session.close()
