from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import mimetypes
import secrets
import uuid
from difflib import SequenceMatcher
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo

import aiohttp

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.enterprise_deps import ActorContext, get_actor, require_roles
from app.models.models import (
    CalendarConnection,
    CalendarEntry,
    HolidayRecord,
    AssistantConversation,
    AssistantMessage,
    Attachment,
    AuditLog,
    CheckinQuestion,
    CheckinTemplate,
    Checkin,
    CheckinAnswer,
    Client,
    CompanyPlanItem,
    CompanyLibraryItem,
    CompanyKnowledge,
    Employee,
    EmployeeQuestion,
    ExchangeRateSnapshot,
    IdempotencyRecord,
    JobQueue,
    KeyResult,
    Milestone,
    ManagerSettings,
    Objective,
    PersonalTimeBlock,
    Project,
    ProjectRequest,
    ProjectMember,
    ProjectRate,
    Question,
    ReportComment,
    ResourceAllocation,
    ResourceGrant,
    ResourcePolicy,
    RoleAssignment,
    SavedView,
    Task,
    TaskComment,
    TaskAssignee,
    TaskReviewer,
    TaskCheckItem,
    TaskDependency,
    Team,
    TeamMember,
    TimeOff,
    WorkReport,
    WorkReportRevision,
    WorkTimeEntry,
    Organization,
    UserAccount,
    UserNotification,
)
from app.services.enterprise_events import record_change
from app.services.attachment_storage import delete_attachment, get_attachment, put_attachment
from app.core.config import settings
from app.services import voice_service
from app.services.google_calendar import account_from_state, authorization_url as google_authorization_url, exchange_code as google_exchange_code, is_configured as google_is_configured, stop_watch as google_stop_watch
from app.services.secret_box import decrypt_secret, encrypt_secret
from app.services import assistant_ai, exchange_rate_service
from app.services.knowledge_service import rank_knowledge
from app.services.malware_scanner import MalwareDetected, MalwareScanUnavailable, scan_upload
from app.services.user_notifications import create_notifications
from app.services.collaboration_permissions import ALL_EMPLOYEE_ROLES, SETTINGS_KEY, actor_can_assign_tasks, configured_assignment_roles
from app.services import enterprise_tools


router = APIRouter()
MANAGEMENT_ROLES = ("admin", "manager", "team_lead")
WORKFLOW_STATUSES = {"backlog", "to_do", "in_progress", "review", "done", "cancelled"}
LEGACY_STATUS = {
    "backlog": "open", "to_do": "open", "in_progress": "in_progress",
    "review": "open", "done": "done", "cancelled": "cancelled",
}


class PermissionSettingsInput(BaseModel):
    task_assignment_roles: list[Literal["admin", "manager", "team_lead", "member", "contractor", "client_auditor"]]


BRANDING_KEY = "branding"
LEGACY_LOGOS = {
    "legacy-aio": "/oyuns-aio-logo.png",
    "legacy-icon": "/favicon.png",
}
BRANDING_THEMES = ("light", "dark")
BRANDING_MAX_BYTES = 2 * 1024 * 1024
BRANDING_TYPES = {"image/png", "image/jpeg", "image/webp"}


class BrandingSelectionInput(BaseModel):
    theme: Literal["light", "dark"]
    source: Literal["legacy-aio", "legacy-icon", "default"]


def _branding_out(organization: Organization) -> dict:
    branding = (organization.settings or {}).get(BRANDING_KEY, {})
    sources = {theme: branding.get(theme, "default") for theme in BRANDING_THEMES}
    return {
        "light_logo": LEGACY_LOGOS.get(sources["light"], sources["light"] if sources["light"].startswith("data:image/") else LEGACY_LOGOS["legacy-icon"]),
        "dark_logo": LEGACY_LOGOS.get(sources["dark"], sources["dark"] if sources["dark"].startswith("data:image/") else LEGACY_LOGOS["legacy-aio"]),
        "light_source": sources["light"],
        "dark_source": sources["dark"],
        "legacy_options": [{"value": "legacy-aio", "label": "OYUNS All-in-One", "url": LEGACY_LOGOS["legacy-aio"]}, {"value": "legacy-icon", "label": "OYUNS icon", "url": LEGACY_LOGOS["legacy-icon"]}],
    }


async def _management_account_ids(db: AsyncSession, organization_id: int) -> set[int]:
    return set((await db.execute(
        select(RoleAssignment.account_id).join(UserAccount, UserAccount.id == RoleAssignment.account_id).where(
            UserAccount.organization_id == organization_id,
            UserAccount.status == "active",
            RoleAssignment.role.in_(MANAGEMENT_ROLES),
        )
    )).scalars().all())


