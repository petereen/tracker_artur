from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.enterprise_deps import ActorContext, get_actor, require_roles
from app.models.models import COMPANY_PLAN_HORIZONS, CompanyPlanItem, Employee, PlanIdea, UserAccount, WorkReport, WorkReportRevision
from app.services.enterprise_events import record_change
from app.services.user_notifications import create_notifications

router = APIRouter()
MANAGEMENT_ROLES = ("admin", "manager", "team_lead")


def _month_start(value: date) -> date:
    return value.replace(day=1)


async def _report_text(db: AsyncSession, report: WorkReport) -> str | None:
    revision_id = report.approved_revision_id
    if revision_id and (revision := await db.get(WorkReportRevision, revision_id)):
        return revision.text
    revision = (await db.execute(select(WorkReportRevision).where(WorkReportRevision.report_id == report.id).order_by(WorkReportRevision.id.desc()))).scalars().first()
    return revision.text if revision else None


async def _serialize_item(db: AsyncSession, item: CompanyPlanItem) -> dict:
    employee = await db.get(Employee, item.source_employee_id) if item.source_employee_id else None
    idea_ids = (await db.execute(select(PlanIdea.id).where(PlanIdea.merged_into_plan_item_id == item.id))).scalars().all()
    return {"id": item.id, "plan_month": str(item.plan_month), "title": item.title, "content": item.content, "horizon": item.horizon, "position": item.position, "status": item.status, "due_date": str(item.due_date) if item.due_date else None, "source_employee_id": item.source_employee_id, "source_employee_name": employee.name if employee else None, "source_report_id": item.source_report_id, "source_idea_ids": list(idea_ids), "approved_at": item.approved_at, "created_at": item.created_at, "updated_at": item.updated_at}


async def _serialize_idea(db: AsyncSession, idea: PlanIdea) -> dict:
    employee = await db.get(Employee, idea.submitted_by_employee_id) if idea.submitted_by_employee_id else None
    return {"id": idea.id, "plan_month": str(idea.plan_month), "title": idea.title, "content": idea.content, "suggested_due_date": str(idea.suggested_due_date) if idea.suggested_due_date else None, "status": idea.status, "submitted_by_employee_id": idea.submitted_by_employee_id, "submitted_by_name": employee.name if employee else None, "merged_into_plan_item_id": idea.merged_into_plan_item_id, "source_report_id": idea.source_report_id, "created_at": idea.created_at, "updated_at": idea.updated_at}


class CompanyPlanItemCreate(BaseModel):
    source_report_id: int | None = None
    title: str = Field(min_length=1, max_length=1000)
    content: str | None = None
    plan_month: date | None = None
    horizon: str = "short_term"
    due_date: date | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        if not (value := value.strip()):
            raise ValueError("title is required")
        return value

    @field_validator("horizon")
    @classmethod
    def validate_horizon(cls, value: str) -> str:
        if value not in COMPANY_PLAN_HORIZONS:
            raise ValueError("invalid horizon")
        return value


class CompanyPlanItemPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=1000)
    content: str | None = None
    horizon: str | None = None
    due_date: date | None = None


class PlanIdeaInput(BaseModel):
    plan_month: date
    title: str = Field(min_length=1, max_length=1000)
    content: str | None = None
    suggested_due_date: date | None = None


class PlanIdeaPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=1000)
    content: str | None = None
    suggested_due_date: date | None = None
    status: str | None = None


class PlanIdeaMerge(CompanyPlanItemCreate):
    idea_ids: list[int] = Field(min_length=1)


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


