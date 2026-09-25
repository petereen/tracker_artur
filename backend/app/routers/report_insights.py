"""Admin/manager report downloads and OYUNS summaries for a chosen period."""
from __future__ import annotations

from datetime import date
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.enterprise_deps import ActorContext, require_roles
from app.models.models import Department, Employee
from app.services import report_insights_service as insights
from app.services.enterprise_events import record_change

router = APIRouter()
require_export_role = require_roles(*insights.EXPORT_ROLES)
ReportType = Literal["daily", "monthly", "next_month_plan"]


class HistoryItem(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=12_000)


class SummaryIn(BaseModel):
    date_from: date
    date_to: date
    scope: Literal["all", "employee", "department"] = "all"
    employee_id: int | None = None
    department_id: int | None = None
    report_types: list[ReportType] = Field(default_factory=lambda: list(insights.REPORT_TYPES))
    prompt: str | None = Field(default=None, max_length=2_000)
    history: list[HistoryItem] = Field(default_factory=list, max_length=20)


def _period(date_from: date, date_to: date) -> None:
    try:
        insights.validate_period(date_from, date_to)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _content_disposition(filename: str) -> str:
    ascii_name = filename.encode("ascii", "ignore").decode().replace('"', "") or "reports"
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


@router.get("/scope")
async def scope(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_export_role)):
    return await insights.scope_options(db, actor.organization_id)


@router.get("/export/preview")
async def export_preview(
    date_from: date,
    date_to: date,
    group_by: Literal["worker", "department"] = "worker",
    employee_ids: list[int] = Query(default_factory=list),
    department_ids: list[int] = Query(default_factory=list),
    report_types: list[ReportType] = Query(default_factory=lambda: list(insights.REPORT_TYPES)),
    approved_only: bool = False,
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_export_role),
):
    _period(date_from, date_to)
    records = await insights.collect_reports(db, actor.organization_id, date_from, date_to, employee_ids=employee_ids, department_ids=department_ids, report_types=report_types, approved_only=approved_only)
    return insights.export_preview(records, group_by=group_by)


@router.get("/export")
async def export_reports(
    date_from: date,
    date_to: date,
    group_by: Literal["worker", "department"] = "worker",
    employee_ids: list[int] = Query(default_factory=list),
    department_ids: list[int] = Query(default_factory=list),
    report_types: list[ReportType] = Query(default_factory=lambda: list(insights.REPORT_TYPES)),
    approved_only: bool = False,
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_export_role),
):
    _period(date_from, date_to)
    records = await insights.collect_reports(db, actor.organization_id, date_from, date_to, employee_ids=employee_ids, department_ids=department_ids, report_types=report_types, approved_only=approved_only)
    try:
        content, filename, media_type = insights.build_export(records, group_by=group_by, date_from=date_from, date_to=date_to)
    except insights.NoReportsFound as exc:
        raise HTTPException(status_code=404, detail="Сонгосон хугацаанд тайлан олдсонгүй") from exc
    await record_change(db, actor=actor, topic="reports", aggregate_type="report_export", aggregate_id=actor.account_id, operation="exported", after={
        "date_from": date_from, "date_to": date_to, "group_by": group_by, "report_count": len(records),
        "employee_ids": employee_ids, "department_ids": department_ids, "report_types": report_types,
    })
    await db.commit()
    return Response(content, media_type=media_type, headers={
        "Content-Disposition": _content_disposition(filename),
        "X-Report-Count": str(len(records)),
        "Access-Control-Expose-Headers": "Content-Disposition, X-Report-Count",
        "Cache-Control": "no-store",
    })


@router.post("/summary")
async def summary(data: SummaryIn, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_export_role)):
    _period(data.date_from, data.date_to)
    employee_ids: list[int] | None = None
    department_ids: list[int] | None = None
    scope_label = "Бүх ажилтан"
    if data.scope == "employee":
        employee = await db.get(Employee, data.employee_id) if data.employee_id else None
        if not employee or employee.organization_id != actor.organization_id:
            raise HTTPException(status_code=404, detail="Ажилтан олдсонгүй")
        employee_ids, scope_label = [employee.id], f"Ажилтан: {employee.name}"
    elif data.scope == "department":
        department = await db.get(Department, data.department_id) if data.department_id else None
        if not department or department.organization_id != actor.organization_id:
            raise HTTPException(status_code=404, detail="Хэлтэс олдсонгүй")
        department_ids, scope_label = [department.id], f"Хэлтэс: {department.name}"
    result = await insights.generate_summary(
        db, actor.organization_id,
        date_from=data.date_from, date_to=data.date_to, scope_label=scope_label,
        employee_ids=employee_ids, department_ids=department_ids,
        prompt=data.prompt, history=[item.model_dump() for item in data.history], report_types=data.report_types,
    )
    await record_change(db, actor=actor, topic="reports", aggregate_type="report_summary", aggregate_id=actor.account_id, operation="generated", after={
        "date_from": data.date_from, "date_to": data.date_to, "scope": data.scope,
        "employee_id": data.employee_id, "department_id": data.department_id,
        "custom_prompt": bool(data.prompt and data.prompt.strip()), "degraded": result["degraded"],
    })
    await db.commit()
    return result
