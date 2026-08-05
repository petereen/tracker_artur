from __future__ import annotations

import hashlib
import json
import mimetypes
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.enterprise_deps import ActorContext, get_actor, require_roles
from app.models.models import (
    CalendarConnection,
    Attachment,
    CheckinQuestion,
    CheckinTemplate,
    Checkin,
    CheckinAnswer,
    Client,
    Employee,
    ExchangeRateSnapshot,
    IdempotencyRecord,
    JobQueue,
    KeyResult,
    Milestone,
    Objective,
    Project,
    ProjectMember,
    ProjectRate,
    ReportComment,
    ResourceAllocation,
    RoleAssignment,
    SavedView,
    Task,
    TaskComment,
    TaskAssignee,
    TaskCheckItem,
    TaskDependency,
    Team,
    TeamMember,
    TimeOff,
    WorkReport,
    WorkReportRevision,
    WorkTimeEntry,
)
from app.services.enterprise_events import record_change
from app.services.attachment_storage import delete_attachment, get_attachment, put_attachment
from app.core.config import settings
from app.services.voice_service import transcribe
from app.services.google_calendar import account_from_state, authorization_url as google_authorization_url, exchange_code as google_exchange_code, is_configured as google_is_configured
from app.services.secret_box import encrypt_secret


router = APIRouter()
MANAGEMENT_ROLES = ("admin", "manager", "team_lead")
WORKFLOW_STATUSES = {"backlog", "to_do", "in_progress", "review", "done", "cancelled"}
LEGACY_STATUS = {
    "backlog": "open", "to_do": "open", "in_progress": "in_progress",
    "review": "open", "done": "done", "cancelled": "cancelled",
}


