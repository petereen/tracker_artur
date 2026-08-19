from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    DomainEvent,
    Employee,
    ManagerSettings,
    NotificationOutbox,
    UserAccount,
    UserNotification,
    DEFAULT_PRIORITY_NOTIFICATION_KINDS,
)
from app.services.notification_policy import load_policy, next_allowed


async def create_notifications(
    db: AsyncSession,
    *,
    organization_id: int,
    kind: str,
    title: str,
    body: str,
    dedup_key: str,
    employee_ids: Iterable[int] = (),
    account_ids: Iterable[int] = (),
    exclude_employee_id: int | None = None,
    target_url: str | None = None,
    payload: dict | None = None,
    source_event_id: int | None = None,
    task_id: int | None = None,
    immediate: bool = False,
    deliver_telegram: bool = True,
) -> list[UserNotification]:
    employee_set = {int(value) for value in employee_ids if value is not None}
    if exclude_employee_id is not None:
        employee_set.discard(exclude_employee_id)
    account_set = {int(value) for value in account_ids if value is not None}
    query = select(UserAccount, Employee).outerjoin(Employee, UserAccount.employee_id == Employee.id).where(
        UserAccount.organization_id == organization_id,
        UserAccount.status == "active",
        or_(UserAccount.id.in_(account_set), UserAccount.employee_id.in_(employee_set)),
    )
    if not employee_set and not account_set:
        return []
    rows = (await db.execute(query)).all()
    manager_settings = (await db.execute(select(ManagerSettings).limit(1))).scalar_one_or_none()
    policy = load_policy(manager_settings)
    created: list[UserNotification] = []
    covered_employee_ids: set[int] = set()
    for account, employee in rows:
        if employee:
            covered_employee_ids.add(employee.id)
        scoped_key = f"{dedup_key}:account:{account.id}"
        existing = await db.scalar(select(UserNotification.id).where(UserNotification.dedup_key == scoped_key))
        if existing:
            continue
        telegram_available = bool(deliver_telegram and employee and employee.telegram_id)
        notification = UserNotification(
            organization_id=organization_id,
            recipient_account_id=account.id,
            recipient_employee_id=account.employee_id,
            event_id=source_event_id,
            kind=kind,
            title=title,
            body=body,
            target_url=target_url,
            payload=payload or {},
            telegram_status="queued" if telegram_available else "unavailable",
            dedup_key=scoped_key,
            is_priority=kind in DEFAULT_PRIORITY_NOTIFICATION_KINDS,
        )
        db.add(notification)
        await db.flush()
        if telegram_available:
            not_before = datetime.now(timezone.utc) if immediate else next_allowed(datetime.now(timezone.utc), employee.timezone, policy)
            db.add(NotificationOutbox(
                user_notification_id=notification.id,
                event_id=source_event_id,
                task_id=task_id,
                recipient_tg=str(employee.telegram_id),
                kind=kind,
                payload={"title": title, "body": body, "target_url": target_url, **(payload or {})},
                not_before=not_before,
                status="pending",
                dedup_key=f"telegram:{scoped_key}",
            ))
        realtime_event = DomainEvent(
            organization_id=organization_id,
            topic="notifications",
            aggregate_type="user_notification",
            aggregate_id=notification.id,
            operation="created",
            payload={"recipient_account_id": account.id},
        )
        db.add(realtime_event)
        await db.flush()
        await db.execute(text("SELECT pg_notify('oyuns_events', :event_id)"), {"event_id": str(realtime_event.id)})
        created.append(notification)
    # Telegram users may be registered employees before they have opened the
    # web app and therefore have no UserAccount yet. They cannot receive an
    # in-app notification, but must still receive the Telegram delivery.
    unlinked_employee_ids = employee_set - covered_employee_ids if deliver_telegram else set()
    if unlinked_employee_ids:
        unlinked = (await db.execute(select(Employee).where(Employee.id.in_(unlinked_employee_ids), Employee.is_active.is_(True)))).scalars().all()
        for employee in unlinked:
            if not employee.telegram_id:
                continue
            scoped_key = f"telegram:{dedup_key}:employee:{employee.id}"
            exists = await db.scalar(select(NotificationOutbox.id).where(NotificationOutbox.dedup_key == scoped_key))
            if exists:
                continue
            not_before = datetime.now(timezone.utc) if immediate else next_allowed(datetime.now(timezone.utc), employee.timezone, policy)
            db.add(NotificationOutbox(
                event_id=source_event_id, task_id=task_id, recipient_tg=str(employee.telegram_id),
                kind=kind, payload={"title": title, "body": body, "target_url": target_url, **(payload or {})},
                not_before=not_before, status="pending", dedup_key=scoped_key,
            ))
    return created


def mirror_existing_telegram_notification(
    *,
    employee_id: int,
    kind: str,
    title: str,
    body: str,
    dedup_key: str,
    target_url: str,
    payload: dict | None = None,
    telegram_status: str = "sent",
) -> None:
    """Persist a web copy after a legacy scheduler has sent its Telegram message."""
    from app.bot.db import get_session

    with get_session() as db:
        account = db.execute(select(UserAccount).where(UserAccount.employee_id == employee_id, UserAccount.status == "active")).scalar_one_or_none()
        if not account:
            return
        scoped_key = f"{dedup_key}:account:{account.id}"
        existing = db.execute(select(UserNotification).where(UserNotification.dedup_key == scoped_key)).scalar_one_or_none()
        if existing:
            if telegram_status == "sent" and existing.telegram_status != "sent":
                existing.telegram_status = "sent"
                db.commit()
            return
        notification = UserNotification(
            organization_id=account.organization_id,
            recipient_account_id=account.id,
            recipient_employee_id=employee_id,
            kind=kind,
            title=title,
            body=body,
            target_url=target_url,
            payload=payload or {},
            telegram_status=telegram_status,
            dedup_key=scoped_key,
            is_priority=kind in DEFAULT_PRIORITY_NOTIFICATION_KINDS,
        )
        db.add(notification)
        db.flush()
        event = DomainEvent(
            organization_id=account.organization_id,
            topic="notifications",
            aggregate_type="user_notification",
            aggregate_id=notification.id,
            operation="created",
            payload={"recipient_account_id": account.id},
        )
        db.add(event)
        db.flush()
        db.execute(text("SELECT pg_notify('oyuns_events', :event_id)"), {"event_id": str(event.id)})
        db.commit()
