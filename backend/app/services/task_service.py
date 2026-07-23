"""Бизнес-логика задач (sync — используется ботом). Источник правды по задачам."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

import pytz
from sqlalchemy import case, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.bot.db import get_session
from app.models.models import (
    DEFAULT_REMINDER_INTERVALS_MIN,
    Employee,
    NotificationOutbox,
    Task,
    TaskComment,
)

ACTIVE_STATUSES = ("open", "in_progress", "overdue")


def ensure_employee(tg_id, name: Optional[str] = None, username: Optional[str] = None) -> dict:
    """Get-or-create Employee для telegram-пользователя БЕЗ Schedule (значит без
    ежедневных опросов). Делает руководителя/любого отправителя «назначаемым».
    Возвращает плоский dict (detached-safe)."""
    tg = str(tg_id)
    uname = (username or "").lstrip("@") or None
    with get_session() as s:
        emp = s.execute(select(Employee).where(Employee.telegram_id == tg)).scalar_one_or_none()
        if emp:
            if uname and not emp.telegram_username:
                emp.telegram_username = uname
                s.commit()
        else:
            emp = Employee(name=name or "Ажилтан", telegram_id=tg, telegram_username=uname, is_active=True)
            s.add(emp)
            s.commit()
            s.refresh(emp)
        return {"id": emp.id, "name": emp.name, "telegram_id": emp.telegram_id,
                "telegram_username": emp.telegram_username, "timezone": emp.timezone}


def resolve_employee_by_username(username: str) -> Optional[Employee]:
    uname = (username or "").lstrip("@").lower()
    if not uname:
        return None
    with get_session() as s:
        return s.execute(
            select(Employee).where(Employee.telegram_username.ilike(uname))
        ).scalar_one_or_none()


def create_task(
    *,
    title: str,
    assignee_id: Optional[int],
    created_by_id: Optional[int],
    created_by_tg: Optional[str],
    deadline_at: Optional[datetime] = None,
    priority: int = 2,
    description: Optional[str] = None,
    reminder_intervals_min: Optional[list[int]] = None,
) -> dict:
    """Создаёт задачу, возвращает плоский dict (detached-safe)."""
    with get_session() as s:
        task = Task(
            title=title,
            description=description,
            assignee_id=assignee_id,
            created_by_id=created_by_id,
            created_by_tg=created_by_tg,
            deadline_at=deadline_at,
            priority=priority,
            status="open",
            reminder_intervals_min=list(reminder_intervals_min or DEFAULT_REMINDER_INTERVALS_MIN),
        )
        s.add(task)
        s.commit()
        s.refresh(task)
        return _to_dict(s, task)


def get_task(task_id: int) -> Optional[dict]:
    with get_session() as s:
        task = s.get(Task, task_id)
        return _to_dict(s, task) if task else None


def list_assigned_to(employee_id: int, *, only_active: bool = True) -> list[dict]:
    with get_session() as s:
        q = select(Task).where(Task.assignee_id == employee_id)
        if only_active:
            q = q.where(Task.status.in_(ACTIVE_STATUSES))
        q = q.order_by(Task.deadline_at.asc().nullslast(), Task.priority.asc())
        return [_to_dict(s, t) for t in s.execute(q).scalars()]


def list_created_by(*, employee_id: Optional[int], tg_id: Optional[str], only_active: bool = True) -> list[dict]:
    with get_session() as s:
        conds = []
        if employee_id is not None:
            conds.append(Task.created_by_id == employee_id)
        if tg_id is not None:
            conds.append(Task.created_by_tg == tg_id)
        if not conds:
            return []
        q = select(Task).where(or_(*conds))
        if only_active:
            q = q.where(Task.status.in_(ACTIVE_STATUSES))
        q = q.order_by(Task.deadline_at.asc().nullslast(), Task.priority.asc())
        return [_to_dict(s, t) for t in s.execute(q).scalars()]


def local_date_bounds(
    kind: str,
    *,
    tz: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    now: Optional[datetime] = None,
) -> tuple[Optional[datetime], Optional[datetime], bool]:
    """Convert an inclusive local-date request into half-open UTC boundaries."""
    try:
        zone = pytz.timezone(tz or "Asia/Ulaanbaatar")
    except Exception:
        zone = pytz.timezone("Asia/Ulaanbaatar")
    local_now = now.astimezone(zone) if now else datetime.now(zone)

    include_overdue = kind in {"today", "this_week"}
    if kind == "today":
        first = local_now.date()
        last = first
    elif kind == "this_week":
        first = local_now.date() - timedelta(days=local_now.weekday())
        last = first + timedelta(days=6 - first.weekday())
    elif kind == "custom" and start_date and end_date:
        first, last = start_date, end_date
    else:
        return None, None, False

    start_local = zone.localize(datetime.combine(first, time.min))
    end_local = zone.localize(datetime.combine(last + timedelta(days=1), time.min))
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc), include_overdue


def list_for_actor(
    *,
    employee_id: Optional[int],
    tg_id: Optional[str],
    scope: str = "both",
    include_completed: bool = False,
    start_at: Optional[datetime] = None,
    end_at: Optional[datetime] = None,
    include_overdue_before_start: bool = False,
) -> list[dict]:
    """Return one deduplicated, permission-scoped task list for assistant use."""
    with get_session() as s:
        q = select(Task)
        actor_conds = []
        creator_conds = []
        if employee_id is not None:
            creator_conds.append(Task.created_by_id == employee_id)
        if tg_id is not None:
            creator_conds.append(Task.created_by_tg == str(tg_id))

        if scope == "team":
            pass  # Caller must enforce manager authorization.
        elif scope == "assigned":
            if employee_id is None:
                return []
            actor_conds.append(Task.assignee_id == employee_id)
        elif scope == "created":
            actor_conds.extend(creator_conds)
        else:
            if employee_id is not None:
                actor_conds.append(Task.assignee_id == employee_id)
            actor_conds.extend(creator_conds)

        if scope != "team":
            if not actor_conds:
                return []
            q = q.where(or_(*actor_conds))

        statuses = list(ACTIVE_STATUSES)
        if include_completed:
            statuses.append("done")
        q = q.where(Task.status.in_(statuses))

        if start_at is not None and end_at is not None:
            in_range = (
                (Task.deadline_at.isnot(None))
                & (Task.deadline_at >= start_at)
                & (Task.deadline_at < end_at)
            )
            if include_overdue_before_start:
                outstanding_overdue = (
                    (Task.deadline_at.isnot(None))
                    & (Task.deadline_at < start_at)
                    & (Task.status.in_(ACTIVE_STATUSES))
                )
                q = q.where(or_(outstanding_overdue, in_range))
            else:
                q = q.where(in_range)

        now_utc = datetime.now(timezone.utc)
        q = q.order_by(
            case(
                (
                    (Task.status == "overdue")
                    | (
                        Task.deadline_at.isnot(None)
                        & (Task.deadline_at < now_utc)
                        & (Task.status.in_(ACTIVE_STATUSES))
                    ),
                    0,
                ),
                else_=1,
            ),
            Task.priority.asc(),
            Task.deadline_at.asc().nullslast(),
            Task.id.desc(),
        )
        return [_to_dict(s, task) for task in s.execute(q).scalars()]


def list_active_with_deadline() -> list[dict]:
    """Активные задачи с дедлайном — для реконсайла напоминаний из процесса бота."""
    with get_session() as s:
        q = select(Task).where(Task.status.in_(ACTIVE_STATUSES), Task.deadline_at.isnot(None))
        return [_to_dict(s, t) for t in s.execute(q).scalars()]


def all_active_grouped_by_assignee() -> dict[str, list[dict]]:
    """Для дашборда руководителя: активные задачи, сгруппированные по исполнителю."""
    with get_session() as s:
        q = (
            select(Task)
            .where(Task.status.in_(ACTIVE_STATUSES))
            .order_by(Task.assignee_id, Task.deadline_at.asc().nullslast())
        )
        groups: dict[str, list[dict]] = {}
        for t in s.execute(q).scalars():
            d = _to_dict(s, t)
            groups.setdefault(d["assignee_name"] or "—", []).append(d)
        return groups


def set_status(task_id: int, status: str, *, by_employee_id: Optional[int] = None) -> Optional[dict]:
    with get_session() as s:
        task = s.get(Task, task_id)
        if not task:
            return None
        task.status = status
        if status == "done":
            task.completed_at = datetime.now(timezone.utc)
            task.completed_by_id = by_employee_id
        s.commit()
        s.refresh(task)
        return _to_dict(s, task)


def snooze(task_id: int, new_deadline: datetime) -> Optional[dict]:
    with get_session() as s:
        task = s.get(Task, task_id)
        if not task:
            return None
        task.deadline_at = new_deadline
        task.overdue_pinged_at = None  # перенос срока — снова разрешаем пинг о просрочке
        if task.status == "overdue":
            task.status = "open"
        s.commit()
        s.refresh(task)
        return _to_dict(s, task)


def add_comment(task_id: int, *, author_id: Optional[int], author_tg: Optional[str], text: str) -> None:
    with get_session() as s:
        s.add(TaskComment(task_id=task_id, author_id=author_id, author_tg=author_tg, text=text))
        s.commit()


def can_modify(task: dict, *, employee_id: Optional[int], tg_id: Optional[str], is_manager: bool) -> bool:
    if is_manager:
        return True
    if employee_id is not None and task["assignee_id"] == employee_id:
        return True
    if employee_id is not None and task["created_by_id"] == employee_id:
        return True
    if tg_id is not None and task["created_by_tg"] == tg_id:
        return True
    return False


def mark_overdue_pinged(task_id: int) -> None:
    with get_session() as s:
        t = s.get(Task, task_id)
        if t:
            t.overdue_pinged_at = datetime.now(timezone.utc)
            s.commit()


# ─── Notification outbox (мост api → бот) ──────────────────────────────────────

def enqueue_notification(*, recipient_tg, kind, payload, not_before, dedup_key, task_id=None) -> None:
    if not recipient_tg:
        return
    with get_session() as s:
        stmt = (
            pg_insert(NotificationOutbox)
            .values(
                task_id=task_id, recipient_tg=str(recipient_tg), kind=kind,
                payload=payload, not_before=not_before, status="pending", dedup_key=dedup_key,
            )
            .on_conflict_do_nothing(index_elements=["dedup_key"])
        )
        s.execute(stmt)
        s.commit()


def fetch_due_outbox(limit: int = 25) -> list[dict]:
    now = datetime.now(timezone.utc)
    with get_session() as s:
        rows = s.execute(
            select(NotificationOutbox)
            .where(
                NotificationOutbox.status == "pending",
                or_(NotificationOutbox.not_before.is_(None), NotificationOutbox.not_before <= now),
            )
            .order_by(NotificationOutbox.id)
            .limit(limit)
        ).scalars().all()
        out = []
        for r in rows:
            task = s.get(Task, r.task_id) if r.task_id else None
            out.append({
                "id": r.id, "recipient_tg": r.recipient_tg, "kind": r.kind,
                "payload": r.payload or {}, "task_id": r.task_id,
                "task_status": task.status if task else None,
            })
        return out


def mark_outbox(outbox_id: int, status: str) -> None:
    with get_session() as s:
        r = s.get(NotificationOutbox, outbox_id)
        if r:
            r.status = status
            if status == "sent":
                r.sent_at = datetime.now(timezone.utc)
            s.commit()


def _to_dict(s, task: Task) -> dict:
    assignee = s.get(Employee, task.assignee_id) if task.assignee_id else None
    creator = s.get(Employee, task.created_by_id) if task.created_by_id else None
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "status": task.status,
        "priority": task.priority,
        "deadline_at": task.deadline_at,
        "created_at": task.created_at,
        "completed_at": task.completed_at,
        "overdue_pinged_at": task.overdue_pinged_at,
        "assignee_id": task.assignee_id,
        "assignee_name": assignee.name if assignee else None,
        "assignee_tg": assignee.telegram_id if assignee else None,
        "assignee_tz": assignee.timezone if assignee else None,
        "created_by_id": task.created_by_id,
        "created_by_tg": task.created_by_tg,
        "creator_name": creator.name if creator else None,
        "reminder_intervals_min": list(task.reminder_intervals_min or []),
    }
