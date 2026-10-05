"""Дайджесты по задачам (батчинг вместо точечного спама).

Утренний/вечерний сотруднику + утренний обзор руководителю с эскалацией.
Sync-сборка данных + async-отправка (джобы APScheduler в боте). Пустые не шлём.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

import pytz
from sqlalchemy import select

from app.bot.db import get_session
from app.models.models import Employee
from app.services import task_service
from app.services.notification_policy import load_policy, working_days_between
from app.services.manager_recipients import manager_telegram_ids

log = logging.getLogger(__name__)

_PRI = {1: "🔴", 2: "🟡", 3: "🟢"}


def _policy(organization_id: int | None = None):
    """Notification policy of a tenant (explicit, bound, else primary)."""
    from app.bot.db import get_manager_settings
    return load_policy(get_manager_settings(organization_id))


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _local_today(tz: str | None) -> date:
    zone = pytz.timezone(tz or "Asia/Ulaanbaatar")
    return datetime.now(zone).date()


def _deadline(t: dict) -> datetime | None:
    dl = t.get("deadline_at")
    if dl and dl.tzinfo is None:
        return dl.replace(tzinfo=timezone.utc)
    return dl


def _is_overdue(t: dict, now: datetime) -> bool:
    if t.get("workflow_status") == "review":
        return False
    if t["status"] in ("done", "cancelled"):
        return False
    if t["status"] == "overdue":
        return True
    dl = _deadline(t)
    return bool(dl and dl < now)


def _is_due_today(t: dict, tz: str | None, now: datetime) -> bool:
    dl = _deadline(t)
    if not dl or _is_overdue(t, now):
        return False
    zone = pytz.timezone(tz or "Asia/Ulaanbaatar")
    return dl.astimezone(zone).date() == _local_today(tz)


def _is_task_on_day(t: dict, tz: str | None, day: date) -> bool:
    """Return whether a task's deadline falls on ``day`` in its local zone."""
    dl = _deadline(t)
    if not dl:
        return False
    zone = pytz.timezone(tz or "Asia/Ulaanbaatar")
    return dl.astimezone(zone).date() == day


def _has_employee_task_on_day(emp_id: int, tz: str | None, day: date) -> bool:
    return any(
        _is_task_on_day(task, tz, day)
        for task in task_service.list_assigned_to(emp_id, only_active=True)
    )


def _has_manager_task_on_day(day: date) -> bool:
    return any(
        _is_task_on_day(task, task.get("assignee_tz"), day)
        for tasks in task_service.all_active_grouped_by_assignee().values()
        for task in tasks
    )


def _digest_allowed_on_day(day: date, work_weekdays, has_task: bool) -> bool:
    """Allow configured workdays, plus non-workdays with a task due that day."""
    return day.isoweekday() in set(work_weekdays) or has_task


def _line(t: dict, *, with_assignee: bool = False, language: str = "mn") -> str:
    em = _PRI.get(t["priority"], "🟡")
    who = f" → {t['assignee_name']}" if with_assignee and t.get("assignee_name") else ""
    dl = _deadline(t)
    dls = dl.astimezone(timezone.utc).strftime("%d.%m %H:%M") if dl else {"en": "No deadline", "ru": "Без срока"}.get(language, "Хугацаагүй")
    return f"{em} #{t['id']} {t['title']}{who} — {dls}"


def _get_employee(emp_id: int):
    with get_session() as s:
        return s.get(Employee, emp_id)


# ─── Сотрудник: утро ────────────────────────────────────────────────────────────

