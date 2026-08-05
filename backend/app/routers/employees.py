from datetime import date, datetime, timedelta, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import Employee, Schedule, Streak, SurveySession, WorkReport, WorkReportRevision, WorkTimeEntry
from app.services.work_report_service import summarize_work_time

router = APIRouter()


class EmployeeCreate(BaseModel):
    name: str
    telegram_id: str
    telegram_username: Optional[str] = None
    timezone: str = "Asia/Ulaanbaatar"


class EmployeeUpdate(BaseModel):
    name: Optional[str] = None
    telegram_username: Optional[str] = None
    timezone: Optional[str] = None
    is_active: Optional[bool] = None


class EmployeeOut(BaseModel):
    id: int
    name: str
    telegram_id: str
    telegram_username: Optional[str]
    # Legacy rows (e.g. seeded manager) may have NULL timezone — the model's
    # logical default is Asia/Ulaanbaatar, so return that instead of crashing
    # serialization (Sentry issue 28: ResponseValidationError on GET /employees).
    timezone: str = "Asia/Ulaanbaatar"
    is_active: bool

    model_config = {"from_attributes": True}

    @field_validator("timezone", mode="before")
    @classmethod
    def _default_timezone(cls, v):
        # Coerce legacy NULL timezone (from rows inserted without the
        # client-side default, e.g. the seeded manager) to the logical default.
        return v if v else "Asia/Ulaanbaatar"

    @field_validator("is_active", mode="before")
    @classmethod
    def _default_is_active(cls, v):
        # Same class as the timezone bug (Sentry #28): is_active had only a
        # client-side default and no server_default, so a seed/legacy row could
        # be NULL and crash serialization of this required field.
        return True if v is None else v


