from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import Employee, WorkReport, WorkReportRevision

router = APIRouter()
VALID_TYPES = {"daily", "monthly", "next_month_plan", "daily_test", "monthly_test", "next_month_plan_test"}
VALID_STATUSES = {"awaiting", "draft", "editing", "approved"}


async def _serialize(db: AsyncSession, report: WorkReport, *, with_revisions: bool = False) -> dict:
    employee = await db.get(Employee, report.employee_id)
    revisions = (await db.execute(
        select(WorkReportRevision)
        .where(WorkReportRevision.report_id == report.id)
        .order_by(WorkReportRevision.id.desc())
    )).scalars().all()
    approved = next((r for r in revisions if r.id == report.approved_revision_id), None)
    latest = revisions[0] if revisions else None
    out = {
        "id": report.id,
        "employee_id": report.employee_id,
        "employee_name": employee.name if employee else "",
        "report_type": report.report_type,
        "period_date": str(report.period_date),
        "status": report.status,
        "started_at": report.started_at,
        "ended_at": report.ended_at,
        "text": approved.text if approved else (latest.text if latest else None),
        "latest_revision_status": latest.status if latest else None,
        "approved_revision_id": report.approved_revision_id,
        "created_at": report.created_at,
        "updated_at": report.updated_at,
    }
    if with_revisions:
        out["revisions"] = [
            {"id": r.id, "text": r.text, "status": r.status, "created_at": r.created_at, "updated_at": r.updated_at}
            for r in revisions
        ]
    return out


@router.get("")
async def list_work_reports(
    employee_id: Optional[int] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    report_type: Optional[str] = None,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    if report_type and report_type not in VALID_TYPES:
        raise HTTPException(status_code=400, detail="invalid report_type")
    if status and status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail="invalid status")
    q = select(WorkReport).order_by(WorkReport.period_date.desc(), WorkReport.id.desc())
    if employee_id is not None:
        q = q.where(WorkReport.employee_id == employee_id)
    if date_from:
        q = q.where(WorkReport.period_date >= date_from)
    if date_to:
        q = q.where(WorkReport.period_date <= date_to)
    if report_type:
        q = q.where(WorkReport.report_type == report_type)
    if status:
        q = q.where(WorkReport.status == status)
    reports = (await db.execute(q)).scalars().all()
    return [await _serialize(db, report) for report in reports]


@router.get("/{report_id}")
async def get_work_report(
    report_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    report = await db.get(WorkReport, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="not found")
    return await _serialize(db, report, with_revisions=True)
