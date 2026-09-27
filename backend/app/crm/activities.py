"""CRM activity log endpoints (Dayansoft d027 “Харилцаа холбоо”)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.enterprise_deps import ActorContext, get_actor
from app.crm.common import (
    ATTACHMENT_OBJECT_TYPES,
    activity_context,
    activity_out,
    assert_version,
    crm_error,
    get_activity,
    get_party,
    list_object_attachments,
    organization_timezone,
    store_object_attachment,
    validate_contact,
    validate_references,
    validate_status,
)
from app.crm.schemas import ActivityBulkCreate, ActivityCloseInput, ActivityCreate, ActivityPatch, ActivityTaskInput
from app.crm.service import (
    ACTIVITY_REGISTER,
    ACTIVITY_RESOURCE,
    completion_updates,
    descendant_party_ids,
    ensure_crm_defaults,
    local_today,
    next_activity_number,
    next_simple_code,
    utcnow,
)
from app.erp.service import require_capability
from app.models.crm import FINISHED_STATUS_CATEGORIES, CRMActivity, CRMActivityType, ERPPartyContact, ERPStatus
from app.models.models import Employee, Task, TaskAssignee
from app.services.collaboration_permissions import actor_can_assign_tasks
from app.services.enterprise_events import record_change
from app.services.user_notifications import create_notifications

router = APIRouter()

ACTIVITY_REFERENCE_FIELDS = ("party_id", "type_id", "contract_id", "project_id", "responsible_employee_id", "reviewed_by_employee_id")
# Fields copied by “Хувилах”; completion, closure and review are never cloned.
CLONE_FIELDS = (
    "party_id", "contact_id", "contact_name", "contact_phone", "contact_email", "subject", "body", "type_id", "is_important",
    "duration_minutes", "responsible_employee_id", "reference", "contract_id", "project_id", "expected_revenue", "currency", "custom",
)


def _finished_status_ids(organization_id: int):
    return select(ERPStatus.id).where(ERPStatus.organization_id == organization_id, ERPStatus.register == ACTIVITY_REGISTER,
                                      ERPStatus.category.in_(FINISHED_STATUS_CATEGORIES))


def open_activity_clause(organization_id: int) -> list[Any]:
    return [CRMActivity.is_closed.is_(False), CRMActivity.completed_at.is_(None),
            or_(CRMActivity.status_id.is_(None), CRMActivity.status_id.not_in(_finished_status_ids(organization_id)))]


async def _render(db: AsyncSession, actor: ActorContext, rows: list[CRMActivity]) -> list[dict[str, Any]]:
    today = local_today(await organization_timezone(db, actor.organization_id))
    now = utcnow()
    ctx = await activity_context(db, rows)
    return [activity_out(row, ctx, today=today, now=now) for row in rows]


async def _default_status(db: AsyncSession, organization_id: int) -> ERPStatus | None:
    return await db.scalar(select(ERPStatus).where(ERPStatus.organization_id == organization_id, ERPStatus.register == ACTIVITY_REGISTER,
                                                   ERPStatus.is_active.is_(True), ERPStatus.category == "open").order_by(ERPStatus.sort, ERPStatus.id).limit(1))


async def _resolve_type(db: AsyncSession, actor: ActorContext, type_id: int | None, type_name: str | None) -> int | None:
    """Pick an existing type or create one typed in by the user."""
    if type_id is not None or not type_name:
        return type_id
    existing = await db.scalar(select(CRMActivityType.id).where(CRMActivityType.organization_id == actor.organization_id,
                                                                func.lower(CRMActivityType.name) == type_name.strip().lower()))
    if existing:
        return existing
    sort = int(await db.scalar(select(func.coalesce(func.max(CRMActivityType.sort), 0)).where(CRMActivityType.organization_id == actor.organization_id)) or 0) + 10
    row = CRMActivityType(organization_id=actor.organization_id, code=await next_simple_code(db, CRMActivityType, actor.organization_id, "T"), name=type_name.strip(), sort=sort)
    db.add(row)
    await db.flush()
    return row.id


def _contact_snapshot(values: dict[str, Any], contact: ERPPartyContact | None) -> None:
    if not contact:
        return
    values.setdefault("contact_name", contact.name)
    values.setdefault("contact_phone", contact.phone)
    values.setdefault("contact_email", contact.email)


async def _notify_assignment(db: AsyncSession, actor: ActorContext, activity: CRMActivity, source_event_id: int | None) -> None:
    if not activity.responsible_employee_id or activity.responsible_employee_id == actor.employee_id:
        return
    due = f" · Биелэх: {activity.due_at.astimezone(ZoneInfo(await organization_timezone(db, actor.organization_id))).strftime('%Y-%m-%d %H:%M')}" if activity.due_at else ""
    await create_notifications(
        db, organization_id=actor.organization_id, employee_ids=[activity.responsible_employee_id],
        kind="crm_activity_assigned", title="Харилцаа холбоо хариуцуулав",
        body=f"{activity.number}: {activity.subject}{due}", target_url=f"/erp/crm?activity={activity.id}",
        payload={"crm_activity_id": activity.id, "number": activity.number}, source_event_id=source_event_id,
        dedup_key=f"crm-activity-assigned:{activity.id}:{activity.responsible_employee_id}:v{activity.version}",
    )


async def _create_activity(db: AsyncSession, actor: ActorContext, data: ActivityCreate, *, contact_fallback_default: bool = False) -> CRMActivity:
    values = data.model_dump(exclude={"type_name"}, exclude_none=True)
    await validate_references(db, actor.organization_id, {field: values.get(field) for field in ACTIVITY_REFERENCE_FIELDS})
    values["type_id"] = await _resolve_type(db, actor, data.type_id, data.type_name)
    contact = await validate_contact(db, actor.organization_id, data.contact_id, data.party_id)
    if contact is None and contact_fallback_default and data.party_id and not data.contact_name:
        contact = await db.scalar(select(ERPPartyContact).where(ERPPartyContact.party_id == data.party_id, ERPPartyContact.is_active.is_(True))
                                  .order_by(ERPPartyContact.is_default.desc(), ERPPartyContact.id).limit(1))
        if contact:
            values["contact_id"] = contact.id
    _contact_snapshot(values, contact)
    status_row = await validate_status(db, actor.organization_id, data.status_id, ACTIVITY_REGISTER) if data.status_id else await _default_status(db, actor.organization_id)
    values["status_id"] = status_row.id if status_row else None
    values.setdefault("responsible_employee_id", actor.employee_id)
    values.setdefault("activity_at", utcnow())
    values.update(completion_updates(is_closed=bool(values.get("is_closed")), was_closed=False, completed_at=values.get("completed_at"),
                                     status_category=status_row.category if status_row else None, now=utcnow()))
    activity = CRMActivity(organization_id=actor.organization_id, number=await next_activity_number(db, actor.organization_id),
                           created_by_account_id=actor.account_id, created_by_employee_id=actor.employee_id, **values)
    db.add(activity)
    await db.flush()
    return activity


@router.get("/activities")
async def list_activities(
    search: str | None = Query(default=None, max_length=160),
    party_id: int | None = None,
    include_children: bool = False,
    type_id: int | None = None,
    status_id: int | None = None,
    responsible_employee_id: int | None = None,
    contract_id: int | None = None,
    project_id: int | None = None,
    mine: bool = False,
    state: Literal["open", "closed", "all"] = "all",
    overdue: bool = False,
    important: bool = False,
    is_active: bool | None = True,
    date_from: date | None = None,
    date_to: date | None = None,
    due_from: date | None = None,
    due_to: date | None = None,
    sort: Literal["activity_at", "due_at", "number"] = "activity_at",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor),
):
    await require_capability(db, actor, ACTIVITY_RESOURCE, "view")
    statement = select(CRMActivity).where(CRMActivity.organization_id == actor.organization_id)
    if search:
        pattern = f"%{search.strip()}%"
        statement = statement.where(or_(CRMActivity.subject.ilike(pattern), CRMActivity.body.ilike(pattern), CRMActivity.number.ilike(pattern),
                                        CRMActivity.contact_name.ilike(pattern), CRMActivity.reference.ilike(pattern)))
    if party_id is not None:
        ids = await descendant_party_ids(db, actor.organization_id, party_id) if include_children else {party_id}
        statement = statement.where(CRMActivity.party_id.in_(ids))
    for column, value in ((CRMActivity.type_id, type_id), (CRMActivity.status_id, status_id), (CRMActivity.responsible_employee_id, responsible_employee_id),
                          (CRMActivity.contract_id, contract_id), (CRMActivity.project_id, project_id)):
        if value is not None:
            statement = statement.where(column == value)
    if mine:
        statement = statement.where(or_(CRMActivity.responsible_employee_id == actor.employee_id, CRMActivity.created_by_account_id == actor.account_id)
                                    if actor.employee_id else CRMActivity.created_by_account_id == actor.account_id)
    open_clause = open_activity_clause(actor.organization_id)
    if state == "open" or overdue:
        statement = statement.where(*open_clause)
    elif state == "closed":
        statement = statement.where(or_(CRMActivity.is_closed.is_(True), CRMActivity.completed_at.is_not(None),
                                        CRMActivity.status_id.in_(_finished_status_ids(actor.organization_id))))
    if overdue:
        statement = statement.where(CRMActivity.due_at < utcnow())
    if important:
        statement = statement.where(CRMActivity.is_important.is_(True))
    if is_active is not None:
        statement = statement.where(CRMActivity.is_active.is_(is_active))
    zone = ZoneInfo(await organization_timezone(db, actor.organization_id))
    bounds = ((CRMActivity.activity_at, date_from, date_to), (CRMActivity.due_at, due_from, due_to))
    for column, start, end in bounds:
        if start is not None:
            statement = statement.where(column >= datetime.combine(start, time.min, zone))
        if end is not None:
            statement = statement.where(column < datetime.combine(end + timedelta(days=1), time.min, zone))
    total = int(await db.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    if sort == "due_at":
        order = (CRMActivity.due_at.asc().nulls_last(), CRMActivity.id.desc())
    elif sort == "number":
        order = (CRMActivity.number.desc(),)
    else:
        order = (CRMActivity.activity_at.desc(), CRMActivity.id.desc())
    rows = (await db.execute(statement.order_by(*order).offset((page - 1) * page_size).limit(page_size))).scalars().all()
    return {"items": await _render(db, actor, list(rows)), "total": total, "page": page, "page_size": page_size}


@router.post("/activities", status_code=status.HTTP_201_CREATED)
async def create_activity(data: ActivityCreate, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, ACTIVITY_RESOURCE, "create")
    await ensure_crm_defaults(db, actor.organization_id)
    activity = await _create_activity(db, actor, data)
    event = await record_change(db, actor=actor, topic="crm", aggregate_type="crm_activity", aggregate_id=activity.id, operation="created",
                                version=activity.version, after={"number": activity.number, "subject": activity.subject, "party_id": activity.party_id})
    await _notify_assignment(db, actor, activity, event.id)
    await db.commit()
    await db.refresh(activity)
    return (await _render(db, actor, [activity]))[0]


@router.post("/activities/bulk", status_code=status.HTTP_201_CREATED)
async def bulk_create_activities(data: ActivityBulkCreate, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    """Нэмэх (метагаас): one templated activity per selected party."""
    await require_capability(db, actor, ACTIVITY_RESOURCE, "create")
    await ensure_crm_defaults(db, actor.organization_id)
    created: list[CRMActivity] = []
    for party_id in dict.fromkeys(data.party_ids):
        template = data.template.model_copy(update={"party_id": party_id, "contact_id": None, "contact_name": None, "contact_phone": None, "contact_email": None})
        activity = await _create_activity(db, actor, template, contact_fallback_default=True)
        event = await record_change(db, actor=actor, topic="crm", aggregate_type="crm_activity", aggregate_id=activity.id, operation="created",
                                    version=activity.version, after={"number": activity.number, "subject": activity.subject, "party_id": party_id, "bulk": True})
        await _notify_assignment(db, actor, activity, event.id)
        created.append(activity)
    await db.commit()
    return {"created": len(created), "items": await _render(db, actor, created)}


@router.get("/activities/{activity_id}")
async def get_activity_detail(activity_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, ACTIVITY_RESOURCE, "view")
    return (await _render(db, actor, [await get_activity(db, actor, activity_id)]))[0]


@router.patch("/activities/{activity_id}")
async def update_activity(activity_id: int, data: ActivityPatch, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, ACTIVITY_RESOURCE, "edit")
    activity = await get_activity(db, actor, activity_id)
    assert_version(activity, data.version)
    changes = data.model_dump(exclude_unset=True, exclude={"version", "type_name"})
    if "subject" in changes and not changes["subject"]:
        raise crm_error(422, "crm_activity_subject_required", "Утга хоосон байж болохгүй")
    await validate_references(db, actor.organization_id, {field: changes.get(field) for field in ACTIVITY_REFERENCE_FIELDS if field in changes})
    if data.type_name and not changes.get("type_id"):
        changes["type_id"] = await _resolve_type(db, actor, None, data.type_name)
    party_id = changes.get("party_id", activity.party_id)
    if "contact_id" in changes or ("party_id" in changes and activity.contact_id):
        contact_id = changes.get("contact_id", activity.contact_id)
        if "party_id" in changes and "contact_id" not in changes:
            contact_id = None
            changes["contact_id"] = None
        contact = await validate_contact(db, actor.organization_id, contact_id, party_id)
        if contact and contact.id != activity.contact_id:
            for field, value in (("contact_name", contact.name), ("contact_phone", contact.phone), ("contact_email", contact.email)):
                changes.setdefault(field, value)
    status_row = None
    if "status_id" in changes:
        status_row = await validate_status(db, actor.organization_id, changes["status_id"], ACTIVITY_REGISTER)
    elif activity.status_id:
        status_row = await db.get(ERPStatus, activity.status_id)
    for boolean in ("is_important", "is_closed", "is_active"):
        if boolean in changes and changes[boolean] is None:
            changes.pop(boolean)
    if "currency" in changes and not changes["currency"]:
        changes.pop("currency")
    if "activity_at" in changes and changes["activity_at"] is None:
        changes.pop("activity_at")
    previous_responsible, was_closed = activity.responsible_employee_id, activity.is_closed
    for field, value in changes.items():
        setattr(activity, field, value)
    for field, value in completion_updates(is_closed=activity.is_closed, was_closed=was_closed, completed_at=activity.completed_at,
                                           status_category=status_row.category if status_row else None, now=utcnow()).items():
        setattr(activity, field, value)
    activity.version += 1
    event = await record_change(db, actor=actor, topic="crm", aggregate_type="crm_activity", aggregate_id=activity.id, operation="updated",
                                version=activity.version, after={key: value for key, value in changes.items() if key not in {"body", "custom"}})
    if activity.responsible_employee_id != previous_responsible:
        await _notify_assignment(db, actor, activity, event.id)
    await db.commit()
    await db.refresh(activity)
    return (await _render(db, actor, [activity]))[0]


@router.post("/activities/{activity_id}/clone", status_code=status.HTTP_201_CREATED)
async def clone_activity(activity_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    """Хувилах: copy the interaction details into a fresh, open record."""
    await require_capability(db, actor, ACTIVITY_RESOURCE, "create")
    source = await get_activity(db, actor, activity_id)
    status_row = await _default_status(db, actor.organization_id)
    clone = CRMActivity(organization_id=actor.organization_id, number=await next_activity_number(db, actor.organization_id),
                        activity_at=utcnow(), status_id=status_row.id if status_row else None,
                        created_by_account_id=actor.account_id, created_by_employee_id=actor.employee_id,
                        **{field: getattr(source, field) for field in CLONE_FIELDS})
    db.add(clone)
    await db.flush()
    await record_change(db, actor=actor, topic="crm", aggregate_type="crm_activity", aggregate_id=clone.id, operation="cloned",
                        version=clone.version, after={"number": clone.number, "source_id": source.id})
    await db.commit()
    await db.refresh(clone)
    return (await _render(db, actor, [clone]))[0]


@router.post("/activities/{activity_id}/close")
async def close_activity(activity_id: int, data: ActivityCloseInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, ACTIVITY_RESOURCE, "edit")
    activity = await get_activity(db, actor, activity_id)
    now = utcnow()
    activity.is_closed = True
    activity.closed_at = activity.closed_at or now
    activity.completed_at = activity.completed_at or now
    if data.completion_note:
        activity.completion_note = data.completion_note
    done = await db.scalar(select(ERPStatus).where(ERPStatus.organization_id == actor.organization_id, ERPStatus.register == ACTIVITY_REGISTER,
                                                  ERPStatus.is_active.is_(True), ERPStatus.category == "done").order_by(ERPStatus.sort).limit(1))
    if done:
        activity.status_id = done.id
    activity.version += 1
    await record_change(db, actor=actor, topic="crm", aggregate_type="crm_activity", aggregate_id=activity.id, operation="closed", version=activity.version,
                        after={"completion_note": data.completion_note})
    await db.commit()
    await db.refresh(activity)
    return (await _render(db, actor, [activity]))[0]


@router.post("/activities/{activity_id}/reopen")
async def reopen_activity(activity_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, ACTIVITY_RESOURCE, "edit")
    activity = await get_activity(db, actor, activity_id)
    status_row = await _default_status(db, actor.organization_id)
    activity.is_closed, activity.closed_at, activity.completed_at = False, None, None
    activity.status_id = status_row.id if status_row else None
    activity.version += 1
    await record_change(db, actor=actor, topic="crm", aggregate_type="crm_activity", aggregate_id=activity.id, operation="reopened", version=activity.version)
    await db.commit()
    await db.refresh(activity)
    return (await _render(db, actor, [activity]))[0]


@router.post("/activities/{activity_id}/review")
async def review_activity(activity_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    """Хянасан: record who verified the outcome and when."""
    await require_capability(db, actor, ACTIVITY_RESOURCE, "edit")
    activity = await get_activity(db, actor, activity_id)
    if not actor.employee_id:
        raise crm_error(422, "crm_reviewer_requires_employee", "Хянагч нь ажилтны бүртгэлтэй хэрэглэгч байна")
    activity.reviewed_by_employee_id, activity.reviewed_at = actor.employee_id, utcnow()
    activity.version += 1
    await record_change(db, actor=actor, topic="crm", aggregate_type="crm_activity", aggregate_id=activity.id, operation="reviewed", version=activity.version)
    await db.commit()
    await db.refresh(activity)
    return (await _render(db, actor, [activity]))[0]


@router.post("/activities/{activity_id}/task", status_code=status.HTTP_201_CREATED)
async def create_follow_up_task(activity_id: int, data: ActivityTaskInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    """Create a linked Task so the follow-up gets the task board's reminders."""
    await require_capability(db, actor, ACTIVITY_RESOURCE, "edit")
    activity = await get_activity(db, actor, activity_id)
    if activity.task_id and await db.get(Task, activity.task_id):
        raise crm_error(409, "crm_activity_task_exists", "Энэ бүртгэлд даалгавар аль хэдийн үүссэн байна", task_id=activity.task_id)
    assignee_id = data.assignee_employee_id or activity.responsible_employee_id or actor.employee_id
    if assignee_id is not None:
        valid = await db.scalar(select(Employee.id).where(Employee.id == assignee_id, Employee.organization_id == actor.organization_id, Employee.is_active.is_(True)))
        if not valid:
            raise crm_error(422, "crm_invalid_reference", "Хариуцагч олдсонгүй", field="assignee_employee_id")
        if assignee_id != actor.employee_id and not await actor_can_assign_tasks(db, organization_id=actor.organization_id, employee_id=actor.employee_id, roles=actor.roles):
            raise crm_error(403, "crm_task_assignment_forbidden", "Таны эрх бусдад даалгавар оноох боломжгүй")
    party_label = ""
    if activity.party_id:
        party = await get_party(db, actor, activity.party_id)
        party_label = f"Харилцагч: {party.code} {party.name}\n"
    task = Task(
        organization_id=actor.organization_id, project_id=activity.project_id, title=data.title or activity.subject,
        description=f"{party_label}CRM: {activity.number}\n\n{activity.body or ''}".strip(),
        created_by_id=actor.employee_id, assignee_id=assignee_id, deadline_at=data.deadline_at or activity.due_at,
        status="open", workflow_status="to_do", priority=1 if activity.is_important else 2,
    )
    db.add(task)
    await db.flush()
    if assignee_id:
        db.add(TaskAssignee(task_id=task.id, employee_id=assignee_id, assignment_role="primary"))
    activity.task_id = task.id
    activity.version += 1
    event = await record_change(db, actor=actor, topic="tasks", aggregate_type="task", aggregate_id=task.id, operation="created", version=task.version,
                                after={"task_id": task.id, "title": task.title, "crm_activity_id": activity.id})
    if assignee_id and assignee_id != actor.employee_id:
        await create_notifications(
            db, organization_id=actor.organization_id, employee_ids=[assignee_id], kind="task_assigned", title="Шинэ даалгавар",
            body=f"Танд “{task.title}” даалгавар оноолоо.", target_url=f"/tasks?task={task.id}",
            payload={"task_id": task.id, "title": task.title, "deadline_iso": task.deadline_at.isoformat() if task.deadline_at else None,
                     "task_url": f"{settings.PUBLIC_APP_URL.rstrip('/')}/tasks?task={task.id}"},
            source_event_id=event.id, task_id=task.id, dedup_key=f"task-created:{task.id}",
        )
    await db.commit()
    await db.refresh(activity)
    return {"task_id": task.id, "activity": (await _render(db, actor, [activity]))[0]}


