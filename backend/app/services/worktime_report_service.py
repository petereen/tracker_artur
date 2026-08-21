"""Tenant-safe worktime reporting and export helpers."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime, timezone
from tempfile import SpooledTemporaryFile
from typing import Any, AsyncIterator
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from sqlalchemy import false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enterprise_deps import ActorContext
from app.models.models import Employee, RoleAssignment, Team, TeamMember, UserAccount, WorkTimeEntry


REPORT_PAGE_SIZE = 50
REPORT_MAX_PAGE_SIZE = 200
REPORT_MAX_DAYS = 366


@dataclass(frozen=True)
class ReportFilters:
    date_from: date
    date_to: date
    department: str | None = None
    worker_id: int | None = None


@dataclass(frozen=True)
class ReportScope:
    employee_ids: tuple[int, ...]


def validate_filters(filters: ReportFilters) -> None:
    if filters.date_from > filters.date_to:
        raise HTTPException(status_code=400, detail="from must not be after to")
    if (filters.date_to - filters.date_from).days + 1 > REPORT_MAX_DAYS:
        raise HTTPException(status_code=400, detail="Report period must be between 1 and 366 days")
    if filters.department is not None:
        department = filters.department.strip()
        if not department or len(department) > 200:
            raise HTTPException(status_code=400, detail="Invalid department")


def _safe_zone(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or "Asia/Ulaanbaatar")
    except ZoneInfoNotFoundError:
        return ZoneInfo("Asia/Ulaanbaatar")


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _local_timestamp(value: datetime | None, timezone_name: str | None) -> str | None:
    if value is None:
        return None
    return _as_utc(value).astimezone(_safe_zone(timezone_name)).isoformat()


def _duration_minutes(entry: WorkTimeEntry) -> int | None:
    if entry.ended_at is None:
        return None
    return max(0, round((_as_utc(entry.ended_at) - _as_utc(entry.started_at)).total_seconds() / 60))


def _worker_row(entry: WorkTimeEntry, employee: Employee) -> dict[str, Any]:
    return {
        "worker_id": employee.id,
        "worker_name": employee.name,
        "department": employee.work_direction or "",
        "date": entry.local_work_date.isoformat() if entry.local_work_date else "",
        "clock_in": _local_timestamp(entry.started_at, entry.timezone or employee.timezone),
        "clock_out": _local_timestamp(entry.ended_at, entry.timezone or employee.timezone),
        "total_minutes": _duration_minutes(entry),
        "status": "in_progress" if entry.ended_at is None else "complete",
    }


def _employee_query(actor: ActorContext, date_from: date, date_to: date):
    query = select(Employee.id).join(UserAccount, UserAccount.employee_id == Employee.id).where(
        UserAccount.organization_id == actor.organization_id,
        Employee.is_active.is_(True),
    )
    if actor.has_any_role("admin", "manager", "hr"):
        return query

    assigned_team_ids = select(RoleAssignment.team_id).where(
        RoleAssignment.account_id == actor.account_id,
        RoleAssignment.role == "team_lead",
        RoleAssignment.team_id.is_not(None),
        or_(RoleAssignment.valid_from.is_(None), RoleAssignment.valid_from <= date.today()),
        or_(RoleAssignment.valid_until.is_(None), RoleAssignment.valid_until >= date.today()),
    )
    team_clauses = [Team.id.in_(assigned_team_ids)]
    if actor.employee_id is not None:
        team_clauses.append(Team.manager_id == actor.employee_id)
    managed_team_ids = select(Team.id).where(Team.organization_id == actor.organization_id, or_(*team_clauses))
    member_filters = [
        TeamMember.team_id.in_(managed_team_ids),
        or_(TeamMember.starts_on.is_(None), TeamMember.starts_on <= date_to),
        or_(TeamMember.ends_on.is_(None), TeamMember.ends_on >= date_from),
    ]
    return query.where(Employee.id.in_(select(TeamMember.employee_id).where(*member_filters)))


async def resolve_scope(db: AsyncSession, actor: ActorContext, filters: ReportFilters) -> ReportScope:
    validate_filters(filters)
    query = _employee_query(actor, filters.date_from, filters.date_to)
    if filters.department is not None:
        query = query.where(Employee.work_direction == filters.department.strip())
    ids = tuple((await db.execute(query.distinct().order_by(Employee.id))).scalars().all())
    if filters.worker_id is not None:
        if filters.worker_id not in ids:
            raise HTTPException(status_code=404, detail="Worker not found")
        ids = (filters.worker_id,)
    return ReportScope(employee_ids=ids)


async def report_options(db: AsyncSession, actor: ActorContext) -> dict[str, list[dict[str, Any]]]:
    today = date.today()
    query = _employee_query(actor, today, today).distinct()
    employees = list((await db.execute(select(Employee).where(Employee.id.in_(query)).order_by(Employee.name, Employee.id))).scalars().all())
    departments = sorted({employee.work_direction.strip() for employee in employees if employee.work_direction and employee.work_direction.strip()}, key=str.casefold)
    return {
        "departments": [{"value": value, "label": value} for value in departments],
        "workers": [
            {"id": employee.id, "name": employee.name, "department": employee.work_direction or ""}
            for employee in employees
        ],
    }


def _entry_filters(filters: ReportFilters, scope: ReportScope):
    if not scope.employee_ids:
        return [false()]
    return [
        WorkTimeEntry.employee_id.in_(scope.employee_ids),
        WorkTimeEntry.entry_type == "work",
        WorkTimeEntry.local_work_date >= filters.date_from,
        WorkTimeEntry.local_work_date <= filters.date_to,
    ]


async def _count_distinct(db: AsyncSession, columns: list[Any], where: list[Any]) -> int:
    subquery = select(*columns).where(*where).distinct().subquery()
    return int(await db.scalar(select(func.count()).select_from(subquery)) or 0)


async def report_summary(db: AsyncSession, filters: ReportFilters, scope: ReportScope) -> dict[str, int]:
    where = _entry_filters(filters, scope)
    duration = func.extract("epoch", WorkTimeEntry.ended_at - WorkTimeEntry.started_at) / 60
    completed = [*where, WorkTimeEntry.ended_at.is_not(None)]
    total_minutes = round(float(await db.scalar(select(func.coalesce(func.sum(duration), 0)).where(*completed)) or 0))
    active_workers = await _count_distinct(db, [WorkTimeEntry.employee_id], where)
    worker_days = await _count_distinct(db, [WorkTimeEntry.employee_id, WorkTimeEntry.local_work_date], completed)
    iso_year = func.extract("isoyear", WorkTimeEntry.local_work_date).label("iso_year")
    iso_week = func.extract("week", WorkTimeEntry.local_work_date).label("iso_week")
    worker_weeks = await _count_distinct(db, [WorkTimeEntry.employee_id, iso_year, iso_week], completed)
    return {
        "total_minutes": total_minutes,
        "average_minutes_per_worker": round(total_minutes / active_workers) if active_workers else 0,
        "average_daily_minutes_per_worker": round(total_minutes / worker_days) if worker_days else 0,
        "average_weekly_minutes_per_worker": round(total_minutes / worker_weeks) if worker_weeks else 0,
        "active_worker_count": active_workers,
    }


async def preview_report(
    db: AsyncSession,
    filters: ReportFilters,
    scope: ReportScope,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    if page < 1 or page_size < 1 or page_size > REPORT_MAX_PAGE_SIZE:
        raise HTTPException(status_code=400, detail="Invalid pagination")
    where = _entry_filters(filters, scope)
    total = int(await db.scalar(select(func.count()).select_from(WorkTimeEntry).where(*where)) or 0)
    result = await db.execute(
        select(WorkTimeEntry, Employee)
        .join(Employee, Employee.id == WorkTimeEntry.employee_id)
        .where(*where)
        .order_by(WorkTimeEntry.local_work_date.desc(), Employee.name, WorkTimeEntry.started_at, WorkTimeEntry.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = [_worker_row(entry, employee) for entry, employee in result.all()]
    return {
        "range": {"from": filters.date_from.isoformat(), "to": filters.date_to.isoformat()},
        "summary": await report_summary(db, filters, scope),
        "items": rows,
        "page": page,
        "page_size": page_size,
        "total": total,
    }


async def iter_report_rows(db: AsyncSession, filters: ReportFilters, scope: ReportScope, batch_size: int = 1000) -> AsyncIterator[dict[str, Any]]:
    where = _entry_filters(filters, scope)
    offset = 0
    while True:
        result = await db.execute(
            select(WorkTimeEntry, Employee)
            .join(Employee, Employee.id == WorkTimeEntry.employee_id)
            .where(*where)
            .order_by(WorkTimeEntry.local_work_date, Employee.name, WorkTimeEntry.started_at, WorkTimeEntry.id)
            .offset(offset)
            .limit(batch_size)
        )
        rows = result.all()
        if not rows:
            return
        for entry, employee in rows:
            yield _worker_row(entry, employee)
        offset += len(rows)


def _sheet_value(value: Any) -> Any:
    if isinstance(value, str) and value[:1] in {"=", "+", "-", "@"}:
        return "'" + value
    return value


def _hours(minutes: int) -> float:
    return round(minutes / 60, 2)


async def csv_report(db: AsyncSession, filters: ReportFilters, scope: ReportScope, summary: dict[str, int]) -> AsyncIterator[bytes]:
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerow(["Selected Date Range", f"{filters.date_from.isoformat()} - {filters.date_to.isoformat()}"])
    writer.writerow(["Total Accumulated Hours", _hours(summary["total_minutes"])])
    writer.writerow(["Average Hours per Worker", _hours(summary["average_minutes_per_worker"])])
    writer.writerow([])
    writer.writerow(["Worker ID", "Worker Name", "Department/Team", "Date", "Clock In", "Clock Out", "Total Hours"])
    yield ("\ufeff" + output.getvalue()).encode("utf-8")
    async for row in iter_report_rows(db, filters, scope):
        output.seek(0)
        output.truncate(0)
        writer.writerow([
            _sheet_value(row["worker_id"]), _sheet_value(row["worker_name"]), _sheet_value(row["department"]),
            row["date"], row["clock_in"], row["clock_out"],
            "" if row["total_minutes"] is None else _hours(row["total_minutes"]),
        ])
        yield output.getvalue().encode("utf-8")


async def xlsx_report(db: AsyncSession, filters: ReportFilters, scope: ReportScope, summary: dict[str, int]) -> SpooledTemporaryFile:
    from openpyxl import Workbook

    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet("Worktime Report")
    sheet.append(["Selected Date Range", f"{filters.date_from.isoformat()} - {filters.date_to.isoformat()}"])
    sheet.append(["Total Accumulated Hours", _hours(summary["total_minutes"])])
    sheet.append(["Average Hours per Worker", _hours(summary["average_minutes_per_worker"])])
    sheet.append([])
    sheet.append(["Worker ID", "Worker Name", "Department/Team", "Date", "Clock In", "Clock Out", "Total Hours"])
    async for row in iter_report_rows(db, filters, scope):
        sheet.append([
            _sheet_value(row["worker_id"]), _sheet_value(row["worker_name"]), _sheet_value(row["department"]),
            row["date"], row["clock_in"], row["clock_out"],
            "" if row["total_minutes"] is None else _hours(row["total_minutes"]),
        ])
    buffer = SpooledTemporaryFile(max_size=2 * 1024 * 1024, mode="w+b")
    workbook.save(buffer)
    buffer.seek(0)
    return buffer