@router.get("", response_model=list[EmployeeOut])
async def list_employees(db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    result = await db.execute(select(Employee).order_by(Employee.id))
    return result.scalars().all()


@router.get("/{employee_id}/performance")
async def employee_performance(
    employee_id: int,
    period: int = Query(30, ge=1),
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    all_time: bool = False,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Return the operational metrics displayed on an employee's profile."""
    emp = await db.get(Employee, employee_id)
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    since = None if all_time else (date_from or (date.today() - timedelta(days=period - 1)))
    until = date_to or date.today()
    session_range = ([SurveySession.date >= since] if since else []) + [SurveySession.date <= until]
    report_range = ([WorkReport.period_date >= since] if since else []) + [WorkReport.period_date <= until]
    sessions = (await db.execute(
        select(SurveySession)
        .where(SurveySession.employee_id == employee_id, *session_range)
        .order_by(SurveySession.date.desc())
    )).scalars().all()
    daily_reports = (await db.execute(
        select(WorkReport)
        .where(
            WorkReport.employee_id == employee_id,
            WorkReport.report_type == "daily",
            *report_range,
        )
        .order_by(WorkReport.period_date.desc())
    )).scalars().all()
    reports = (await db.execute(
        select(WorkReport)
        .where(WorkReport.employee_id == employee_id, *report_range)
        .order_by(WorkReport.period_date.desc(), WorkReport.id.desc())
    )).scalars().all()

    completed_checkins = sum(s.status == "completed" for s in sessions)
    submitted_checkins = sum(s.status in ("completed", "partial") for s in sessions)
    report_ids = [report.id for report in daily_reports]
    entries = (await db.execute(
        select(WorkTimeEntry)
        .where(WorkTimeEntry.report_id.in_(report_ids or [-1]))
        .order_by(WorkTimeEntry.started_at, WorkTimeEntry.id)
    )).scalars().all()
    entries_by_report: dict[int, list[WorkTimeEntry]] = {}
    for entry in entries:
        entries_by_report.setdefault(entry.report_id, []).append(entry)
    now = datetime.now(timezone.utc)
    daily_work_time = {
        report.id: summarize_work_time(entries_by_report.get(report.id, []), now=now)
        for report in daily_reports
    }
    work_totals = {
        "total_minutes": sum(item["total_minutes"] for item in daily_work_time.values()),
        "remote_minutes": sum(item["remote_minutes"] for item in daily_work_time.values()),
        "in_person_minutes": sum(item["in_person_minutes"] for item in daily_work_time.values()),
        "complete_entries": sum(item["complete_entries"] for item in daily_work_time.values()),
        "incomplete_entries": sum(item["incomplete_entries"] for item in daily_work_time.values()),
    }
    approved_daily = sum(report.status == "approved" for report in daily_reports)

    def report_summary(report_type: str) -> dict:
        matching = [r for r in reports if r.report_type == report_type]
        return {
            "total": len(matching),
            "approved": sum(r.status == "approved" for r in matching),
            "pending": sum(r.status != "approved" for r in matching),
        }

    recent_reports = reports[:8]
    revisions = (await db.execute(
        select(WorkReportRevision)
        .where(WorkReportRevision.report_id.in_([report.id for report in recent_reports] or [-1]))
        .order_by(WorkReportRevision.id.desc())
    )).scalars().all()
    latest_revision = {}
    revision_by_id = {revision.id: revision for revision in revisions}
    for revision in revisions:
        latest_revision.setdefault(revision.report_id, revision)

    return {
        "employee": {
            "id": emp.id,
            "name": emp.name,
            "telegram_username": emp.telegram_username,
            "timezone": emp.timezone or "Asia/Ulaanbaatar",
            "is_active": True if emp.is_active is None else emp.is_active,
        },
        "date_from": str(since) if since else None,
        "date_to": str(until),
        "checkins": {
            "total": len(sessions),
            "completed": completed_checkins,
            "partial": sum(s.status == "partial" for s in sessions),
            "missed": sum(s.status == "missed" for s in sessions),
            "pending": sum(s.status == "pending" for s in sessions),
            "submitted": submitted_checkins,
            "completion_rate": round(submitted_checkins / len(sessions) * 100) if sessions else 0,
        },
        "work_time": {
            **work_totals,
            "average_minutes": round(work_totals["total_minutes"] / len(daily_work_time)) if daily_work_time else 0,
            "days": [
                {
                    "period_date": str(report.period_date),
                    **daily_work_time[report.id],
                }
                for report in daily_reports
            ],
        },
        "reports": {
            "daily": {**report_summary("daily"), "approved": approved_daily},
            "monthly": report_summary("monthly"),
            "next_month_plan": report_summary("next_month_plan"),
        },
        "recent_reports": [
            {
                "id": report.id,
                "report_type": report.report_type,
                "period_date": str(report.period_date),
                "status": report.status,
                "started_at": report.started_at,
                "ended_at": report.ended_at,
                "work_time": daily_work_time.get(report.id, {"total_minutes": 0, "remote_minutes": 0, "in_person_minutes": 0, "entries": []}),
                "text": (
                    revision_by_id[report.approved_revision_id].text
                    if report.approved_revision_id in revision_by_id
                    else (latest_revision[report.id].text if report.id in latest_revision else None)
                ),
            }
            for report in recent_reports
        ],
    }


@router.post("", response_model=EmployeeOut, status_code=status.HTTP_201_CREATED)
async def create_employee(data: EmployeeCreate, db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    emp = Employee(**data.model_dump())
    db.add(emp)
    await db.flush()
    db.add(Schedule(employee_id=emp.id))
    db.add(Streak(employee_id=emp.id))
    await db.commit()
    await db.refresh(emp)
    return emp


@router.put("/{employee_id}", response_model=EmployeeOut)
async def update_employee(employee_id: int, data: EmployeeUpdate, db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    result = await db.execute(select(Employee).where(Employee.id == employee_id))
    emp = result.scalar_one_or_none()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(emp, k, v)
    await db.commit()
    await db.refresh(emp)
    return emp


@router.delete("/{employee_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_employee(employee_id: int, db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    result = await db.execute(select(Employee).where(Employee.id == employee_id))
    emp = result.scalar_one_or_none()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    await db.delete(emp)
    await db.commit()