@router.delete("/activities/{activity_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_activity(activity_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, ACTIVITY_RESOURCE, "archive")
    activity = await get_activity(db, actor, activity_id)
    snapshot = {"number": activity.number, "subject": activity.subject, "party_id": activity.party_id}
    await db.delete(activity)
    await record_change(db, actor=actor, topic="crm", aggregate_type="crm_activity", aggregate_id=activity_id, operation="deleted", before=snapshot)
    await db.commit()


@router.get("/activities/{activity_id}/files")
async def list_activity_files(activity_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, ACTIVITY_RESOURCE, "view")
    await get_activity(db, actor, activity_id)
    return await list_object_attachments(db, actor, ATTACHMENT_OBJECT_TYPES["activity"], activity_id)


@router.post("/activities/{activity_id}/files", status_code=status.HTTP_201_CREATED)
async def upload_activity_file(activity_id: int, file: UploadFile = File(...), db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, ACTIVITY_RESOURCE, "edit")
    await get_activity(db, actor, activity_id)
    return await store_object_attachment(db, actor, ATTACHMENT_OBJECT_TYPES["activity"], activity_id, file)


@router.get("/summary")
async def crm_summary(mine: bool = False, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    """Dashboard strip: open, overdue, due soon, and pipeline value of open activities."""
    await require_capability(db, actor, ACTIVITY_RESOURCE, "view")
    zone = ZoneInfo(await organization_timezone(db, actor.organization_id))
    today = local_today(str(zone))
    start_today = datetime.combine(today, time.min, zone)
    now = utcnow()
    base = [CRMActivity.organization_id == actor.organization_id, CRMActivity.is_active.is_(True), *open_activity_clause(actor.organization_id)]
    if mine:
        base.append(CRMActivity.responsible_employee_id == actor.employee_id)

    async def count(*extra: Any) -> int:
        return int(await db.scalar(select(func.count(CRMActivity.id)).where(*base, *extra)) or 0)

    revenue = (await db.execute(select(CRMActivity.currency, func.sum(CRMActivity.expected_revenue)).where(*base, CRMActivity.expected_revenue.is_not(None))
                                .group_by(CRMActivity.currency))).all()
    by_status = (await db.execute(select(ERPStatus.id, ERPStatus.name, ERPStatus.color, func.count(CRMActivity.id))
                                  .join(CRMActivity, CRMActivity.status_id == ERPStatus.id)
                                  .where(*base).group_by(ERPStatus.id, ERPStatus.name, ERPStatus.color, ERPStatus.sort).order_by(ERPStatus.sort))).all()
    by_responsible = (await db.execute(select(Employee.id, Employee.name, func.count(CRMActivity.id), func.count(CRMActivity.id).filter(CRMActivity.due_at < now))
                                       .join(CRMActivity, CRMActivity.responsible_employee_id == Employee.id)
                                       .where(*base).group_by(Employee.id, Employee.name).order_by(func.count(CRMActivity.id).desc()).limit(10))).all()
    return {
        "open": await count(),
        "overdue": await count(CRMActivity.due_at < now),
        "due_today": await count(CRMActivity.due_at >= now, CRMActivity.due_at < start_today + timedelta(days=1)),
        "due_this_week": await count(CRMActivity.due_at >= now, CRMActivity.due_at < start_today + timedelta(days=7)),
        "important": await count(CRMActivity.is_important.is_(True)),
        "expected_revenue": [{"currency": currency, "amount": str(amount)} for currency, amount in revenue if amount is not None],
        "by_status": [{"status_id": sid, "name": name, "color": color, "count": total} for sid, name, color, total in by_status],
        "by_responsible": [{"employee_id": eid, "name": name, "open": total, "overdue": late} for eid, name, total, late in by_responsible],
    }
