"""Планирование напоминаний по задачам + эскалация просрочки (APScheduler)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.services import task_service
from app.services.notification_policy import load_policy, next_allowed

log = logging.getLogger(__name__)

ESCALATION_DELAY_MIN = 15
DEFAULT_TZ = "Asia/Ulaanbaatar"


def _job_prefix(task_id: int) -> str:
    return f"task:{task_id}:"


def _policy():
    from app.bot.db import get_manager_settings
    return load_policy(get_manager_settings())


def _task_tz(task: dict) -> str:
    return task.get("assignee_tz") or DEFAULT_TZ


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
    policy = _policy()
    tz = _task_tz(task)

    scheduled_at: set[int] = set()  # дедуп схлопнувшихся в тихие часы напоминаний
    for minutes_before in task.get("reminder_intervals_min") or []:
        run_at = next_allowed(deadline - timedelta(minutes=minutes_before), tz, policy)
        if run_at <= now:
            continue
        key = int(run_at.timestamp() // 60)
        if key in scheduled_at:
            continue
        scheduled_at.add(key)
        scheduler.add_job(
            send_task_reminder, "date", run_date=run_at,
            args=[task["id"], minutes_before],
            id=f"{_job_prefix(task['id'])}rem:{minutes_before}",
            replace_existing=True,
        )

    # Эскалация (маркер просрочки) — фиксированный момент deadline+15м; не клампим,
    # но сам пинг исполнителю отправляется через outbox с учётом тихих часов.
    esc_run = deadline + timedelta(minutes=ESCALATION_DELAY_MIN)
    if esc_run > now:
        scheduler.add_job(
            escalate_overdue, "date", run_date=esc_run,
            args=[task["id"]],
            id=f"{_job_prefix(task['id'])}escalate",
            replace_existing=True,
        )


def reconcile_task_reminders() -> None:
    """Догоняет напоминания для активных задач с дедлайном (в т.ч. созданных из веба,
    где APScheduler не запущен). Идемпотентно: пропускает задачи, у которых джобы уже есть."""
    from app.bot.scheduler import scheduler

    for task in task_service.list_active_with_deadline():
        if task["status"] == "overdue":
            continue  # уже просрочена и обработана — не пересоздаём джобы
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
        return "Хугацаагүй"
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
        when = "хугацаа яг одоо"
    elif minutes_before % 1440 == 0:
        when = f"{minutes_before // 1440} хоногийн дараа"
    elif minutes_before % 60 == 0:
        when = f"{minutes_before // 60} цагийн дараа"
    else:
        when = f"{minutes_before} минутын дараа"

    text = (
        f"⏰ <b>Даалгаврын сануулга</b>\n\n"
        f"#{task['id']} {task['title']}\n"
        f"Хугацаа: <b>{_fmt_deadline(task['deadline_at'])}</b> ({when})"
    )
    bot = _make_bot()
    try:
        await bot.send_message(task["assignee_tg"], text, reply_markup=task_reminder_kb(task["id"]))
    finally:
        await bot.session.close()


def escalate_overdue(task_id: int) -> None:
    """Маркер просрочки: статус→overdue + ОДИН пинг исполнителю через outbox
    (с учётом тихих часов). Руководителю — НЕ здесь, а в утреннем дайджесте
    после `overdue_escalation_days` рабочих дней. Sync (date-job в threadpool)."""
    task = task_service.get_task(task_id)
    if not task or task["status"] in ("done", "cancelled"):
        return

    task_service.set_status(task_id, "overdue")
    if task.get("overdue_pinged_at"):
        return  # уже пинговали (защита от повторного запуска джоба)

    if task["assignee_tg"]:
        policy = _policy()
        not_before = next_allowed(datetime.now(timezone.utc), _task_tz(task), policy)
        task_service.enqueue_notification(
            task_id=task_id,
            recipient_tg=task["assignee_tg"],
            kind="task_overdue",
            payload={"title": task["title"], "deadline_iso": _iso(task["deadline_at"])},
            not_before=not_before,
            dedup_key=f"task_overdue:{task_id}",
        )
    task_service.mark_overdue_pinged(task_id)


def _iso(dt: datetime | None) -> str | None:
    return dt.astimezone(timezone.utc).isoformat() if dt else None


async def drain_notification_outbox() -> None:
    """Отправляет готовые (not_before<=now) уведомления из outbox. Interval-джоб бота."""
    from app.bot.keyboards import task_actions_kb
    from app.bot.scheduler import _make_bot

    due = task_service.fetch_due_outbox()
    if not due:
        return
    bot = _make_bot()
    try:
        for item in due:
            try:
                # Для задач, которые уже закрыты — не слать (но пометить отправленным).
                if item["task_id"] and item["task_status"] in ("done", "cancelled"):
                    task_service.mark_outbox(item["id"], "sent")
                    continue
                text, kb = _render_outbox(item)
                await bot.send_message(item["recipient_tg"], text, reply_markup=kb)
                task_service.mark_outbox(item["id"], "sent")
            except Exception:  # noqa: BLE001
                log.exception("drain: ошибка отправки outbox id=%s", item["id"])
                task_service.mark_outbox(item["id"], "failed")
    finally:
        await bot.session.close()


def _render_outbox(item: dict):
    from app.bot.keyboards import task_actions_kb

    p = item.get("payload") or {}
    tid = item["task_id"]
    title = p.get("title", "")
    deadline = p.get("deadline_iso")
    dl_h = _fmt_deadline(datetime.fromisoformat(deadline)) if deadline else "Хугацаагүй"
    if item["kind"] == "task_assigned":
        text = (f"📌 Танд #{tid} даалгавар оноолоо:\n«{title}»\nХугацаа: {dl_h}")
        return text, (task_actions_kb(tid) if tid else None)
    if item["kind"] == "task_overdue":
        text = (f"🔴 #{tid} даалгаврын хугацаа хэтэрлээ: {title}\n"
                f"/done {tid} гэж дуусгах эсвэл /snooze {tid} <цаг> гэж хугацааг хойшлуулна уу.")
        return text, (task_actions_kb(tid) if tid else None)
    return p.get("text", "🔔 Мэдэгдэл"), None