@router.get("/ideas")
async def list_ideas(month: date, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    query = select(PlanIdea).where(PlanIdea.organization_id == actor.organization_id, PlanIdea.plan_month == _month_start(month))
    if not actor.has_any_role(*MANAGEMENT_ROLES):
        query = query.where(PlanIdea.submitted_by_account_id == actor.account_id)
    rows = (await db.execute(query.order_by(PlanIdea.created_at.desc()))).scalars().all()
    return [await _serialize_idea(db, row) for row in rows]


@router.post("/ideas", status_code=201)
async def create_idea(data: PlanIdeaInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    idea = PlanIdea(organization_id=actor.organization_id, submitted_by_account_id=actor.account_id, submitted_by_employee_id=actor.employee_id, plan_month=_month_start(data.plan_month), title=data.title.strip(), content=data.content, suggested_due_date=data.suggested_due_date)
    db.add(idea); await db.commit(); await db.refresh(idea)
    return await _serialize_idea(db, idea)


@router.patch("/ideas/{idea_id}")
async def update_idea(idea_id: int, data: PlanIdeaPatch, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    idea = await db.get(PlanIdea, idea_id, with_for_update=True)
    if not idea or idea.organization_id != actor.organization_id:
        raise HTTPException(status_code=404, detail="Plan idea not found")
    management = actor.has_any_role(*MANAGEMENT_ROLES)
    if not management and (idea.submitted_by_account_id != actor.account_id or idea.status != "pending"):
        raise HTTPException(status_code=403, detail="This idea can no longer be edited")
    patch = data.model_dump(exclude_unset=True)
    if "status" in patch:
        if not management or patch["status"] not in {"pending", "approved", "rejected"}:
            raise HTTPException(status_code=403, detail="Only management can review ideas")
        idea.reviewed_by_account_id, idea.reviewed_at = actor.account_id, datetime.now(timezone.utc)
    for field, value in patch.items():
        setattr(idea, field, value.strip() if isinstance(value, str) and field in {"title", "content"} else value)
    await db.commit()
    return await _serialize_idea(db, idea)


@router.delete("/ideas/{idea_id}", status_code=status.HTTP_204_NO_CONTENT)
async def reject_idea(idea_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles(*MANAGEMENT_ROLES))):
    idea = await db.get(PlanIdea, idea_id, with_for_update=True)
    if not idea or idea.organization_id != actor.organization_id:
        raise HTTPException(status_code=404, detail="Plan idea not found")
    idea.status, idea.reviewed_by_account_id, idea.reviewed_at = "rejected", actor.account_id, datetime.now(timezone.utc)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/suggestions")
async def list_plan_suggestions(month: date, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles(*MANAGEMENT_ROLES))):
    month = _month_start(month)
    reports = (await db.execute(select(WorkReport).where(WorkReport.report_type == "next_month_plan", WorkReport.status == "approved", WorkReport.period_date == month).order_by(WorkReport.updated_at.desc()))).scalars().all()
    result = []
    for report in reports:
        employee = await db.get(Employee, report.employee_id)
        result.append({"id": report.id, "employee_id": report.employee_id, "employee_name": employee.name if employee else "", "period_date": str(report.period_date), "text": await _report_text(db, report), "created_at": report.created_at, "updated_at": report.updated_at})
    return result


@router.get("")
async def list_company_plan(month: date, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    items = (await db.execute(select(CompanyPlanItem).where(CompanyPlanItem.organization_id == actor.organization_id, CompanyPlanItem.plan_month == _month_start(month), CompanyPlanItem.status == "approved").order_by(CompanyPlanItem.horizon, CompanyPlanItem.position, CompanyPlanItem.id))).scalars().all()
    return [await _serialize_item(db, item) for item in items]


async def _create_item(data: CompanyPlanItemCreate, db: AsyncSession, actor: ActorContext) -> CompanyPlanItem:
    report = await db.get(WorkReport, data.source_report_id) if data.source_report_id else None
    plan_month = _month_start(data.plan_month or (report.period_date if report else date.today()))
    position = await db.scalar(select(func.coalesce(func.max(CompanyPlanItem.position), -1) + 1).where(CompanyPlanItem.organization_id == actor.organization_id, CompanyPlanItem.plan_month == plan_month, CompanyPlanItem.horizon == data.horizon))
    item = CompanyPlanItem(organization_id=actor.organization_id, plan_month=plan_month, title=data.title, content=data.content.strip() if data.content and data.content.strip() else None, horizon=data.horizon, position=position or 0, status="approved", due_date=data.due_date, source_employee_id=report.employee_id if report else None, source_report_id=report.id if report else None, approved_by_account_id=actor.account_id)
    db.add(item); await db.flush()
    return item


async def _notify_item_created(db: AsyncSession, actor: ActorContext, item: CompanyPlanItem) -> None:
    event = await record_change(db, actor=actor, topic="plans", aggregate_type="company_plan_item", aggregate_id=item.id, operation="created", after={"title": item.title, "plan_month": str(item.plan_month), "due_date": str(item.due_date) if item.due_date else None})
    employee_ids = set((await db.execute(select(UserAccount.employee_id).where(
        UserAccount.organization_id == actor.organization_id,
        UserAccount.status == "active",
        UserAccount.employee_id.isnot(None),
    ))).scalars().all())
    await create_notifications(
        db, organization_id=actor.organization_id, employee_ids=employee_ids,
        kind="company_plan_created", title="Шинэ компанийн төлөвлөгөө",
        body=f"“{item.title}” төлөвлөгөө нэмэгдлээ.", target_url="/plans",
        payload={"plan_item_id": item.id, "plan_month": str(item.plan_month)},
        source_event_id=event.id, dedup_key=f"company-plan-created:{item.id}",
    )


@router.post("/items", status_code=201)
async def approve_company_plan_item(data: CompanyPlanItemCreate, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles(*MANAGEMENT_ROLES))):
    item = await _create_item(data, db, actor); await _notify_item_created(db, actor, item); await db.commit(); return await _serialize_item(db, item)


@router.post("/ideas/merge", status_code=201)
async def merge_ideas(data: PlanIdeaMerge, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles(*MANAGEMENT_ROLES))):
    ideas = (await db.execute(select(PlanIdea).where(PlanIdea.organization_id == actor.organization_id, PlanIdea.id.in_(set(data.idea_ids))).with_for_update())).scalars().all()
    if len(ideas) != len(set(data.idea_ids)) or any(idea.status != "pending" for idea in ideas):
        raise HTTPException(status_code=409, detail="Every selected idea must still be pending")
    item = await _create_item(CompanyPlanItemCreate(**data.model_dump(exclude={"idea_ids"})), db, actor)
    now = datetime.now(timezone.utc)
    for idea in ideas:
        idea.status, idea.merged_into_plan_item_id, idea.reviewed_by_account_id, idea.reviewed_at = "merged", item.id, actor.account_id, now
    await _notify_item_created(db, actor, item)
    await db.commit(); return await _serialize_item(db, item)


