"""Helpers for synchronizing worktime activity into HR attendance."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import AttendanceLog, Employee, WorkTimeEntry


def apply_worktime_attendance(
    log: AttendanceLog | None,
    employee: Employee,
    local_day: date,
    entries: Iterable[WorkTimeEntry],
    *,
    at: datetime | None = None,
) -> AttendanceLog | None:
    """Apply the current day's work intervals to an attendance log.

    Worktime can suggest or maintain attendance, but a manager-confirmed
    manual record remains authoritative for its status.
    """
    work_entries = [entry for entry in entries if entry.entry_type == "work" and entry.mode in {"in_person", "remote"}]
    if not work_entries:
        return log

    modes = {entry.mode for entry in work_entries}
    attendance_status = "remote" if modes == {"remote"} else "present"
    current = at or datetime.now(timezone.utc)
    worked_minutes = sum(
        max(0, round(((entry.ended_at or current) - entry.started_at).total_seconds() / 60))
        for entry in work_entries
    )
    first_started_at = min(entry.started_at for entry in work_entries)
    ended = [entry.ended_at for entry in work_entries if entry.ended_at]
    last_ended_at = max(ended) if ended else None

    if log is None:
        return AttendanceLog(
            organization_id=employee.organization_id,
            employee_id=employee.id,
            attendance_date=local_day,
            status=attendance_status,
            source="worktime",
            worked_minutes=worked_minutes,
            first_started_at=first_started_at,
            last_ended_at=last_ended_at,
        )

    previous = (
        log.status,
        log.source,
        log.worked_minutes,
        log.first_started_at,
        log.last_ended_at,
    )
    if not log.confirmed_at:
        log.status = attendance_status
        log.source = "worktime"
    log.worked_minutes = worked_minutes
    log.first_started_at = first_started_at
    log.last_ended_at = last_ended_at
    current_values = (
        log.status,
        log.source,
        log.worked_minutes,
        log.first_started_at,
        log.last_ended_at,
    )
    if current_values != previous:
        log.version += 1
    return log


async def sync_worktime_attendance(
    db: AsyncSession,
    employee: Employee,
    local_day: date,
    *,
    at: datetime | None = None,
) -> AttendanceLog | None:
    """Persist the worktime attendance status for one employee and day."""
    entries = (
        await db.execute(
            select(WorkTimeEntry)
            .where(
                WorkTimeEntry.employee_id == employee.id,
                WorkTimeEntry.local_work_date == local_day,
            )
            .order_by(WorkTimeEntry.started_at, WorkTimeEntry.id)
        )
    ).scalars().all()
    log = await db.scalar(
        select(AttendanceLog)
        .where(
            AttendanceLog.organization_id == employee.organization_id,
            AttendanceLog.employee_id == employee.id,
            AttendanceLog.attendance_date == local_day,
        )
        .with_for_update()
    )
    updated = apply_worktime_attendance(log, employee, local_day, entries, at=at)
    if log is None and updated is not None:
        db.add(updated)
    return updated
