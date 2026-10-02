"""CRM activity follow-ups: due-soon and overdue reminders plus escalation.

Runs in the bot's scheduler like the other reconcilers. Every notification is
deduplicated per activity and deadline, so re-running is safe and changing
the deadline produces a fresh reminder.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html import escape

from sqlalchemy import or_, select

from app.core.database import AsyncSessionLocal
from app.models.crm import FINISHED_STATUS_CATEGORIES, CRMActivity, ERPStatus
from app.models.models import Employee, ERPParty, ManagerSettings
from app.services.notification_policy import load_policy, working_days_between
from app.services.user_notifications import create_notifications

DUE_SOON_WINDOW = timedelta(hours=1)
# Activities overdue for longer than this are considered abandoned and stop
# producing reminders; they remain visible in the CRM overdue filter.
REMINDER_HORIZON = timedelta(days=90)


def _label(activity: CRMActivity, party_name: str | None) -> str:
    return f"{activity.number}: {activity.subject}" + (f" ({party_name})" if party_name else "")


async def reconcile_crm_activity_reminders(now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        policy = load_policy((await db.execute(select(ManagerSettings).limit(1))).scalar_one_or_none())
        if not policy.enabled:
            return
        finished = select(ERPStatus.id).where(ERPStatus.category.in_(FINISHED_STATUS_CATEGORIES))
        rows = (await db.execute(
            select(CRMActivity, ERPParty.name, Employee.manager_id)
            .outerjoin(ERPParty, ERPParty.id == CRMActivity.party_id)
            .join(Employee, Employee.id == CRMActivity.responsible_employee_id)
            .where(
                CRMActivity.is_active.is_(True), CRMActivity.is_closed.is_(False), CRMActivity.completed_at.is_(None),
                or_(CRMActivity.status_id.is_(None), CRMActivity.status_id.not_in(finished)),
                CRMActivity.due_at.is_not(None), CRMActivity.due_at <= now + DUE_SOON_WINDOW, CRMActivity.due_at >= now - REMINDER_HORIZON,
                Employee.is_active.is_(True),
            )
        )).all()
        for activity, party_name, manager_id in rows:
            deadline = activity.due_at.isoformat()
            target = f"/erp/crm?activity={activity.id}"
            payload = {"crm_activity_id": activity.id, "number": activity.number, "due_at": deadline}
            label = _label(activity, party_name)
            if activity.due_at > now:
                await create_notifications(
                    db, organization_id=activity.organization_id, employee_ids=[activity.responsible_employee_id],
                    kind="crm_activity_due", title="Харилцаа холбооны хугацаа дөхлөө", body=f"{label} — удахгүй биелэх хугацаа дуусна.",
                    target_url=target, payload=payload, dedup_key=f"crm-activity-due:{activity.id}:{deadline}",
                )
                continue
            await create_notifications(
                db, organization_id=activity.organization_id, employee_ids=[activity.responsible_employee_id],
                kind="crm_activity_overdue", title="Харилцаа холбооны хугацаа хэтэрлээ", body=f"{label} — биелэх хугацаа өнгөрсөн байна.",
                target_url=target, payload=payload, dedup_key=f"crm-activity-overdue:{activity.id}:{deadline}",
            )
            if manager_id and manager_id != activity.responsible_employee_id and working_days_between(activity.due_at, now, policy) >= policy.escalation_days:
                await create_notifications(
                    db, organization_id=activity.organization_id, employee_ids=[manager_id],
                    kind="crm_activity_escalated", title="Хоцорсон харилцаа холбоо",
                    body=f"{label} — {policy.escalation_days}+ ажлын өдөр хоцорсон байна.",
                    target_url=target, payload=payload, dedup_key=f"crm-activity-escalated:{activity.id}:{deadline}",
                )
        await db.commit()


def crm_digest_lines(employee_id: int, now: datetime, local_day_end: datetime, language: str = "mn") -> list[str]:
    """Morning-digest section: the employee's overdue and due-today CRM work."""
    from app.bot.db import get_session

    with get_session() as session:
        finished = select(ERPStatus.id).where(ERPStatus.category.in_(FINISHED_STATUS_CATEGORIES))
        rows = session.execute(
            select(CRMActivity, ERPParty.name)
            .outerjoin(ERPParty, ERPParty.id == CRMActivity.party_id)
            .where(
                CRMActivity.responsible_employee_id == employee_id, CRMActivity.is_active.is_(True), CRMActivity.is_closed.is_(False),
                CRMActivity.completed_at.is_(None), or_(CRMActivity.status_id.is_(None), CRMActivity.status_id.not_in(finished)),
                CRMActivity.due_at.is_not(None), CRMActivity.due_at < local_day_end, CRMActivity.due_at >= now - REMINDER_HORIZON,
            )
            .order_by(CRMActivity.due_at).limit(15)
        ).all()
    overdue = [(row, name) for row, name in rows if row.due_at < now]
    today = [(row, name) for row, name in rows if row.due_at >= now]
    lines: list[str] = []
    if overdue:
        label = {"en": "overdue", "ru": "просрочено"}.get(language, "хугацаа хэтэрсэн")
        lines.append(f"\n🔴 CRM — {label} ({len(overdue)}):")
        lines += [f"  • {escape(_label(row, name))}" for row, name in overdue]
    if today:
        label = {"en": "due today", "ru": "срок сегодня"}.get(language, "өнөөдөр")
        lines.append(f"\n🤝 CRM — {label} ({len(today)}):")
        lines += [f"  • {escape(_label(row, name))}" for row, name in today]
    return lines
