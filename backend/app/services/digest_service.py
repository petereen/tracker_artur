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

log = logging.getLogger(__name__)

_PRI = {1: "🔴", 2: "🟡", 3: "🟢"}


def _policy():
    from app.bot.db import get_manager_settings
    return load_policy(get_manager_settings())


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _local_today(tz: str | None) -> date:
    zone = pytz.timezone(tz or "Europe/Moscow")
    return datetime.now(zone).date()


def _deadline(t: dict) -> datetime | None:
    dl = t.get("deadline_at")
    if dl and dl.tzinfo is None:
        return dl.replace(tzinfo=timezone.utc)
    return dl


def _is_overdue(t: dict, now: datetime) -> bool:
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
    zone = pytz.timezone(tz or "Europe/Moscow")
    return dl.astimezone(zone).date() == _local_today(tz)


def _line(t: dict, *, with_assignee: bool = False) -> str:
    em = _PRI.get(t["priority"], "🟡")
    who = f" → {t['assignee_name']}" if with_assignee and t.get("assignee_name") else ""
    dl = _deadline(t)
    dls = dl.astimezone(timezone.utc).strftime("%d.%m %H:%M") if dl else "без срока"
    return f"{em} #{t['id']} {t['title']}{who} — {dls}"


def _get_employee(emp_id: int):
    with get_session() as s:
        return s.get(Employee, emp_id)


# ─── Сотрудник: утро ────────────────────────────────────────────────────────────

def build_employee_morning(emp_id: int, tz: str | None) -> str | None:
    now = _now_utc()
    tasks = task_service.list_assigned_to(emp_id, only_active=True)
    overdue = [t for t in tasks if _is_overdue(t, now)]
    today = [t for t in tasks if _is_due_today(t, tz, now)]
    if not overdue and not today:
        return None
    lines = ["🌅 <b>Доброе утро! Задачи на сегодня</b>"]
    if overdue:
        lines.append(f"\n🔴 Просрочено ({len(overdue)}):")
        lines += [f"  {_line(t)}" for t in overdue]
    if today:
        lines.append(f"\n📌 Сегодня дедлайн ({len(today)}):")
        lines += [f"  {_line(t)}" for t in today]
    return "\n".join(lines)


# ─── Сотрудник: вечер ─────────────────────────────────────────────────────────

def build_employee_evening(emp_id: int, tz: str | None) -> str | None:
    now = _now_utc()
    active = task_service.list_assigned_to(emp_id, only_active=True)
    done_today = _done_today(emp_id, tz)
    if not active and not done_today:
        return None
    lines = ["🌆 <b>Итоги дня</b>"]
    if done_today:
        lines.append(f"\n✅ Закрыто сегодня: {done_today}")
    if active:
        lines.append(f"\n📋 Ещё открыто ({len(active)}):")
        lines += [f"  {_line(t)}" for t in active[:10]]
        if len(active) > 10:
            lines.append(f"  …и ещё {len(active) - 10}")
    return "\n".join(lines)


def _done_today(emp_id: int, tz: str | None) -> int:
    from app.models.models import Task
    today = _local_today(tz)
    zone = pytz.timezone(tz or "Europe/Moscow")
    with get_session() as s:
        rows = s.execute(
            select(Task).where(Task.assignee_id == emp_id, Task.status == "done", Task.completed_at.isnot(None))
        ).scalars().all()
        return sum(1 for r in rows if r.completed_at and r.completed_at.astimezone(zone).date() == today)


# ─── Руководитель: утренний обзор ────────────────────────────────────────────────

def build_manager_overview() -> str | None:
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
    lines = [f"👔 <b>Обзор задач команды ({total})</b>"]
    for name, items in groups.items():
        od = [t for t in items if _is_overdue(t, now)]
        td = [t for t in items if _is_due_today(t, t.get("assignee_tz"), now)]
        if not od and not td:
            continue
        lines.append(f"\n👤 <b>{name}</b>:")
        lines += [f"  {_line(t)}" for t in od + td]
    if escalate:
        lines.append(f"\n🚨 <b>Эскалация</b> (висят &gt; {policy.escalation_days} раб. дн.):")
        lines += [f"  {_line(t, with_assignee=True)}" for t in escalate]
    if len(lines) == 1:
        return None
    return "\n".join(lines)


# ─── Отправка ────────────────────────────────────────────────────────────────────

async def _send(recipient_tg: str | None, text: str | None) -> None:
    if not text or not recipient_tg:
        return
    from app.bot.scheduler import _make_bot
    bot = _make_bot()
    try:
        await bot.send_message(recipient_tg, text)
    finally:
        await bot.session.close()


async def send_employee_morning_digest(emp_id: int) -> None:
    if not _policy().enabled:
        return
    emp = _get_employee(emp_id)
    if not emp:
        return
    await _send(emp.telegram_id, build_employee_morning(emp_id, emp.timezone))


async def send_employee_evening_digest(emp_id: int) -> None:
    if not _policy().enabled:
        return
    emp = _get_employee(emp_id)
    if not emp:
        return
    await _send(emp.telegram_id, build_employee_evening(emp_id, emp.timezone))


async def send_manager_task_digest() -> None:
    if not _policy().enabled:
        return
    from app.bot.db import get_manager_settings
    ms = get_manager_settings()
    tg = (ms.telegram_id if ms and ms.telegram_id else None)
    from app.core.config import settings
    tg = tg or (str(settings.MANAGER_TG_ID) if settings.MANAGER_TG_ID else None)
    await _send(tg, build_manager_overview())
