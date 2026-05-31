"""Планирование напоминаний по задачам + эскалация просрочки (APScheduler)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.services import task_service

log = logging.getLogger(__name__)

ESCALATION_DELAY_MIN = 15


def _job_prefix(task_id: int) -> str:
    return f"task:{task_id}:"


def cancel_task_jobs(task_id: int) -> None:
    from app.bot.scheduler import scheduler

    prefix = _job_prefix(task_id)
    for job in scheduler.get_jobs():
        if job.id and job.id.startswith(prefix):
            try:
                job.remove()
            except Exception:  # noqa: BLE001
                pass


def schedule_task_reminders(task: dict) -> None:
    """Создаёт date-джобы напоминаний и эскалации для задачи с дедлайном."""
    from app.bot.scheduler import scheduler

    deadline = task.get("deadline_at")
    if not deadline:
        return
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)

    cancel_task_jobs(task["id"])
    now = datetime.now(timezone.utc)

    for minutes_before in task.get("reminder_intervals_min") or []:
        run_at = deadline - timedelta(minutes=minutes_before)
        if run_at <= now:
            continue
        scheduler.add_job(
            send_task_reminder, "date", run_date=run_at,
            args=[task["id"], minutes_before],
            id=f"{_job_prefix(task['id'])}rem:{minutes_before}",
            replace_existing=True,
        )

    scheduler.add_job(
        escalate_overdue, "date",
        run_date=deadline + timedelta(minutes=ESCALATION_DELAY_MIN),
        args=[task["id"]],
        id=f"{_job_prefix(task['id'])}escalate",
        replace_existing=True,
    )


def reconcile_task_reminders() -> None:
    """Догоняет напоминания для активных задач с дедлайном (в т.ч. созданных из веба,
    где APScheduler не запущен). Идемпотентно: пропускает задачи, у которых джобы уже есть."""
    from app.bot.scheduler import scheduler

    for task in task_service.list_active_with_deadline():
        if scheduler.get_job(f"{_job_prefix(task['id'])}escalate"):
            continue
        try:
            schedule_task_reminders(task)
        except Exception:  # noqa: BLE001
            log.exception("reconcile: не удалось запланировать напоминания task=%s", task["id"])


def _manager_tg() -> str | None:
    from app.bot.db import get_manager_settings

    ms = get_manager_settings()
    if ms and ms.telegram_id:
        return str(ms.telegram_id)
    return str(settings.MANAGER_TG_ID) if settings.MANAGER_TG_ID else None


def _fmt_deadline(dt: datetime | None) -> str:
    if not dt:
        return "без срока"
    return dt.astimezone(timezone.utc).strftime("%d.%m %H:%M UTC")


async def send_task_reminder(task_id: int, minutes_before: int) -> None:
    from app.bot.keyboards import task_reminder_kb
    from app.bot.scheduler import _make_bot

    task = task_service.get_task(task_id)
    if not task or task["status"] in ("done", "cancelled"):
        return
    if not task["assignee_tg"]:
        return

    if minutes_before == 0:
        when = "сейчас дедлайн"
    elif minutes_before % 1440 == 0:
        when = f"через {minutes_before // 1440} дн."
    elif minutes_before % 60 == 0:
        when = f"через {minutes_before // 60} ч."
    else:
        when = f"через {minutes_before} мин."

    text = (
        f"⏰ <b>Напоминание о задаче</b>\n\n"
        f"#{task['id']} {task['title']}\n"
        f"Дедлайн: <b>{_fmt_deadline(task['deadline_at'])}</b> ({when})"
    )
    bot = _make_bot()
    try:
        await bot.send_message(task["assignee_tg"], text, reply_markup=task_reminder_kb(task["id"]))
    finally:
        await bot.session.close()


async def escalate_overdue(task_id: int) -> None:
    from app.bot.scheduler import _make_bot

    task = task_service.get_task(task_id)
    if not task or task["status"] in ("done", "cancelled"):
        return

    task_service.set_status(task_id, "overdue")
    bot = _make_bot()
    try:
        if task["assignee_tg"]:
            await bot.send_message(
                task["assignee_tg"],
                f"🔴 Задача просрочена: #{task['id']} {task['title']}\nОтметь /done {task['id']} или перенеси /snooze {task['id']} <время>.",
            )
        mgr = _manager_tg()
        if mgr:
            await bot.send_message(
                mgr,
                f"🚨 Просрочена задача #{task['id']} «{task['title']}»\n"
                f"Исполнитель: {task['assignee_name'] or '—'}\nДедлайн был: {_fmt_deadline(task['deadline_at'])}",
            )
    finally:
        await bot.session.close()