@router.get("/notifications")
async def list_notifications(
    cursor: int | None = None,
    limit: int = Query(default=20, ge=1, le=50),
    unread_only: bool = False,
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    query = select(UserNotification).where(UserNotification.recipient_account_id == actor.account_id)
    if cursor:
        query = query.where(UserNotification.id < cursor)
    if unread_only:
        query = query.where(UserNotification.read_at.is_(None))
    rows = (await db.execute(query.order_by(UserNotification.id.desc()).limit(limit + 1))).scalars().all()
    page = rows[:limit]
    unread_count = await db.scalar(select(func.count()).select_from(UserNotification).where(UserNotification.recipient_account_id == actor.account_id, UserNotification.read_at.is_(None)))
    return {
        "items": [{
            "id": item.id, "kind": item.kind, "title": item.title, "body": item.body,
            "target_url": item.target_url, "payload": item.payload, "created_at": item.created_at,
            "read_at": item.read_at, "telegram_status": item.telegram_status,
        } for item in page],
        "unread_count": unread_count or 0,
        "next_cursor": page[-1].id if len(rows) > limit and page else None,
    }


@router.post("/notifications/{notification_id:int}/read")
async def read_notification(notification_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    item = await db.get(UserNotification, notification_id, with_for_update=True)
    if not item or item.recipient_account_id != actor.account_id:
        raise HTTPException(status_code=404, detail="Notification not found")
    item.read_at = item.read_at or datetime.now(timezone.utc)
    await db.commit()
    return {"id": item.id, "read_at": item.read_at}


@router.post("/notifications/read-all")
async def read_all_notifications(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    now = datetime.now(timezone.utc)
    rows = (await db.execute(select(UserNotification).where(UserNotification.recipient_account_id == actor.account_id, UserNotification.read_at.is_(None)))).scalars().all()
    for item in rows:
        item.read_at = now
    await db.commit()
    return {"updated": len(rows), "read_at": now}


@router.get("/settings/permissions")
async def get_permission_settings(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    organization = await db.get(Organization, actor.organization_id)
    return {"task_assignment_roles": sorted(configured_assignment_roles(organization)), "available_roles": sorted(ALL_EMPLOYEE_ROLES)}


@router.put("/settings/permissions")
async def update_permission_settings(data: PermissionSettingsInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles("admin", "manager"))):
    organization = await db.get(Organization, actor.organization_id, with_for_update=True)
    roles = sorted(set(data.task_assignment_roles))
    organization.settings = {**(organization.settings or {}), SETTINGS_KEY: roles}
    await record_change(db, actor=actor, topic="settings", aggregate_type="organization_permissions", aggregate_id=organization.id, operation="updated", after={SETTINGS_KEY: roles})
    await db.commit()
    return {"task_assignment_roles": roles, "available_roles": sorted(ALL_EMPLOYEE_ROLES)}


@router.get("/settings/branding")
async def get_branding_settings(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    organization = await db.get(Organization, actor.organization_id)
    return _branding_out(organization)


@router.put("/settings/branding")
async def update_branding_settings(data: BrandingSelectionInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles("admin", "manager"))):
    organization = await db.get(Organization, actor.organization_id, with_for_update=True)
    branding = {**((organization.settings or {}).get(BRANDING_KEY) or {}), data.theme: data.source}
    organization.settings = {**(organization.settings or {}), BRANDING_KEY: branding}
    await record_change(db, actor=actor, topic="settings", aggregate_type="organization_branding", aggregate_id=organization.id, operation="updated", after={data.theme: data.source})
    await db.commit()
    return _branding_out(organization)


@router.post("/settings/branding/logo")
async def upload_branding_logo(theme: Literal["light", "dark"], file: UploadFile = File(...), db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles("admin", "manager"))):
    content = await file.read(BRANDING_MAX_BYTES + 1)
    if not content:
        raise HTTPException(status_code=400, detail="Logo is empty")
    if len(content) > BRANDING_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Logo exceeds the 2 MB limit")
    content_type = (file.content_type or "").lower()
    if content_type not in BRANDING_TYPES:
        raise HTTPException(status_code=415, detail="Logo must be PNG, JPEG, or WebP")
    if (content_type == "image/png" and not content.startswith(b"\x89PNG\r\n\x1a\n")) or (content_type == "image/jpeg" and not content.startswith(b"\xff\xd8\xff")) or (content_type == "image/webp" and (not content.startswith(b"RIFF") or content[8:12] != b"WEBP")):
        raise HTTPException(status_code=415, detail="Logo content does not match its image type")
    organization = await db.get(Organization, actor.organization_id, with_for_update=True)
    data_url = f"data:{content_type};base64,{base64.b64encode(content).decode('ascii')}"
    branding = {**((organization.settings or {}).get(BRANDING_KEY) or {}), theme: data_url}
    organization.settings = {**(organization.settings or {}), BRANDING_KEY: branding}
    await record_change(db, actor=actor, topic="settings", aggregate_type="organization_branding", aggregate_id=organization.id, operation="uploaded", after={theme: "uploaded"})
    await db.commit()
    return _branding_out(organization)


def _decimal(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _birthday_occurrences(birthday: date, period_start: date, period_end: date) -> list[date]:
    occurrences = []
    for year in range(period_start.year, period_end.year + 1):
        try:
            occurrence = birthday.replace(year=year)
        except ValueError:
            occurrence = date(year, 2, 28)
        if period_start <= occurrence <= period_end:
            occurrences.append(occurrence)
    return occurrences


def _project_out(item: Project) -> dict:
    return {
        "id": item.id, "public_id": str(item.public_id), "client_id": item.client_id,
        "manager_id": item.manager_id, "code": item.code, "name": item.name,
        "description": item.description, "status": item.status,
        "starts_on": item.starts_on, "ends_on": item.ends_on,
        "budget_minutes": item.budget_minutes, "budget_amount": _decimal(item.budget_amount),
        "currency": item.currency, "default_billable": item.default_billable,
        "version": item.version, "updated_at": item.updated_at,
        "archived_at": item.archived_at,
    }


def _task_out(item: Task) -> dict:
    return {
        "id": item.id, "public_id": str(item.public_id), "project_id": item.project_id,
        "parent_task_id": item.parent_task_id, "title": item.title,
        "description": item.description, "workflow_status": item.workflow_status,
        "priority": item.priority, "primary_owner_id": item.assignee_id, "reviewer_id": getattr(item, "reviewer_id", None), "reviewer_ids": [],
        "start_at": item.start_at, "deadline_at": item.deadline_at,
        "estimate_minutes": item.estimate_minutes, "sort_position": _decimal(item.sort_position),
        "work_location_type": item.work_location_type, "work_location": item.work_location,
        "version": item.version, "is_archived": item.is_archived,
        "created_by_id": item.created_by_id,
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
    member_ids: list[int] = Field(default_factory=list)
    description: str | None = None
    status: Literal["draft", "planned", "active", "on_hold", "completed", "cancelled"] = "draft"
    starts_on: date | None = None
    ends_on: date | None = None
    budget_minutes: int | None = Field(default=None, ge=0)
    budget_amount: Decimal | None = Field(default=None, ge=0)
    currency: str = Field(default="MNT", min_length=3, max_length=3)
    default_billable: bool = False


class ProjectPatch(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=40)
    name: str | None = Field(default=None, min_length=1, max_length=240)
    client_id: int | None = None
    manager_id: int | None = None
    member_ids: list[int] | None = None
    description: str | None = None
    status: Literal["draft", "planned", "active", "on_hold", "completed", "cancelled"] | None = None
    starts_on: date | None = None
    ends_on: date | None = None
    budget_minutes: int | None = Field(default=None, ge=0)
    budget_amount: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)


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
    priority: int = Field(default=2, ge=1, le=3)
    primary_owner_id: int | None = None
    assignee_ids: list[int] = Field(default_factory=list)
    reviewer_id: int | None = None
    reviewer_ids: list[int] = Field(default_factory=list)
    start_at: datetime | None = None
    deadline_at: datetime | None = None
    estimate_minutes: int | None = Field(default=None, ge=0)
    work_location_type: Literal["office", "remote", "custom"] | None = None
    work_location: str | None = Field(default=None, max_length=500)
    sort_position: Decimal = Decimal("0")


class EnterpriseTaskPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None
    project_id: int | None = None
    parent_task_id: int | None = None
    workflow_status: str | None = None
    priority: int | None = Field(default=None, ge=1, le=3)
    primary_owner_id: int | None = None
    assignee_ids: list[int] | None = None
    reviewer_id: int | None = None
    reviewer_ids: list[int] | None = None
    start_at: datetime | None = None
    deadline_at: datetime | None = None
    estimate_minutes: int | None = Field(default=None, ge=0)
    work_location_type: Literal["office", "remote", "custom"] | None = None
    work_location: str | None = Field(default=None, max_length=500)
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


class CheckItemPatch(BaseModel):
    text: str | None = Field(default=None, min_length=1, max_length=500)
    assignee_id: int | None = None
    position: Decimal | None = None
    is_completed: bool | None = None


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


class ReportCreateInput(BaseModel):
    report_type: Literal["daily", "monthly"] = "daily"
    period_date: date


class CheckinAnswerInput(BaseModel):
    question_id: int
    value_text: str | None = None
    value_numeric: Decimal | None = None
    value_json: dict | list | None = None


class CheckinSubmitInput(BaseModel):
    answers: list[CheckinAnswerInput] = Field(default_factory=list, max_length=100)


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


class PersonalTimeBlockInput(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    starts_at: datetime
    ends_at: datetime
    task_id: int | None = None


class PersonalTimeBlockPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    task_id: int | None = None


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


class AssistantChatInput(BaseModel):
    text: str = Field(min_length=1, max_length=6000)
    conversation_id: int | None = None
    voice_mode: bool = False


class AssistantToolRequest(BaseModel):
    tool_name: Literal["file_search_tool", "get_stats_tool", "project_mgmt_tool", "project_mgmt_update_tool", "calendar_tool"]
    arguments: dict = Field(default_factory=dict)


class AssistantActionConfirmInput(BaseModel):
    token: str = Field(min_length=20, max_length=200)


class ResourceGrantInput(BaseModel):
    principal_type: Literal["role", "team", "project", "account"]
    principal_key: str = Field(min_length=1, max_length=128)


class ResourcePolicyInput(BaseModel):
    classification: Literal["public_link_safe", "internal", "confidential", "restricted"]
    inherit_from_parent: bool = True
    grants: list[ResourceGrantInput] = Field(default_factory=list, max_length=100)


class ProjectRequestReview(BaseModel):
    action: Literal["approved", "rejected"]
    note: str | None = Field(default=None, max_length=2000)


class CalendarEntryInput(BaseModel):
    kind: Literal["reminder", "event"]
    visibility: Literal["private", "company"] = "private"
    title: str = Field(min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=6000)
    starts_at: datetime
    ends_at: datetime
    remind_at: datetime | None = None


class HolidayOverrideInput(BaseModel):
    holiday_date: date
    name: str = Field(min_length=1, max_length=500)
    is_active: bool = True


class HolidayCountryInput(BaseModel):
    country_code: str = Field(min_length=2, max_length=2)


class CalendarSyncInput(BaseModel):
    task_id: int


class CalendarSyncModeInput(BaseModel):
    sync_mode: Literal["outbound", "bidirectional"]


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
        reviewer = not write and task.workflow_status == "review" and (task.reviewer_id == actor.employee_id or bool(await db.scalar(select(TaskReviewer.id).where(TaskReviewer.task_id == task.id, TaskReviewer.employee_id == actor.employee_id))) )
        if assigned or reviewer:
            return task
    raise HTTPException(status_code=404, detail="Task not found")


def _search_score(query: str, *values: str | None) -> float:
    """Small, deterministic fuzzy scorer used after organization-scoped filtering."""
    needle = query.casefold().strip()
    haystack = " ".join(value for value in values if value).casefold()
    if not needle or not haystack:
        return 0
    if needle == haystack:
        return 1.0
    if any(part.startswith(needle) for part in haystack.split()):
        return 0.95
    if needle in haystack:
        return 0.8
    return SequenceMatcher(None, needle, haystack).ratio()


@router.get("/search")
async def global_search(
    q: str = Query(min_length=1, max_length=120),
    limit_per_group: int = Query(default=5, ge=1, le=10),
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    """Permission-safe command-bar search across live workspace entities."""
    task_query = select(Task).where(Task.organization_id == actor.organization_id, Task.is_archived.is_(False))
    if actor.has_any_role("client_auditor"):
        scoped_projects = select(RoleAssignment.project_id).where(RoleAssignment.account_id == actor.account_id, RoleAssignment.project_id.isnot(None))
        scoped_clients = select(RoleAssignment.client_id).where(RoleAssignment.account_id == actor.account_id, RoleAssignment.client_id.isnot(None))
        task_query = task_query.where(or_(Task.project_id.in_(scoped_projects), Task.project_id.in_(select(Project.id).where(Project.client_id.in_(scoped_clients)))))
    elif not actor.has_any_role(*MANAGEMENT_ROLES):
        if not actor.employee_id:
            task_query = task_query.where(False)
        else:
            contributor = select(TaskAssignee.task_id).where(TaskAssignee.employee_id == actor.employee_id)
            reviewer = select(TaskReviewer.task_id).where(TaskReviewer.employee_id == actor.employee_id)
            task_query = task_query.where(or_(Task.assignee_id == actor.employee_id, Task.id.in_(contributor), and_(Task.workflow_status == "review", or_(Task.reviewer_id == actor.employee_id, Task.id.in_(reviewer)))))
    tasks = list((await db.execute(task_query)).scalars().all())
    task_people = {row.id: row.name for row in (await db.execute(select(Employee))).scalars().all()}
    projects = {row.id: row.name for row in (await db.execute(select(Project).where(Project.organization_id == actor.organization_id))).scalars().all()}
    task_results = []
    for task in tasks:
        score = _search_score(q, task.title, task.description, projects.get(task.project_id), task_people.get(task.assignee_id))
        if score >= 0.28:
            task_results.append({"id": task.id, "type": "task", "title": task.title, "subtitle": projects.get(task.project_id), "score": score, "metadata": {"status": task.workflow_status, "assignee": task_people.get(task.assignee_id), "project": projects.get(task.project_id)}})

    account_employees = select(UserAccount.employee_id).where(UserAccount.organization_id == actor.organization_id, UserAccount.employee_id.isnot(None), UserAccount.status == "active")
    workers = list((await db.execute(select(Employee).where(Employee.id.in_(account_employees), Employee.is_active.is_(True)))).scalars().all())
    worker_results = []
    for worker in workers:
        score = _search_score(q, worker.name, worker.job_title, worker.telegram_username)
        if score >= 0.28:
            worker_results.append({"id": worker.id, "type": "worker", "title": worker.name, "subtitle": worker.job_title or worker.telegram_username, "score": score, "metadata": {"avatar_url": (worker.metadata_json or {}).get("avatar_url"), "role": worker.job_title, "presence": "offline"}})

    files = list((await db.execute(select(CompanyLibraryItem).where(CompanyLibraryItem.organization_id == actor.organization_id, CompanyLibraryItem.deleted_at.is_(None)))).scalars().all())
    file_results = []
    for item in files:
        score = _search_score(q, item.name, item.content_type, item.kind)
        if score >= 0.28:
            file_results.append({"id": item.id, "type": "file", "title": item.name, "subtitle": item.content_type or item.kind, "score": score, "metadata": {"kind": item.kind, "size": item.size, "parent_id": item.parent_id}})
    rank = lambda rows: sorted(rows, key=lambda row: (-row["score"], row["title"].casefold()))[:limit_per_group]
    return {"query": q, "groups": {"tasks": rank(task_results), "workers": rank(worker_results), "files": rank(file_results)}}


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
    query = select(Project).where(Project.organization_id == actor.organization_id, Project.archived_at.is_(None))
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
    employee_ids = {row.manager_id for row in rows if row.manager_id}
    people = {row.id: row.name for row in (await db.execute(select(Employee).where(Employee.id.in_(employee_ids)))).scalars().all()} if employee_ids else {}
    member_rows = (await db.execute(select(ProjectMember).where(ProjectMember.project_id.in_([row.id for row in rows])))).scalars().all() if rows else []
    members_by_project: dict[int, list[int]] = {}
    for member in member_rows:
        members_by_project.setdefault(member.project_id, []).append(member.employee_id)
    return [{**_project_out(row), "manager_name": people.get(row.manager_id), "member_ids": members_by_project.get(row.id, [])} for row in rows]


@router.get("/projects/{project_id}")
async def get_project(project_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    project = await db.get(Project, project_id)
    if not project or project.organization_id != actor.organization_id or project.archived_at:
        raise HTTPException(status_code=404, detail="Project not found")
    if not actor.has_any_role(*MANAGEMENT_ROLES):
        member = actor.employee_id and await db.scalar(select(ProjectMember.id).where(ProjectMember.project_id == project.id, ProjectMember.employee_id == actor.employee_id))
        if not member: raise HTTPException(status_code=404, detail="Project not found")
    members = (await db.execute(select(ProjectMember.employee_id).where(ProjectMember.project_id == project.id))).scalars().all()
    manager = await db.get(Employee, project.manager_id) if project.manager_id else None
    return {**_project_out(project), "manager_name": manager.name if manager else None, "member_ids": sorted(set(members)), "can_archive": actor.has_any_role(*MANAGEMENT_ROLES) or project.manager_id == actor.employee_id}


@router.patch("/projects/{project_id}")
async def update_project(project_id: int, data: ProjectPatch, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    project = await db.get(Project, project_id, with_for_update=True)
    if not project or project.organization_id != actor.organization_id or project.archived_at:
        raise HTTPException(status_code=404, detail="Project not found")
    if not actor.has_any_role(*MANAGEMENT_ROLES) and project.manager_id != actor.employee_id:
        raise HTTPException(status_code=403, detail="Only management or the project owner can edit this project")
    patch = data.model_dump(exclude_unset=True)
    member_ids = patch.pop("member_ids", None)
    before = _project_out(project)
    for field, value in patch.items():
        setattr(project, field, value)
    if member_ids is not None:
        requested = set(member_ids)
        if project.manager_id:
            requested.add(project.manager_id)
        valid = set((await db.execute(select(Employee.id).where(Employee.id.in_(requested), Employee.is_active.is_(True)))).scalars().all()) if requested else set()
        if valid != requested:
            raise HTTPException(status_code=400, detail="Project member is invalid")
        await db.execute(ProjectMember.__table__.delete().where(ProjectMember.project_id == project.id))
        for employee_id in requested:
            db.add(ProjectMember(project_id=project.id, employee_id=employee_id, project_role="owner" if employee_id == project.manager_id else "member"))
    project.version += 1
    await record_change(db, actor=actor, topic="projects", aggregate_type="project", aggregate_id=project.id, operation="updated", version=project.version, before=before, after=_project_out(project))
    await db.commit()
    return await get_project(project.id, db, actor)


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_project(project_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    project = await db.get(Project, project_id, with_for_update=True)
    if not project or project.organization_id != actor.organization_id or project.archived_at:
        raise HTTPException(status_code=404, detail="Project not found")
    if not actor.has_any_role(*MANAGEMENT_ROLES) and project.manager_id != actor.employee_id:
        raise HTTPException(status_code=403, detail="Only management or the project owner can archive this project")
    project.archived_at = datetime.now(timezone.utc)
    project.archived_by_account_id = actor.account_id
    project.status = "cancelled"
    project.version += 1
    await record_change(db, actor=actor, topic="projects", aggregate_type="project", aggregate_id=project.id, operation="archived", version=project.version, after={"archived_at": project.archived_at})
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/projects", status_code=status.HTTP_201_CREATED)
async def create_project(data: ProjectInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    if not actor.has_any_role(*MANAGEMENT_ROLES) and not actor.employee_id:
        raise HTTPException(status_code=409, detail="Account is not linked to an employee")
    manager_id = data.manager_id or (actor.employee_id if not actor.has_any_role(*MANAGEMENT_ROLES) else None)
    payload = data.model_dump(exclude={"member_ids", "manager_id"}) | {"manager_id": manager_id}
    employee_ids = set(data.member_ids)
    if manager_id:
        employee_ids.add(manager_id)
    if actor.employee_id and not actor.has_any_role(*MANAGEMENT_ROLES):
        employee_ids.add(actor.employee_id)
    if employee_ids:
        valid = set((await db.execute(select(Employee.id).where(Employee.id.in_(employee_ids), Employee.is_active.is_(True)))).scalars().all())
        if valid != employee_ids:
            raise HTTPException(status_code=400, detail="Project owner or member is invalid")
    project = Project(organization_id=actor.organization_id, **payload)
    db.add(project)
    try:
        await db.flush()
        for employee_id in employee_ids:
            db.add(ProjectMember(project_id=project.id, employee_id=employee_id, project_role="owner" if employee_id == manager_id else "member"))
        await db.flush()
        manager = await db.get(Employee, manager_id) if manager_id else None
        output = {**_project_out(project), "manager_name": manager.name if manager else None, "member_ids": sorted(employee_ids)}
        source_event = await record_change(db, actor=actor, topic="projects", aggregate_type="project", aggregate_id=project.id, operation="created", version=project.version, after=output)
        await create_notifications(
            db, organization_id=actor.organization_id, employee_ids=employee_ids,
            kind="project_member_added",
            title="Шинэ төсөл", body=f"Та “{project.name}” төсөлд нэмэгдлээ.",
            target_url=f"/projects?project={project.id}", payload={"project_id": project.id},
            source_event_id=source_event.id, dedup_key=f"project-created:{project.id}",
        )
        await db.commit()
        return output
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Project code already exists") from exc


@router.get("/project-requests")
async def list_project_requests(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    query = select(ProjectRequest).where(ProjectRequest.organization_id == actor.organization_id)
    if not actor.has_any_role(*MANAGEMENT_ROLES):
        query = query.where(ProjectRequest.requested_by_account_id == actor.account_id)
    rows = (await db.execute(query.order_by(ProjectRequest.created_at.desc()))).scalars().all()
    return [{"id": row.id, "status": row.status, "payload": row.payload, "review_note": row.review_note, "project_id": row.project_id, "created_at": row.created_at, "reviewed_at": row.reviewed_at} for row in rows]


@router.post("/project-requests/{request_id}/review")
async def review_project_request(request_id: int, data: ProjectRequestReview, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles(*MANAGEMENT_ROLES))):
    request = await db.get(ProjectRequest, request_id, with_for_update=True)
    if not request or request.organization_id != actor.organization_id:
        raise HTTPException(status_code=404, detail="Project request not found")
    if request.status != "pending":
        raise HTTPException(status_code=409, detail="Project request has already been reviewed")
    request.status, request.reviewer_account_id, request.review_note, request.reviewed_at = data.action, actor.account_id, data.note, datetime.now(timezone.utc)
    if data.action == "approved":
        payload = ProjectInput.model_validate(request.payload)
        member_ids = set(payload.member_ids)
        if request.requested_by_employee_id:
            member_ids.add(request.requested_by_employee_id)
        manager_id = payload.manager_id or request.requested_by_employee_id
        if manager_id:
            member_ids.add(manager_id)
        project = Project(organization_id=actor.organization_id, **payload.model_dump(exclude={"member_ids", "manager_id"}), manager_id=manager_id)
        db.add(project)
        await db.flush()
        for employee_id in member_ids:
            db.add(ProjectMember(project_id=project.id, employee_id=employee_id, project_role="owner" if employee_id == manager_id else "member"))
        request.project_id = project.id
    source_event = await record_change(db, actor=actor, topic="projects", aggregate_type="project_request", aggregate_id=request.id, operation=data.action, after={"status": request.status, "project_id": request.project_id})
    await create_notifications(
        db, organization_id=actor.organization_id, account_ids={request.requested_by_account_id},
        kind="project_request_reviewed", title="Төслийн хүсэлт шийдэгдлээ",
        body=f"Таны төслийн хүсэлт {('зөвшөөрөгдлөө' if data.action == 'approved' else 'татгалзагдлаа')}.",
        target_url=f"/projects{f'?project={request.project_id}' if request.project_id else ''}",
        payload={"request_id": request.id, "project_id": request.project_id, "status": request.status},
        source_event_id=source_event.id, dedup_key=f"project-request-reviewed:{request.id}",
    )
    if data.action == "approved" and request.project_id:
        await create_notifications(
            db, organization_id=actor.organization_id, employee_ids=member_ids,
            kind="project_member_added", title="Шинэ төсөл",
            body=f"Та “{payload.name}” төсөлд нэмэгдлээ.", target_url=f"/projects?project={request.project_id}",
            payload={"project_id": request.project_id}, source_event_id=source_event.id,
            dedup_key=f"project-created:{request.project_id}",
        )
    await db.commit()
    return {"id": request.id, "status": request.status, "project_id": request.project_id}


@router.post("/projects/{project_id}/members", status_code=status.HTTP_201_CREATED)
async def add_project_member(project_id: int, data: ProjectMemberInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles(*MANAGEMENT_ROLES))):
    project = await db.get(Project, project_id)
    if not project or project.organization_id != actor.organization_id:
        raise HTTPException(status_code=404, detail="Project not found")
    member = ProjectMember(project_id=project_id, **data.model_dump())
    db.add(member)
    await db.flush()
    source_event = await record_change(db, actor=actor, topic="capacity", aggregate_type="project_member", aggregate_id=member.id, operation="created", after=data.model_dump(mode="json"))
    await create_notifications(
        db, organization_id=actor.organization_id, employee_ids={data.employee_id},
        kind="project_member_added", title="Төсөлд нэмэгдлээ",
        body=f"Та “{project.name}” төсөлд нэмэгдлээ.", target_url=f"/projects?project={project.id}",
        payload={"project_id": project.id}, source_event_id=source_event.id,
        dedup_key=f"project-member:{project.id}:{data.employee_id}",
    )
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
async def list_tasks(
    project_id: int | None = None,
    workflow_status: str | None = None,
    priority: int | None = Query(default=None, ge=1, le=3),
    scope: Literal["mine", "organization", "project", "delegated"] = "mine",
    kind: Literal["all", "standalone", "project", "subtask"] = "all",
    overdue: bool = False,
    date_from: date | None = None,
    date_to: date | None = None,
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    query = select(Task).where(Task.organization_id == actor.organization_id, Task.is_archived.is_(False))
    if project_id:
        query = query.where(Task.project_id == project_id)
    if workflow_status:
        query = query.where(Task.workflow_status == workflow_status)
    if priority:
        query = query.where(Task.priority == priority)
    if kind == "standalone":
        query = query.where(Task.project_id.is_(None), Task.parent_task_id.is_(None))
    elif kind == "project":
        query = query.where(Task.project_id.isnot(None), Task.parent_task_id.is_(None))
    elif kind == "subtask":
        query = query.where(Task.parent_task_id.isnot(None))
    if overdue:
        query = query.where(Task.deadline_at < datetime.now(timezone.utc), Task.workflow_status.notin_({"done", "cancelled"}))
    if date_from:
        query = query.where(or_(Task.deadline_at.is_(None), Task.deadline_at >= datetime.combine(date_from, datetime.min.time(), tzinfo=timezone.utc)))
    if date_to:
        query = query.where(or_(Task.start_at.is_(None), Task.start_at < datetime.combine(date_to + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)))
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
    elif scope == "delegated":
        if not actor.employee_id:
            return []
        query = query.where(Task.created_by_id == actor.employee_id)
    elif scope == "organization" and not actor.has_any_role(*MANAGEMENT_ROLES):
        raise HTTPException(status_code=403, detail="Organization task scope requires management access")
    elif scope == "project":
        if not project_id:
            raise HTTPException(status_code=400, detail="Project scope requires a project")
        if not actor.has_any_role(*MANAGEMENT_ROLES):
            member = actor.employee_id and await db.scalar(select(ProjectMember.id).where(ProjectMember.project_id == project_id, ProjectMember.employee_id == actor.employee_id))
            if not member: raise HTTPException(status_code=403, detail="Project task scope requires project membership")
    elif scope == "mine" or not actor.has_any_role(*MANAGEMENT_ROLES):
        if not actor.employee_id:
            return []
        contributor_tasks = select(TaskAssignee.task_id).where(TaskAssignee.employee_id == actor.employee_id)
        query = query.where(or_(
            Task.assignee_id == actor.employee_id,
            Task.id.in_(contributor_tasks),
            or_(and_(Task.reviewer_id == actor.employee_id, Task.workflow_status == "review"), and_(Task.workflow_status == "review", Task.id.in_(select(TaskReviewer.task_id).where(TaskReviewer.employee_id == actor.employee_id)))),
        ))
    rows = (await db.execute(query.order_by(Task.workflow_status, Task.sort_position, Task.id))).scalars().all()
    task_ids = [row.id for row in rows]
    assignment_rows = (await db.execute(select(TaskAssignee).where(TaskAssignee.task_id.in_(task_ids)))).scalars().all() if task_ids else []
    reviewer_rows = (await db.execute(select(TaskReviewer).where(TaskReviewer.task_id.in_(task_ids)))).scalars().all() if task_ids else []
    assignees: dict[int, list[int]] = {}
    for assignment in assignment_rows:
        assignees.setdefault(assignment.task_id, []).append(assignment.employee_id)
    reviewers: dict[int, list[int]] = {}
    for reviewer in reviewer_rows:
        reviewers.setdefault(reviewer.task_id, []).append(reviewer.employee_id)
    employee_ids = {row.assignee_id for row in rows if row.assignee_id} | {row.reviewer_id for row in rows if row.reviewer_id} | {row.created_by_id for row in rows if row.created_by_id} | {item.employee_id for item in assignment_rows} | {item.employee_id for item in reviewer_rows}
    people = {row.id: row.name for row in (await db.execute(select(Employee).where(Employee.id.in_(employee_ids)))).scalars().all()} if employee_ids else {}
    project_ids = {row.project_id for row in rows if row.project_id}
    projects = {row.id: row.name for row in (await db.execute(select(Project).where(Project.id.in_(project_ids)))).scalars().all()} if project_ids else {}
    return [{**_task_out(row), "primary_owner_name": people.get(row.assignee_id), "reviewer_name": people.get(row.reviewer_id), "reviewer_ids": reviewers.get(row.id, ([row.reviewer_id] if row.reviewer_id else [])), "reviewer_names": [people[employee_id] for employee_id in reviewers.get(row.id, ([row.reviewer_id] if row.reviewer_id else [])) if employee_id in people], "creator_name": people.get(row.created_by_id), "assignee_ids": assignees.get(row.id, []), "assignee_names": [people[employee_id] for employee_id in assignees.get(row.id, []) if employee_id in people], "project_name": projects.get(row.project_id)} for row in rows]


@router.get("/tasks/{task_id}")
async def get_task(task_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    task = await _task_for_actor(db, task_id, actor)
    assignee_ids = list((await db.execute(select(TaskAssignee.employee_id).where(TaskAssignee.task_id == task.id))).scalars().all())
    reviewer_ids = list((await db.execute(select(TaskReviewer.employee_id).where(TaskReviewer.task_id == task.id))).scalars().all())
    people = {row.id: row.name for row in (await db.execute(select(Employee).where(Employee.id.in_({*assignee_ids, *reviewer_ids, task.assignee_id, task.reviewer_id, task.created_by_id} - {None})))).scalars().all()} if assignee_ids or reviewer_ids or task.assignee_id or task.reviewer_id or task.created_by_id else {}
    project = await db.get(Project, task.project_id) if task.project_id else None
    return {**_task_out(task), "primary_owner_name": people.get(task.assignee_id), "reviewer_name": people.get(task.reviewer_id), "reviewer_ids": reviewer_ids or ([task.reviewer_id] if task.reviewer_id else []), "reviewer_names": [people[item] for item in reviewer_ids if item in people], "creator_name": people.get(task.created_by_id), "assignee_ids": assignee_ids, "assignee_names": [people[item] for item in assignee_ids if item in people], "project_name": project.name if project and project.organization_id == actor.organization_id else None}


@router.post("/tasks", status_code=status.HTTP_201_CREATED)
async def create_task(data: EnterpriseTaskInput, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    if data.workflow_status not in WORKFLOW_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid workflow status")
    can_assign = await actor_can_assign_tasks(db, organization_id=actor.organization_id, employee_id=actor.employee_id, roles=actor.roles)
    requested_targets = set(data.assignee_ids)
    if data.primary_owner_id:
        requested_targets.add(data.primary_owner_id)
    if any(target != actor.employee_id for target in requested_targets) and not can_assign:
        raise HTTPException(status_code=403, detail="Your role cannot assign work to other workers")
    request_hash = hashlib.sha256(data.model_dump_json().encode()).hexdigest()
    if idempotency_key:
        existing = (
            await db.execute(select(IdempotencyRecord).where(IdempotencyRecord.account_id == actor.account_id, IdempotencyRecord.operation == "create_task", IdempotencyRecord.key == idempotency_key))
        ).scalar_one_or_none()
        if existing:
            if existing.request_hash != request_hash:
                raise HTTPException(status_code=409, detail="Idempotency key was used with different input")
            return existing.response_body
    project_id = data.project_id
    if data.parent_task_id:
        parent = await db.get(Task, data.parent_task_id)
        if not parent or parent.organization_id != actor.organization_id:
            raise HTTPException(status_code=404, detail="Parent task not found")
        if not actor.has_any_role(*MANAGEMENT_ROLES):
            project_member = actor.employee_id and parent.project_id and await db.scalar(select(ProjectMember.id).where(ProjectMember.project_id == parent.project_id, ProjectMember.employee_id == actor.employee_id))
            assigned = actor.employee_id and (parent.assignee_id == actor.employee_id or await db.scalar(select(TaskAssignee.id).where(TaskAssignee.task_id == parent.id, TaskAssignee.employee_id == actor.employee_id)))
            if not project_member and not assigned:
                raise HTTPException(status_code=404, detail="Parent task not found")
        if project_id is not None and project_id != parent.project_id:
            raise HTTPException(status_code=400, detail="A subtask must belong to the same project as its parent")
        project_id = parent.project_id
    if project_id:
        project = await db.get(Project, project_id)
        if not project or project.organization_id != actor.organization_id:
            raise HTTPException(status_code=400, detail="Project is invalid")
    requested_assignees = set(data.assignee_ids)
    if data.primary_owner_id:
        requested_assignees.add(data.primary_owner_id)
    if requested_assignees:
        valid = set((await db.execute(select(Employee.id).where(Employee.id.in_(requested_assignees), Employee.is_active.is_(True)))).scalars().all())
        if valid != requested_assignees:
            raise HTTPException(status_code=400, detail="Task assignee is invalid")
    reviewer_ids = list(dict.fromkeys(data.reviewer_ids + ([data.reviewer_id] if data.reviewer_id else [])))
    if reviewer_ids:
        valid_reviewers = set((await db.execute(select(Employee.id).where(Employee.id.in_(reviewer_ids), Employee.is_active.is_(True)))).scalars().all())
        if valid_reviewers != set(reviewer_ids):
            raise HTTPException(status_code=400, detail="Task reviewer is invalid")
    owner_id = data.primary_owner_id or (actor.employee_id if not actor.has_any_role(*MANAGEMENT_ROLES) else None)
    task = Task(
        organization_id=actor.organization_id, project_id=project_id, parent_task_id=data.parent_task_id,
        title=data.title, description=data.description, workflow_status=data.workflow_status,
        status=LEGACY_STATUS[data.workflow_status], priority=data.priority, assignee_id=owner_id,
        start_at=data.start_at, deadline_at=data.deadline_at, estimate_minutes=data.estimate_minutes,
        work_location_type=data.work_location_type, work_location=data.work_location,
        sort_position=data.sort_position, created_by_id=actor.employee_id, reviewer_id=reviewer_ids[0] if reviewer_ids else None,
    )
    db.add(task)
    await db.flush()
    assignees = set(data.assignee_ids)
    if owner_id:
        assignees.add(owner_id)
    for employee_id in assignees:
        db.add(TaskAssignee(task_id=task.id, employee_id=employee_id, assignment_role="primary" if employee_id == owner_id else "contributor"))
    for employee_id in reviewer_ids:
        db.add(TaskReviewer(task_id=task.id, employee_id=employee_id))
    owner = await db.get(Employee, owner_id) if owner_id else None
    output = {**_task_out(task), "assignee_ids": sorted(assignees), "reviewer_ids": reviewer_ids, "primary_owner_name": owner.name if owner else None}
    source_event = await record_change(db, actor=actor, topic="tasks", aggregate_type="task", aggregate_id=task.id, operation="created", version=task.version, after=output)
    await create_notifications(
        db, organization_id=actor.organization_id, employee_ids=assignees,
        kind="task_assigned", title="Шинэ даалгавар",
        body=f"Танд “{task.title}” даалгавар оноолоо.", target_url=f"/tasks?task={task.id}",
        payload={"task_id": task.id, "title": task.title, "deadline_iso": task.deadline_at.isoformat() if task.deadline_at else None},
        source_event_id=source_event.id, task_id=task.id, dedup_key=f"task-created:{task.id}",
    )
    if task.workflow_status == "review" and reviewer_ids:
        assignee = await db.get(Employee, task.assignee_id) if task.assignee_id else None
        task_url = f"{settings.PUBLIC_APP_URL.rstrip('/')}/tasks?task={task.id}"
        await create_notifications(
            db, organization_id=actor.organization_id, employee_ids=reviewer_ids,
            kind="task_review_requested", title="Хянах шаардлагатай",
            body=f"“{task.title}” даалгаврыг хянахаар илгээлээ. Хариуцагч: {assignee.name if assignee else 'Хариуцагчгүй'}.", target_url=f"/tasks?task={task.id}",
            payload={"task_id": task.id, "title": task.title, "assignee_name": assignee.name if assignee else None, "task_url": task_url}, source_event_id=source_event.id,
            task_id=task.id, dedup_key=f"task-review-requested:{task.id}:v{task.version}", immediate=True,
        )
    if idempotency_key:
        db.add(IdempotencyRecord(account_id=actor.account_id, operation="create_task", key=idempotency_key, request_hash=request_hash, response_status=201, response_body=json.loads(json.dumps(output, default=str)), expires_at=datetime.now(timezone.utc) + timedelta(days=1)))
    await db.commit()
    return output


@router.patch("/tasks/{task_id}")
async def update_task(task_id: int, data: EnterpriseTaskPatch, if_match: str | None = Header(default=None, alias="If-Match"), db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    task = await db.get(Task, task_id, with_for_update=True)
    if not task or task.organization_id != actor.organization_id:
        raise HTTPException(status_code=404, detail="Task not found")
    can_manage = actor.has_any_role(*MANAGEMENT_ROLES) or (actor.employee_id is not None and task.created_by_id == actor.employee_id)
    is_contributor = actor.employee_id is not None and bool(await db.scalar(select(TaskAssignee.id).where(TaskAssignee.task_id == task.id, TaskAssignee.employee_id == actor.employee_id)))
    is_reviewer = actor.employee_id is not None and (task.reviewer_id == actor.employee_id or bool(await db.scalar(select(TaskReviewer.id).where(TaskReviewer.task_id == task.id, TaskReviewer.employee_id == actor.employee_id))))
    if not can_manage:
        if task.assignee_id != actor.employee_id and not is_contributor and not (is_reviewer and task.workflow_status == "review"):
            raise HTTPException(status_code=403, detail="Task is outside your scope")
    if if_match is not None:
        try:
            expected = int(if_match.strip('W/"'))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="If-Match must contain a version") from exc
        if task.version != expected:
            raise HTTPException(status_code=409, detail={"message": "Task changed", "latest": _task_out(task)})
    patch = data.model_dump(exclude_unset=True)
    next_workflow = patch.get("workflow_status")
    if not can_manage:
        current = set((await db.execute(select(TaskAssignee.employee_id).where(TaskAssignee.task_id == task.id))).scalars().all())
        changed = (("primary_owner_id" in patch and patch["primary_owner_id"] != task.assignee_id) or ("project_id" in patch and patch["project_id"] != task.project_id) or ("assignee_ids" in patch and set(patch["assignee_ids"] or []) != current))
        if changed and not await actor_can_assign_tasks(db, organization_id=actor.organization_id, employee_id=actor.employee_id, roles=actor.roles):
            raise HTTPException(status_code=403, detail="Your role cannot assign work to other workers")
    if patch.get("workflow_status") and patch["workflow_status"] not in WORKFLOW_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid workflow status")
    reviewer_ids = patch.pop("reviewer_ids", None)
    if reviewer_ids is not None:
        reviewer_ids = list(dict.fromkeys(reviewer_ids + ([patch.get("reviewer_id")] if patch.get("reviewer_id") else [])))
        valid_reviewers = set((await db.execute(select(Employee.id).where(Employee.id.in_(reviewer_ids), Employee.is_active.is_(True)))).scalars().all()) if reviewer_ids else set()
        if valid_reviewers != set(reviewer_ids):
            raise HTTPException(status_code=400, detail="Task reviewer is invalid")
        await db.execute(TaskReviewer.__table__.delete().where(TaskReviewer.task_id == task.id))
        for employee_id in reviewer_ids:
            db.add(TaskReviewer(task_id=task.id, employee_id=employee_id))
        patch["reviewer_id"] = reviewer_ids[0] if reviewer_ids else None
    if "parent_task_id" in patch and patch["parent_task_id"]:
        if patch["parent_task_id"] == task.id:
            raise HTTPException(status_code=400, detail="A task cannot be its own parent")
        parent = await _task_for_actor(db, patch["parent_task_id"], actor, write=True)
        target_project = patch.get("project_id", task.project_id)
        if target_project is not None and target_project != parent.project_id:
            raise HTTPException(status_code=400, detail="A subtask must belong to the same project as its parent")
        patch["project_id"] = parent.project_id
    before = _task_out(task)
    assignee_ids = patch.pop("assignee_ids", None)
    if assignee_ids is not None:
        requested = set(assignee_ids)
        if patch.get("primary_owner_id"):
            requested.add(patch["primary_owner_id"])
        valid = set((await db.execute(select(Employee.id).where(Employee.id.in_(requested), Employee.is_active.is_(True)))).scalars().all()) if requested else set()
        if valid != requested:
            raise HTTPException(status_code=400, detail="Task assignee is invalid")
        await db.execute(TaskAssignee.__table__.delete().where(TaskAssignee.task_id == task.id))
        owner = patch.get("primary_owner_id", task.assignee_id)
        for employee_id in requested:
            db.add(TaskAssignee(task_id=task.id, employee_id=employee_id, assignment_role="primary" if employee_id == owner else "contributor"))
    for field, value in patch.items():
        setattr(task, "assignee_id" if field == "primary_owner_id" else field, value)
    if data.workflow_status:
        task.status = LEGACY_STATUS[data.workflow_status]
        task.completed_at = datetime.now(timezone.utc) if data.workflow_status == "done" else None
    task.version += 1
    await db.flush()
    current_assignees = (await db.execute(select(TaskAssignee.employee_id).where(TaskAssignee.task_id == task.id))).scalars().all()
    current_reviewers = (await db.execute(select(TaskReviewer.employee_id).where(TaskReviewer.task_id == task.id))).scalars().all()
    if task.reviewer_id and task.reviewer_id not in current_reviewers:
        current_reviewers.append(task.reviewer_id)
    output = {**_task_out(task), "assignee_ids": sorted(set(current_assignees)), "reviewer_ids": sorted(set(current_reviewers))}
    source_event = await record_change(db, actor=actor, topic="tasks", aggregate_type="task", aggregate_id=task.id, operation="updated", version=task.version, before=before, after=output)
    if next_workflow == "review" and before["workflow_status"] != "review" and current_reviewers:
        assignee = await db.get(Employee, task.assignee_id) if task.assignee_id else None
        task_url = f"{settings.PUBLIC_APP_URL.rstrip('/')}/tasks?task={task.id}"
        await create_notifications(
            db, organization_id=actor.organization_id, employee_ids=current_reviewers,
            kind="task_review_requested", title="Хянах шаардлагатай",
            body=f"“{task.title}” даалгаврыг хянахаар илгээлээ. Хариуцагч: {assignee.name if assignee else 'Хариуцагчгүй'}.", target_url=f"/tasks?task={task.id}",
            payload={"task_id": task.id, "title": task.title, "assignee_name": assignee.name if assignee else None, "task_url": task_url}, source_event_id=source_event.id,
            task_id=task.id, dedup_key=f"task-review-requested:{task.id}:v{task.version}", immediate=True,
        )
    await db.commit()
    return output


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(task_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    task = await db.get(Task, task_id, with_for_update=True)
    if not task or task.organization_id != actor.organization_id:
        raise HTTPException(status_code=404, detail="Task not found")
    created_by_account = await db.scalar(
        select(AuditLog.id).where(
            AuditLog.organization_id == actor.organization_id,
            AuditLog.actor_account_id == actor.account_id,
            AuditLog.action == "created",
            AuditLog.entity_type == "task",
            AuditLog.entity_id == task.id,
        ).limit(1)
    )
    can_manage = actor.has_any_role(*MANAGEMENT_ROLES) or (
        (actor.employee_id is not None and task.created_by_id == actor.employee_id)
        or created_by_account is not None
    )
    if not can_manage:
        raise HTTPException(status_code=403, detail="Only the task creator or management can delete this task")
    before = _task_out(task)
    await record_change(db, actor=actor, topic="tasks", aggregate_type="task", aggregate_id=task.id, operation="deleted", version=task.version, before=before)
    await db.delete(task)
    await db.commit()


@router.get("/deadlines")
async def list_deadlines(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles(*MANAGEMENT_ROLES))):
    now = datetime.now(timezone.utc)
    projects = (await db.execute(select(Project).where(Project.organization_id == actor.organization_id, Project.archived_at.is_(None)))).scalars().all()
    tasks = (await db.execute(select(Task).where(Task.organization_id == actor.organization_id, Task.is_archived.is_(False)))).scalars().all()
    plan_items = (await db.execute(select(CompanyPlanItem).where(CompanyPlanItem.organization_id == actor.organization_id, CompanyPlanItem.status == "approved"))).scalars().all()
    project_names = {project.id: project.name for project in projects}
    employee_ids = {task.assignee_id for task in tasks if task.assignee_id} | {project.manager_id for project in projects if project.manager_id}
    people = {employee.id: employee.name for employee in (await db.execute(select(Employee).where(Employee.id.in_(employee_ids)))).scalars().all()} if employee_ids else {}
    items = []
    for project in projects:
        items.append({"id": f"project-{project.id}", "entity_id": project.id, "type": "project", "title": project.name, "due_date": str(project.ends_on) if project.ends_on else None, "status": project.status, "owner": people.get(project.manager_id), "project_id": project.id, "project_name": project.name})
    for task in tasks:
        items.append({"id": f"task-{task.id}", "entity_id": task.id, "type": "subtask" if task.parent_task_id else "task", "title": task.title, "due_date": task.deadline_at.isoformat() if task.deadline_at else None, "status": task.workflow_status, "owner": people.get(task.assignee_id), "project_id": task.project_id, "project_name": project_names.get(task.project_id)})
    for item in plan_items:
        items.append({"id": f"plan-{item.id}", "entity_id": item.id, "type": "plan", "title": item.title, "due_date": str(item.due_date) if item.due_date else None, "status": item.status, "owner": None, "project_id": None, "project_name": None})
    for item in items:
        if not item["due_date"]:
            item["bucket"] = "none"
            continue
        due = datetime.fromisoformat(item["due_date"].replace("Z", "+00:00")) if "T" in item["due_date"] else datetime.combine(date.fromisoformat(item["due_date"]), datetime.max.time(), tzinfo=timezone.utc)
        item["bucket"] = "overdue" if due < now else "soon" if due <= now + timedelta(days=7) else "later"
    order = {"overdue": 0, "soon": 1, "later": 2, "none": 3}
    return sorted(items, key=lambda item: (order[item["bucket"]], item["due_date"] or "9999", item["title"]))


@router.put("/tasks/{task_id}/assignees")
async def replace_assignees(task_id: int, data: AssigneesInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    task = await db.get(Task, task_id)
    if not task or task.organization_id != actor.organization_id:
        raise HTTPException(status_code=404, detail="Task not found")
    if not await actor_can_assign_tasks(db, organization_id=actor.organization_id, employee_id=actor.employee_id, roles=actor.roles):
        raise HTTPException(status_code=403, detail="Your role cannot assign work to other workers")
    await db.execute(TaskAssignee.__table__.delete().where(TaskAssignee.task_id == task_id))
    for employee_id in sorted(set(data.employee_ids)):
        db.add(TaskAssignee(task_id=task_id, employee_id=employee_id, assignment_role="primary" if employee_id == task.assignee_id else "contributor"))
    task.version += 1
    await record_change(db, actor=actor, topic="tasks", aggregate_type="task", aggregate_id=task.id, operation="assignees_changed", version=task.version, after={"employee_ids": data.employee_ids})
    await db.commit()
    return {"employee_ids": sorted(set(data.employee_ids)), "version": task.version}


def _time_block_out(item: PersonalTimeBlock) -> dict:
    return {"id": item.id, "title": item.title, "starts_at": item.starts_at, "ends_at": item.ends_at, "task_id": item.task_id, "version": item.version}


def _calendar_entry_out(item: CalendarEntry) -> dict:
    return {"id": item.id, "kind": item.kind, "visibility": item.visibility, "title": item.title, "description": item.description, "starts_at": item.starts_at, "ends_at": item.ends_at, "remind_at": item.remind_at, "version": item.version, "can_edit": item.created_by_account_id is None or item.created_by_account_id == item.account_id}


def _holiday_provider_rows(payload: object) -> list[tuple[date, str, str | None]]:
    """Validate the public-holidays response before it reaches the calendar feed."""
    if not isinstance(payload, list):
        raise HTTPException(status_code=502, detail="Holiday provider returned an invalid response")
    rows: list[tuple[date, str, str | None]] = []
    seen: set[tuple[date, str]] = set()
    for item in payload:
        if not isinstance(item, dict) or not isinstance(item.get("date"), str) or not isinstance(item.get("name"), str):
            raise HTTPException(status_code=502, detail="Holiday provider returned an invalid response")
        try:
            holiday_day = date.fromisoformat(item["date"])
        except ValueError as exc:
            raise HTTPException(status_code=502, detail="Holiday provider returned an invalid response") from exc
        local_name = item.get("localName")
        identity = (holiday_day, item["name"])
        if identity in seen:
            continue
        seen.add(identity)
        rows.append((holiday_day, item["name"], local_name if isinstance(local_name, str) else None))
    return rows


async def _sync_holiday_year(db: AsyncSession, organization_id: int, country: str, year: int) -> int:
    """Populate a missing holiday year without making calendar viewers need admin access."""
    async with aiohttp.ClientSession() as session:
        async with session.get(f"https://date.nager.at/api/v3/PublicHolidays/{year}/{country}", timeout=aiohttp.ClientTimeout(total=10)) as response:
            if response.status != 200:
                raise HTTPException(status_code=502, detail="Holiday provider is unavailable")
            payload = await response.json()
    added = 0
    for holiday_day, name, local_name in _holiday_provider_rows(payload):
        exists = await db.scalar(select(HolidayRecord.id).where(HolidayRecord.organization_id == organization_id, HolidayRecord.country_code == country, HolidayRecord.holiday_date == holiday_day, HolidayRecord.name == name))
        if not exists:
            db.add(HolidayRecord(organization_id=organization_id, country_code=country, holiday_date=holiday_day, name=name, local_name=local_name))
            added += 1
    if added:
        await db.flush()
    return added


@router.get("/calendar/events")
async def calendar_events(scope: Literal["private", "corporate"] = "private", date_from: date | None = None, date_to: date | None = None, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    period_start = date_from or date.today() - timedelta(days=14)
    period_end = date_to or period_start + timedelta(days=41)
    task_scope = "organization" if scope == "corporate" and actor.has_any_role(*MANAGEMENT_ROLES) else "mine"
    # ``list_tasks`` is also a FastAPI endpoint, whose priority default is a
    # Query marker until FastAPI resolves an HTTP request.  This internal call
    # must provide the concrete value rather than passing that marker to SQL.
    task_rows = await list_tasks(scope=task_scope, priority=None, date_from=period_start, date_to=period_end, db=db, actor=actor)
    if scope == "private":
        task_rows = [row for row in task_rows if actor.employee_id and actor.employee_id in row.get("assignee_ids", [])]
    task_events = [{"kind": "task", "visibility": "company" if scope == "corporate" else "private", "can_edit": actor.has_any_role(*MANAGEMENT_ROLES) or actor.employee_id in row.get("assignee_ids", []), **row} for row in task_rows if row.get("start_at") or row.get("deadline_at")]
    project_query = select(Project).where(
        Project.organization_id == actor.organization_id,
        Project.archived_at.is_(None),
        Project.starts_on.isnot(None),
        Project.ends_on.isnot(None),
        Project.starts_on <= period_end,
        Project.ends_on >= period_start,
    )
    if scope == "private" and not actor.has_any_role(*MANAGEMENT_ROLES):
        member_projects = select(ProjectMember.project_id).where(ProjectMember.employee_id == actor.employee_id) if actor.employee_id else select(ProjectMember.project_id).where(ProjectMember.id == -1)
        project_query = project_query.where(or_(Project.manager_id == actor.employee_id, Project.id.in_(member_projects)))
    projects = (await db.execute(project_query.order_by(Project.starts_on, Project.ends_on, Project.id))).scalars().all()
    project_events = [{"kind": "project", "visibility": "company" if scope == "corporate" else "private", "title": project.name, "description": project.description, "starts_on": project.starts_on, "ends_on": project.ends_on, "project_id": project.id, "code": project.code, "status": project.status, "can_edit": actor.has_any_role(*MANAGEMENT_ROLES)} for project in projects]
    plan_events: list[dict] = []
    if scope == "corporate":
        plan_query = select(CompanyPlanItem).where(
            CompanyPlanItem.organization_id == actor.organization_id,
            CompanyPlanItem.status == "approved",
            CompanyPlanItem.due_date.isnot(None),
            CompanyPlanItem.plan_month <= period_end,
            CompanyPlanItem.due_date >= period_start,
        )
        plans = (await db.execute(plan_query.order_by(CompanyPlanItem.plan_month, CompanyPlanItem.due_date, CompanyPlanItem.id))).scalars().all()
        plan_events = [{"kind": "plan", "visibility": "company", "title": plan.title, "description": plan.content, "plan_month": plan.plan_month, "due_date": plan.due_date, "horizon": plan.horizon, "plan_id": plan.id, "can_edit": actor.has_any_role(*MANAGEMENT_ROLES)} for plan in plans]
    blocks: list[dict] = []
    entries: list[dict] = []
    holidays: list[dict] = []
    start = datetime.combine(period_start, datetime.min.time(), tzinfo=timezone.utc)
    end = datetime.combine(period_end + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
    if scope == "private":
        rows = (await db.execute(select(PersonalTimeBlock).where(PersonalTimeBlock.account_id == actor.account_id, PersonalTimeBlock.starts_at < end, PersonalTimeBlock.ends_at > start).order_by(PersonalTimeBlock.starts_at))).scalars().all()
        blocks = [{"kind": "time_block", **_time_block_out(row)} for row in rows]
    entry_query = select(CalendarEntry).where(CalendarEntry.organization_id == actor.organization_id, CalendarEntry.starts_at < end, CalendarEntry.ends_at > start)
    if scope == "private":
        entry_query = entry_query.where(CalendarEntry.account_id == actor.account_id)
    else:
        entry_query = entry_query.where(CalendarEntry.visibility == "company")
    entry_rows = (await db.execute(entry_query.order_by(CalendarEntry.starts_at))).scalars().all()
    entries = [{**_calendar_entry_out(row), "can_edit": row.created_by_account_id == actor.account_id or (row.visibility == "company" and actor.has_any_role(*MANAGEMENT_ROLES))} for row in entry_rows]
    organization = await db.get(Organization, actor.organization_id)
    country = str((organization.settings or {}).get("holiday_country", "MN")).upper()
    # A fresh organization used to show an empty calendar until an administrator
    # manually pressed sync.  Load each visible year on demand, then cache it.
    for year in range(period_start.year, period_end.year + 1):
        has_year = await db.scalar(select(HolidayRecord.id).where(HolidayRecord.organization_id == actor.organization_id, HolidayRecord.country_code == country, HolidayRecord.holiday_date >= date(year, 1, 1), HolidayRecord.holiday_date <= date(year, 12, 31)))
        if not has_year:
            try:
                await _sync_holiday_year(db, actor.organization_id, country, year)
                await db.commit()
            # Holiday data is a supplemental cache.  Do not fail a calendar
            # request if a second viewer wins the same cache insert race.
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, HTTPException, IntegrityError):
                await db.rollback()
    holiday_rows = (await db.execute(select(HolidayRecord).where(HolidayRecord.organization_id == actor.organization_id, HolidayRecord.country_code == country, HolidayRecord.is_active.is_(True), HolidayRecord.holiday_date >= period_start, HolidayRecord.holiday_date <= period_end))).scalars().all()
    holidays = [{"id": row.id, "kind": "holiday", "visibility": "company", "title": row.local_name or row.name, "starts_at": datetime.combine(row.holiday_date, datetime.min.time(), tzinfo=timezone.utc), "ends_at": datetime.combine(row.holiday_date + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc), "can_edit": actor.has_any_role(*MANAGEMENT_ROLES)} for row in holiday_rows]
    birthdays = (await db.execute(select(Employee).where(Employee.is_active.is_(True), Employee.birthday.isnot(None)))).scalars().all()
    for employee in birthdays:
        for birthday in _birthday_occurrences(employee.birthday, period_start, period_end):
            holidays.append({"id": f"birthday-{employee.id}-{birthday.year}", "kind": "birthday", "visibility": "company", "title": f"{employee.name}-ийн төрсөн өдөр", "starts_at": datetime.combine(birthday, datetime.min.time(), tzinfo=timezone.utc), "ends_at": datetime.combine(birthday + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc), "can_edit": False})
    return {"scope": scope, "tasks": task_events, "projects": project_events, "plans": plan_events, "time_blocks": blocks, "entries": entries, "holidays": holidays}


@router.post("/calendar/entries", status_code=status.HTTP_201_CREATED)
async def create_calendar_entry(data: CalendarEntryInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    if data.ends_at <= data.starts_at:
        raise HTTPException(status_code=400, detail="Calendar entry must end after it starts")
    if data.visibility == "company" and not actor.has_any_role(*MANAGEMENT_ROLES):
        raise HTTPException(status_code=403, detail="Only supervisors can publish company events")
    entry = CalendarEntry(organization_id=actor.organization_id, account_id=None if data.visibility == "company" else actor.account_id, created_by_account_id=actor.account_id, **data.model_dump())
    db.add(entry)
    await db.flush()
    await record_change(db, actor=actor, topic="calendar", aggregate_type="calendar_entry", aggregate_id=entry.id, operation="created", after=_calendar_entry_out(entry))
    await db.commit()
    return _calendar_entry_out(entry)


@router.post("/calendar/holidays/sync")
async def sync_holidays(year: int = Query(default_factory=lambda: date.today().year), db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles(*MANAGEMENT_ROLES))):
    organization = await db.get(Organization, actor.organization_id)
    country = str((organization.settings or {}).get("holiday_country", "MN")).upper()
    if len(country) != 2:
        raise HTTPException(status_code=400, detail="Set a two-letter holiday country first")
    try:
        added = await _sync_holiday_year(db, actor.organization_id, country, year)
    except aiohttp.ClientError as exc:
        raise HTTPException(status_code=502, detail="Holiday provider is unavailable") from exc
    await db.commit()
    return {"country": country, "year": year, "added": added}


@router.get("/calendar/holiday-settings")
async def get_holiday_settings(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    organization = await db.get(Organization, actor.organization_id)
    current = str((organization.settings or {}).get("holiday_country", "MN")).upper()
    countries = [{"countryCode": "MN", "name": "Mongolia"}]
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://date.nager.at/api/v3/AvailableCountries", timeout=aiohttp.ClientTimeout(total=5)) as response:
                if response.status == 200:
                    countries = await response.json()
    except aiohttp.ClientError:
        pass
    return {"country": current, "countries": countries}


@router.put("/calendar/holiday-country")
async def set_holiday_country(data: HolidayCountryInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles("admin"))):
    country = data.country_code.strip().upper()
    if len(country) != 2 or not country.isalpha():
        raise HTTPException(status_code=400, detail="Country must be a two-letter code")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://date.nager.at/api/v3/AvailableCountries", timeout=aiohttp.ClientTimeout(total=5)) as response:
                if response.status == 200:
                    supported = {item["countryCode"] for item in await response.json()}
                    if country not in supported:
                        raise HTTPException(status_code=400, detail="Holiday country is not supported")
    except aiohttp.ClientError:
        if country != "MN":
            raise HTTPException(status_code=502, detail="Holiday provider is unavailable")
    organization = await db.get(Organization, actor.organization_id, with_for_update=True)
    organization.settings = {**(organization.settings or {}), "holiday_country": country}
    await db.commit()
    return {"country": country}


@router.post("/calendar/holidays/overrides", status_code=status.HTTP_201_CREATED)
async def create_holiday_override(data: HolidayOverrideInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles(*MANAGEMENT_ROLES))):
    organization = await db.get(Organization, actor.organization_id)
    country = str((organization.settings or {}).get("holiday_country", "MN")).upper()
    holiday = HolidayRecord(organization_id=actor.organization_id, country_code=country, holiday_date=data.holiday_date, name=data.name, local_name=data.name, is_active=data.is_active, is_override=True)
    db.add(holiday)
    await db.commit()
    return {"id": holiday.id, "kind": "holiday", "title": holiday.name, "date": holiday.holiday_date}


@router.post("/calendar/time-blocks", status_code=status.HTTP_201_CREATED)
async def create_time_block(data: PersonalTimeBlockInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    if data.ends_at <= data.starts_at:
        raise HTTPException(status_code=400, detail="Time block must end after it starts")
    if data.task_id:
        await _task_for_actor(db, data.task_id, actor, write=True)
    block = PersonalTimeBlock(organization_id=actor.organization_id, account_id=actor.account_id, **data.model_dump())
    db.add(block)
    await db.flush()
    await record_change(db, actor=actor, topic="calendar", aggregate_type="personal_time_block", aggregate_id=block.id, operation="created", after=_time_block_out(block))
    await db.commit()
    return _time_block_out(block)


@router.get("/today/agenda")
async def today_agenda(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    start_day = date.today()
    end_day = start_day + timedelta(days=6)
    start = datetime.combine(start_day, datetime.min.time(), tzinfo=timezone.utc)
    end = datetime.combine(end_day + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
    task_query = select(Task).where(Task.organization_id == actor.organization_id, Task.is_archived.is_(False), or_(Task.start_at < end, Task.deadline_at < end), or_(Task.start_at.is_(None), Task.start_at >= start, Task.deadline_at >= start))
    # Today is personal even for supervisors; company aggregation belongs in Stats.
    if actor.employee_id:
        task_query = task_query.where(_task_employee_scope(actor.employee_id))
    else:
        task_query = task_query.where(Task.id == -1)
    tasks = (await db.execute(task_query.order_by(Task.start_at.nulls_last(), Task.deadline_at.nulls_last()))).scalars().all()
    entries = (await db.execute(select(CalendarEntry).where(CalendarEntry.organization_id == actor.organization_id, CalendarEntry.starts_at < end, CalendarEntry.ends_at > start, or_(CalendarEntry.account_id == actor.account_id, CalendarEntry.visibility == "company")).order_by(CalendarEntry.starts_at))).scalars().all()
    return {"date_from": start_day, "date_to": end_day, "tasks": [{"kind": "task", **_task_out(task)} for task in tasks], "entries": [_calendar_entry_out(entry) for entry in entries]}


@router.patch("/calendar/time-blocks/{block_id}")
async def update_time_block(block_id: int, data: PersonalTimeBlockPatch, if_match: str | None = Header(default=None, alias="If-Match"), db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    block = await db.get(PersonalTimeBlock, block_id, with_for_update=True)
    if not block or block.account_id != actor.account_id:
        raise HTTPException(status_code=404, detail="Time block not found")
    if if_match is not None:
        try:
            expected = int(if_match.strip('W/"'))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="If-Match must contain a version") from exc
        if expected != block.version:
            raise HTTPException(status_code=409, detail="Time block changed")
    patch = data.model_dump(exclude_unset=True)
    starts_at = patch.get("starts_at", block.starts_at)
    ends_at = patch.get("ends_at", block.ends_at)
    if ends_at <= starts_at:
        raise HTTPException(status_code=400, detail="Time block must end after it starts")
    if patch.get("task_id"):
        await _task_for_actor(db, patch["task_id"], actor, write=True)
    for field, value in patch.items():
        setattr(block, field, value)
    block.version += 1
    await db.commit()
    return _time_block_out(block)


@router.delete("/calendar/time-blocks/{block_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_time_block(block_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    block = await db.get(PersonalTimeBlock, block_id)
    if not block or block.account_id != actor.account_id:
        raise HTTPException(status_code=404, detail="Time block not found")
    await db.delete(block)
    await db.commit()


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


@router.get("/tasks/{task_id}/dependencies")
async def list_dependencies(task_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await _task_for_actor(db, task_id, actor)
    rows = (await db.execute(
        select(TaskDependency, Task.title).join(Task, Task.id == TaskDependency.predecessor_task_id).where(
            TaskDependency.successor_task_id == task_id,
            Task.organization_id == actor.organization_id,
        ).order_by(TaskDependency.id)
    )).all()
    return [{"id": row.id, "predecessor_task_id": row.predecessor_task_id, "predecessor_title": title, "successor_task_id": row.successor_task_id, "dependency_type": row.dependency_type} for row, title in rows]


@router.delete("/tasks/{task_id}/dependencies/{dependency_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_dependency(task_id: int, dependency_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles(*MANAGEMENT_ROLES))):
    await _task_for_actor(db, task_id, actor, write=True)
    dependency = await db.get(TaskDependency, dependency_id)
    if not dependency or dependency.successor_task_id != task_id:
        raise HTTPException(status_code=404, detail="Dependency not found")
    await record_change(db, actor=actor, topic="tasks", aggregate_type="task_dependency", aggregate_id=dependency.id, operation="deleted", before={"predecessor_task_id": dependency.predecessor_task_id, "successor_task_id": task_id})
    await db.delete(dependency)
    await db.commit()


@router.post("/tasks/{task_id}/check-items", status_code=status.HTTP_201_CREATED)
async def add_check_item(task_id: int, data: CheckItemInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    task = await _task_for_actor(db, task_id, actor, write=True)
    item = TaskCheckItem(task_id=task_id, **data.model_dump())
    db.add(item)
    await db.flush()
    await record_change(db, actor=actor, topic="tasks", aggregate_type="task_check_item", aggregate_id=item.id, operation="created", after={"task_id": task_id, "text": item.text})
    await db.commit()
    return {"id": item.id, "task_id": task_id, **data.model_dump()}


@router.get("/tasks/{task_id}/check-items")
async def list_check_items(task_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await _task_for_actor(db, task_id, actor)
    rows = (await db.execute(select(TaskCheckItem).where(TaskCheckItem.task_id == task_id).order_by(TaskCheckItem.position, TaskCheckItem.id))).scalars().all()
    return [{"id": row.id, "task_id": row.task_id, "text": row.text, "is_completed": row.is_completed, "assignee_id": row.assignee_id, "position": _decimal(row.position), "completed_at": row.completed_at, "created_at": row.created_at} for row in rows]


@router.patch("/tasks/{task_id}/check-items/{item_id}")
async def update_check_item(task_id: int, item_id: int, data: CheckItemPatch, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await _task_for_actor(db, task_id, actor, write=True)
    item = await db.get(TaskCheckItem, item_id, with_for_update=True)
    if not item or item.task_id != task_id:
        raise HTTPException(status_code=404, detail="Checklist item not found")
    before = {"text": item.text, "is_completed": item.is_completed, "assignee_id": item.assignee_id, "position": _decimal(item.position)}
    patch = data.model_dump(exclude_unset=True)
    for field, value in patch.items():
        setattr(item, field, value)
    if "is_completed" in patch:
        item.completed_at = datetime.now(timezone.utc) if item.is_completed else None
    await record_change(db, actor=actor, topic="tasks", aggregate_type="task_check_item", aggregate_id=item.id, operation="updated", before=before, after={"task_id": task_id, **patch})
    await db.commit()
    return {"id": item.id, "task_id": task_id, "text": item.text, "is_completed": item.is_completed, "assignee_id": item.assignee_id, "position": _decimal(item.position), "completed_at": item.completed_at}


@router.delete("/tasks/{task_id}/check-items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_check_item(task_id: int, item_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await _task_for_actor(db, task_id, actor, write=True)
    item = await db.get(TaskCheckItem, item_id)
    if not item or item.task_id != task_id:
        raise HTTPException(status_code=404, detail="Checklist item not found")
    await record_change(db, actor=actor, topic="tasks", aggregate_type="task_check_item", aggregate_id=item.id, operation="deleted", before={"task_id": task_id, "text": item.text})
    await db.delete(item)
    await db.commit()


@router.get("/tasks/{task_id}/activity")
async def task_activity(task_id: int, limit: int = Query(default=100, ge=1, le=200), db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await _task_for_actor(db, task_id, actor)
    candidates = (await db.execute(select(AuditLog).where(
        AuditLog.organization_id == actor.organization_id,
        AuditLog.entity_type.in_(("task", "task_assignees", "task_dependency", "task_check_item", "task_comment", "attachment")),
    ).order_by(AuditLog.created_at.desc()).limit(limit * 4))).scalars().all()
    rows = []
    for event in candidates:
        before = event.before_data or {}
        after = event.after_data or {}
        belongs = event.entity_type == "task" and event.entity_id == task_id
        belongs = belongs or before.get("task_id") == task_id or after.get("task_id") == task_id
        belongs = belongs or after.get("object_type") == "task" and after.get("object_id") == task_id
        belongs = belongs or before.get("object_type") == "task" and before.get("object_id") == task_id
        if belongs:
            rows.append({"id": event.id, "action": event.action, "entity_type": event.entity_type, "entity_id": event.entity_id, "actor_account_id": event.actor_account_id, "actor_employee_id": event.actor_employee_id, "before": before, "after": after, "created_at": event.created_at})
        if len(rows) >= limit:
            break
    return rows


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
    try:
        scan_status = await scan_upload(content)
    except MalwareDetected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except MalwareScanUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    storage_key = f"{actor.organization_id}/{object_type}/{object_id}/{uuid.uuid4().hex}"
    checksum = hashlib.sha256(content).hexdigest()
    await put_attachment(storage_key, content, content_type)
    attachment = Attachment(organization_id=actor.organization_id, object_type=object_type, object_id=object_id, storage_key=storage_key, filename=filename, content_type=content_type, size=len(content), checksum=checksum, uploaded_by_account_id=actor.account_id, scan_status=scan_status)
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
    employee = await db.get(Employee, actor.employee_id)
    now = datetime.now(timezone.utc)
    local_day = now.astimezone(ZoneInfo(employee.timezone)).date()
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
    active = next((item for item in reversed(entries) if item.ended_at is None), None)
    return {
        "active": _entry_out(active) if active else None,
        "today_entries": [_entry_out(item) for item in entries],
        "timezone": employee.timezone,
        "server_time": now,
    }


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
async def capacity(
    date_from: date | None = None,
    date_to: date | None = None,
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_roles(*MANAGEMENT_ROLES)),
):
    today = date.today()
    week_start = date_from or today - timedelta(days=today.weekday())
    week_end = date_to or week_start + timedelta(days=6)
    if week_start > week_end or (week_end - week_start).days > 366:
        raise HTTPException(status_code=400, detail="Capacity period must be between 1 and 367 days")
    period_workdays = sum(1 for offset in range((week_end - week_start).days + 1) if (week_start + timedelta(days=offset)).weekday() < 5)
    employees = (await db.execute(select(Employee).where(Employee.is_active.is_(True)).order_by(Employee.name))).scalars().all()
    allocations = (await db.execute(select(ResourceAllocation).where(ResourceAllocation.status.in_(("planned", "active")), ResourceAllocation.starts_on <= week_end, ResourceAllocation.ends_on >= week_start))).scalars().all()
    approved_leave = (await db.execute(select(TimeOff).where(TimeOff.status == "approved", TimeOff.starts_on <= week_end, TimeOff.ends_on >= week_start))).scalars().all()
    estimated_tasks = (await db.execute(select(Task).where(Task.organization_id == actor.organization_id, Task.workflow_status.in_(("backlog", "to_do", "in_progress", "review")), Task.estimate_minutes.isnot(None), or_(Task.deadline_at.is_(None), Task.deadline_at >= datetime.combine(week_start, datetime.min.time(), tzinfo=timezone.utc)), or_(Task.start_at.is_(None), Task.start_at < datetime.combine(week_end + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc))))).scalars().all()
    by_employee: dict[int, int] = {}
    for allocation in allocations:
        by_employee[allocation.employee_id] = by_employee.get(allocation.employee_id, 0) + int(allocation.planned_minutes or 0)
        if allocation.planned_minutes is None and allocation.allocation_percent is not None:
            employee = next((item for item in employees if item.id == allocation.employee_id), None)
            if employee:
                by_employee[allocation.employee_id] += round(employee.weekly_capacity_minutes / 5 * period_workdays * float(allocation.allocation_percent) / 100)
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
        available = max(0, round(employee.weekly_capacity_minutes / 5 * period_workdays) - leave_minutes.get(employee.id, 0))
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
    if not report or report.employee_id != actor.employee_id:
        raise HTTPException(status_code=404, detail="Report not found")
    if report.status not in {"awaiting", "draft", "editing", "revision_requested"}:
        raise HTTPException(status_code=409, detail="Report cannot be submitted from its current state")
    report.status = "submitted"
    report.submitted_by_account_id = actor.account_id
    report.submitted_at = datetime.now(timezone.utc)
    report.version += 1
    source_event = await record_change(db, actor=actor, topic="reports", aggregate_type="work_report", aggregate_id=report.id, operation="submitted", version=report.version, after={"status": report.status})
    employee = await db.get(Employee, report.employee_id)
    await create_notifications(
        db, organization_id=actor.organization_id, account_ids=await _management_account_ids(db, actor.organization_id),
        kind="report_submitted", title="Шинэ тайлан", body=f"{employee.name if employee else 'Ажилтан'} тайлангаа илгээлээ.",
        target_url=f"/reports?report={report.id}", payload={"report_id": report.id}, source_event_id=source_event.id,
        dedup_key=f"report-submitted:{report.id}:v{report.version}",
    )
    await db.commit()
    return {"id": report.id, "status": report.status, "version": report.version}


@router.post("/reports", status_code=status.HTTP_201_CREATED)
async def create_report(data: ReportCreateInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    if not actor.employee_id:
        raise HTTPException(status_code=409, detail="Account is not linked to an employee")
    period_date = data.period_date if data.report_type == "daily" else data.period_date.replace(day=1)
    report = (await db.execute(select(WorkReport).where(
        WorkReport.employee_id == actor.employee_id,
        WorkReport.report_type == data.report_type,
        WorkReport.period_date == period_date,
    ))).scalar_one_or_none()
    if report is None:
        report = WorkReport(employee_id=actor.employee_id, report_type=data.report_type, period_date=period_date, status="awaiting")
        db.add(report)
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            report = (await db.execute(select(WorkReport).where(
                WorkReport.employee_id == actor.employee_id,
                WorkReport.report_type == data.report_type,
                WorkReport.period_date == period_date,
            ))).scalar_one()
        else:
            await record_change(db, actor=actor, topic="reports", aggregate_type="work_report", aggregate_id=report.id, operation="created", after={"report_type": report.report_type, "period_date": str(report.period_date), "status": report.status})
            await db.commit()
    return {"id": report.id, "employee_id": report.employee_id, "report_type": report.report_type, "period_date": report.period_date, "status": report.status, "title": report.title, "version": report.version}


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
    if not report or report.employee_id != actor.employee_id:
        raise HTTPException(status_code=404, detail="Report not found")
    if report.status == "approved":
        raise HTTPException(status_code=409, detail="Approved reports are immutable")
    if if_match is not None and int(if_match.strip('W/"')) != report.version:
        raise HTTPException(status_code=409, detail={"message": "Report changed", "latest_version": report.version})
    await db.execute(WorkReportRevision.__table__.update().where(WorkReportRevision.report_id == report_id, WorkReportRevision.status == "draft").values(status="superseded"))
    revision = WorkReportRevision(report_id=report_id, text=data.markdown, author_account_id=actor.account_id, status="draft")
    db.add(revision)
    report.title = data.title
    # A submitted report remains submitted while its author makes follow-up
    # edits. This preserves the one-time submit action and keeps monthly reports
    # available for review until they are approved.
    if report.status != "submitted":
        report.status = "draft"
    report.version += 1
    await db.flush()
    await record_change(db, actor=actor, topic="reports", aggregate_type="work_report", aggregate_id=report.id, operation="draft_saved", version=report.version, after={"title": report.title, "revision_id": revision.id, "status": report.status})
    await db.commit()
    return {"id": report.id, "title": report.title, "status": report.status, "version": report.version, "revision_id": revision.id, "markdown": revision.text}


@router.get("/reports")
async def list_enterprise_reports(
    report_status: str | None = Query(default=None, alias="status"),
    date_from: date | None = None,
    date_to: date | None = None,
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
    if date_from:
        query = query.where(WorkReport.period_date >= date_from)
    if date_to:
        query = query.where(WorkReport.period_date <= date_to)
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
    if report.report_type != "monthly":
        raise HTTPException(status_code=409, detail="Only monthly reports require approval")
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
    source_event = await record_change(db, actor=actor, topic="reports", aggregate_type="work_report", aggregate_id=report.id, operation=operation, version=report.version, after={"status": report.status})
    await create_notifications(
        db, organization_id=actor.organization_id, employee_ids={report.employee_id},
        exclude_employee_id=actor.employee_id, kind=f"report_{operation}",
        title="Тайлангийн төлөв шинэчлэгдлээ",
        body="Таны тайлан батлагдлаа." if target_status == "approved" else "Таны тайланд засвар хүссэн байна.",
        target_url=f"/reports?report={report.id}", payload={"report_id": report.id, "status": report.status},
        source_event_id=source_event.id, dedup_key=f"report-{operation}:{report.id}:v{report.version}",
    )
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
    if not report or (not actor.has_any_role(*MANAGEMENT_ROLES) and report.employee_id != actor.employee_id):
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


@router.post("/reports/{report_id}/reopen")
async def reopen_report(
    report_id: int,
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_roles("admin")),
):
    report = await db.get(WorkReport, report_id, with_for_update=True)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    if report.report_type != "monthly":
        raise HTTPException(status_code=409, detail="Only monthly reports can be reopened")
    if report.status not in {"submitted", "approved"}:
        raise HTTPException(status_code=409, detail="Only sent reports can be reopened")
    before = {"status": report.status, "version": report.version}
    report.status = "revision_requested"
    report.reviewed_at = None
    report.reviewer_account_id = None
    report.version += 1
    await record_change(
        db,
        actor=actor,
        topic="reports",
        aggregate_type="work_report",
        aggregate_id=report.id,
        operation="admin_reopened",
        version=report.version,
        before=before,
        after={"status": report.status, "version": report.version},
    )
    await db.commit()
    return {"id": report.id, "status": report.status, "version": report.version}


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
    if not templates and actor.has_any_role(*MANAGEMENT_ROLES):
        legacy_questions = (await db.execute(select(Question).order_by(Question.sort_order))).scalars().all()
        if legacy_questions:
            template = CheckinTemplate(organization_id=actor.organization_id, name="Daily check-in", cadence="daily")
            db.add(template)
            await db.flush()
            for position, question in enumerate(legacy_questions):
                db.add(CheckinQuestion(template_id=template.id, prompt={"mn": question.text, "source_question_id": question.id}, answer_type=question.answer_type, choices=question.options or [], is_required=bool(question.is_required), position=position))
            await db.commit()
            templates = [template]
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


async def _applicable_legacy_questions(db: AsyncSession, employee_id: int) -> list[Question]:
    assigned_to_employee = select(EmployeeQuestion.question_id).where(EmployeeQuestion.employee_id == employee_id)
    assigned_to_anyone = select(EmployeeQuestion.question_id)
    return list((await db.execute(
        select(Question).where(or_(Question.id.in_(assigned_to_employee), Question.id.not_in(assigned_to_anyone))).order_by(Question.sort_order, Question.id)
    )).scalars().all())


async def _employee_checkin_template(db: AsyncSession, organization_id: int, employee_id: int, questions: list[Question]) -> CheckinTemplate:
    template_name = f"Daily check-in [employee:{employee_id}]"
    template = (await db.execute(select(CheckinTemplate).where(
        CheckinTemplate.organization_id == organization_id,
        CheckinTemplate.name == template_name,
    ))).scalar_one_or_none()
    if template is None:
        template = CheckinTemplate(organization_id=organization_id, name=template_name, cadence="daily")
        db.add(template)
        await db.flush()
    canonical = (await db.execute(select(CheckinQuestion).where(CheckinQuestion.template_id == template.id))).scalars().all()
    by_source = {
        int(item.prompt["source_question_id"]): item
        for item in canonical
        if isinstance(item.prompt, dict) and item.prompt.get("source_question_id") is not None
    }
    for position, question in enumerate(questions):
        prompt = {"mn": question.text, "source_question_id": question.id}
        item = by_source.get(question.id)
        if item is None:
            item = CheckinQuestion(template_id=template.id)
            db.add(item)
        item.prompt = prompt
        item.answer_type = question.answer_type
        item.choices = question.options or []
        item.is_required = bool(question.is_required)
        item.position = position
    await db.flush()
    return template


@router.get("/checkins/today")
async def today_checkin(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    if not actor.employee_id:
        return {"template": None, "checkin": None, "answers": []}
    employee = await db.get(Employee, actor.employee_id)
    local_day = datetime.now(timezone.utc).astimezone(ZoneInfo(employee.timezone)).date()
    legacy_questions = await _applicable_legacy_questions(db, actor.employee_id)
    if not legacy_questions:
        return {"template": None, "checkin": None, "answers": []}
    template = await _employee_checkin_template(db, actor.organization_id, actor.employee_id, legacy_questions)
    source_ids = {question.id for question in legacy_questions}
    questions = [
        question for question in (await db.execute(select(CheckinQuestion).where(CheckinQuestion.template_id == template.id).order_by(CheckinQuestion.position))).scalars().all()
        if isinstance(question.prompt, dict) and question.prompt.get("source_question_id") in source_ids
    ]
    await db.commit()
    checkin = (await db.execute(select(Checkin).where(Checkin.employee_id == actor.employee_id, Checkin.template_id == template.id, Checkin.local_date == local_day))).scalar_one_or_none()
    answers = (await db.execute(select(CheckinAnswer).where(CheckinAnswer.checkin_id == checkin.id))).scalars().all() if checkin else []
    return {
        "template": {"id": template.id, "name": template.name, "questions": [{"id": q.id, "prompt": q.prompt, "answer_type": q.answer_type, "choices": q.choices, "is_required": q.is_required} for q in questions]},
        "checkin": {"id": checkin.id, "status": checkin.status, "local_date": checkin.local_date} if checkin else None,
        "answers": [{"question_id": a.question_id, "value_text": a.value_text, "value_numeric": _decimal(a.value_numeric), "value_json": a.value_json} for a in answers],
    }


@router.post("/checkins", status_code=status.HTTP_201_CREATED)
async def start_checkin(data: CheckinStartInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    if not actor.employee_id:
        raise HTTPException(status_code=409, detail="Account is not linked to an employee")
    template = await db.get(CheckinTemplate, data.template_id)
    if not template or template.organization_id != actor.organization_id or not template.is_active:
        raise HTTPException(status_code=404, detail="Check-in template not found")
    employee = await db.get(Employee, actor.employee_id)
    local_day = data.local_date or datetime.now(timezone.utc).astimezone(ZoneInfo(employee.timezone)).date()
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
    applicable = await _applicable_legacy_questions(db, checkin.employee_id)
    source_ids = {question.id for question in applicable}
    questions = [
        question for question in (await db.execute(select(CheckinQuestion).where(CheckinQuestion.template_id == checkin.template_id))).scalars().all()
        if isinstance(question.prompt, dict) and question.prompt.get("source_question_id") in source_ids
    ]
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


def _task_employee_scope(employee_id: int):
    contributor_tasks = select(TaskAssignee.task_id).where(TaskAssignee.employee_id == employee_id)
    return or_(Task.assignee_id == employee_id, Task.id.in_(contributor_tasks))


async def _performance_summary(db: AsyncSession, actor: ActorContext, employee_id: int | None, date_from: date, date_to: date) -> dict:
    task_conditions = [Task.organization_id == actor.organization_id, Task.is_archived.is_(False)]
    if employee_id is not None:
        task_conditions.append(_task_employee_scope(employee_id))
    task_conditions.extend((
        or_(Task.deadline_at.is_(None), Task.deadline_at >= datetime.combine(date_from, datetime.min.time(), tzinfo=timezone.utc)),
        or_(Task.start_at.is_(None), Task.start_at < datetime.combine(date_to + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)),
    ))
    task_total = await db.scalar(select(func.count()).select_from(Task).where(*task_conditions)) or 0
    completed = await db.scalar(select(func.count()).select_from(Task).where(*task_conditions, Task.workflow_status == "done")) or 0

    work_conditions = [
        WorkTimeEntry.entry_type == "work",
        WorkTimeEntry.employee_id.isnot(None),
        WorkTimeEntry.ended_at.isnot(None),
        WorkTimeEntry.local_work_date >= date_from,
        WorkTimeEntry.local_work_date <= date_to,
        UserAccount.organization_id == actor.organization_id,
        UserAccount.status == "active",
    ]
    if employee_id is not None:
        work_conditions.append(WorkTimeEntry.employee_id == employee_id)
    worked = await db.scalar(select(func.coalesce(func.sum(func.extract("epoch", WorkTimeEntry.ended_at - WorkTimeEntry.started_at) / 60), 0)).join(UserAccount, UserAccount.employee_id == WorkTimeEntry.employee_id).where(*work_conditions)) or 0
    billable = await db.scalar(select(func.coalesce(func.sum(func.extract("epoch", WorkTimeEntry.ended_at - WorkTimeEntry.started_at) / 60), 0)).join(UserAccount, UserAccount.employee_id == WorkTimeEntry.employee_id).where(*work_conditions, WorkTimeEntry.is_billable.is_(True), WorkTimeEntry.approval_status == "approved")) or 0

    report_conditions = [WorkReport.period_date >= date_from, WorkReport.period_date <= date_to, UserAccount.organization_id == actor.organization_id, UserAccount.status == "active"]
    if employee_id is not None:
        report_conditions.append(WorkReport.employee_id == employee_id)
    report_total = await db.scalar(select(func.count()).select_from(WorkReport).join(UserAccount, UserAccount.employee_id == WorkReport.employee_id).where(*report_conditions)) or 0
    submitted_reports = await db.scalar(select(func.count()).select_from(WorkReport).join(UserAccount, UserAccount.employee_id == WorkReport.employee_id).where(*report_conditions, WorkReport.status.in_(("submitted", "approved")))) or 0
    return {
        "task_total": task_total,
        "completed_tasks": completed,
        "completion_rate": round(completed * 100 / max(task_total, 1), 1),
        "worked_minutes": round(float(worked)),
        "average_work_minutes": round(float(worked) / max((date_to - date_from).days + 1, 1)),
        "billable_minutes": round(float(billable)),
        "billable_ratio": round(float(billable) * 100 / max(float(worked), 1), 1),
        "report_total": report_total,
        "submitted_reports": submitted_reports,
        "report_submission_rate": round(submitted_reports * 100 / max(report_total, 1), 1),
        "date_from": date_from,
        "date_to": date_to,
    }


@router.get("/analytics/summary")
async def analytics_summary(
    date_from: date | None = None,
    date_to: date | None = None,
    employee_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    period_end = date_to or date.today()
    period_start = date_from or period_end - timedelta(days=6)
    if period_start > period_end:
        raise HTTPException(status_code=400, detail="date_from must not be after date_to")
    if employee_id is not None and employee_id != actor.employee_id and not actor.has_any_role(*MANAGEMENT_ROLES):
        raise HTTPException(status_code=403, detail="Worker analytics are outside your scope")
    employee_scope = employee_id if actor.has_any_role(*MANAGEMENT_ROLES) and employee_id is not None else None if actor.has_any_role(*MANAGEMENT_ROLES) else actor.employee_id
    if employee_scope is None and not actor.has_any_role(*MANAGEMENT_ROLES):
        return {**await _performance_summary(db, actor, -1, period_start, period_end), "active_projects": 0, "scope": "personal"}
    summary = await _performance_summary(db, actor, employee_scope, period_start, period_end)
    project_query = select(func.count()).select_from(Project).where(Project.organization_id == actor.organization_id, Project.status == "active")
    if employee_scope is not None:
        project_query = project_query.where(Project.id.in_(select(ProjectMember.project_id).where(ProjectMember.employee_id == employee_scope)))
    summary["active_projects"] = await db.scalar(project_query) or 0
    summary["scope"] = "organization" if employee_scope is None else "worker" if actor.has_any_role(*MANAGEMENT_ROLES) and employee_id else "personal"
    return summary


@router.get("/analytics/daily")
async def analytics_daily(
    date_from: date,
    date_to: date,
    employee_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    if date_from > date_to or (date_to - date_from).days > 370:
        raise HTTPException(status_code=400, detail="Analytics period must be between 1 and 371 days")
    if employee_id is not None and employee_id != actor.employee_id and not actor.has_any_role(*MANAGEMENT_ROLES):
        raise HTTPException(status_code=403, detail="Worker analytics are outside your scope")
    target = employee_id if actor.has_any_role(*MANAGEMENT_ROLES) else actor.employee_id
    analytics_now = datetime.now(timezone.utc)
    work_query = select(
        WorkTimeEntry.local_work_date,
        func.coalesce(func.sum(func.extract("epoch", func.coalesce(WorkTimeEntry.ended_at, analytics_now) - WorkTimeEntry.started_at) / 60), 0),
    ).where(
        WorkTimeEntry.entry_type == "work", WorkTimeEntry.employee_id.isnot(None),
        WorkTimeEntry.local_work_date >= date_from, WorkTimeEntry.local_work_date <= date_to,
        UserAccount.organization_id == actor.organization_id, UserAccount.status == "active",
    )
    if target is not None:
        work_query = work_query.where(WorkTimeEntry.employee_id == target)
    work_rows = (await db.execute(work_query.join(UserAccount, UserAccount.employee_id == WorkTimeEntry.employee_id).group_by(WorkTimeEntry.local_work_date))).all()
    work_by_day = {row[0]: round(float(row[1])) for row in work_rows}
    task_query = select(Task.completed_at).where(
        Task.organization_id == actor.organization_id, Task.workflow_status == "done", Task.completed_at.isnot(None),
        Task.completed_at >= datetime.combine(date_from, datetime.min.time(), tzinfo=timezone.utc),
        Task.completed_at < datetime.combine(date_to + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc),
    )
    if target is not None:
        task_query = task_query.where(_task_employee_scope(target))
    completed_by_day: dict[date, int] = {}
    for completed_at in (await db.execute(task_query)).scalars().all():
        completed_by_day[completed_at.date()] = completed_by_day.get(completed_at.date(), 0) + 1
    days = []
    cursor = date_from
    while cursor <= date_to:
        days.append({"date": cursor, "worked_minutes": work_by_day.get(cursor, 0), "completed_tasks": completed_by_day.get(cursor, 0)})
        cursor += timedelta(days=1)
    return {"date_from": date_from, "date_to": date_to, "employee_id": target, "days": days}


@router.get("/analytics/work-hours")
async def analytics_work_hours(
    date_from: date,
    date_to: date,
    employee_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    if date_from > date_to or (date_to - date_from).days > 370:
        raise HTTPException(status_code=400, detail="Analytics period must be between 1 and 371 days")
    if employee_id is not None and employee_id != actor.employee_id and not actor.has_any_role(*MANAGEMENT_ROLES):
        raise HTTPException(status_code=403, detail="Worker analytics are outside your scope")

    target = employee_id if actor.has_any_role(*MANAGEMENT_ROLES) else actor.employee_id or -1
    analytics_now = datetime.now(timezone.utc)
    conditions = [
        WorkTimeEntry.entry_type == "work",
        WorkTimeEntry.mode.in_(("remote", "in_person")),
        WorkTimeEntry.employee_id.isnot(None),
        WorkTimeEntry.local_work_date >= date_from,
        WorkTimeEntry.local_work_date <= date_to,
        UserAccount.organization_id == actor.organization_id,
        UserAccount.status == "active",
    ]
    if target is not None:
        conditions.append(WorkTimeEntry.employee_id == target)

    rows = (
        await db.execute(
            select(
                WorkTimeEntry.mode,
                func.coalesce(
                    func.sum(
                        func.extract(
                            "epoch",
                            func.coalesce(WorkTimeEntry.ended_at, analytics_now) - WorkTimeEntry.started_at,
                        )
                        / 60,
                    ),
                    0,
                ),
            )
            .join(UserAccount, UserAccount.employee_id == WorkTimeEntry.employee_id)
            .where(*conditions)
            .group_by(WorkTimeEntry.mode)
        )
    ).all()
    minutes_by_mode = {mode: round(float(minutes or 0)) for mode, minutes in rows}
    remote_minutes = minutes_by_mode.get("remote", 0)
    office_minutes = minutes_by_mode.get("in_person", 0)
    return {
        "date_from": date_from,
        "date_to": date_to,
        "employee_id": None if actor.has_any_role(*MANAGEMENT_ROLES) and employee_id is None else target,
        "remote_minutes": remote_minutes,
        "office_minutes": office_minutes,
        "total_minutes": remote_minutes + office_minutes,
        "scope": "organization" if actor.has_any_role(*MANAGEMENT_ROLES) and employee_id is None else "worker",
    }


ANALYTIC_METRICS = ("utilization", "billable_ratio", "budget_burn", "task_completion", "deadline_health", "report_compliance")


async def _drilldown_employee_ids(db: AsyncSession, actor: ActorContext, employee_id: int | None) -> list[int]:
    active = select(Employee.id).join(UserAccount, UserAccount.employee_id == Employee.id).where(
        UserAccount.organization_id == actor.organization_id, UserAccount.status == "active", Employee.is_active.is_(True),
    )
    if actor.has_any_role("admin", "manager"):
        if employee_id is not None:
            active = active.where(Employee.id == employee_id)
    elif actor.has_any_role("team_lead"):
        managed_team_ids = select(Team.id).where(Team.organization_id == actor.organization_id, Team.manager_id == actor.employee_id)
        assigned_team_ids = select(RoleAssignment.team_id).where(RoleAssignment.account_id == actor.account_id, RoleAssignment.role == "team_lead", RoleAssignment.team_id.isnot(None))
        allowed = select(TeamMember.employee_id).where(TeamMember.team_id.in_(managed_team_ids.union(assigned_team_ids)))
        if actor.employee_id:
            active = active.where(or_(Employee.id.in_(allowed), Employee.id == actor.employee_id))
        else:
            active = active.where(Employee.id.in_(allowed))
        if employee_id is not None:
            active = active.where(Employee.id == employee_id)
    else:
        if actor.has_any_role("contractor", "client_auditor") or not actor.employee_id:
            raise HTTPException(status_code=403, detail="Employee analytics are outside your scope")
        if employee_id is not None and employee_id != actor.employee_id:
            raise HTTPException(status_code=403, detail="Employee analytics are outside your scope")
        active = active.where(Employee.id == actor.employee_id)
    return list((await db.execute(active.distinct().order_by(Employee.id))).scalars().all())


@router.get("/analytics/drilldown")
async def analytics_drilldown(
    metric: Literal["utilization", "billable_ratio", "budget_burn", "task_completion", "deadline_health", "report_compliance"],
    date_from: date | None = None,
    date_to: date | None = None,
    employee_id: int | None = None,
    project_id: int | None = None,
    client_id: int | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    period_end = date_to or date.today()
    period_start = date_from or period_end - timedelta(days=29)
    if period_start > period_end or (period_end - period_start).days > 370:
        raise HTTPException(status_code=400, detail="Analytics period must be between 1 and 371 days")
    if metric == "budget_burn":
        if not actor.has_any_role("admin", "manager"):
            raise HTTPException(status_code=403, detail="Financial analytics require administrator or manager access")
        query = select(Project).where(Project.organization_id == actor.organization_id, Project.archived_at.is_(None))
        if project_id: query = query.where(Project.id == project_id)
        if client_id: query = query.where(Project.client_id == client_id)
        projects = list((await db.execute(query.order_by(Project.name))).scalars().all())
        rows = []
        for project in projects:
            entries = (await db.execute(select(WorkTimeEntry).where(
                WorkTimeEntry.project_id == project.id, WorkTimeEntry.entry_type == "work", WorkTimeEntry.is_billable.is_(True),
                WorkTimeEntry.approval_status == "approved", WorkTimeEntry.ended_at.isnot(None),
                WorkTimeEntry.local_work_date >= period_start, WorkTimeEntry.local_work_date <= period_end,
            ))).scalars().all()
            burned = Decimal("0"); unpriced_minutes = 0
            for entry in entries:
                minutes = Decimal(str((entry.ended_at - entry.started_at).total_seconds() / 60))
                if entry.hourly_rate_snapshot is None or not entry.rate_currency:
                    unpriced_minutes += round(float(minutes)); continue
                amount = minutes * Decimal(entry.hourly_rate_snapshot) / Decimal("60")
                if entry.rate_currency != project.currency:
                    snapshot = await db.get(ExchangeRateSnapshot, entry.exchange_rate_snapshot_id) if entry.exchange_rate_snapshot_id else None
                    if not snapshot or snapshot.base_currency != entry.rate_currency or snapshot.quote_currency != project.currency:
                        unpriced_minutes += round(float(minutes)); continue
                    amount *= Decimal(snapshot.rate)
                burned += amount
            budget = Decimal(project.budget_amount or 0)
            rows.append({"project_id": project.id, "project_name": project.name, "client_id": project.client_id, "currency": project.currency, "budget_amount": _decimal(budget), "burned_amount": float(burned.quantize(Decimal("0.01"))), "remaining_amount": float((budget - burned).quantize(Decimal("0.01"))) if project.budget_amount is not None else None, "value": round(float(burned * 100 / budget), 1) if budget > 0 else None, "unpriced_minutes": unpriced_minutes, "historical_snapshots": True})
    else:
        employee_ids = await _drilldown_employee_ids(db, actor, employee_id)
        employees = {row.id: row for row in (await db.execute(select(Employee).where(Employee.id.in_(employee_ids)))).scalars().all()} if employee_ids else {}
        rows = []
        weekdays = sum(1 for offset in range((period_end - period_start).days + 1) if (period_start + timedelta(days=offset)).weekday() < 5)
        for target_id in employee_ids:
            employee = employees[target_id]
            worked = await db.scalar(select(func.coalesce(func.sum(func.extract("epoch", WorkTimeEntry.ended_at - WorkTimeEntry.started_at) / 60), 0)).where(WorkTimeEntry.employee_id == target_id, WorkTimeEntry.entry_type == "work", WorkTimeEntry.ended_at.isnot(None), WorkTimeEntry.local_work_date >= period_start, WorkTimeEntry.local_work_date <= period_end)) or 0
            billable = await db.scalar(select(func.coalesce(func.sum(func.extract("epoch", WorkTimeEntry.ended_at - WorkTimeEntry.started_at) / 60), 0)).where(WorkTimeEntry.employee_id == target_id, WorkTimeEntry.entry_type == "work", WorkTimeEntry.ended_at.isnot(None), WorkTimeEntry.is_billable.is_(True), WorkTimeEntry.approval_status == "approved", WorkTimeEntry.local_work_date >= period_start, WorkTimeEntry.local_work_date <= period_end)) or 0
            task_scope = [Task.organization_id == actor.organization_id, _task_employee_scope(target_id)]
            if project_id: task_scope.append(Task.project_id == project_id)
            task_total = await db.scalar(select(func.count()).select_from(Task).where(*task_scope, Task.created_at < datetime.combine(period_end + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc))) or 0
            completed = await db.scalar(select(func.count()).select_from(Task).where(*task_scope, Task.workflow_status == "done", Task.completed_at >= datetime.combine(period_start, datetime.min.time(), tzinfo=timezone.utc), Task.completed_at < datetime.combine(period_end + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc))) or 0
            due_total = await db.scalar(select(func.count()).select_from(Task).where(*task_scope, Task.deadline_at >= datetime.combine(period_start, datetime.min.time(), tzinfo=timezone.utc), Task.deadline_at < datetime.combine(period_end + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc))) or 0
            overdue = await db.scalar(select(func.count()).select_from(Task).where(*task_scope, Task.deadline_at < datetime.now(timezone.utc), Task.workflow_status.notin_(("done", "cancelled")), Task.deadline_at >= datetime.combine(period_start, datetime.min.time(), tzinfo=timezone.utc))) or 0
            report_total = await db.scalar(select(func.count()).select_from(WorkReport).where(WorkReport.employee_id == target_id, WorkReport.period_date >= period_start, WorkReport.period_date <= period_end)) or 0
            submitted = await db.scalar(select(func.count()).select_from(WorkReport).where(WorkReport.employee_id == target_id, WorkReport.period_date >= period_start, WorkReport.period_date <= period_end, WorkReport.status.in_(("submitted", "approved")))) or 0
            capacity = round((employee.weekly_capacity_minutes or 2400) * weekdays / 5)
            values = {"utilization": round(float(worked) * 100 / max(capacity, 1), 1), "billable_ratio": round(float(billable) * 100 / max(float(worked), 1), 1), "task_completion": round(completed * 100 / max(task_total, 1), 1), "deadline_health": round((due_total - overdue) * 100 / max(due_total, 1), 1), "report_compliance": round(submitted * 100 / max(report_total, 1), 1)}
            rows.append({"employee_id": target_id, "employee_name": employee.name, "value": values[metric], "worked_minutes": round(float(worked)), "available_minutes": capacity, "billable_minutes": round(float(billable)), "task_total": task_total, "completed_tasks": completed, "due_tasks": due_total, "overdue_tasks": overdue, "report_total": report_total, "submitted_reports": submitted})
    total_count = len(rows); start = (page - 1) * page_size; items = rows[start:start + page_size]
    numeric_values = [row["value"] for row in rows if row.get("value") is not None]
    return {"metric": metric, "scope": "organization" if actor.has_any_role("admin", "manager") and employee_id is None else "scoped", "date_from": period_start, "date_to": period_end, "items": items, "totals": {"count": total_count, "average_value": round(sum(numeric_values) / len(numeric_values), 1) if numeric_values else None, "unpriced_minutes": sum(row.get("unpriced_minutes", 0) for row in rows)}, "page": page, "page_size": page_size, "total": total_count}


@router.get("/workers")
async def worker_directory(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    employees = (await db.execute(select(Employee).where(Employee.is_active.is_(True)).order_by(Employee.name))).scalars().all()
    open_entries = (await db.execute(select(WorkTimeEntry).where(WorkTimeEntry.ended_at.is_(None)))).scalars().all()
    by_employee = {entry.employee_id: entry for entry in open_entries}
    return [
        {
            "id": employee.id,
            "name": employee.name,
            "job_title": employee.job_title,
            "telegram_username": employee.telegram_username,
            "avatar_url": (employee.metadata_json or {}).get("avatar_url"),
            "presence": (
                "break" if by_employee.get(employee.id) and by_employee[employee.id].entry_type == "break"
                else by_employee[employee.id].mode if by_employee.get(employee.id) else "offline"
            ),
        }
        for employee in employees
    ]


@router.get("/workers/{employee_id}/performance")
async def worker_performance(
    employee_id: int,
    date_from: date | None = None,
    date_to: date | None = None,
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_roles(*MANAGEMENT_ROLES)),
):
    employee = await db.get(Employee, employee_id)
    if not employee or not employee.is_active:
        raise HTTPException(status_code=404, detail="Worker not found")
    period_end = date_to or date.today()
    period_start = date_from or period_end - timedelta(days=6)
    if period_start > period_end:
        raise HTTPException(status_code=400, detail="date_from must not be after date_to")
    return {
        "employee": {"id": employee.id, "name": employee.name, "job_title": employee.job_title},
        **await _performance_summary(db, actor, employee.id, period_start, period_end),
    }


async def _assistant_web_tool(db: AsyncSession, decision, actor: ActorContext) -> tuple[dict, dict | None, list[dict]]:
    """Async web adapter for the same classified OYUNS tools Telegram uses."""
    tool = decision.selected_tool
    arguments = decision.tool_arguments
    if tool == assistant_ai.AssistantToolName.CREATE_TASK_DRAFT:
        draft = {"title": arguments.get("title") or "Шинэ даалгавар", "description": None, "priority": arguments.get("priority", 2)}
        if arguments.get("due_date"):
            draft["deadline_at"] = arguments["due_date"]
        return draft, {"type": "task_draft", "payload": draft}, []
    if tool == assistant_ai.AssistantToolName.GET_USER_TASKS:
        if not actor.employee_id:
            return {"count": 0, "tasks": []}, None, []
        tasks = (await db.execute(select(Task).where(Task.organization_id == actor.organization_id, _task_employee_scope(actor.employee_id), Task.is_archived.is_(False)).order_by(Task.deadline_at.nulls_last()).limit(50))).scalars().all()
        return {"count": len(tasks), "tasks": [{"title": task.title, "description": task.description, "status": task.workflow_status, "deadline_at": task.deadline_at} for task in tasks]}, None, []
    if tool == assistant_ai.AssistantToolName.SEARCH_COMPANY_KNOWLEDGE:
        rows = (await db.execute(select(CompanyKnowledge).where(CompanyKnowledge.is_active.is_(True)).order_by(CompanyKnowledge.updated_at.desc()))).scalars().all()
        records = [{"id": row.id, "title": row.title, "category": row.category, "content": row.content, "is_active": row.is_active} for row in rows]
        matches = rank_knowledge(records, [arguments.get("query", "")], limit=5)
        return {"query": arguments.get("query"), "count": len(matches), "documents": matches}, None, [{"id": item["id"], "title": item["title"]} for item in matches]
    if tool == assistant_ai.AssistantToolName.GET_EXCHANGE_RATE:
        result = await exchange_rate_service.get_exchange_rate(provider=arguments["provider"], pair=arguments["pair"], force_refresh=arguments.get("force_refresh", False), request_type=arguments.get("request_type", "single"))
        return result, None, []
    return {}, None, []


@router.post("/assistant/conversations")
async def assistant_chat(data: AssistantChatInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    conversation = await db.get(AssistantConversation, data.conversation_id) if data.conversation_id else None
    if conversation and (conversation.account_id != actor.account_id or conversation.organization_id != actor.organization_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    if not conversation:
        conversation = AssistantConversation(account_id=actor.account_id, organization_id=actor.organization_id, title=data.text.strip()[:120])
        db.add(conversation)
        await db.flush()
    history_rows = (await db.execute(select(AssistantMessage).where(AssistantMessage.conversation_id == conversation.id).order_by(AssistantMessage.id.desc()).limit(12))).scalars().all()
    history = [{"role": row.role, "content": row.content} for row in reversed(history_rows)]
    text = data.text.strip()
    db.add(AssistantMessage(conversation_id=conversation.id, role="user", content=text))
    if settings.ENTERPRISE_TOOLS_ENABLED:
        enterprise = await enterprise_tools.run_agent(db, actor, text=text, history=history, channel="web", conversation_id=conversation.id)
        answer = enterprise["answer"]
        action = {"type": "task_update_preview", "payload": enterprise["action"]} if enterprise.get("action") else None
        sources = enterprise["sources"]
    else:
        workers = [{"id": employee.id, "name": employee.name, "timezone": employee.timezone, "is_active": employee.is_active} for employee in (await db.execute(select(Employee).where(Employee.is_active.is_(True)))).scalars().all()]
        decision = await assistant_ai.classify_intent(text, now=datetime.now(ZoneInfo("Asia/Ulaanbaatar")), timezone_name="Asia/Ulaanbaatar", is_manager=actor.has_any_role(*MANAGEMENT_ROLES), workers=workers, voice_mode=data.voice_mode, chat_history=history, learned_contexts=[])
        raw, action, sources = await _assistant_web_tool(db, decision, actor) if decision.selected_tool else ({}, None, [])
        if action:
            answer = f"“{action['payload']['title']}” даалгаврын ноорог бэлэн. Үүсгэхээс өмнө шалгана уу."
        elif decision.selected_tool and decision.react_messages and decision.assistant_tool_message and decision.tool_call_id:
            answer = await assistant_ai.synthesize_tool_result(request_messages=decision.react_messages, assistant_message=decision.assistant_tool_message, tool_call_id=decision.tool_call_id, raw_result=raw, voice_mode=data.voice_mode)
        else:
            answer = decision.direct_answer or "Асуултаа арай дэлгэрэнгүй асууна уу."
    if not answer:
        answer = "Одоогоор хариулт боловсруулж чадсангүй. Түр хүлээгээд дахин оролдоно уу."
    assistant_message = AssistantMessage(conversation_id=conversation.id, role="assistant", content=answer, action=action, sources=sources)
    db.add(assistant_message)
    conversation.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return {"conversation_id": conversation.id, "message": {"id": assistant_message.id, "role": "assistant", "content": answer, "action": action, "sources": sources}}


@router.post("/assistant/tools")
async def assistant_tool(data: AssistantToolRequest, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    """Typed direct endpoint used by the web client and verification harness."""
    result = await enterprise_tools.execute(db, actor, data.tool_name, data.arguments, channel="web", prompt="direct tool request")
    await db.commit()
    return result


@router.get("/assistant/resources/{resource_type}/{resource_id}/policy")
async def get_assistant_resource_policy(resource_type: Literal["company_file", "company_knowledge"], resource_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles("admin", "manager"))):
    policy = await db.scalar(select(ResourcePolicy).where(ResourcePolicy.organization_id == actor.organization_id, ResourcePolicy.resource_type == resource_type, ResourcePolicy.resource_id == resource_id))
    if not policy:
        return {"classification": "internal", "inherit_from_parent": True, "grants": []}
    grants = list((await db.execute(select(ResourceGrant).where(ResourceGrant.policy_id == policy.id))).scalars().all())
    return {"classification": policy.classification, "inherit_from_parent": policy.inherit_from_parent, "grants": [{"principal_type": grant.principal_type, "principal_key": grant.principal_key} for grant in grants]}


@router.put("/assistant/resources/{resource_type}/{resource_id}/policy")
async def update_assistant_resource_policy(resource_type: Literal["company_file", "company_knowledge"], resource_id: int, data: ResourcePolicyInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles("admin", "manager"))):
    if resource_type == "company_file":
        source = await db.get(CompanyLibraryItem, resource_id)
        valid = bool(source and source.organization_id == actor.organization_id)
    else:
        source = await db.get(CompanyKnowledge, resource_id)
        valid = bool(source and source.organization_id == actor.organization_id)
    if not valid:
        raise HTTPException(status_code=404, detail="Resource not found")
    policy = await db.scalar(select(ResourcePolicy).where(ResourcePolicy.organization_id == actor.organization_id, ResourcePolicy.resource_type == resource_type, ResourcePolicy.resource_id == resource_id).with_for_update())
    if not policy:
        policy = ResourcePolicy(organization_id=actor.organization_id, resource_type=resource_type, resource_id=resource_id, created_by_account_id=actor.account_id)
        db.add(policy); await db.flush()
    policy.classification = data.classification; policy.inherit_from_parent = data.inherit_from_parent
    await db.execute(ResourceGrant.__table__.delete().where(ResourceGrant.policy_id == policy.id))
    for grant in data.grants:
        db.add(ResourceGrant(policy_id=policy.id, **grant.model_dump()))
    await record_change(db, actor=actor, topic="assistant_tools", aggregate_type="resource_policy", aggregate_id=policy.id, operation="updated", after={"resource_type": resource_type, "resource_id": resource_id, "classification": data.classification, "grant_count": len(data.grants)})
    await db.commit()
    return await get_assistant_resource_policy(resource_type, resource_id, db, actor)


@router.post("/assistant/actions/confirm")
async def confirm_assistant_action(data: AssistantActionConfirmInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    result = await enterprise_tools.confirm_task_update(db, actor, data.token, channel="web")
    await db.commit()
    return result


@router.get("/assistant/conversations/{conversation_id}")
async def assistant_conversation(conversation_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    conversation = await db.get(AssistantConversation, conversation_id)
    if not conversation or conversation.account_id != actor.account_id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    rows = (await db.execute(select(AssistantMessage).where(AssistantMessage.conversation_id == conversation_id).order_by(AssistantMessage.id))).scalars().all()
    return {"id": conversation.id, "messages": [{"id": row.id, "role": row.role, "content": row.content, "action": row.action, "sources": row.sources, "created_at": row.created_at} for row in rows]}


@router.delete("/assistant/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_assistant_conversation(conversation_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    conversation = await db.get(AssistantConversation, conversation_id)
    if not conversation or conversation.account_id != actor.account_id or conversation.organization_id != actor.organization_id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    await db.delete(conversation)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/assistant/drafts")
async def assistant_draft(data: AssistantDraftInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    """Compatibility endpoint for clients not yet migrated to conversations."""
    response = await assistant_chat(AssistantChatInput(text=data.text), db, actor)
    action = response["message"].get("action") or {"type": "report_draft", "payload": {"title": "AI-assisted report", "markdown": data.text}}
    return {"kind": data.kind, "requires_confirmation": action["type"] == "task_draft", "draft": action["payload"], "conversation_id": response["conversation_id"]}


@router.post("/voice/transcriptions")
async def transcribe_voice(file: UploadFile = File(...), actor: ActorContext = Depends(get_actor)):
    if file.content_type not in {"audio/ogg", "audio/webm", "audio/wav", "audio/mpeg", "audio/mp4"}:
        raise HTTPException(status_code=415, detail="Unsupported audio format")
    audio = await file.read(12 * 1024 * 1024 + 1)
    if len(audio) > 12 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Audio file exceeds 12 MB")
    text, error = await voice_service.transcribe(audio, filename=file.filename or "voice.ogg")
    if error:
        raise HTTPException(status_code=502, detail=error)
    return {"transcript": text, "retained": False, "requires_review": True}


@router.post("/assistant/speech")
async def assistant_speech(data: AssistantChatInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    """Return a Chimege WAV answer only while the shared bot TTS mode is enabled."""
    settings_row = (await db.execute(select(ManagerSettings).limit(1))).scalar_one_or_none()
    if settings_row is not None and settings_row.tts_answers_enabled is False:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    if not voice_service.synthesis_enabled():
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    audio, error = await voice_service.synthesize(data.text)
    if error or not audio:
        raise HTTPException(status_code=502, detail=error or "Chimege audio could not be generated")
    return Response(content=audio, media_type="audio/wav", headers={"Content-Disposition": "inline; filename=oyuns-answer.wav"})


@router.get("/integrations/google-calendar/connect")
async def google_calendar_connect(actor: ActorContext = Depends(get_actor)):
    if not google_is_configured():
        return {"provider": "google", "status": "configuration_required", "fallback": "calendar_template_url", "message": "Configure Google OAuth client credentials to enable synchronized calendars."}
    return {"provider": "google", "status": "ready", "authorization_url": google_authorization_url(actor.account_id)}


@router.get("/integrations/google-calendar/status")
async def google_calendar_status(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    connection = (await db.execute(select(CalendarConnection).where(CalendarConnection.account_id == actor.account_id, CalendarConnection.provider == "google"))).scalar_one_or_none()
    if not connection:
        return {"provider": "google", "status": "disconnected", "sync_mode": "outbound", "configured": google_is_configured()}
    return {"provider": "google", "status": connection.status, "sync_mode": connection.sync_mode, "configured": google_is_configured(), "calendar_id": connection.calendar_id, "watch_active": bool(connection.webhook_channel_id and connection.channel_expires_at and connection.channel_expires_at > datetime.now(timezone.utc)), "watch_expires_at": connection.channel_expires_at, "last_synced_at": connection.last_synced_at, "last_error": connection.last_error, "sync_failure_count": connection.sync_failure_count}


@router.put("/integrations/google-calendar/sync-mode")
async def google_calendar_sync_mode(data: CalendarSyncModeInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    connection = (await db.execute(select(CalendarConnection).where(CalendarConnection.account_id == actor.account_id, CalendarConnection.provider == "google"))).scalar_one_or_none()
    if not connection:
        raise HTTPException(status_code=409, detail="Connect Google Calendar first")
    connection.sync_mode = data.sync_mode
    await db.commit()
    return {"status": connection.status, "sync_mode": connection.sync_mode}


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
    await db.flush()
    db.add(JobQueue(job_type="calendar_watch", payload={"connection_id": connection.id}, dedup_key=f"calendar-watch:{connection.id}:initial:{uuid.uuid4().hex}"))
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
        try:
            await google_stop_watch(db, connection)
        except Exception:
            pass
        await db.delete(connection)
        await db.commit()


@router.post("/integrations/google-calendar/webhook", status_code=status.HTTP_202_ACCEPTED)
async def google_calendar_webhook(
    channel_id: str | None = Header(default=None, alias="X-Goog-Channel-ID"),
    resource_id: str | None = Header(default=None, alias="X-Goog-Resource-ID"),
    channel_token: str | None = Header(default=None, alias="X-Goog-Channel-Token"),
    message_number: str | None = Header(default=None, alias="X-Goog-Message-Number"),
    resource_state: str | None = Header(default=None, alias="X-Goog-Resource-State"),
    db: AsyncSession = Depends(get_db),
):
    if not all((channel_id, resource_id, channel_token, message_number)) or not message_number.isdigit():
        raise HTTPException(status_code=400, detail="Google Calendar webhook headers are incomplete")
    connection = (await db.execute(select(CalendarConnection).where(CalendarConnection.webhook_channel_id == channel_id).with_for_update())).scalar_one_or_none()
    if not connection or connection.webhook_resource_id != resource_id or not connection.encrypted_channel_token:
        raise HTTPException(status_code=404, detail="Calendar channel not found")
    if not secrets.compare_digest(decrypt_secret(connection.encrypted_channel_token), channel_token):
        raise HTTPException(status_code=403, detail="Calendar channel token is invalid")
    if connection.channel_expires_at and connection.channel_expires_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="Calendar channel expired")
    previous = int(connection.last_webhook_message_number or 0)
    current = int(message_number)
    if current <= previous:
        return {"status": "duplicate", "message_number": message_number}
    connection.last_webhook_message_number = message_number
    dedup_key = f"calendar-inbound:{connection.id}:{message_number}"
    existing = await db.scalar(select(JobQueue.id).where(JobQueue.dedup_key == dedup_key))
    if not existing and resource_state != "sync":
        db.add(JobQueue(job_type="calendar_inbound", payload={"connection_id": connection.id, "message_number": message_number}, dedup_key=dedup_key))
    await db.commit()
    return {"status": "queued" if resource_state != "sync" else "channel_ready", "message_number": message_number}
