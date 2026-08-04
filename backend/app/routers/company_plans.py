from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import COMPANY_PLAN_HORIZONS, CompanyPlanItem, Employee, WorkReport, WorkReportRevision

router = APIRouter()


def _month_start(value: date) -> date:
    return value.replace(day=1)


async def _report_text(db: AsyncSession, report: WorkReport) -> str | None:
    revision_id = report.approved_revision_id
    if revision_id:
        revision = await db.get(WorkReportRevision, revision_id)
        if revision:
            return revision.text
    revision = (await db.execute(
        select(WorkReportRevision)
        .where(WorkReportRevision.report_id == report.id)
        .order_by(WorkReportRevision.id.desc())
    )).scalars().first()
    return revision.text if revision else None


async def _serialize_item(db: AsyncSession, item: CompanyPlanItem) -> dict:
    employee = await db.get(Employee, item.source_employee_id) if item.source_employee_id else None
    return {
        "id": item.id,
        "plan_month": str(item.plan_month),
        "title": item.title,
        "content": item.content,
        "horizon": item.horizon,
        "position": item.position,
        "status": item.status,
        "source_employee_id": item.source_employee_id,
        "source_employee_name": employee.name if employee else None,
        "source_report_id": item.source_report_id,
        "approved_at": item.approved_at,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


class CompanyPlanItemCreate(BaseModel):
    source_report_id: int
    title: str = Field(min_length=1, max_length=1000)
    content: str | None = None
    plan_month: date | None = None
    horizon: str = "short_term"

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("title is required")
        return value

    @field_validator("horizon")
    @classmethod
    def validate_horizon(cls, value: str) -> str:
        if value not in COMPANY_PLAN_HORIZONS:
            raise ValueError("invalid horizon")
        return value


class CompanyPlanReorder(BaseModel):
    plan_month: date
    columns: dict[str, list[int]]

    @field_validator("columns")
    @classmethod
    def validate_columns(cls, columns: dict[str, list[int]]) -> dict[str, list[int]]:
        if set(columns) != set(COMPANY_PLAN_HORIZONS):
            raise ValueError("all plan horizons are required")
        ids = [item_id for values in columns.values() for item_id in values]
        if len(ids) != len(set(ids)):
            raise ValueError("item ids must be unique")
        return columns


@router.get("/suggestions")
async def list_plan_suggestions(
    month: date,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Worker-approved next-month submissions available for company-plan review."""
    month = _month_start(month)
    reports = (await db.execute(
        select(WorkReport)
        .where(
            WorkReport.report_type == "next_month_plan",
            WorkReport.status == "approved",
            WorkReport.period_date == month,
        )
        .order_by(WorkReport.updated_at.desc(), WorkReport.id.desc())
    )).scalars().all()
    source_counts = dict((await db.execute(
        select(CompanyPlanItem.source_report_id, func.count(CompanyPlanItem.id))
        .where(CompanyPlanItem.source_report_id.in_([report.id for report in reports] or [-1]))
        .group_by(CompanyPlanItem.source_report_id)
    )).all())
    result = []
    for report in reports:
        employee = await db.get(Employee, report.employee_id)
        result.append({
            "id": report.id,
            "employee_id": report.employee_id,
            "employee_name": employee.name if employee else "",
            "period_date": str(report.period_date),
            "text": await _report_text(db, report),
            "created_at": report.created_at,
            "updated_at": report.updated_at,
            "company_plan_item_count": source_counts.get(report.id, 0),
        })
    return result


@router.get("")
async def list_company_plan(
    month: date,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    month = _month_start(month)
    items = (await db.execute(
        select(CompanyPlanItem)
        .where(CompanyPlanItem.plan_month == month)
        .order_by(CompanyPlanItem.horizon, CompanyPlanItem.position, CompanyPlanItem.id)
    )).scalars().all()
    return [await _serialize_item(db, item) for item in items]


@router.post("/items", status_code=201)
async def approve_company_plan_item(
    data: CompanyPlanItemCreate,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    report = await db.get(WorkReport, data.source_report_id)
    if not report or report.report_type != "next_month_plan" or report.status != "approved":
        raise HTTPException(status_code=400, detail="source must be an approved next-month plan")
    plan_month = _month_start(data.plan_month or report.period_date)
    position = await db.scalar(
        select(func.coalesce(func.max(CompanyPlanItem.position), -1) + 1).where(
            CompanyPlanItem.plan_month == plan_month,
            CompanyPlanItem.horizon == data.horizon,
        )
    )
    item = CompanyPlanItem(
        plan_month=plan_month,
        title=data.title,
        content=data.content.strip() if data.content and data.content.strip() else None,
        horizon=data.horizon,
        position=position or 0,
        source_employee_id=report.employee_id,
        source_report_id=report.id,
        status="approved",
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return await _serialize_item(db, item)


@router.put("/reorder")
async def reorder_company_plan(
    data: CompanyPlanReorder,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    month = _month_start(data.plan_month)
    expected = {item_id for values in data.columns.values() for item_id in values}
    existing = (await db.execute(
        select(CompanyPlanItem).where(CompanyPlanItem.plan_month == month)
    )).scalars().all()
    if {item.id for item in existing} != expected:
        raise HTTPException(status_code=400, detail="columns must include every item for this month exactly once")
    for horizon, item_ids in data.columns.items():
        by_id = {item.id: item for item in existing}
        for position, item_id in enumerate(item_ids):
            by_id[item_id].horizon = horizon
            by_id[item_id].position = position
    await db.commit()
    return [await _serialize_item(db, item) for item in existing]