def build_employee_morning(emp_id: int, tz: str | None, language: str = "mn") -> str | None:
    now = _now_utc()
    tasks = task_service.list_assigned_to(emp_id, only_active=True)
    overdue = [t for t in tasks if _is_overdue(t, now)]
    today = [t for t in tasks if _is_due_today(t, tz, now)]
    crm_lines = _crm_morning_lines(emp_id, tz, now, language)
    if not overdue and not today and not crm_lines:
        return None
    lines = [{"en": "🌅 <b>Good morning! Today's tasks</b>", "ru": "🌅 <b>Доброе утро! Задачи на сегодня</b>"}.get(language, "🌅 <b>Өглөөний мэнд! Өнөөдрийн даалгавар</b>")]
    if overdue:
        label = {"en": "Overdue", "ru": "Просрочено"}.get(language, "Хугацаа хэтэрсэн")
        lines.append(f"\n🔴 {label} ({len(overdue)}):")
        lines += [f"  {_line(t, language=language)}" for t in overdue]
    if today:
        label = {"en": "Due today", "ru": "Срок сегодня"}.get(language, "Өнөөдөр дуусах хугацаатай")
        lines.append(f"\n📌 {label} ({len(today)}):")
        lines += [f"  {_line(t, language=language)}" for t in today]
    lines += crm_lines
    return "\n".join(lines)


def _crm_morning_lines(emp_id: int, tz: str | None, now: datetime, language: str = "mn") -> list[str]:
    """CRM follow-ups are optional; a CRM failure must never block the task digest."""
    from datetime import timedelta

    from app.services.crm_reminders import crm_digest_lines

    zone = pytz.timezone(tz or "Asia/Ulaanbaatar")
    day_end = zone.localize(datetime.combine(_local_today(tz) + timedelta(days=1), datetime.min.time()))
    try:
        return crm_digest_lines(emp_id, now, day_end.astimezone(timezone.utc), language)
    except Exception:
        log.warning("digest.crm_section_failed", exc_info=True)
        return []


# ─── Сотрудник: вечер ─────────────────────────────────────────────────────────

def build_employee_evening(emp_id: int, tz: str | None, language: str = "mn") -> str | None:
    active = task_service.list_assigned_to(emp_id, only_active=True)
    done_today = _done_today(emp_id, tz)
    if not active and not done_today:
        return None
    lines = [{"en": "🌆 <b>End-of-day summary</b>", "ru": "🌆 <b>Итоги дня</b>"}.get(language, "🌆 <b>Өдрийн дүн</b>")]
    if done_today:
        label = {"en": "Tasks completed today", "ru": "Задач выполнено сегодня"}.get(language, "Өнөөдөр дуусгасан даалгаврын тоо")
        lines.append(f"\n✅ {label}: {done_today}")
    if active:
        label = {"en": "Remaining tasks", "ru": "Осталось задач"}.get(language, "Үлдсэн даалгавар")
        lines.append(f"\n📋 {label} ({len(active)}):")
        lines += [f"  {_line(t, language=language)}" for t in active[:10]]
        if len(active) > 10:
            lines.append(f"  …{'and' if language == 'en' else 'и' if language == 'ru' else 'мөн'} {len(active) - 10}")
    return "\n".join(lines)


def _done_today(emp_id: int, tz: str | None) -> int:
    from app.models.models import Task
    today = _local_today(tz)
    zone = pytz.timezone(tz or "Asia/Ulaanbaatar")
    with get_session() as s:
        rows = s.execute(
            select(Task).where(Task.assignee_id == emp_id, Task.status == "done", Task.completed_at.isnot(None))
        ).scalars().all()
        return sum(1 for r in rows if r.completed_at and r.completed_at.astimezone(zone).date() == today)


# ─── Руководитель: утренний обзор ────────────────────────────────────────────────

def build_manager_overview(language: str = "mn") -> str | None:
    now = _now_utc()
    policy = _policy()
    groups = task_service.all_active_grouped_by_assignee()
    if not groups:
        return None
    total = sum(len(v) for v in groups.values())
    overdue_all = [t for items in groups.values() for t in items if _is_overdue(t, now)]
    escalate = [
        t for t in overdue_all
        if _deadline(t) and working_days_between(_deadline(t), now, policy) >= policy.escalation_days
    ]
    heading = {"en": "Team task overview", "ru": "Обзор задач команды"}.get(language, "Багийн даалгаврын тойм")
    lines = [f"👔 <b>{heading} ({total})</b>"]
    for name, items in groups.items():
        od = [t for t in items if _is_overdue(t, now)]
        td = [t for t in items if _is_due_today(t, t.get("assignee_tz"), now)]
        if not od and not td:
            continue
        lines.append(f"\n👤 <b>{name}</b>:")
        lines += [f"  {_line(t, language=language)}" for t in od + td]
    if escalate:
        label = {"en": "Needs attention", "ru": "Требует внимания"}.get(language, "Анхаарал шаардлагатай")
        days = {"en": "business days", "ru": "рабочих дней"}.get(language, "ажлын өдөр")
        lines.append(f"\n🚨 <b>{label}</b> (&gt; {policy.escalation_days} {days}):")
        lines += [f"  {_line(t, with_assignee=True, language=language)}" for t in escalate]
    if len(lines) == 1:
        return None
    return "\n".join(lines)


