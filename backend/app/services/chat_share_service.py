"""Role-scoped workspace items that can be shared into chat as info cards.

The slash menu in chat lists items the *sender* may see. A shared card stores
a snapshot of the item at send time; whether a *reader* may open the item's
location is re-evaluated on every read, so a card never grants access by
itself.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enterprise_deps import ActorContext
from app.models.contracts import ContractDocument, ContractReview, ContractRevision
from app.models.models import (
    CompanyPlanItem,
    Employee,
    Organization,
    PlanIdea,
    Project,
    RoleAssignment,
    Task,
    TaskAssignee,
    TaskReviewer,
    UserAccount,
    WorkReport,
    WorkReportRevision,
)

MANAGEMENT_ROLES = ("admin", "manager", "team_lead")
ShareKind = Literal["task", "plan_item", "plan_idea", "plan_report", "contract", "report"]
SHARE_KINDS: tuple[str, ...] = ("task", "plan_item", "plan_idea", "plan_report", "contract", "report")
ACTIVE_TASK_EXCLUDED = ("done", "cancelled")
REPORT_TYPES = ("daily", "monthly")
GROUPS = (
    ("tasks", "Идэвхтэй даалгавар"),
    ("plans", "Төлөвлөгөө"),
    ("contracts", "Гэрээний ноорог"),
    ("reports", "Тайлан"),
)
KIND_GROUP = {"task": "tasks", "plan_item": "plans", "plan_idea": "plans", "plan_report": "plans", "contract": "contracts", "report": "reports"}

TASK_STATUS = {"backlog": "Хойшлуулсан", "to_do": "Хийх", "in_progress": "Хийгдэж буй", "review": "Хянагдаж буй", "done": "Дууссан", "cancelled": "Цуцлагдсан"}
PRIORITY = {1: "Яаралтай", 2: "Энгийн", 3: "Бага"}
REPORT_STATUS = {"awaiting": "Хүлээгдэж буй", "draft": "Ноорог", "editing": "Засварлаж буй", "submitted": "Илгээсэн", "revision_requested": "Засвар хүссэн", "approved": "Батлагдсан"}
REPORT_TYPE = {"daily": "Өдрийн тайлан", "monthly": "Сарын тайлан", "next_month_plan": "Дараа сарын төлөвлөгөө"}
CONTRACT_STATUS = {"DRAFT": "Ноорог", "PENDING_REVIEW": "Хянагдаж буй", "CHANGES_REQUESTED": "Засвар хүссэн", "APPROVED": "Батлагдсан", "REJECTED": "Татгалзсан", "SIGNED_AND_STAMPED": "Гарын үсэг зурсан"}
CONTRACT_TYPE = {"contract": "Гэрээ", "agreement": "Хэлэлцээр", "official_letter": "Албан бичиг", "other": "Бусад"}
IDEA_STATUS = {"pending": "Хүлээгдэж буй", "approved": "Зөвшөөрсөн", "rejected": "Татгалзсан", "merged": "Нэгтгэсэн"}
HORIZON = {"long_term": "Урт хугацаа", "mid_term": "Дунд хугацаа", "short_term": "Богино хугацаа"}
KIND_LABEL = {"task": "Даалгавар", "plan_item": "Компанийн төлөвлөгөө", "plan_idea": "Төлөвлөгөөний санал", "plan_report": "Дараа сарын төлөвлөгөө", "contract": "Гэрээ", "report": "Тайлан"}


class ShareItemNotFound(LookupError):
    pass


@dataclass(frozen=True)
class _Ctx:
    actor: ActorContext
    management: bool
    tz: ZoneInfo


def _is_management(actor: ActorContext) -> bool:
    return actor.has_any_role(*MANAGEMENT_ROLES)


async def _ctx(db: AsyncSession, actor: ActorContext) -> _Ctx:
    organization = await db.get(Organization, actor.organization_id)
    try:
        tz = ZoneInfo(organization.timezone if organization else "Asia/Ulaanbaatar")
    except Exception:
        tz = ZoneInfo("Asia/Ulaanbaatar")
    return _Ctx(actor=actor, management=_is_management(actor), tz=tz)


def _fmt_dt(value: datetime | None, tz: ZoneInfo) -> str | None:
    if not value:
        return None
    return value.astimezone(tz).strftime("%Y-%m-%d %H:%M")


def _fmt_date(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _fmt_month(value: date | None) -> str | None:
    return value.strftime("%Y-%m") if value else None


def _excerpt(text: str | None, limit: int = 320) -> str | None:
    if not text:
        return None
    compact = " ".join(text.split())
    return compact if len(compact) <= limit else f"{compact[:limit].rstrip()}…"


def _org_employee_ids(organization_id: int):
    return select(UserAccount.employee_id).where(UserAccount.organization_id == organization_id, UserAccount.employee_id.isnot(None))


def _term(q: str) -> str | None:
    value = q.strip()
    return f"%{value}%" if value else None


# ─── Visibility predicates ──────────────────────────────────────────────────
# Listing visibility decides what the *sender* may share. Open access mirrors
# the detail endpoints so a card link only appears when the page will load.


def _task_listing_clause(ctx: _Ctx):
    base = [Task.organization_id == ctx.actor.organization_id, Task.is_archived.is_(False), Task.workflow_status.notin_(ACTIVE_TASK_EXCLUDED)]
    if ctx.management:
        return and_(*base)
    employee_id = ctx.actor.employee_id
    if not employee_id:
        return False
    contributor = select(TaskAssignee.task_id).where(TaskAssignee.employee_id == employee_id)
    reviewer = select(TaskReviewer.task_id).where(TaskReviewer.employee_id == employee_id)
    return and_(*base, or_(
        Task.assignee_id == employee_id,
        Task.created_by_id == employee_id,
        Task.reviewer_id == employee_id,
        Task.id.in_(contributor),
        Task.id.in_(reviewer),
    ))


async def _can_open_task(db: AsyncSession, actor: ActorContext, task: Task) -> bool:
    """Mirror of enterprise._task_for_actor(read) for web task detail access."""
    if task.organization_id != actor.organization_id:
        return False
    if _is_management(actor):
        return True
    if actor.has_any_role("client_auditor"):
        # Client auditors are scoped through project/client role assignments.
        if not task.project_id:
            return False
        project = await db.get(Project, task.project_id)
        if not project:
            return False
        assignments = (await db.execute(select(RoleAssignment.project_id, RoleAssignment.client_id).where(RoleAssignment.account_id == actor.account_id))).all()
        return any(project_id == project.id or (client_id and client_id == project.client_id) for project_id, client_id in assignments)
    if not actor.employee_id:
        return False
    if task.assignee_id == actor.employee_id:
        return True
    if await db.scalar(select(TaskAssignee.id).where(TaskAssignee.task_id == task.id, TaskAssignee.employee_id == actor.employee_id)):
        return True
    if task.workflow_status == "review":
        if task.reviewer_id == actor.employee_id:
            return True
        return bool(await db.scalar(select(TaskReviewer.id).where(TaskReviewer.task_id == task.id, TaskReviewer.employee_id == actor.employee_id)))
    return False


def _contract_clause(actor: ActorContext):
    base = ContractDocument.organization_id == actor.organization_id
    if actor.has_any_role("admin"):
        return base
    participant = exists(select(ContractReview.id).where(ContractReview.contract_id == ContractDocument.id, ContractReview.reviewer_account_id == actor.account_id))
    return and_(base, or_(ContractDocument.author_account_id == actor.account_id, participant))


async def _can_open_contract(db: AsyncSession, actor: ActorContext, contract: ContractDocument) -> bool:
    return bool(await db.scalar(select(ContractDocument.id).where(ContractDocument.id == contract.id, _contract_clause(actor))))


def _report_clause(ctx: _Ctx, report_types: tuple[str, ...]):
    base = [WorkReport.report_type.in_(report_types), WorkReport.employee_id.in_(_org_employee_ids(ctx.actor.organization_id))]
    if ctx.management:
        return and_(*base)
    if not ctx.actor.employee_id:
        return False
    return and_(*base, WorkReport.employee_id == ctx.actor.employee_id)


def _can_open_report(actor: ActorContext, report: WorkReport) -> bool:
    return _is_management(actor) or (actor.employee_id is not None and report.employee_id == actor.employee_id)


def _idea_clause(ctx: _Ctx):
    base = [PlanIdea.organization_id == ctx.actor.organization_id, PlanIdea.status.in_(("pending", "approved"))]
    if ctx.management:
        return and_(*base)
    return and_(*base, PlanIdea.submitted_by_account_id == ctx.actor.account_id)


# ─── Menu search ─────────────────────────────────────────────────────────────


def _row(kind: str, ref: Any, title: str, subtitle: str | None, status: str | None, status_label: str | None, updated: datetime | date | None, *, kind_label: str | None = None) -> dict:
    return {
        "kind": kind,
        "ref": str(ref),
        "group": KIND_GROUP[kind],
        "kind_label": kind_label or KIND_LABEL[kind],
        "title": title,
        "subtitle": subtitle,
        "status": status,
        "status_label": status_label,
        "updated_at": updated.isoformat() if updated else None,
    }


async def search_shareable(db: AsyncSession, actor: ActorContext, q: str = "", *, limit_per_group: int = 6) -> dict:
    ctx = await _ctx(db, actor)
    term = _term(q)
    names = {row.id: row.name for row in (await db.execute(select(Employee.id, Employee.name).where(Employee.id.in_(_org_employee_ids(actor.organization_id))))).all()}
    groups: dict[str, list[dict]] = {key: [] for key, _ in GROUPS}

    task_query = select(Task).where(_task_listing_clause(ctx))
    if term:
        task_query = task_query.where(or_(Task.title.ilike(term), Task.description.ilike(term)))
    tasks = (await db.execute(task_query.order_by(Task.deadline_at.asc().nulls_last(), Task.id.desc()).limit(limit_per_group))).scalars().all()
    for task in tasks:
        deadline = _fmt_dt(task.deadline_at, ctx.tz)
        owner = names.get(task.assignee_id)
        subtitle = " · ".join(part for part in (owner, f"Хугацаа {deadline}" if deadline else None) if part)
        groups["tasks"].append(_row("task", task.id, task.title, subtitle or None, task.workflow_status, TASK_STATUS.get(task.workflow_status), task.deadline_at))

    plan_rows: list[tuple[date | datetime | None, dict]] = []
    item_query = select(CompanyPlanItem).where(CompanyPlanItem.organization_id == actor.organization_id, CompanyPlanItem.status == "approved")
    if term:
        item_query = item_query.where(or_(CompanyPlanItem.title.ilike(term), CompanyPlanItem.content.ilike(term)))
    for item in (await db.execute(item_query.order_by(CompanyPlanItem.plan_month.desc(), CompanyPlanItem.position).limit(limit_per_group))).scalars().all():
        plan_rows.append((item.updated_at, _row("plan_item", item.id, item.title, f"{_fmt_month(item.plan_month)} · {HORIZON.get(item.horizon, item.horizon)}", item.status, "Батлагдсан", item.updated_at)))
    idea_query = select(PlanIdea).where(_idea_clause(ctx))
    if term:
        idea_query = idea_query.where(or_(PlanIdea.title.ilike(term), PlanIdea.content.ilike(term)))
    for idea in (await db.execute(idea_query.order_by(PlanIdea.updated_at.desc()).limit(limit_per_group))).scalars().all():
        author = names.get(idea.submitted_by_employee_id)
        plan_rows.append((idea.updated_at, _row("plan_idea", idea.id, idea.title, " · ".join(part for part in (_fmt_month(idea.plan_month), author) if part), idea.status, IDEA_STATUS.get(idea.status), idea.updated_at)))
    plan_report_query = select(WorkReport).where(_report_clause(ctx, ("next_month_plan",)))
    if term:
        plan_report_query = plan_report_query.where(or_(WorkReport.title.ilike(term), WorkReport.employee_id.in_(select(Employee.id).where(Employee.name.ilike(term)))))
    for report in (await db.execute(plan_report_query.order_by(WorkReport.period_date.desc(), WorkReport.id.desc()).limit(limit_per_group))).scalars().all():
        employee = names.get(report.employee_id, "")
        plan_rows.append((report.updated_at, _row("plan_report", report.id, report.title or f"{employee} — {REPORT_TYPE['next_month_plan']}", f"{employee} · {_fmt_month(report.period_date)}", report.status, REPORT_STATUS.get(report.status), report.updated_at)))
    plan_rows.sort(key=lambda pair: pair[0].isoformat() if pair[0] else "", reverse=True)
    groups["plans"] = [row for _, row in plan_rows[:limit_per_group]]

    contract_query = select(ContractDocument).where(_contract_clause(actor), ContractDocument.status != "SIGNED_AND_STAMPED")
    if term:
        contract_query = contract_query.where(ContractDocument.title.ilike(term))
    contracts = (await db.execute(contract_query.order_by((ContractDocument.status == "DRAFT").desc(), ContractDocument.updated_at.desc()).limit(limit_per_group))).scalars().all()
    for contract in contracts:
        subtitle = " · ".join(part for part in (names.get(contract.author_employee_id), f"Шинэчилсэн {_fmt_dt(contract.updated_at, ctx.tz)}" if contract.updated_at else None) if part)
        groups["contracts"].append(_row("contract", contract.public_id, contract.title, subtitle or None, contract.status, CONTRACT_STATUS.get(contract.status), contract.updated_at, kind_label=CONTRACT_TYPE.get(contract.document_type)))

    report_query = select(WorkReport).where(_report_clause(ctx, REPORT_TYPES))
    if term:
        report_query = report_query.where(or_(WorkReport.title.ilike(term), WorkReport.employee_id.in_(select(Employee.id).where(Employee.name.ilike(term)))))
    for report in (await db.execute(report_query.order_by(WorkReport.period_date.desc(), WorkReport.id.desc()).limit(limit_per_group))).scalars().all():
        employee = names.get(report.employee_id, "")
        period = _fmt_month(report.period_date) if report.report_type == "monthly" else _fmt_date(report.period_date)
        title = report.title or f"{employee} — {REPORT_TYPE.get(report.report_type, report.report_type)}"
        groups["reports"].append(_row("report", report.id, title, f"{employee} · {REPORT_TYPE.get(report.report_type)} · {period}", report.status, REPORT_STATUS.get(report.status), report.updated_at))

    return {
        "query": q,
        "groups": [{"key": key, "label": label, "items": groups[key]} for key, label in GROUPS],
    }


# ─── Snapshots ───────────────────────────────────────────────────────────────


def _field(label: str, value: Any) -> dict | None:
    if value is None or value == "" or value == []:
        return None
    return {"label": label, "value": str(value)}


def _card(kind: str, ref: Any, *, title: str, status: str | None, status_label: str | None, fields: list[dict | None], excerpt: str | None, target_url: str, kind_label: str | None = None) -> dict:
    return {
        "kind": kind,
        "ref": str(ref),
        "group": KIND_GROUP[kind],
        "kind_label": kind_label or KIND_LABEL[kind],
        "title": title,
        "status": status,
        "status_label": status_label,
        "fields": [item for item in fields if item],
        "excerpt": excerpt,
        "target_url": target_url,
    }


async def _report_text(db: AsyncSession, report: WorkReport) -> str | None:
    if report.approved_revision_id:
        revision = await db.get(WorkReportRevision, report.approved_revision_id)
        if revision:
            return revision.text
    revision = (await db.execute(select(WorkReportRevision).where(WorkReportRevision.report_id == report.id, WorkReportRevision.status != "deleted").order_by(WorkReportRevision.id.desc()).limit(1))).scalars().first()
    return revision.text if revision else None


def target_url(kind: str, ref: str, *, month: date | None = None) -> str:
    if kind == "task":
        return f"/tasks?task={ref}"
    if kind == "contract":
        return f"/contracts/{ref}"
    if kind in {"report", "plan_report"}:
        return f"/reports?report={ref}"
    month_part = f"month={_fmt_month(month)}&" if month else ""
    return f"/plans?{month_part}{'item' if kind == 'plan_item' else 'idea'}={ref}"


def _int_ref(ref: str) -> int:
    try:
        return int(ref)
    except (TypeError, ValueError) as exc:
        raise ShareItemNotFound(ref) from exc


async def build_snapshot(db: AsyncSession, actor: ActorContext, kind: str, ref: str) -> dict:
    """Return the info-card payload, enforcing that the *sender* may share it."""
    ctx = await _ctx(db, actor)
    if kind == "task":
        task = await db.scalar(select(Task).where(Task.id == _int_ref(ref), _task_listing_clause(ctx)))
        if not task:
            raise ShareItemNotFound(ref)
        assignee_ids = list((await db.execute(select(TaskAssignee.employee_id).where(TaskAssignee.task_id == task.id))).scalars().all())
        people_ids = {task.assignee_id, task.created_by_id, *assignee_ids} - {None}
        people = {row.id: row.name for row in (await db.execute(select(Employee.id, Employee.name).where(Employee.id.in_(people_ids)))).all()} if people_ids else {}
        project = await db.get(Project, task.project_id) if task.project_id else None
        contributors = [people[item] for item in assignee_ids if item in people and item != task.assignee_id]
        overdue = bool(task.deadline_at and task.deadline_at < datetime.now(task.deadline_at.tzinfo) and task.workflow_status not in {"done", "cancelled", "review"})
        return _card("task", task.id, title=task.title, status=task.workflow_status, status_label=TASK_STATUS.get(task.workflow_status), fields=[
            _field("Хариуцагч", people.get(task.assignee_id)),
            _field("Хамтрагч", ", ".join(contributors)),
            _field("Эхлэх", _fmt_dt(task.start_at, ctx.tz)),
            _field("Дуусах хугацаа", f"{_fmt_dt(task.deadline_at, ctx.tz)}{' · хэтэрсэн' if overdue else ''}" if task.deadline_at else None),
            _field("Эрэмбэ", PRIORITY.get(task.priority)),
            _field("Төсөл", project.name if project and project.organization_id == actor.organization_id else None),
            _field("Үүсгэсэн", people.get(task.created_by_id)),
        ], excerpt=_excerpt(task.description), target_url=target_url("task", str(task.id)))

    if kind == "plan_item":
        item = await db.scalar(select(CompanyPlanItem).where(CompanyPlanItem.id == _int_ref(ref), CompanyPlanItem.organization_id == actor.organization_id, CompanyPlanItem.status == "approved"))
        if not item:
            raise ShareItemNotFound(ref)
        source = await db.get(Employee, item.source_employee_id) if item.source_employee_id else None
        return _card("plan_item", item.id, title=item.title, status=item.status, status_label="Батлагдсан", fields=[
            _field("Сар", _fmt_month(item.plan_month)),
            _field("Хугацааны төрөл", HORIZON.get(item.horizon, item.horizon)),
            _field("Дуусах огноо", _fmt_date(item.due_date)),
            _field("Санаачилсан", source.name if source else None),
        ], excerpt=_excerpt(item.content), target_url=target_url("plan_item", str(item.id), month=item.plan_month))

    if kind == "plan_idea":
        idea = await db.scalar(select(PlanIdea).where(PlanIdea.id == _int_ref(ref), _idea_clause(ctx)))
        if not idea:
            raise ShareItemNotFound(ref)
        author = await db.get(Employee, idea.submitted_by_employee_id) if idea.submitted_by_employee_id else None
        return _card("plan_idea", idea.id, title=idea.title, status=idea.status, status_label=IDEA_STATUS.get(idea.status), fields=[
            _field("Сар", _fmt_month(idea.plan_month)),
            _field("Санал гаргасан", author.name if author else None),
            _field("Санал болгосон хугацаа", _fmt_date(idea.suggested_due_date)),
        ], excerpt=_excerpt(idea.content), target_url=target_url("plan_idea", str(idea.id), month=idea.plan_month))

    if kind in {"report", "plan_report"}:
        types = ("next_month_plan",) if kind == "plan_report" else REPORT_TYPES
        report = await db.scalar(select(WorkReport).where(WorkReport.id == _int_ref(ref), _report_clause(ctx, types)))
        if not report:
            raise ShareItemNotFound(ref)
        employee = await db.get(Employee, report.employee_id)
        period = _fmt_month(report.period_date) if report.report_type != "daily" else _fmt_date(report.period_date)
        type_label = REPORT_TYPE.get(report.report_type, report.report_type)
        return _card(kind, report.id, title=report.title or f"{employee.name if employee else ''} — {type_label}", status=report.status, status_label=REPORT_STATUS.get(report.status), fields=[
            _field("Ажилтан", employee.name if employee else None),
            _field("Төрөл", type_label),
            _field("Хугацаа", period),
            _field("Илгээсэн", _fmt_dt(report.submitted_at, ctx.tz)),
            _field("Хянасан", _fmt_dt(report.reviewed_at, ctx.tz)),
        ], excerpt=_excerpt(await _report_text(db, report), 420), target_url=target_url(kind, str(report.id)))

    if kind == "contract":
        try:
            public_id = UUID(str(ref))
        except ValueError as exc:
            raise ShareItemNotFound(ref) from exc
        contract = await db.scalar(select(ContractDocument).where(ContractDocument.public_id == public_id, _contract_clause(actor)))
        if not contract:
            raise ShareItemNotFound(ref)
        author = await db.get(Employee, contract.author_employee_id) if contract.author_employee_id else None
        revision = await db.get(ContractRevision, contract.current_revision_id) if contract.current_revision_id else None
        reviews = (await db.execute(select(ContractReview.decision).where(ContractReview.contract_id == contract.id, ContractReview.round_number == contract.submission_round))).scalars().all()
        effective = " – ".join(value for value in (_fmt_date(contract.effective_start_on), _fmt_date(contract.effective_end_on)) if value)
        return _card("contract", contract.public_id, title=contract.title, status=contract.status, status_label=CONTRACT_STATUS.get(contract.status), kind_label=CONTRACT_TYPE.get(contract.document_type), fields=[
            _field("Зохиогч", author.name if author else None),
            _field("Хүчинтэй хугацаа", effective or None),
            _field("Хянагчид", f"{sum(1 for item in reviews if item == 'approved')}/{len(reviews)} баталсан" if reviews else None),
            _field("Шинэчилсэн", _fmt_dt(contract.updated_at, ctx.tz)),
        ], excerpt=_excerpt(revision.plain_text if revision else None), target_url=target_url("contract", str(contract.public_id)))

    raise ShareItemNotFound(ref)


async def reader_can_open(db: AsyncSession, actor: ActorContext, kind: str, ref: str) -> bool:
    """Whether this reader can open the item's page. Missing items are closed."""
    try:
        if kind == "task":
            task = await db.get(Task, _int_ref(ref))
            return bool(task and not task.is_archived and await _can_open_task(db, actor, task))
        if kind == "plan_item":
            item = await db.get(CompanyPlanItem, _int_ref(ref))
            return bool(item and item.organization_id == actor.organization_id and item.status == "approved")
        if kind == "plan_idea":
            idea = await db.get(PlanIdea, _int_ref(ref))
            return bool(idea and idea.organization_id == actor.organization_id and (_is_management(actor) or idea.submitted_by_account_id == actor.account_id))
        if kind in {"report", "plan_report"}:
            report = await db.get(WorkReport, _int_ref(ref))
            return bool(report and _can_open_report(actor, report))
        if kind == "contract":
            contract = await db.scalar(select(ContractDocument).where(ContractDocument.public_id == UUID(str(ref))))
            return bool(contract and await _can_open_contract(db, actor, contract))
    except (ShareItemNotFound, ValueError):
        return False
    return False


def fallback_body(card: dict) -> str:
    """Plain-text form used for previews, push notifications and search."""
    icon = {"tasks": "✅", "plans": "🗓️", "contracts": "📄", "reports": "📊"}.get(card["group"], "📌")
    status = f" · {card['status_label']}" if card.get("status_label") else ""
    return f"{icon} {card['kind_label']}: {card['title']}{status}"[:4000]
