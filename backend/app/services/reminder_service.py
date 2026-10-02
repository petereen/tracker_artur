"""Планирование напоминаний по задачам + эскалация просрочки (APScheduler)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.services import task_service
from app.services.notification_policy import load_policy, next_allowed

log = logging.getLogger(__name__)

ESCALATION_DELAY_MIN = 15
DEFAULT_TZ = "Asia/Ulaanbaatar"


def _job_prefix(task_id: int) -> str:
    return f"task:{task_id}:"


def _policy(organization_id: int | None = None):
    """Quiet hours etc. of the task's tenant (``None``: bound tenant or primary)."""
    from app.bot.db import get_manager_settings
    return load_policy(get_manager_settings(organization_id))


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

    if task.get("workflow_status") == "review":
        cancel_task_jobs(task["id"])
        return
    deadline = task.get("deadline_at")
    if not deadline:
        return
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)

    cancel_task_jobs(task["id"])
    now = datetime.now(timezone.utc)
    policy = _policy(task.get("organization_id"))
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
        if task["status"] == "overdue" or task.get("workflow_status") == "review":
            continue  # уже просрочена и обработана — не пересоздаём джобы
        if scheduler.get_job(f"{_job_prefix(task['id'])}escalate"):
            continue
        try:
            schedule_task_reminders(task)
        except Exception:  # noqa: BLE001
            log.exception("reconcile: не удалось запланировать напоминания task=%s", task["id"])


def _fmt_deadline(dt: datetime | None, language: str = "mn") -> str:
    if not dt:
        return {"en": "No deadline", "ru": "Без срока"}.get(language, "Хугацаагүй")
    zone_label = {"en": "ULAT", "ru": "УЛАТ"}.get(language, "УБ")
    return dt.astimezone(ZoneInfo(DEFAULT_TZ)).strftime("%d.%m %H:%M ") + zone_label


async def send_task_reminder(task_id: int, minutes_before: int) -> None:
    task = task_service.get_task(task_id)
    if not task or task["status"] in ("done", "cancelled") or task.get("workflow_status") == "review":
        return
    recipients = task.get("assignees") or ([{"id": task["assignee_id"], "telegram_id": task["assignee_tg"], "timezone": task["assignee_tz"]}] if task.get("assignee_id") else [])
    if not recipients:
        return

    if minutes_before == 0:
        when = "хугацаа яг одоо"
    elif minutes_before % 1440 == 0:
        when = f"{minutes_before // 1440} хоногийн дараа"
    elif minutes_before % 60 == 0:
        when = f"{minutes_before // 60} цагийн дараа"
    else:
        when = f"{minutes_before} минутын дараа"

    for recipient in recipients:
        telegram_id = recipient.get("telegram_id")
        if not telegram_id:
            continue
        task_service.enqueue_notification(
            task_id=task["id"], recipient_tg=telegram_id, kind="task_deadline",
            payload={
                "title": task["title"], "deadline_iso": _iso(task["deadline_at"]),
                "when": when, "minutes_before": minutes_before,
                "timezone_name": recipient.get("timezone") or DEFAULT_TZ,
            },
            not_before=datetime.now(timezone.utc),
            dedup_key=f"task-reminder:{task['id']}:{minutes_before}:employee:{recipient['id']}",
        )


def escalate_overdue(task_id: int) -> None:
    """Маркер просрочки: статус→overdue + ОДИН пинг исполнителю через outbox
    (с учётом тихих часов). Руководителю — НЕ здесь, а в утреннем дайджесте
    после `overdue_escalation_days` рабочих дней. Sync (date-job в threadpool)."""
    task = task_service.get_task(task_id)
    if not task or task["status"] in ("done", "cancelled") or task.get("workflow_status") == "review":
        return

    task_service.set_status(task_id, "overdue")
    if task.get("overdue_pinged_at"):
        return  # уже пинговали (защита от повторного запуска джоба)

    if task["assignee_tg"]:
        policy = _policy(task.get("organization_id"))
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
    from app.bot.scheduler import _make_bot
    from app.services.notification_preferences import telegram_allowed_sync
    from app.services.telegram_bots import tenant_app_url_sync

    due = task_service.fetch_due_outbox()
    if not due:
        return
    # One client per tenant bot for this batch; tenants without a bot get
    # their Telegram copy marked failed (the web notification still exists).
    bots: dict[int | None, object] = {}
    app_urls: dict[int | None, str] = {}
    try:
        for item in due:
            organization_id = item.get("organization_id")
            try:
                # Для задач, которые уже закрыты — не слать (но пометить отправленным).
                if item["task_id"] and (item["task_status"] in ("done", "cancelled") or item.get("task_workflow_status") == "review"):
                    task_service.mark_outbox(item["id"], "sent")
                    continue
                # Preferences are checked again at send time: a category the
                # tenant or the user switched off after queueing is dropped.
                if not telegram_allowed_sync(item["recipient_tg"], item["kind"], organization_id):
                    task_service.mark_outbox(item["id"], "skipped", "notification_preferences", final=True)
                    continue
                if organization_id not in bots:
                    bots[organization_id] = _make_bot(organization_id)
                    app_urls[organization_id] = tenant_app_url_sync(organization_id)
                bot = bots[organization_id]
                if bot is None:
                    task_service.mark_outbox(item["id"], "failed", "telegram_bot_not_connected", final=True)
                    continue
                text, kb = _render_outbox({**item, "app_url": app_urls[organization_id]})
                await bot.send_message(item["recipient_tg"], text, reply_markup=kb)
                task_service.mark_outbox(item["id"], "sent")
            except Exception as exc:  # noqa: BLE001
                log.exception("drain: ошибка отправки outbox id=%s", item["id"])
                task_service.mark_outbox(item["id"], "failed", str(exc))
    finally:
        for bot in bots.values():
            if bot is not None:
                await bot.session.close()