# ─── Отправка ────────────────────────────────────────────────────────────────────

async def _send(recipient_tg: str | None, text: str | None, organization_id: int | None = None) -> None:
    if not text or not recipient_tg:
        return
    from app.bot.scheduler import send_telegram
    await send_telegram(recipient_tg, text, organization_id=organization_id)


def _digest_allowed_for(emp_id: int) -> bool:
    from app.services.notification_preferences import delivery_for_employee_sync

    return delivery_for_employee_sync(emp_id, "task_digest").telegram


async def send_employee_morning_digest(emp_id: int) -> None:
    emp = _get_employee(emp_id)
    if not emp or not _policy(emp.organization_id).enabled or not _digest_allowed_for(emp_id):
        return
    from app.bot.scheduler import _employee_language
    language = _employee_language(emp.id, emp.primary_language)
    message = build_employee_morning(emp_id, emp.timezone, language)
    from app.bot.db import get_schedule
    from app.bot.scheduler import _schedule_weekdays
    local_day = _local_today(emp.timezone)
    if not _digest_allowed_on_day(
        local_day,
        _schedule_weekdays(get_schedule(emp_id)),
        _has_employee_task_on_day(emp_id, emp.timezone, local_day),
    ):
        return
    await _send(emp.telegram_id, message, emp.organization_id)


async def send_employee_evening_digest(emp_id: int) -> None:
    emp = _get_employee(emp_id)
    if not emp or not _policy(emp.organization_id).enabled or not _digest_allowed_for(emp_id):
        return
    from app.bot.scheduler import _employee_language
    language = _employee_language(emp.id, emp.primary_language)
    message = build_employee_evening(emp_id, emp.timezone, language)
    from app.bot.db import get_schedule
    from app.bot.scheduler import _schedule_weekdays
    local_day = _local_today(emp.timezone)
    if not _digest_allowed_on_day(
        local_day,
        _schedule_weekdays(get_schedule(emp_id)),
        _has_employee_task_on_day(emp_id, emp.timezone, local_day),
    ):
        return
    await _send(emp.telegram_id, message, emp.organization_id)


async def send_manager_task_digest() -> None:
    """One overview per tenant with a live bot, built from that tenant's tasks only."""
    from app.bot.db import get_manager_settings, is_primary_tenant
    from app.core.tenancy import tenant_scope
    from app.services.telegram_bots import registry

    for organization_id in sorted({bot.organization_id for bot in registry.bots_sync() if bot.delivers}):
        try:
            with tenant_scope(organization_id):
                policy = _policy(organization_id)
                from app.services.notification_preferences import tenant_category_enabled_sync

                if not policy.enabled or not tenant_category_enabled_sync(organization_id, "digests"):
                    continue
                ms = get_manager_settings(organization_id)
                local_day = _local_today("Asia/Ulaanbaatar")
                if not _digest_allowed_on_day(local_day, policy.work_weekdays, _has_manager_task_on_day(local_day)):
                    continue
                recipients = manager_telegram_ids(ms, primary=is_primary_tenant(organization_id))
            for recipient in recipients:
                from app.bot.scheduler import _telegram_language
                language = _telegram_language(recipient, organization_id)
                with tenant_scope(organization_id):
                    message = build_manager_overview(language)
                await _send(recipient, message, organization_id)
        except Exception:  # noqa: BLE001 - one tenant must not block the others
            log.exception("digest.manager_digest_failed tenant=%s", organization_id)
