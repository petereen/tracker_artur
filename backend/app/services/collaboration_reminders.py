from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.models import CalendarEntry, Employee, Project, ProjectMember, UserAccount
from app.services.user_notifications import create_notifications


def _local_now(timezone_name: str, now: datetime) -> datetime:
    try:
        return now.astimezone(ZoneInfo(timezone_name or "Asia/Ulaanbaatar"))
    except Exception:
        return now.astimezone(ZoneInfo("Asia/Ulaanbaatar"))


async def reconcile_calendar_reminders() -> None:
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        entries = (await db.execute(
            select(CalendarEntry).where(
                CalendarEntry.remind_at.isnot(None),
                CalendarEntry.remind_at <= now,
                CalendarEntry.remind_at >= now - timedelta(days=30),
            ).order_by(CalendarEntry.remind_at.desc()).limit(500)
        )).scalars().all()
        for entry in entries:
            common = dict(
                organization_id=entry.organization_id,
                kind="calendar_reminder",
                title="Календарийн сануулга",
                body=f"“{entry.title}” эхлэх гэж байна.",
                target_url="/calendar",
                payload={"calendar_entry_id": entry.id, "starts_at": entry.starts_at.isoformat()},
                dedup_key=f"calendar-reminder:{entry.id}:{entry.remind_at.isoformat()}",
            )
            if entry.visibility == "company":
                employee_ids = set((await db.execute(select(UserAccount.employee_id).where(
                    UserAccount.organization_id == entry.organization_id,
                    UserAccount.status == "active",
                    UserAccount.employee_id.isnot(None),
                ))).scalars().all())
                await create_notifications(db, employee_ids=employee_ids, **common)
            elif entry.account_id:
                await create_notifications(db, account_ids={entry.account_id}, **common)
        await db.commit()


async def reconcile_project_deadlines() -> None:
    now = datetime.now(timezone.utc)
    utc_day = now.date()
    async with AsyncSessionLocal() as db:
        projects = (await db.execute(select(Project).where(
            Project.archived_at.is_(None),
            Project.ends_on.isnot(None),
            Project.ends_on >= utc_day - timedelta(days=1),
            Project.ends_on <= utc_day + timedelta(days=2),
            Project.status.notin_({"completed", "cancelled"}),
        ))).scalars().all()
        for project in projects:
            member_ids = set((await db.execute(select(ProjectMember.employee_id).where(ProjectMember.project_id == project.id))).scalars().all())
            employees = (await db.execute(select(Employee).where(Employee.id.in_(member_ids), Employee.is_active.is_(True)))).scalars().all() if member_ids else []
            for employee in employees:
                local_now = _local_now(employee.timezone, now)
                days_before = (project.ends_on - local_now.date()).days
                if days_before not in {0, 1} or local_now.hour < 9:
                    continue
                label = "өнөөдөр" if days_before == 0 else "маргааш"
                await create_notifications(
                    db, organization_id=project.organization_id, employee_ids={employee.id},
                    kind="project_deadline", title="Төслийн хугацааны сануулга",
                    body=f"“{project.name}” төслийн хугацаа {label} дуусна.",
                    target_url=f"/projects?project={project.id}",
                    payload={"project_id": project.id, "ends_on": str(project.ends_on)},
                    dedup_key=f"project-deadline:{project.id}:{project.ends_on}:days:{days_before}",
                )
        await db.commit()