CATEGORY_ICONS = {
    "tasks": "📌", "reports": "📝", "worktime": "🕘", "calendar": "📅", "contracts": "📄",
    "hr": "🧑‍💼", "crm": "🤝", "payroll": "💰", "digests": "🗞", "checkin": "✅", "system": "🔔",
}


def _open_button(url: str | None, label: str = "🔗 Нээх"):
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    if not url or not url.startswith("http"):
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=label, url=url)]])


def _absolute(app_url: str, target: str | None) -> str | None:
    if not target:
        return None
    return target if target.startswith("http") else f"{app_url}{target if target.startswith('/') else '/' + target}"


def _render_outbox(item: dict):
    from html import escape

    from app.bot.keyboards import task_actions_kb
    from app.services.notification_preferences import category_for

    p = item.get("payload") or {}
    language = p.get("locale") or item.get("locale") or "mn"
    tid = item["task_id"]
    app_url = (item.get("app_url") or settings.PUBLIC_APP_URL).rstrip("/")
    title = p.get("title") or item.get("task_title") or "Task"
    description = p.get("description") or item.get("task_description")
    deadline = p.get("deadline_iso")
    deadline_dt = datetime.fromisoformat(deadline) if deadline else item.get("task_deadline_at")
    timezone_name = p.get("timezone_name") or "Asia/Ulaanbaatar"
    dl_h = _fmt_deadline(deadline_dt, language)
    if item["kind"] == "task_assigned":
        task_url = p.get("task_url") or f"{app_url}/tasks?task={tid}"
        creator_name = p.get("creator_name") or "Тодорхойгүй"
        if language == "en":
            text = f"📌 New task assigned to you: #{tid}\n“{title}”\nCreated by: {creator_name}\nDue: {dl_h}\n🔗 View task: {task_url}"
        elif language == "ru":
            text = f"📌 Вам назначена новая задача: #{tid}\n«{title}»\nСоздал: {creator_name}\nСрок: {dl_h}\n🔗 Открыть задачу: {task_url}"
        else:
            text = (f"📌 Танд #{tid} даалгавар оноолоо:\n«{title}»\n"
                    f"Үүсгэсэн: {creator_name}\nХугацаа: {dl_h}\n🔗 Даалгавар харах: {task_url}")
        return text, (
            task_actions_kb(
                tid, title=title, deadline=deadline_dt, description=description,
                timezone_name=timezone_name, task_url=task_url, language=language,
            )
            if tid else None
        )
    if item["kind"] == "task_review_requested":
        task_url = p.get("task_url") or f"{app_url}/tasks?task={tid}"
        assignee = p.get("assignee_name") or "Хариуцагчгүй"
        if language == "en":
            text = f"🔎 <b>Review requested</b>\n\n<b>Task:</b> #{tid} {title}\n<b>Assignee:</b> {assignee}\n<b>Open:</b> {task_url}\n{p.get('text', '')}"
        elif language == "ru":
            text = f"🔎 <b>Требуется проверка</b>\n\n<b>Задача:</b> #{tid} {title}\n<b>Исполнитель:</b> {assignee}\n<b>Открыть:</b> {task_url}\n{p.get('text', '')}"
        else:
            text = f"🔎 <b>Хянах шаардлагатай</b>\n\n<b>Даалгавар:</b> #{tid} {title}\n<b>Хариуцагч:</b> {assignee}\n<b>Нээх:</b> {task_url}\n{p.get('text', '')}"
        return text, (task_actions_kb(tid, title=title, deadline=deadline_dt, description=description, timezone_name=timezone_name, include_submit_for_review=False, task_url=task_url, language=language) if tid else None)
    if item["kind"] == "task_overdue":
        task_url = p.get("task_url") or f"{app_url}/tasks?task={tid}"
        if language == "en":
            text = f"🔴 <b>Task overdue</b>\n\n#{tid} {escape(title)}\nDue: <b>{dl_h}</b>\nComplete or snooze it using the buttons below."
        elif language == "ru":
            text = f"🔴 <b>Срок задачи истёк</b>\n\n#{tid} {escape(title)}\nСрок: <b>{dl_h}</b>\nЗавершите задачу или отложите её кнопками ниже."
        else:
            text = (f"🔴 <b>Даалгаврын хугацаа хэтэрлээ</b>\n\n#{tid} {escape(title)}\n"
                    f"Хугацаа: <b>{dl_h}</b>\nДоорх товчоор дуусгах эсвэл хойшлуулна уу.")
        return text, (task_actions_kb(tid, title=title, deadline=deadline_dt, timezone_name=timezone_name, task_url=task_url, language=language) if tid else None)
    if item["kind"] == "task_deadline":
        task_url = p.get("task_url") or f"{app_url}/tasks?task={tid}"
        minutes_before = p.get("minutes_before")
        if minutes_before is None:
            when_label = {"en": "soon", "ru": "скоро"}.get(language, p.get("when", "удахгүй"))
        elif minutes_before == 0:
            when_label = {"en": "now", "ru": "сейчас"}.get(language, "яг одоо")
        elif minutes_before % 1440 == 0:
            count = minutes_before // 1440
            when_label = f"in {count} day{'s' if count != 1 else ''}" if language == "en" else f"через {count} дн." if language == "ru" else f"{count} хоногийн дараа"
        elif minutes_before % 60 == 0:
            count = minutes_before // 60
            when_label = f"in {count} hour{'s' if count != 1 else ''}" if language == "en" else f"через {count} ч." if language == "ru" else f"{count} цагийн дараа"
        else:
            when_label = f"in {minutes_before} minute{'s' if minutes_before != 1 else ''}" if language == "en" else f"через {minutes_before} мин." if language == "ru" else f"{minutes_before} минутын дараа"
        if language == "en":
            text = f"⏰ <b>Task reminder</b>\n\n#{tid} {escape(title)}\nDue: <b>{dl_h}</b> ({when_label})"
        elif language == "ru":
            text = f"⏰ <b>Напоминание о задаче</b>\n\n#{tid} {escape(title)}\nСрок: <b>{dl_h}</b> ({when_label})"
        else:
            text = f"⏰ <b>Даалгаврын сануулга</b>\n\n#{tid} {escape(title)}\nХугацаа: <b>{dl_h}</b> ({when_label})"
        return text, (task_actions_kb(tid, title=title, deadline=deadline_dt, timezone_name=timezone_name, task_url=task_url, language=language) if tid else None)
    if item["kind"] in {"calendar_reminder", "event"}:
        starts_at = p.get("starts_at")
        starts_at_dt = datetime.fromisoformat(starts_at) if starts_at else None
        entry_url = p.get("target_url") or f"{app_url}/calendar"
        start_label = {"en": "Starts", "ru": "Начало"}.get(language, "Эхлэх")
        unknown = {"en": "Unknown", "ru": "Не указано"}.get(language, "Тодорхойгүй")
        text = (
            f"{'⏰' if item['kind'] == 'calendar_reminder' else '📅'} <b>{title}</b>\n\n"
            f"{p.get('body', '')}\n"
            f"{start_label}: <b>{_fmt_deadline(starts_at_dt, language) if starts_at_dt else unknown}</b>"
        )
        if p.get("location"):
            location_label = {"en": "Location", "ru": "Место"}.get(language, "Байршил")
            text += f"\n{location_label}: {p['location']}"
        open_label = {"en": "Open calendar", "ru": "Открыть календарь"}.get(language, "Календарь нээх")
        return f"{text}\n🔗 <b>{open_label}:</b> {entry_url}", None
    # Every other kind: category icon, title, body and an "open" button to
    # the same page the in-app notification opens.
    icon = CATEGORY_ICONS.get(category_for(item["kind"]), "🔔")
    target = _absolute(app_url, p.get("target_url"))
    if p.get("text"):
        return p["text"], _open_button(target)
    from app.services.notification_localization import render_notification_payload

    heading, body_text = render_notification_payload(item["kind"], p, language)
    heading = escape(str(heading))
    body = escape(str(body_text))
    open_label = {"en": "Open", "ru": "Открыть"}.get(language, "Нээх")
    return f"{icon} <b>{heading}</b>" + (f"\n\n{body}" if body else ""), _open_button(target, f"🔗 {open_label}")