@router.patch("/items/{item_id}")
async def update_item(item_id: int, data: CompanyPlanItemPatch, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles(*MANAGEMENT_ROLES))):
    item = await db.get(CompanyPlanItem, item_id, with_for_update=True)
    if not item or item.organization_id != actor.organization_id or item.status != "approved":
        raise HTTPException(status_code=404, detail="Plan item not found")
    patch = data.model_dump(exclude_unset=True)
    if patch.get("horizon") and patch["horizon"] not in COMPANY_PLAN_HORIZONS:
        raise HTTPException(status_code=400, detail="Invalid horizon")
    for field, value in patch.items(): setattr(item, field, value)
    await db.commit(); return await _serialize_item(db, item)


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_item(item_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles(*MANAGEMENT_ROLES))):
    item = await db.get(CompanyPlanItem, item_id, with_for_update=True)
    if not item or item.organization_id != actor.organization_id:
        raise HTTPException(status_code=404, detail="Plan item not found")
    item.status = "archived"; await db.commit(); return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/reorder")
async def reorder_company_plan(data: CompanyPlanReorder, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles(*MANAGEMENT_ROLES))):
    month = _month_start(data.plan_month)
    existing = (await db.execute(select(CompanyPlanItem).where(CompanyPlanItem.organization_id == actor.organization_id, CompanyPlanItem.plan_month == month, CompanyPlanItem.status == "approved"))).scalars().all()
    expected = {item_id for values in data.columns.values() for item_id in values}
    if {item.id for item in existing} != expected:
        raise HTTPException(status_code=400, detail="columns must include every item for this month exactly once")
    by_id = {item.id: item for item in existing}
    for horizon, item_ids in data.columns.items():
        for position, item_id in enumerate(item_ids): by_id[item_id].horizon, by_id[item_id].position = horizon, position
    await db.commit(); return [await _serialize_item(db, item) for item in existing]