def _decimal(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _project_out(item: Project) -> dict:
    return {
        "id": item.id, "public_id": str(item.public_id), "client_id": item.client_id,
        "manager_id": item.manager_id, "code": item.code, "name": item.name,
        "description": item.description, "status": item.status,
        "starts_on": item.starts_on, "ends_on": item.ends_on,
        "budget_minutes": item.budget_minutes, "budget_amount": _decimal(item.budget_amount),
        "currency": item.currency, "default_billable": item.default_billable,
        "version": item.version, "updated_at": item.updated_at,
    }


def _task_out(item: Task) -> dict:
    return {
        "id": item.id, "public_id": str(item.public_id), "project_id": item.project_id,
        "parent_task_id": item.parent_task_id, "title": item.title,
        "description": item.description, "workflow_status": item.workflow_status,
        "priority": item.priority, "primary_owner_id": item.assignee_id,
        "start_at": item.start_at, "deadline_at": item.deadline_at,
        "estimate_minutes": item.estimate_minutes, "sort_position": _decimal(item.sort_position),
        "version": item.version, "is_archived": item.is_archived,
        "created_at": item.created_at, "completed_at": item.completed_at,
        "is_overdue": bool(item.deadline_at and item.deadline_at < datetime.now(timezone.utc) and item.workflow_status not in {"done", "cancelled"}),
    }


def _entry_out(item: WorkTimeEntry) -> dict:
    return {
        "id": item.id, "employee_id": item.employee_id, "project_id": item.project_id,
        "task_id": item.task_id, "local_work_date": item.local_work_date,
        "entry_type": item.entry_type, "mode": item.mode, "started_at": item.started_at,
        "ended_at": item.ended_at, "source_channel": item.source_channel,
        "is_billable": item.is_billable, "approval_status": item.approval_status,
        "version": item.version,
    }


class TeamInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    code: str = Field(min_length=1, max_length=40)
    parent_team_id: int | None = None
    manager_id: int | None = None
    timezone: str = "Asia/Ulaanbaatar"


class ClientInput(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=240)
    default_currency: str = Field(default="MNT", min_length=3, max_length=3)
    contacts: list[dict] = Field(default_factory=list)


class ProjectInput(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=240)
    client_id: int | None = None
    manager_id: int | None = None
    description: str | None = None
    status: Literal["draft", "planned", "active", "on_hold", "completed", "cancelled"] = "draft"
    starts_on: date | None = None
    ends_on: date | None = None
    budget_minutes: int | None = Field(default=None, ge=0)
    budget_amount: Decimal | None = Field(default=None, ge=0)
    currency: str = Field(default="MNT", min_length=3, max_length=3)
    default_billable: bool = False


class ProjectMemberInput(BaseModel):
    employee_id: int
    project_role: str | None = None
    allocation_percent: Decimal = Field(default=0, ge=0, le=100)
    is_billable: bool = False


class RateInput(BaseModel):
    employee_id: int | None = None
    role_name: str | None = None
    hourly_amount: Decimal = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    effective_from: date
    effective_until: date | None = None


class EnterpriseTaskInput(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    description: str | None = None
    project_id: int | None = None
    parent_task_id: int | None = None
    workflow_status: str = "to_do"
    priority: int = Field(default=2, ge=1, le=4)
    primary_owner_id: int | None = None
    assignee_ids: list[int] = Field(default_factory=list)
    start_at: datetime | None = None
    deadline_at: datetime | None = None
    estimate_minutes: int | None = Field(default=None, ge=0)
    sort_position: Decimal = Decimal("0")


class EnterpriseTaskPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None
    project_id: int | None = None
    parent_task_id: int | None = None
    workflow_status: str | None = None
    priority: int | None = Field(default=None, ge=1, le=4)
    primary_owner_id: int | None = None
    start_at: datetime | None = None
    deadline_at: datetime | None = None
    estimate_minutes: int | None = Field(default=None, ge=0)
    sort_position: Decimal | None = None
    is_archived: bool | None = None


class AssigneesInput(BaseModel):
    employee_ids: list[int]


class DependencyInput(BaseModel):
    predecessor_task_id: int
    dependency_type: str = "blocks"


class CheckItemInput(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    assignee_id: int | None = None
    position: Decimal = Decimal("0")


class TaskCommentInput(BaseModel):
    text: str = Field(min_length=1, max_length=6000)
    mentions: list[int] = Field(default_factory=list)


class TaskCommentPatch(BaseModel):
    text: str | None = Field(default=None, min_length=1, max_length=6000)
    is_resolved: bool | None = None


class SavedViewInput(BaseModel):
    module: Literal["tasks", "projects", "reports", "capacity", "okrs"]
    name: str = Field(min_length=1, max_length=160)
    view_type: str = Field(min_length=1, max_length=40)
    filters: dict = Field(default_factory=dict)
    grouping: dict = Field(default_factory=dict)
    visible_columns: list[str] = Field(default_factory=list)
    sort: list[dict] = Field(default_factory=list)
    is_shared: bool = False


class ClockStartInput(BaseModel):
    mode: Literal["in_person", "remote"]
    project_id: int | None = None
    task_id: int | None = None
    is_billable: bool = False
    notes: str | None = None
    exchange_rate_snapshot_id: int | None = None


class ReportCommentInput(BaseModel):
    text: str = Field(min_length=1, max_length=6000)
    revision_id: int | None = None
    range_metadata: dict | None = None


class ReportDraftInput(BaseModel):
    title: str | None = Field(default=None, max_length=500)
    markdown: str = Field(min_length=1, max_length=100_000)


class CheckinAnswerInput(BaseModel):
    question_id: int
    value_text: str | None = None
    value_numeric: Decimal | None = None
    value_json: dict | list | None = None


class CheckinSubmitInput(BaseModel):
    answers: list[CheckinAnswerInput] = Field(min_length=1, max_length=100)


class CheckinStartInput(BaseModel):
    template_id: int
    local_date: date | None = None


class ExchangeSnapshotInput(BaseModel):
    provider: str = Field(min_length=1, max_length=100)
    base_currency: str = Field(min_length=3, max_length=3)
    quote_currency: str = Field(min_length=3, max_length=3)
    rate: Decimal = Field(gt=0)
    fetched_at: datetime
    source_payload: dict = Field(default_factory=dict)


class ReportBatchInput(BaseModel):
    report_ids: list[int] = Field(min_length=1, max_length=200)


class ObjectiveInput(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    description: str | None = None
    level: Literal["company", "department", "team"] = "company"
    period_start: date
    period_end: date
    owner_team_id: int | None = None
    owner_employee_id: int | None = None


class KeyResultInput(BaseModel):
    title: str
    metric_type: str
    target_value: Decimal
    start_value: Decimal = Decimal("0")
    current_value: Decimal = Decimal("0")
    unit: str | None = None
    due_date: date | None = None


class MilestoneInput(BaseModel):
    title: str
    project_id: int | None = None
    owner_employee_id: int | None = None
    due_date: date | None = None


class CheckinTemplateInput(BaseModel):
    name: str
    team_id: int | None = None
    cadence: str = "daily"
    questions: list[dict] = Field(default_factory=list)


class TimeOffInput(BaseModel):
    employee_id: int
    time_off_type: str = "vacation"
    starts_on: date
    ends_on: date
    partial_day_minutes: int | None = Field(default=None, ge=0)


class AllocationInput(BaseModel):
    employee_id: int
    project_id: int
    starts_on: date
    ends_on: date
    planned_minutes: int | None = Field(default=None, ge=0)
    allocation_percent: Decimal | None = Field(default=None, ge=0, le=100)


class AssistantDraftInput(BaseModel):
    text: str = Field(min_length=1, max_length=6000)
    kind: Literal["task", "report"] = "task"


class CalendarSyncInput(BaseModel):
    task_id: int


async def _daily_report(db: AsyncSession, employee: Employee, local_day: date) -> WorkReport:
    report = (
        await db.execute(
            select(WorkReport).where(
                WorkReport.employee_id == employee.id,
                WorkReport.report_type == "daily",
                WorkReport.period_date == local_day,
            )
        )
    ).scalar_one_or_none()
    if not report:
        report = WorkReport(employee_id=employee.id, report_type="daily", period_date=local_day, status="awaiting")
        db.add(report)
        await db.flush()
    return report


async def _billing_rate(db: AsyncSession, project_id: int | None, employee_id: int, local_day: date) -> tuple[Decimal | None, str | None]:
    if not project_id:
        return None, None
    rate = (
        await db.execute(
            select(ProjectRate)
            .where(
                ProjectRate.project_id == project_id,
                or_(ProjectRate.employee_id == employee_id, ProjectRate.employee_id.is_(None)),
                ProjectRate.effective_from <= local_day,
                or_(ProjectRate.effective_until.is_(None), ProjectRate.effective_until >= local_day),
            )
            .order_by(ProjectRate.employee_id.is_(None), ProjectRate.effective_from.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return (rate.hourly_amount, rate.currency) if rate else (None, None)


async def _active_entry(db: AsyncSession, employee_id: int) -> WorkTimeEntry | None:
    return (
        await db.execute(
            select(WorkTimeEntry)
            .where(WorkTimeEntry.employee_id == employee_id, WorkTimeEntry.ended_at.is_(None))
            .order_by(WorkTimeEntry.started_at.desc())
            .with_for_update()
        )
    ).scalars().first()


async def _task_for_actor(db: AsyncSession, task_id: int, actor: ActorContext, *, write: bool = False) -> Task:
    task = await db.get(Task, task_id)
    if not task or task.organization_id != actor.organization_id:
        raise HTTPException(status_code=404, detail="Task not found")
    if actor.has_any_role(*MANAGEMENT_ROLES):
        return task
    if actor.has_any_role("client_auditor"):
        if write:
            raise HTTPException(status_code=403, detail="Client auditors have read-only task access")
        allowed = await db.scalar(
            select(func.count()).select_from(Project).where(
                Project.id == task.project_id,
                or_(
                    Project.id.in_(select(RoleAssignment.project_id).where(RoleAssignment.account_id == actor.account_id)),
                    Project.client_id.in_(select(RoleAssignment.client_id).where(RoleAssignment.account_id == actor.account_id)),
                ),
            )
        )
        if allowed:
            return task
    elif actor.employee_id:
        assigned = task.assignee_id == actor.employee_id or bool(await db.scalar(select(TaskAssignee.id).where(TaskAssignee.task_id == task.id, TaskAssignee.employee_id == actor.employee_id)))
        if assigned:
            return task
    raise HTTPException(status_code=404, detail="Task not found")


@router.get("/teams")
async def list_teams(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    rows = (await db.execute(select(Team).where(Team.organization_id == actor.organization_id).order_by(Team.name))).scalars().all()
    return [{"id": row.id, "name": row.name, "code": row.code, "manager_id": row.manager_id, "parent_team_id": row.parent_team_id, "timezone": row.timezone, "is_active": row.is_active} for row in rows]


@router.post("/teams", status_code=status.HTTP_201_CREATED)
async def create_team(data: TeamInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles(*MANAGEMENT_ROLES))):
    team = Team(organization_id=actor.organization_id, **data.model_dump())
    db.add(team)
    await db.flush()
    await record_change(db, actor=actor, topic="teams", aggregate_type="team", aggregate_id=team.id, operation="created", after={"name": team.name, "code": team.code})
    await db.commit()
    return {"id": team.id, **data.model_dump()}


@router.get("/clients")
async def list_clients(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    query = select(Client).where(Client.organization_id == actor.organization_id)
    if actor.roles == {"client_auditor"}:
        client_ids = select(RoleAssignment.client_id).where(RoleAssignment.account_id == actor.account_id, RoleAssignment.client_id.isnot(None))
        query = query.where(Client.id.in_(client_ids))
    rows = (await db.execute(query.order_by(Client.name))).scalars().all()
    return [{"id": row.id, "public_id": str(row.public_id), "code": row.code, "name": row.name, "status": row.status, "default_currency": row.default_currency, "contacts": row.contacts} for row in rows]


@router.post("/clients", status_code=status.HTTP_201_CREATED)
async def create_client(data: ClientInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles("admin", "manager"))):
    client = Client(organization_id=actor.organization_id, **data.model_dump())
    db.add(client)
    await db.flush()
    await record_change(db, actor=actor, topic="projects", aggregate_type="client", aggregate_id=client.id, operation="created", after={"name": client.name, "code": client.code})
    await db.commit()
    return {"id": client.id, "public_id": str(client.public_id), **data.model_dump()}


@router.get("/projects")
async def list_projects(status_filter: str | None = Query(default=None, alias="status"), db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    query = select(Project).where(Project.organization_id == actor.organization_id)
    if status_filter:
        query = query.where(Project.status == status_filter)
    if actor.roles == {"client_auditor"}:
        project_ids = select(RoleAssignment.project_id).where(RoleAssignment.account_id == actor.account_id, RoleAssignment.project_id.isnot(None))
        client_ids = select(RoleAssignment.client_id).where(RoleAssignment.account_id == actor.account_id, RoleAssignment.client_id.isnot(None))
        query = query.where(or_(Project.id.in_(project_ids), Project.client_id.in_(client_ids)))
    elif not actor.has_any_role(*MANAGEMENT_ROLES):
        if not actor.employee_id:
            return []
        member_projects = select(ProjectMember.project_id).where(ProjectMember.employee_id == actor.employee_id)
        query = query.where(Project.id.in_(member_projects))
    rows = (await db.execute(query.order_by(Project.status, Project.name))).scalars().all()
    return [_project_out(row) for row in rows]


@router.post("/projects", status_code=status.HTTP_201_CREATED)
async def create_project(data: ProjectInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles("admin", "manager"))):
    project = Project(organization_id=actor.organization_id, **data.model_dump())
    db.add(project)
    await db.flush()
    await record_change(db, actor=actor, topic="projects", aggregate_type="project", aggregate_id=project.id, operation="created", version=project.version, after=_project_out(project))
    await db.commit()
    return _project_out(project)


@router.post("/projects/{project_id}/members", status_code=status.HTTP_201_CREATED)
async def add_project_member(project_id: int, data: ProjectMemberInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles(*MANAGEMENT_ROLES))):
    project = await db.get(Project, project_id)
    if not project or project.organization_id != actor.organization_id:
        raise HTTPException(status_code=404, detail="Project not found")
    member = ProjectMember(project_id=project_id, **data.model_dump())
    db.add(member)
    await db.flush()
    await record_change(db, actor=actor, topic="capacity", aggregate_type="project_member", aggregate_id=member.id, operation="created", after=data.model_dump(mode="json"))
    await db.commit()
    return {"id": member.id, **data.model_dump()}


@router.post("/projects/{project_id}/rates", status_code=status.HTTP_201_CREATED)
async def add_project_rate(project_id: int, data: RateInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles("admin", "manager"))):
    project = await db.get(Project, project_id)
    if not project or project.organization_id != actor.organization_id:
        raise HTTPException(status_code=404, detail="Project not found")
    if not data.employee_id and not data.role_name:
        raise HTTPException(status_code=400, detail="Employee or role scope required")
    rate = ProjectRate(project_id=project_id, **data.model_dump())
    db.add(rate)
    await db.flush()
    await record_change(db, actor=actor, topic="projects", aggregate_type="project_rate", aggregate_id=rate.id, operation="created", after={"project_id": project_id, "currency": rate.currency, "hourly_amount": str(rate.hourly_amount)})
    await db.commit()
    return {"id": rate.id, **data.model_dump()}


@router.post("/projects/{project_id}/exchange-rate-snapshots", status_code=status.HTTP_201_CREATED)
async def create_exchange_snapshot(project_id: int, data: ExchangeSnapshotInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles("admin", "manager"))):
    project = await db.get(Project, project_id)
    if not project or project.organization_id != actor.organization_id:
        raise HTTPException(status_code=404, detail="Project not found")
    payload = json.dumps(data.source_payload, sort_keys=True, separators=(",", ":"), default=str)
    snapshot = ExchangeRateSnapshot(
        provider=data.provider,
        base_currency=data.base_currency.upper(),
        quote_currency=data.quote_currency.upper(),
        rate=data.rate,
        fetched_at=data.fetched_at,
        source_payload_hash=hashlib.sha256(payload.encode()).hexdigest(),
    )
    db.add(snapshot)
    await db.flush()
    await record_change(db, actor=actor, topic="projects", aggregate_type="exchange_rate_snapshot", aggregate_id=snapshot.id, operation="created", after={"project_id": project_id, "provider": snapshot.provider, "pair": f"{snapshot.base_currency}/{snapshot.quote_currency}", "rate": str(snapshot.rate), "fetched_at": snapshot.fetched_at.isoformat()})
    await db.commit()
    return {"id": snapshot.id, "provider": snapshot.provider, "base_currency": snapshot.base_currency, "quote_currency": snapshot.quote_currency, "rate": _decimal(snapshot.rate), "fetched_at": snapshot.fetched_at, "source_payload_hash": snapshot.source_payload_hash}


@router.get("/projects/{project_id}/budget-burn")
async def project_budget_burn(project_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles("admin", "manager", "team_lead"))):
    project = await db.get(Project, project_id)
    if not project or project.organization_id != actor.organization_id:
        raise HTTPException(status_code=404, detail="Project not found")
    entries = (await db.execute(select(WorkTimeEntry).where(WorkTimeEntry.project_id == project_id, WorkTimeEntry.entry_type == "work", WorkTimeEntry.is_billable.is_(True), WorkTimeEntry.approval_status == "approved", WorkTimeEntry.ended_at.isnot(None)))).scalars().all()
    burned = Decimal("0")
    unpriced_minutes = 0
    for entry in entries:
        minutes = Decimal(str((entry.ended_at - entry.started_at).total_seconds() / 60))
        if entry.hourly_rate_snapshot is None or not entry.rate_currency:
            unpriced_minutes += round(float(minutes))
            continue
        amount = minutes * Decimal(entry.hourly_rate_snapshot) / Decimal("60")
        if entry.rate_currency != project.currency:
            snapshot = await db.get(ExchangeRateSnapshot, entry.exchange_rate_snapshot_id) if entry.exchange_rate_snapshot_id else None
            if not snapshot or snapshot.base_currency != entry.rate_currency or snapshot.quote_currency != project.currency:
                unpriced_minutes += round(float(minutes))
                continue
            amount *= Decimal(snapshot.rate)
        burned += amount
    budget = Decimal(project.budget_amount or 0)
    return {"project_id": project.id, "currency": project.currency, "budget_amount": _decimal(budget), "burned_amount": float(burned.quantize(Decimal("0.01"))), "remaining_amount": float((budget - burned).quantize(Decimal("0.01"))) if project.budget_amount is not None else None, "burn_percent": round(float(burned * 100 / budget), 1) if budget > 0 else None, "unpriced_minutes": unpriced_minutes, "historical_snapshots": True}


@router.get("/tasks")
async def list_tasks(project_id: int | None = None, workflow_status: str | None = None, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    query = select(Task).where(Task.organization_id == actor.organization_id, Task.is_archived.is_(False))
    if project_id:
        query = query.where(Task.project_id == project_id)
    if workflow_status:
        query = query.where(Task.workflow_status == workflow_status)
    if actor.has_any_role("client_auditor"):
        scoped_projects = select(RoleAssignment.project_id).where(
            RoleAssignment.account_id == actor.account_id,
            RoleAssignment.project_id.isnot(None),
        )
        scoped_clients = select(RoleAssignment.client_id).where(
            RoleAssignment.account_id == actor.account_id,
            RoleAssignment.client_id.isnot(None),
        )
        client_projects = select(Project.id).where(Project.client_id.in_(scoped_clients))
        query = query.where(or_(Task.project_id.in_(scoped_projects), Task.project_id.in_(client_projects)))
    elif not actor.has_any_role(*MANAGEMENT_ROLES):
        if not actor.employee_id:
            return []
        contributor_tasks = select(TaskAssignee.task_id).where(TaskAssignee.employee_id == actor.employee_id)
        query = query.where(or_(Task.assignee_id == actor.employee_id, Task.id.in_(contributor_tasks)))
    rows = (await db.execute(query.order_by(Task.workflow_status, Task.sort_position, Task.id))).scalars().all()
    return [_task_out(row) for row in rows]


@router.post("/tasks", status_code=status.HTTP_201_CREATED)
async def create_task(data: EnterpriseTaskInput, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    if data.workflow_status not in WORKFLOW_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid workflow status")
    if not actor.has_any_role(*MANAGEMENT_ROLES) and data.primary_owner_id not in {None, actor.employee_id}:
        raise HTTPException(status_code=403, detail="Only managers can assign work to others")
    request_hash = hashlib.sha256(data.model_dump_json().encode()).hexdigest()
    if idempotency_key:
        existing = (
            await db.execute(select(IdempotencyRecord).where(IdempotencyRecord.account_id == actor.account_id, IdempotencyRecord.operation == "create_task", IdempotencyRecord.key == idempotency_key))
        ).scalar_one_or_none()
        if existing:
            if existing.request_hash != request_hash:
                raise HTTPException(status_code=409, detail="Idempotency key was used with different input")
            return existing.response_body
    owner_id = data.primary_owner_id or actor.employee_id
    task = Task(
        organization_id=actor.organization_id, project_id=data.project_id, parent_task_id=data.parent_task_id,
        title=data.title, description=data.description, workflow_status=data.workflow_status,
        status=LEGACY_STATUS[data.workflow_status], priority=data.priority, assignee_id=owner_id,
        start_at=data.start_at, deadline_at=data.deadline_at, estimate_minutes=data.estimate_minutes,
        sort_position=data.sort_position, created_by_id=actor.employee_id,
    )
    db.add(task)
    await db.flush()
    assignees = set(data.assignee_ids)
    if owner_id:
        assignees.add(owner_id)
    for employee_id in assignees:
        db.add(TaskAssignee(task_id=task.id, employee_id=employee_id, assignment_role="primary" if employee_id == owner_id else "contributor"))
    output = _task_out(task)
    await record_change(db, actor=actor, topic="tasks", aggregate_type="task", aggregate_id=task.id, operation="created", version=task.version, after=output)
    if idempotency_key:
        db.add(IdempotencyRecord(account_id=actor.account_id, operation="create_task", key=idempotency_key, request_hash=request_hash, response_status=201, response_body=json.loads(json.dumps(output, default=str)), expires_at=datetime.now(timezone.utc) + timedelta(days=1)))
    await db.commit()
    return output


@router.patch("/tasks/{task_id}")
async def update_task(task_id: int, data: EnterpriseTaskPatch, if_match: str | None = Header(default=None, alias="If-Match"), db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    task = await db.get(Task, task_id, with_for_update=True)
    if not task or task.organization_id != actor.organization_id:
        raise HTTPException(status_code=404, detail="Task not found")
    if not actor.has_any_role(*MANAGEMENT_ROLES) and task.assignee_id != actor.employee_id:
        raise HTTPException(status_code=403, detail="Task is outside your scope")
    if if_match is not None:
        try:
            expected = int(if_match.strip('W/"'))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="If-Match must contain a version") from exc
        if task.version != expected:
            raise HTTPException(status_code=409, detail={"message": "Task changed", "latest": _task_out(task)})
    patch = data.model_dump(exclude_unset=True)
    if patch.get("workflow_status") and patch["workflow_status"] not in WORKFLOW_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid workflow status")
    before = _task_out(task)
    for field, value in patch.items():
        setattr(task, "assignee_id" if field == "primary_owner_id" else field, value)
    if data.workflow_status:
        task.status = LEGACY_STATUS[data.workflow_status]
        task.completed_at = datetime.now(timezone.utc) if data.workflow_status == "done" else None
    task.version += 1
    await db.flush()
    output = _task_out(task)
    await record_change(db, actor=actor, topic="tasks", aggregate_type="task", aggregate_id=task.id, operation="updated", version=task.version, before=before, after=output)
    await db.commit()
    return output


@router.put("/tasks/{task_id}/assignees")
async def replace_assignees(task_id: int, data: AssigneesInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles(*MANAGEMENT_ROLES))):
    task = await db.get(Task, task_id)
    if not task or task.organization_id != actor.organization_id:
        raise HTTPException(status_code=404, detail="Task not found")
    await db.execute(TaskAssignee.__table__.delete().where(TaskAssignee.task_id == task_id))
    for employee_id in sorted(set(data.employee_ids)):
        db.add(TaskAssignee(task_id=task_id, employee_id=employee_id, assignment_role="primary" if employee_id == task.assignee_id else "contributor"))
    task.version += 1
    await record_change(db, actor=actor, topic="tasks", aggregate_type="task", aggregate_id=task.id, operation="assignees_changed", version=task.version, after={"employee_ids": data.employee_ids})
    await db.commit()
    return {"employee_ids": sorted(set(data.employee_ids)), "version": task.version}


@router.post("/tasks/{task_id}/dependencies", status_code=status.HTTP_201_CREATED)
async def add_dependency(task_id: int, data: DependencyInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles(*MANAGEMENT_ROLES))):
    if task_id == data.predecessor_task_id:
        raise HTTPException(status_code=400, detail="A task cannot depend on itself")
    graph_rows = (await db.execute(select(TaskDependency.predecessor_task_id, TaskDependency.successor_task_id))).all()
    graph: dict[int, set[int]] = {}
    for predecessor, successor in graph_rows:
        graph.setdefault(predecessor, set()).add(successor)
    stack = [task_id]
    seen: set[int] = set()
    while stack:
        current = stack.pop()
        if current == data.predecessor_task_id:
            raise HTTPException(status_code=409, detail="Dependency would create a cycle")
        if current not in seen:
            seen.add(current)
            stack.extend(graph.get(current, ()))
    dependency = TaskDependency(predecessor_task_id=data.predecessor_task_id, successor_task_id=task_id, dependency_type=data.dependency_type)
    db.add(dependency)
    await db.flush()
    await record_change(db, actor=actor, topic="tasks", aggregate_type="task_dependency", aggregate_id=dependency.id, operation="created", after={"predecessor_task_id": data.predecessor_task_id, "successor_task_id": task_id})
    await db.commit()
    return {"id": dependency.id, "predecessor_task_id": data.predecessor_task_id, "successor_task_id": task_id}


@router.post("/tasks/{task_id}/check-items", status_code=status.HTTP_201_CREATED)
async def add_check_item(task_id: int, data: CheckItemInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    task = await _task_for_actor(db, task_id, actor, write=True)
    item = TaskCheckItem(task_id=task_id, **data.model_dump())
    db.add(item)
    await db.flush()
    await record_change(db, actor=actor, topic="tasks", aggregate_type="task_check_item", aggregate_id=item.id, operation="created", after={"task_id": task_id, "text": item.text})
    await db.commit()
    return {"id": item.id, "task_id": task_id, **data.model_dump()}


@router.get("/tasks/{task_id}/comments")
async def list_task_comments(task_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await _task_for_actor(db, task_id, actor)
    rows = (await db.execute(select(TaskComment).where(TaskComment.task_id == task_id).order_by(TaskComment.created_at))).scalars().all()
    return [{"id": row.id, "task_id": row.task_id, "author_account_id": row.author_account_id, "author_employee_id": row.author_id, "text": row.text, "mentions": row.mentions, "is_resolved": row.is_resolved, "edited_at": row.edited_at, "created_at": row.created_at} for row in rows]


@router.post("/tasks/{task_id}/comments", status_code=status.HTTP_201_CREATED)
async def create_task_comment(task_id: int, data: TaskCommentInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await _task_for_actor(db, task_id, actor, write=True)
    comment = TaskComment(task_id=task_id, author_id=actor.employee_id, author_account_id=actor.account_id, text=data.text, mentions=sorted(set(data.mentions)))
    db.add(comment)
    await db.flush()
    await record_change(db, actor=actor, topic="tasks", aggregate_type="task_comment", aggregate_id=comment.id, operation="created", after={"task_id": task_id, "text": comment.text, "mentions": comment.mentions})
    await db.commit()
    return {"id": comment.id, "task_id": task_id, "text": comment.text, "mentions": comment.mentions, "is_resolved": False, "created_at": comment.created_at}


@router.patch("/tasks/{task_id}/comments/{comment_id}")
async def update_task_comment(task_id: int, comment_id: int, data: TaskCommentPatch, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await _task_for_actor(db, task_id, actor, write=True)
    comment = await db.get(TaskComment, comment_id, with_for_update=True)
    if not comment or comment.task_id != task_id:
        raise HTTPException(status_code=404, detail="Comment not found")
    if data.text is not None and comment.author_account_id != actor.account_id and not actor.has_any_role(*MANAGEMENT_ROLES):
        raise HTTPException(status_code=403, detail="Only the author can edit this comment")
    if data.text is not None:
        comment.text = data.text
        comment.edited_at = datetime.now(timezone.utc)
    if data.is_resolved is not None:
        comment.is_resolved = data.is_resolved
    await record_change(db, actor=actor, topic="tasks", aggregate_type="task_comment", aggregate_id=comment.id, operation="updated", after={"text": comment.text, "is_resolved": comment.is_resolved})
    await db.commit()
    return {"id": comment.id, "text": comment.text, "is_resolved": comment.is_resolved, "edited_at": comment.edited_at}


async def _authorize_attachment_object(db: AsyncSession, object_type: str, object_id: int, actor: ActorContext, *, write: bool = False) -> None:
    if object_type == "task":
        await _task_for_actor(db, object_id, actor, write=write)
        return
    if object_type == "report":
        report = await db.get(WorkReport, object_id)
        if report and (actor.has_any_role(*MANAGEMENT_ROLES) or report.employee_id == actor.employee_id):
            return
    raise HTTPException(status_code=404, detail="Attachment target not found")


@router.get("/attachments")
async def list_attachments(object_type: Literal["task", "report"], object_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await _authorize_attachment_object(db, object_type, object_id, actor)
    rows = (await db.execute(select(Attachment).where(Attachment.organization_id == actor.organization_id, Attachment.object_type == object_type, Attachment.object_id == object_id).order_by(Attachment.created_at))).scalars().all()
    return [{"id": row.id, "filename": row.filename, "content_type": row.content_type, "size": row.size, "checksum": row.checksum, "scan_status": row.scan_status, "created_at": row.created_at} for row in rows]


@router.post("/attachments", status_code=status.HTTP_201_CREATED)
async def upload_attachment(object_type: Literal["task", "report"], object_id: int, file: UploadFile = File(...), db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await _authorize_attachment_object(db, object_type, object_id, actor, write=True)
    content = await file.read(settings.ATTACHMENT_MAX_BYTES + 1)
    if len(content) > settings.ATTACHMENT_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Attachment exceeds configured size limit")
    if not content:
        raise HTTPException(status_code=400, detail="Attachment is empty")
    filename = (file.filename or "attachment").replace("\\", "/").split("/")[-1].strip()[:240] or "attachment"
    content_type = file.content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    blocked = {"application/x-msdownload", "application/x-sh", "application/x-executable"}
    if content_type in blocked or filename.lower().endswith((".exe", ".dll", ".bat", ".cmd", ".sh")):
        raise HTTPException(status_code=415, detail="Executable attachments are not allowed")
    storage_key = f"{actor.organization_id}/{object_type}/{object_id}/{uuid.uuid4().hex}"
    checksum = hashlib.sha256(content).hexdigest()
    await put_attachment(storage_key, content, content_type)
    attachment = Attachment(organization_id=actor.organization_id, object_type=object_type, object_id=object_id, storage_key=storage_key, filename=filename, content_type=content_type, size=len(content), checksum=checksum, uploaded_by_account_id=actor.account_id, scan_status="accepted")
    db.add(attachment)
    try:
        await db.flush()
        await record_change(db, actor=actor, topic="tasks" if object_type == "task" else "reports", aggregate_type="attachment", aggregate_id=attachment.id, operation="created", after={"object_type": object_type, "object_id": object_id, "filename": filename, "size": len(content), "checksum": checksum})
        await db.commit()
    except Exception:
        await delete_attachment(storage_key)
        raise
    return {"id": attachment.id, "filename": filename, "content_type": content_type, "size": len(content), "checksum": checksum, "scan_status": attachment.scan_status}


@router.get("/attachments/{attachment_id}/download")
async def download_attachment(attachment_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    attachment = await db.get(Attachment, attachment_id)
    if not attachment or attachment.organization_id != actor.organization_id:
        raise HTTPException(status_code=404, detail="Attachment not found")
    await _authorize_attachment_object(db, attachment.object_type, attachment.object_id, actor)
    content = await get_attachment(attachment.storage_key)
    safe_name = attachment.filename.replace('"', "")
    return Response(content, media_type=attachment.content_type, headers={"Content-Disposition": f'attachment; filename="{safe_name}"', "X-Content-Type-Options": "nosniff"})


@router.delete("/attachments/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_attachment(attachment_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    attachment = await db.get(Attachment, attachment_id)
    if not attachment or attachment.organization_id != actor.organization_id:
        raise HTTPException(status_code=404, detail="Attachment not found")
    await _authorize_attachment_object(db, attachment.object_type, attachment.object_id, actor, write=True)
    storage_key = attachment.storage_key
    await record_change(db, actor=actor, topic="tasks" if attachment.object_type == "task" else "reports", aggregate_type="attachment", aggregate_id=attachment.id, operation="deleted", before={"filename": attachment.filename, "object_type": attachment.object_type, "object_id": attachment.object_id})
    await db.delete(attachment)
    await db.commit()
    await delete_attachment(storage_key)


@router.get("/saved-views")
async def list_saved_views(module: str | None = None, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    query = select(SavedView).where(or_(SavedView.account_id == actor.account_id, SavedView.is_shared.is_(True)))
    if module:
        query = query.where(SavedView.module == module)
    rows = (await db.execute(query.order_by(SavedView.name))).scalars().all()
    return [{"id": row.id, "account_id": row.account_id, "module": row.module, "name": row.name, "view_type": row.view_type, "filters": row.filters, "grouping": row.grouping, "visible_columns": row.visible_columns, "sort": row.sort, "is_shared": row.is_shared, "can_edit": row.account_id == actor.account_id} for row in rows]


@router.post("/saved-views", status_code=status.HTTP_201_CREATED)
async def create_saved_view(data: SavedViewInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    if data.is_shared and not actor.has_any_role(*MANAGEMENT_ROLES):
        raise HTTPException(status_code=403, detail="Only managers can share views")
    view = SavedView(account_id=actor.account_id, **data.model_dump())
    db.add(view)
    await db.commit()
    await db.refresh(view)
    return {"id": view.id, **data.model_dump()}


@router.delete("/saved-views/{view_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_saved_view(view_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    view = await db.get(SavedView, view_id)
    if not view or view.account_id != actor.account_id:
        raise HTTPException(status_code=404, detail="Saved view not found")
    await db.delete(view)
    await db.commit()


@router.get("/clock/status")
async def clock_status(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    if not actor.employee_id:
        raise HTTPException(status_code=409, detail="Account is not linked to an employee")
    entry = await _active_entry(db, actor.employee_id)
    return {"active": _entry_out(entry) if entry else None, "server_time": datetime.now(timezone.utc)}


@router.post("/clock/start")
async def clock_start(data: ClockStartInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    if not actor.employee_id:
        raise HTTPException(status_code=409, detail="Account is not linked to an employee")
    employee = await db.get(Employee, actor.employee_id)
    now = datetime.now(timezone.utc)
    local_day = now.astimezone(ZoneInfo(employee.timezone)).date()
    existing = await _active_entry(db, employee.id)
    if existing and existing.entry_type == "work" and existing.mode == data.mode:
        return _entry_out(existing)
    if existing:
        existing.ended_at = now
        existing.version += 1
        await db.flush()
    report = await _daily_report(db, employee, local_day)
    hourly_rate, rate_currency = await _billing_rate(db, data.project_id, employee.id, local_day) if data.is_billable else (None, None)
    if data.exchange_rate_snapshot_id:
        snapshot = await db.get(ExchangeRateSnapshot, data.exchange_rate_snapshot_id)
        if not snapshot:
            raise HTTPException(status_code=400, detail="Exchange-rate snapshot not found")
    entry = WorkTimeEntry(report_id=report.id, employee_id=employee.id, local_work_date=local_day, timezone=employee.timezone, entry_type="work", mode=data.mode, started_at=now, source_channel="web", project_id=data.project_id, task_id=data.task_id, is_billable=data.is_billable, notes=data.notes, hourly_rate_snapshot=hourly_rate, rate_currency=rate_currency, exchange_rate_snapshot_id=data.exchange_rate_snapshot_id)
    db.add(entry)
    await db.flush()
    output = _entry_out(entry)
    await record_change(db, actor=actor, topic="clocks", aggregate_type="time_entry", aggregate_id=entry.id, operation="started", after=output)
    await db.commit()
    return output


@router.post("/clock/break")
async def clock_break(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    if not actor.employee_id:
        raise HTTPException(status_code=409, detail="Account is not linked to an employee")
    employee = await db.get(Employee, actor.employee_id)
    now = datetime.now(timezone.utc)
    active = await _active_entry(db, employee.id)
    if active and active.entry_type == "break":
        return _entry_out(active)
    if not active:
        raise HTTPException(status_code=409, detail="Start work before starting a break")
    active.ended_at = now
    active.version += 1
    await db.flush()
    report = await _daily_report(db, employee, now.astimezone(ZoneInfo(employee.timezone)).date())
    entry = WorkTimeEntry(report_id=report.id, employee_id=employee.id, local_work_date=report.period_date, timezone=employee.timezone, entry_type="break", mode=None, started_at=now, source_channel="web")
    db.add(entry)
    await db.flush()
    output = _entry_out(entry)
    await record_change(db, actor=actor, topic="clocks", aggregate_type="time_entry", aggregate_id=entry.id, operation="break_started", after=output)
    await db.commit()
    return output


@router.post("/clock/resume")
async def clock_resume(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    if not actor.employee_id:
        raise HTTPException(status_code=409, detail="Account is not linked to an employee")
    employee = await db.get(Employee, actor.employee_id)
    now = datetime.now(timezone.utc)
    active = await _active_entry(db, employee.id)
    if not active or active.entry_type != "break":
        raise HTTPException(status_code=409, detail="No active break")
    previous = (
        await db.execute(select(WorkTimeEntry).where(WorkTimeEntry.employee_id == employee.id, WorkTimeEntry.entry_type == "work", WorkTimeEntry.ended_at.isnot(None)).order_by(WorkTimeEntry.ended_at.desc()))
    ).scalars().first()
    active.ended_at = now
    active.version += 1
    await db.flush()
    entry = WorkTimeEntry(report_id=active.report_id, employee_id=employee.id, local_work_date=active.local_work_date, timezone=employee.timezone, entry_type="work", mode=previous.mode if previous else "in_person", started_at=now, source_channel="web", project_id=previous.project_id if previous else None, task_id=previous.task_id if previous else None, is_billable=previous.is_billable if previous else False, hourly_rate_snapshot=previous.hourly_rate_snapshot if previous else None, rate_currency=previous.rate_currency if previous else None, exchange_rate_snapshot_id=previous.exchange_rate_snapshot_id if previous else None)
    db.add(entry)
    await db.flush()
    output = _entry_out(entry)
    await record_change(db, actor=actor, topic="clocks", aggregate_type="time_entry", aggregate_id=entry.id, operation="resumed", after=output)
    await db.commit()
    return output


@router.post("/clock/stop")
async def clock_stop(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    if not actor.employee_id:
        raise HTTPException(status_code=409, detail="Account is not linked to an employee")
    active = await _active_entry(db, actor.employee_id)
    if not active:
        return {"active": None}
    active.ended_at = datetime.now(timezone.utc)
    active.version += 1
    output = _entry_out(active)
    await record_change(db, actor=actor, topic="clocks", aggregate_type="time_entry", aggregate_id=active.id, operation="stopped", version=active.version, after=output)
    await db.commit()
    return output


@router.get("/time-entries")
async def list_time_entries(employee_id: int | None = None, date_from: date | None = None, date_to: date | None = None, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    target = employee_id if actor.has_any_role(*MANAGEMENT_ROLES) else actor.employee_id
    if target is None:
        return []
    query = select(WorkTimeEntry).where(WorkTimeEntry.employee_id == target)
    if date_from:
        query = query.where(WorkTimeEntry.local_work_date >= date_from)
    if date_to:
        query = query.where(WorkTimeEntry.local_work_date <= date_to)
    rows = (await db.execute(query.order_by(WorkTimeEntry.started_at.desc()).limit(500))).scalars().all()
    return [_entry_out(row) for row in rows]


@router.get("/capacity")
async def capacity(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles(*MANAGEMENT_ROLES))):
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    employees = (await db.execute(select(Employee).where(Employee.is_active.is_(True)).order_by(Employee.name))).scalars().all()
    allocations = (await db.execute(select(ResourceAllocation).where(ResourceAllocation.status.in_(("planned", "active")), ResourceAllocation.starts_on <= week_end, ResourceAllocation.ends_on >= week_start))).scalars().all()
    approved_leave = (await db.execute(select(TimeOff).where(TimeOff.status == "approved", TimeOff.starts_on <= week_end, TimeOff.ends_on >= week_start))).scalars().all()
    estimated_tasks = (await db.execute(select(Task).where(Task.organization_id == actor.organization_id, Task.workflow_status.in_(("backlog", "to_do", "in_progress", "review")), Task.estimate_minutes.isnot(None)))).scalars().all()
    by_employee: dict[int, int] = {}
    for allocation in allocations:
        by_employee[allocation.employee_id] = by_employee.get(allocation.employee_id, 0) + int(allocation.planned_minutes or 0)
        if allocation.planned_minutes is None and allocation.allocation_percent is not None:
            employee = next((item for item in employees if item.id == allocation.employee_id), None)
            if employee:
                by_employee[allocation.employee_id] += round(employee.weekly_capacity_minutes * float(allocation.allocation_percent) / 100)
    for task in estimated_tasks:
        if task.assignee_id:
            by_employee[task.assignee_id] = by_employee.get(task.assignee_id, 0) + int(task.estimate_minutes or 0)
    leave_minutes: dict[int, int] = {}
    for leave in approved_leave:
        employee = next((item for item in employees if item.id == leave.employee_id), None)
        if not employee:
            continue
        overlap_start = max(leave.starts_on, week_start)
        overlap_end = min(leave.ends_on, week_end)
        working_days = sum(1 for offset in range((overlap_end - overlap_start).days + 1) if (overlap_start + timedelta(days=offset)).weekday() < 5)
        leave_minutes[leave.employee_id] = leave_minutes.get(leave.employee_id, 0) + (leave.partial_day_minutes or round(employee.weekly_capacity_minutes / 5) * working_days)
    result = []
    for employee in employees:
        available = max(0, employee.weekly_capacity_minutes - leave_minutes.get(employee.id, 0))
        planned = by_employee.get(employee.id, 0)
        utilization = round(planned * 100 / max(available, 1), 1)
        result.append({"employee_id": employee.id, "name": employee.name, "available_minutes": available, "planned_minutes": planned, "leave_minutes": leave_minutes.get(employee.id, 0), "utilization_percent": utilization, "warning": "over" if utilization > 100 else "near" if utilization >= 90 else None})
    return result


@router.post("/time-off", status_code=status.HTTP_201_CREATED)
async def create_time_off(data: TimeOffInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    if not actor.has_any_role(*MANAGEMENT_ROLES) and data.employee_id != actor.employee_id:
        raise HTTPException(status_code=403, detail="Time off is outside your scope")
    if data.ends_on < data.starts_on:
        raise HTTPException(status_code=400, detail="End date must not precede start date")
    item = TimeOff(**data.model_dump(), status="approved" if actor.has_any_role("admin", "manager") else "pending", approved_by_account_id=actor.account_id if actor.has_any_role("admin", "manager") else None)
    db.add(item)
    await db.flush()
    await record_change(db, actor=actor, topic="capacity", aggregate_type="time_off", aggregate_id=item.id, operation="created", after=data.model_dump(mode="json") | {"status": item.status})
    await db.commit()
    return {"id": item.id, "status": item.status, **data.model_dump()}


@router.post("/resource-allocations", status_code=status.HTTP_201_CREATED)
async def create_resource_allocation(data: AllocationInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles(*MANAGEMENT_ROLES))):
    if data.ends_on < data.starts_on or (data.planned_minutes is None and data.allocation_percent is None):
        raise HTTPException(status_code=400, detail="Valid dates and minutes or percentage are required")
    allocation = ResourceAllocation(**data.model_dump(), source="manual", status="planned")
    db.add(allocation)
    await db.flush()
    await record_change(db, actor=actor, topic="capacity", aggregate_type="resource_allocation", aggregate_id=allocation.id, operation="created", after=data.model_dump(mode="json"))
    await db.commit()
    return {"id": allocation.id, **data.model_dump()}


@router.post("/reports/{report_id}/submit")
async def submit_report(report_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    report = await db.get(WorkReport, report_id, with_for_update=True)
    if not report or (not actor.has_any_role(*MANAGEMENT_ROLES) and report.employee_id != actor.employee_id):
        raise HTTPException(status_code=404, detail="Report not found")
    if report.status not in {"awaiting", "draft", "editing", "revision_requested"}:
        raise HTTPException(status_code=409, detail="Report cannot be submitted from its current state")
    report.status = "submitted"
    report.submitted_by_account_id = actor.account_id
    report.submitted_at = datetime.now(timezone.utc)
    report.version += 1
    await record_change(db, actor=actor, topic="reports", aggregate_type="work_report", aggregate_id=report.id, operation="submitted", version=report.version, after={"status": report.status})
    await db.commit()
    return {"id": report.id, "status": report.status, "version": report.version}


@router.get("/reports/{report_id}")
async def report_detail(report_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    report = await db.get(WorkReport, report_id)
    if not report or (not actor.has_any_role(*MANAGEMENT_ROLES) and report.employee_id != actor.employee_id):
        raise HTTPException(status_code=404, detail="Report not found")
    revisions = (await db.execute(select(WorkReportRevision).where(WorkReportRevision.report_id == report_id).order_by(WorkReportRevision.created_at.desc()))).scalars().all()
    comments = (await db.execute(select(ReportComment).where(ReportComment.report_id == report_id).order_by(ReportComment.created_at))).scalars().all()
    return {"id": report.id, "employee_id": report.employee_id, "report_type": report.report_type, "period_date": report.period_date, "status": report.status, "title": report.title, "version": report.version, "revisions": [{"id": row.id, "markdown": row.text, "status": row.status, "author_account_id": row.author_account_id, "created_at": row.created_at} for row in revisions], "comments": [{"id": row.id, "revision_id": row.revision_id, "author_account_id": row.author_account_id, "text": row.text, "range_metadata": row.range_metadata, "is_resolved": row.is_resolved, "created_at": row.created_at} for row in comments]}


@router.put("/reports/{report_id}/draft")
async def save_report_draft(report_id: int, data: ReportDraftInput, if_match: str | None = Header(default=None, alias="If-Match"), db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    report = await db.get(WorkReport, report_id, with_for_update=True)
    if not report or (not actor.has_any_role(*MANAGEMENT_ROLES) and report.employee_id != actor.employee_id):
        raise HTTPException(status_code=404, detail="Report not found")
    if report.status == "approved":
        raise HTTPException(status_code=409, detail="Approved reports are immutable")
    if if_match is not None and int(if_match.strip('W/"')) != report.version:
        raise HTTPException(status_code=409, detail={"message": "Report changed", "latest_version": report.version})
    await db.execute(WorkReportRevision.__table__.update().where(WorkReportRevision.report_id == report_id, WorkReportRevision.status == "draft").values(status="superseded"))
    revision = WorkReportRevision(report_id=report_id, text=data.markdown, author_account_id=actor.account_id, status="draft")
    db.add(revision)
    report.title = data.title
    report.status = "draft"
    report.version += 1
    await db.flush()
    await record_change(db, actor=actor, topic="reports", aggregate_type="work_report", aggregate_id=report.id, operation="draft_saved", version=report.version, after={"title": report.title, "revision_id": revision.id, "status": report.status})
    await db.commit()
    return {"id": report.id, "title": report.title, "status": report.status, "version": report.version, "revision_id": revision.id, "markdown": revision.text}


@router.get("/reports")
async def list_enterprise_reports(
    report_status: str | None = Query(default=None, alias="status"),
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    query = select(WorkReport, Employee.name).join(Employee, Employee.id == WorkReport.employee_id)
    if not actor.has_any_role(*MANAGEMENT_ROLES):
        if not actor.employee_id:
            return []
        query = query.where(WorkReport.employee_id == actor.employee_id)
    if report_status:
        query = query.where(WorkReport.status == report_status)
    rows = (await db.execute(query.order_by(WorkReport.period_date.desc(), WorkReport.id.desc()).limit(500))).all()
    return [
        {
            "id": report.id, "employee_id": report.employee_id, "employee_name": employee_name,
            "report_type": report.report_type, "period_date": report.period_date,
            "status": report.status, "title": report.title, "submitted_at": report.submitted_at,
            "reviewed_at": report.reviewed_at, "version": report.version, "updated_at": report.updated_at,
        }
        for report, employee_name in rows
    ]


async def _review_report(report_id: int, target_status: str, operation: str, db: AsyncSession, actor: ActorContext) -> dict:
    report = await db.get(WorkReport, report_id, with_for_update=True)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    if report.status != "submitted":
        raise HTTPException(status_code=409, detail="Only submitted reports can be reviewed")
    report.status = target_status
    report.reviewer_account_id = actor.account_id
    report.reviewed_at = datetime.now(timezone.utc)
    report.version += 1
    if target_status == "approved":
        revision = (await db.execute(select(WorkReportRevision).where(WorkReportRevision.report_id == report.id, WorkReportRevision.status != "deleted").order_by(WorkReportRevision.id.desc()))).scalars().first()
        if revision:
            revision.status = "approved"
            report.approved_revision_id = revision.id
    await record_change(db, actor=actor, topic="reports", aggregate_type="work_report", aggregate_id=report.id, operation=operation, version=report.version, after={"status": report.status})
    return {"id": report.id, "status": report.status, "version": report.version}


@router.post("/reports/{report_id}/request-revision")
async def request_revision(report_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles(*MANAGEMENT_ROLES))):
    output = await _review_report(report_id, "revision_requested", "revision_requested", db, actor)
    await db.commit()
    return output


@router.post("/reports/{report_id}/approve")
async def approve_report(report_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles(*MANAGEMENT_ROLES))):
    output = await _review_report(report_id, "approved", "approved", db, actor)
    await db.commit()
    return output


@router.post("/reports/batch-approve")
async def batch_approve_reports(data: ReportBatchInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles(*MANAGEMENT_ROLES))):
    outputs = []
    for report_id in dict.fromkeys(data.report_ids):
        outputs.append(await _review_report(report_id, "approved", "approved", db, actor))
    await db.commit()
    return {"approved": outputs, "count": len(outputs)}


@router.post("/reports/{report_id}/comments", status_code=status.HTTP_201_CREATED)
async def add_report_comment(report_id: int, data: ReportCommentInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    report = await db.get(WorkReport, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    comment = ReportComment(report_id=report_id, author_account_id=actor.account_id, **data.model_dump())
    db.add(comment)
    await db.flush()
    await record_change(db, actor=actor, topic="reports", aggregate_type="report_comment", aggregate_id=comment.id, operation="created", after={"report_id": report_id, "text": comment.text})
    await db.commit()
    return {"id": comment.id, "report_id": report_id, **data.model_dump()}


@router.patch("/reports/{report_id}/comments/{comment_id}")
async def resolve_report_comment(report_id: int, comment_id: int, is_resolved: bool, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    report = await db.get(WorkReport, report_id)
    if not report or (not actor.has_any_role(*MANAGEMENT_ROLES) and report.employee_id != actor.employee_id):
        raise HTTPException(status_code=404, detail="Report not found")
    comment = await db.get(ReportComment, comment_id)
    if not comment or comment.report_id != report_id:
        raise HTTPException(status_code=404, detail="Comment not found")
    comment.is_resolved = is_resolved
    await record_change(db, actor=actor, topic="reports", aggregate_type="report_comment", aggregate_id=comment.id, operation="resolved" if is_resolved else "reopened", after={"is_resolved": is_resolved})
    await db.commit()
    return {"id": comment.id, "is_resolved": comment.is_resolved}


@router.post("/checkin-templates", status_code=status.HTTP_201_CREATED)
async def create_checkin_template(data: CheckinTemplateInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles(*MANAGEMENT_ROLES))):
    template = CheckinTemplate(organization_id=actor.organization_id, team_id=data.team_id, name=data.name, cadence=data.cadence)
    db.add(template)
    await db.flush()
    for position, question in enumerate(data.questions):
        db.add(CheckinQuestion(template_id=template.id, prompt=question.get("prompt", {"mn": question.get("text", "")}), answer_type=question.get("answer_type", "text"), choices=question.get("choices", []), is_required=question.get("is_required", True), position=position))
    await record_change(db, actor=actor, topic="checkins", aggregate_type="checkin_template", aggregate_id=template.id, operation="created", after={"name": template.name, "question_count": len(data.questions)})
    await db.commit()
    return {"id": template.id, "name": template.name, "cadence": template.cadence, "question_count": len(data.questions)}


@router.get("/checkin-templates")
async def list_checkin_templates(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    templates = (await db.execute(select(CheckinTemplate).where(CheckinTemplate.organization_id == actor.organization_id, CheckinTemplate.is_active.is_(True)).order_by(CheckinTemplate.name))).scalars().all()
    output = []
    for template in templates:
        questions = (await db.execute(select(CheckinQuestion).where(CheckinQuestion.template_id == template.id).order_by(CheckinQuestion.position))).scalars().all()
        output.append({"id": template.id, "name": template.name, "team_id": template.team_id, "cadence": template.cadence, "questions": [{"id": q.id, "prompt": q.prompt, "answer_type": q.answer_type, "choices": q.choices, "is_required": q.is_required, "position": q.position} for q in questions]})
    return output


@router.get("/checkins")
async def list_checkins(local_date: date | None = None, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    if not actor.employee_id:
        return []
    query = select(Checkin).where(Checkin.employee_id == actor.employee_id)
    if local_date:
        query = query.where(Checkin.local_date == local_date)
    rows = (await db.execute(query.order_by(Checkin.local_date.desc()).limit(100))).scalars().all()
    return [{"id": row.id, "template_id": row.template_id, "local_date": row.local_date, "status": row.status, "source": row.source, "started_at": row.started_at, "submitted_at": row.submitted_at} for row in rows]


@router.post("/checkins", status_code=status.HTTP_201_CREATED)
async def start_checkin(data: CheckinStartInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    if not actor.employee_id:
        raise HTTPException(status_code=409, detail="Account is not linked to an employee")
    template = await db.get(CheckinTemplate, data.template_id)
    if not template or template.organization_id != actor.organization_id or not template.is_active:
        raise HTTPException(status_code=404, detail="Check-in template not found")
    local_day = data.local_date or date.today()
    existing = (await db.execute(select(Checkin).where(Checkin.employee_id == actor.employee_id, Checkin.template_id == data.template_id, Checkin.local_date == local_day))).scalar_one_or_none()
    if existing:
        return {"id": existing.id, "template_id": existing.template_id, "local_date": existing.local_date, "status": existing.status}
    checkin = Checkin(employee_id=actor.employee_id, template_id=data.template_id, local_date=local_day, status="in_progress", source="web", started_at=datetime.now(timezone.utc))
    db.add(checkin)
    await db.flush()
    await record_change(db, actor=actor, topic="checkins", aggregate_type="checkin", aggregate_id=checkin.id, operation="started", after={"template_id": checkin.template_id, "local_date": str(local_day)})
    await db.commit()
    return {"id": checkin.id, "template_id": checkin.template_id, "local_date": checkin.local_date, "status": checkin.status}


@router.post("/checkins/{checkin_id}/submit")
async def submit_checkin(checkin_id: int, data: CheckinSubmitInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    checkin = await db.get(Checkin, checkin_id, with_for_update=True)
    if not checkin or checkin.employee_id != actor.employee_id:
        raise HTTPException(status_code=404, detail="Check-in not found")
    questions = (await db.execute(select(CheckinQuestion).where(CheckinQuestion.template_id == checkin.template_id))).scalars().all()
    by_id = {answer.question_id: answer for answer in data.answers}
    question_ids = {question.id for question in questions}
    if not set(by_id).issubset(question_ids) or any(question.is_required and question.id not in by_id for question in questions):
        raise HTTPException(status_code=400, detail="Required check-in answers are missing or invalid")
    await db.execute(CheckinAnswer.__table__.delete().where(CheckinAnswer.checkin_id == checkin.id))
    for answer in by_id.values():
        db.add(CheckinAnswer(checkin_id=checkin.id, **answer.model_dump()))
    checkin.status = "submitted"
    checkin.submitted_at = datetime.now(timezone.utc)
    await record_change(db, actor=actor, topic="checkins", aggregate_type="checkin", aggregate_id=checkin.id, operation="submitted", after={"answer_count": len(by_id), "status": checkin.status})
    await db.commit()
    return {"id": checkin.id, "status": checkin.status, "submitted_at": checkin.submitted_at}


@router.get("/objectives")
async def list_objectives(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    rows = (await db.execute(select(Objective).where(Objective.organization_id == actor.organization_id).order_by(Objective.period_start.desc(), Objective.id.desc()))).scalars().all()
    return [{"id": row.id, "title": row.title, "description": row.description, "level": row.level, "period_start": row.period_start, "period_end": row.period_end, "status": row.status, "version": row.version} for row in rows]


@router.post("/objectives", status_code=status.HTTP_201_CREATED)
async def create_objective(data: ObjectiveInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles(*MANAGEMENT_ROLES))):
    objective = Objective(organization_id=actor.organization_id, **data.model_dump())
    db.add(objective)
    await db.flush()
    await record_change(db, actor=actor, topic="okrs", aggregate_type="objective", aggregate_id=objective.id, operation="created", after=data.model_dump(mode="json"))
    await db.commit()
    return {"id": objective.id, "version": objective.version, **data.model_dump()}


@router.post("/objectives/{objective_id}/key-results", status_code=status.HTTP_201_CREATED)
async def create_key_result(objective_id: int, data: KeyResultInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles(*MANAGEMENT_ROLES))):
    objective = await db.get(Objective, objective_id)
    if not objective or objective.organization_id != actor.organization_id:
        raise HTTPException(status_code=404, detail="Objective not found")
    result = KeyResult(objective_id=objective_id, **data.model_dump())
    db.add(result)
    await db.flush()
    await record_change(db, actor=actor, topic="okrs", aggregate_type="key_result", aggregate_id=result.id, operation="created", after={"objective_id": objective_id, "title": result.title})
    await db.commit()
    return {"id": result.id, "objective_id": objective_id, **data.model_dump()}


@router.post("/milestones", status_code=status.HTTP_201_CREATED)
async def create_milestone(data: MilestoneInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles(*MANAGEMENT_ROLES))):
    milestone = Milestone(organization_id=actor.organization_id, **data.model_dump())
    db.add(milestone)
    await db.flush()
    await record_change(db, actor=actor, topic="okrs", aggregate_type="milestone", aggregate_id=milestone.id, operation="created", after=data.model_dump(mode="json"))
    await db.commit()
    return {"id": milestone.id, **data.model_dump()}


@router.get("/analytics/summary")
async def analytics_summary(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    task_total = await db.scalar(select(func.count()).select_from(Task).where(Task.organization_id == actor.organization_id)) or 0
    completed = await db.scalar(select(func.count()).select_from(Task).where(Task.organization_id == actor.organization_id, Task.workflow_status == "done")) or 0
    active_projects = await db.scalar(select(func.count()).select_from(Project).where(Project.organization_id == actor.organization_id, Project.status == "active")) or 0
    worked = await db.scalar(select(func.coalesce(func.sum(func.extract("epoch", WorkTimeEntry.ended_at - WorkTimeEntry.started_at) / 60), 0)).where(WorkTimeEntry.entry_type == "work", WorkTimeEntry.ended_at.isnot(None))) or 0
    billable = await db.scalar(select(func.coalesce(func.sum(func.extract("epoch", WorkTimeEntry.ended_at - WorkTimeEntry.started_at) / 60), 0)).where(WorkTimeEntry.entry_type == "work", WorkTimeEntry.is_billable.is_(True), WorkTimeEntry.approval_status == "approved", WorkTimeEntry.ended_at.isnot(None))) or 0
    return {"task_total": task_total, "completed_tasks": completed, "completion_rate": round(completed * 100 / max(task_total, 1), 1), "active_projects": active_projects, "worked_minutes": round(float(worked)), "billable_minutes": round(float(billable)), "billable_ratio": round(float(billable) * 100 / max(float(worked), 1), 1)}


@router.post("/assistant/drafts")
async def assistant_draft(data: AssistantDraftInput, actor: ActorContext = Depends(get_actor)):
    text = data.text.strip()
    return {"kind": data.kind, "requires_confirmation": True, "draft": {"title": text[:120] if data.kind == "task" else "AI-assisted report", "description": text if data.kind == "task" else None, "markdown": text if data.kind == "report" else None}, "actor_employee_id": actor.employee_id}


@router.post("/voice/transcriptions")
async def transcribe_voice(file: UploadFile = File(...), actor: ActorContext = Depends(get_actor)):
    if file.content_type not in {"audio/ogg", "audio/webm", "audio/wav", "audio/mpeg", "audio/mp4"}:
        raise HTTPException(status_code=415, detail="Unsupported audio format")
    audio = await file.read(12 * 1024 * 1024 + 1)
    if len(audio) > 12 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Audio file exceeds 12 MB")
    text, error = await transcribe(audio, filename=file.filename or "voice.ogg")
    if error:
        raise HTTPException(status_code=502, detail=error)
    return {"transcript": text, "retained": False, "requires_review": True}


@router.get("/integrations/google-calendar/connect")
async def google_calendar_connect(actor: ActorContext = Depends(get_actor)):
    if not google_is_configured():
        return {"provider": "google", "status": "configuration_required", "fallback": "calendar_template_url", "message": "Configure Google OAuth client credentials to enable synchronized calendars."}
    return {"provider": "google", "status": "ready", "authorization_url": google_authorization_url(actor.account_id)}


@router.get("/integrations/google-calendar/callback")
async def google_calendar_callback(code: str | None = None, state: str | None = None, error: str | None = None, db: AsyncSession = Depends(get_db)):
    if error or not code or not state or not google_is_configured():
        return RedirectResponse(f"{settings.PUBLIC_APP_URL.rstrip('/')}/administration?calendar=error", status_code=303)
    try:
        account_id = account_from_state(state)
        token = await google_exchange_code(code)
    except (ValueError, RuntimeError):
        return RedirectResponse(f"{settings.PUBLIC_APP_URL.rstrip('/')}/administration?calendar=error", status_code=303)
    connection = (await db.execute(select(CalendarConnection).where(CalendarConnection.account_id == account_id, CalendarConnection.provider == "google"))).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if not connection:
        connection = CalendarConnection(account_id=account_id, provider="google")
        db.add(connection)
    connection.encrypted_access_token = encrypt_secret(token["access_token"])
    if token.get("refresh_token"):
        connection.encrypted_refresh_token = encrypt_secret(token["refresh_token"])
    connection.token_expires_at = now + timedelta(seconds=int(token.get("expires_in", 3600)))
    connection.scopes = str(token.get("scope", "")).split()
    connection.status = "active"
    connection.last_error = None
    await db.commit()
    return RedirectResponse(f"{settings.PUBLIC_APP_URL.rstrip('/')}/administration?calendar=connected", status_code=303)


@router.post("/integrations/google-calendar/sync", status_code=status.HTTP_202_ACCEPTED)
async def google_calendar_sync(data: CalendarSyncInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    connection = (await db.execute(select(CalendarConnection).where(CalendarConnection.account_id == actor.account_id, CalendarConnection.provider == "google", CalendarConnection.status == "active"))).scalar_one_or_none()
    if not connection:
        raise HTTPException(status_code=409, detail="Connect Google Calendar first")
    await _task_for_actor(db, data.task_id, actor)
    job = JobQueue(job_type="calendar_sync", payload={"account_id": actor.account_id, "task_id": data.task_id}, dedup_key=f"calendar-sync:{actor.account_id}:{data.task_id}:{uuid.uuid4().hex}")
    db.add(job)
    await db.commit()
    return {"status": "queued", "task_id": data.task_id}


@router.post("/integrations/google-calendar/disconnect", status_code=status.HTTP_204_NO_CONTENT)
async def google_calendar_disconnect(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    connection = (await db.execute(select(CalendarConnection).where(CalendarConnection.account_id == actor.account_id, CalendarConnection.provider == "google"))).scalar_one_or_none()
    if connection:
        await db.delete(connection)
        await db.commit()
