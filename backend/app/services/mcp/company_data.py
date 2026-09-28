"""Read adapters that give OYUNS the rest of the company data.

Every function mirrors the permission rules of the page that owns the data
(reports, worktime, HR, CRM, contracts, payroll) by reusing that module's own
scope helpers or endpoint functions. Results go through the MCP envelope, which
strips database IDs and secrets before the model sees them.
"""
from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.enterprise_deps import ActorContext
from app.models.contracts import ContractDocument
from app.models.models import (
    Employee,
    MonthlyPayrollMonth,
    MonthlyPayrollRun,
    MonthlyPayrollRunRow,
    Organization,
    PlanIdea,
    WorkReport,
    WorkReportRevision,
    WorkTimeEntry,
)
from app.services import chat_share_service
from app.services.mcp import schemas
from app.services.mcp.references import resolve_resource_reference

MAX_RANGE_DAYS = 92
MISSING_REPORT_STATUSES = ("awaiting", "draft", "editing", "revision_requested")
PAYROLL_TOTAL_KEYS = ("gross", "pit", "employee_shi", "employer_shi", "advance", "other_deductions", "total_deductions", "net_pay")


class ToolDenied(Exception):
    """The caller may not see the requested data; reported as status=denied."""


async def _zone(db: AsyncSession, actor: ActorContext) -> ZoneInfo:
    organization = await db.get(Organization, actor.organization_id)
    try:
        return ZoneInfo(organization.timezone if organization and organization.timezone else "Asia/Ulaanbaatar")
    except Exception:
        return ZoneInfo("Asia/Ulaanbaatar")


def _employee_id(actor: ActorContext, reference: str | None) -> int | None:
    if not reference:
        return None
    value = resolve_resource_reference(actor, reference, kind="employee")
    if not str(value).isdigit():
        raise ValueError("INVALID_EMPLOYEE_REFERENCE")
    return int(value)


def _window(date_from: date | None, date_to: date | None, today: date, *, default_days: int) -> tuple[date, date]:
    end = date_to or (date_from if date_from and default_days == 0 else today)
    start = date_from or end - timedelta(days=default_days)
    if start > end:
        start, end = end, start
    if (end - start).days > MAX_RANGE_DAYS:
        start = end - timedelta(days=MAX_RANGE_DAYS)
    return start, end


def _excerpt(text: str | None, limit: int) -> str | None:
    if not text:
        return None
    compact = " ".join(text.split())
    return compact if len(compact) <= limit else compact[:limit].rstrip() + "…"


def _money(value: Any) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except (InvalidOperation, ValueError):
        return Decimal(0)


def _hours(minutes: float) -> float:
    return round(minutes / 60, 1)


def _app_link(path: str) -> str:
    return f"{settings.PUBLIC_APP_URL.rstrip('/')}{path}"


# ─── Work reports ───────────────────────────────────────────────────────────

async def reports_search(db: AsyncSession, actor: ActorContext, data: schemas.ReportsSearchInput) -> dict:
    ctx = await chat_share_service._ctx(db, actor)
    today = datetime.now(ctx.tz).date()
    date_from, date_to = _window(data.date_from, data.date_to, today, default_days=6)
    clause = chat_share_service._report_clause(ctx, tuple(data.report_types))
    if clause is False:
        return {"status": "denied", "data": {}}
    target = _employee_id(actor, data.employee_reference)
    if target is not None and not ctx.management and target != actor.employee_id:
        return {"status": "denied", "data": {}}
    # Monthly reports and plans are dated on the first day of their month.
    filters = [clause, WorkReport.period_date >= date_from.replace(day=1), WorkReport.period_date <= date_to]
    if "daily" in data.report_types and len(data.report_types) == 1:
        filters[1] = WorkReport.period_date >= date_from
    if target is not None:
        filters.append(WorkReport.employee_id == target)
    if data.status == "submitted":
        filters.append(WorkReport.status.in_(("submitted", "approved")))
    elif data.status == "approved":
        filters.append(WorkReport.status == "approved")
    elif data.status == "missing":
        filters.append(WorkReport.status.in_(MISSING_REPORT_STATUSES))
    if data.text_query:
        pattern = f"%{data.text_query.strip()}%"
        filters.append(or_(WorkReport.title.ilike(pattern), exists(select(WorkReportRevision.id).where(WorkReportRevision.report_id == WorkReport.id, WorkReportRevision.status != "deleted", WorkReportRevision.text.ilike(pattern)))))
    total = int(await db.scalar(select(func.count()).select_from(WorkReport).where(*filters)) or 0)
    by_status = dict((await db.execute(select(WorkReport.status, func.count()).where(*filters).group_by(WorkReport.status))).all())
    rows = (await db.execute(
        select(WorkReport, Employee).join(Employee, Employee.id == WorkReport.employee_id)
        .where(*filters).order_by(WorkReport.period_date.desc(), Employee.name).limit(data.limit)
    )).all()
    items = []
    text_budget = max(300, 9_000 // max(1, len(rows)))
    for report, employee in rows:
        item = {
            "employee": employee.name,
            "report_type": report.report_type,
            "period": report.period_date.isoformat() if report.report_type == "daily" else report.period_date.strftime("%Y-%m"),
            "status": report.status,
            "title": report.title,
            "submitted_at": report.submitted_at.astimezone(ctx.tz).isoformat(timespec="minutes") if report.submitted_at else None,
            "open_url": _app_link(f"/reports?report={report.id}"),
        }
        if data.include_text:
            item["text"] = _excerpt(await chat_share_service._report_text(db, report), text_budget)
        items.append(item)
    return {
        "status": "ok" if items else "empty",
        "data": {"date_from": date_from, "date_to": date_to, "total": total, "count_by_status": by_status, "items": items},
    }


# ─── Work time ──────────────────────────────────────────────────────────────

async def _worktime_scope(db: AsyncSession, actor: ActorContext, data: schemas.WorktimeGetInput, date_from: date, date_to: date) -> list[int]:
    from app.services.worktime_report_service import _employee_query

    visible = set((await db.execute(_employee_query(actor, date_from, date_to).distinct())).scalars().all())
    if actor.employee_id is not None:
        visible.add(actor.employee_id)
    target = _employee_id(actor, data.employee_reference)
    if target is not None:
        if target not in visible:
            raise ToolDenied()
        return [target]
    if data.scope == "self":
        if actor.employee_id is None:
            raise ToolDenied()
        return [actor.employee_id]
    return sorted(visible)


async def worktime_get(db: AsyncSession, actor: ActorContext, data: schemas.WorktimeGetInput) -> dict:
    zone = await _zone(db, actor)
    now = datetime.now(timezone.utc)
    today = now.astimezone(zone).date()
    date_from, date_to = _window(data.date_from, data.date_to, today, default_days=0)
    if data.date_from is None and data.date_to is None:
        date_from = date_to = today
    employee_ids = await _worktime_scope(db, actor, data, date_from, date_to)
    if not employee_ids:
        return {"status": "empty", "data": {}}
    names = dict((await db.execute(select(Employee.id, Employee.name).where(Employee.id.in_(employee_ids)))).all())

    if data.view == "status_now":
        entries = (await db.execute(
            select(WorkTimeEntry).where(WorkTimeEntry.employee_id.in_(employee_ids), WorkTimeEntry.ended_at.is_(None))
            .order_by(WorkTimeEntry.started_at)
        )).scalars().all()
        active = {}
        for entry in entries:
            active[entry.employee_id] = {
                "employee": names.get(entry.employee_id),
                "state": "on_break" if entry.entry_type == "break" else "working",
                "mode": entry.mode or "in_person",
                "since": entry.started_at.astimezone(zone).isoformat(timespec="minutes"),
            }
        not_clocked_in = sorted(names[item] for item in employee_ids if item not in active and item in names)
        return {"status": "ok", "data": {
            "as_of": now.astimezone(zone).isoformat(timespec="minutes"),
            "items": list(active.values()),
            "working_count": sum(1 for item in active.values() if item["state"] == "working"),
            "on_break_count": sum(1 for item in active.values() if item["state"] == "on_break"),
            "not_clocked_in": not_clocked_in[:60],
            "not_clocked_in_count": len(not_clocked_in),
        }}

    entries = (await db.execute(
        select(WorkTimeEntry).where(
            WorkTimeEntry.employee_id.in_(employee_ids),
            WorkTimeEntry.local_work_date >= date_from,
            WorkTimeEntry.local_work_date <= date_to,
        ).order_by(WorkTimeEntry.local_work_date, WorkTimeEntry.started_at)
    )).scalars().all()

    def minutes(entry: WorkTimeEntry) -> float:
        end = entry.ended_at or now
        return max(0.0, (end - entry.started_at).total_seconds() / 60)

    if data.view == "daily":
        days: dict[tuple[int, date], dict] = {}
        for entry in entries:
            key = (entry.employee_id, entry.local_work_date)
            day = days.setdefault(key, {"employee": names.get(entry.employee_id), "date": entry.local_work_date, "first_in": None, "last_out": None, "work_minutes": 0.0, "break_minutes": 0.0, "remote_minutes": 0.0, "in_progress": False})
            local_start = entry.started_at.astimezone(zone).strftime("%H:%M")
            day["first_in"] = day["first_in"] or local_start
            if entry.ended_at:
                day["last_out"] = entry.ended_at.astimezone(zone).strftime("%H:%M")
            else:
                day["in_progress"] = True
            if entry.entry_type == "break":
                day["break_minutes"] += minutes(entry)
            else:
                day["work_minutes"] += minutes(entry)
                if entry.mode == "remote":
                    day["remote_minutes"] += minutes(entry)
        items = [{**day, "worked_hours": _hours(day.pop("work_minutes")), "break_hours": _hours(day.pop("break_minutes")), "remote_hours": _hours(day.pop("remote_minutes"))} for day in days.values()]
        return {"status": "ok" if items else "empty", "data": {"date_from": date_from, "date_to": date_to, "items": items[:80], "row_count": len(items)}}

    totals: dict[int, dict] = {}
    for entry in entries:
        if entry.entry_type == "break":
            continue
        total = totals.setdefault(entry.employee_id, {"employee": names.get(entry.employee_id), "work_minutes": 0.0, "remote_minutes": 0.0, "days": set()})
        total["work_minutes"] += minutes(entry)
        if entry.mode == "remote":
            total["remote_minutes"] += minutes(entry)
        total["days"].add(entry.local_work_date)
    items = sorted(
        ({"employee": total["employee"], "worked_hours": _hours(total["work_minutes"]), "remote_hours": _hours(total["remote_minutes"]), "days_worked": len(total["days"])} for total in totals.values()),
        key=lambda item: item["worked_hours"], reverse=True,
    )
    no_time = sorted(names[item] for item in employee_ids if item not in totals and item in names)
    return {"status": "ok" if items else "empty", "data": {
        "date_from": date_from, "date_to": date_to, "items": items[:80],
        "total_worked_hours": round(sum(item["worked_hours"] for item in items), 1),
        "employees_without_time": no_time[:60],
    }}


# ─── HR ─────────────────────────────────────────────────────────────────────

async def hr_get(db: AsyncSession, actor: ActorContext, data: schemas.HRGetInput) -> dict:
    from app.hr.router import employee_in_scope, get_leave_balances, list_attendance, list_departments, list_leave_requests

    employee_id = _employee_id(actor, data.employee_reference)
    if data.resource == "departments":
        rows = await list_departments(db=db, actor=actor)
        return {"status": "ok" if rows else "empty", "data": {"items": rows}}
    if data.resource == "leave_requests":
        if employee_id is not None:
            await employee_in_scope(db, actor, employee_id)
        rows = await list_leave_requests(year=data.year, status_filter=data.leave_status, employee_id=employee_id, db=db, actor=actor)
        items = [{key: value for key, value in row.items() if key not in {"version"}} for row in rows[:50]]
        return {"status": "ok" if items else "empty", "data": {"items": items, "total": len(rows)}}
    if data.resource == "leave_balances":
        rows = await get_leave_balances(year=data.year, employee_id=employee_id, db=db, actor=actor)
        return {"status": "ok" if rows else "empty", "data": {"items": rows[:90]}}
    today = datetime.now(await _zone(db, actor)).date()
    start = data.date_from or today.replace(day=1)
    end = data.date_to or min(today, date(start.year, start.month, calendar.monthrange(start.year, start.month)[1]))
    if end < start:
        start, end = end, start
    end = min(end, start + timedelta(days=31))
    result = await list_attendance(month=None, employee_id=employee_id, start_date=start, end_date=end, db=db, actor=actor)
    rows = result.get("items", [])
    if employee_id is not None:
        items = [
            {key: row.get(key) for key in ("employee_name", "attendance_date", "status", "worked_minutes", "first_started_at", "last_ended_at", "on_leave", "is_non_working_day", "non_working_day_name")}
            for row in rows
        ]
        return {"status": "ok" if items else "empty", "data": {"date_from": start, "date_to": end, "items": items}}
    summary: dict[str, dict] = {}
    for row in rows:
        if row.get("is_non_working_day"):
            continue
        person = summary.setdefault(row.get("employee_name") or "—", {"employee": row.get("employee_name"), "present": 0, "remote": 0, "late": 0, "absent": 0, "on_leave": 0, "worked_hours": 0.0})
        if row.get("on_leave"):
            person["on_leave"] += 1
        elif row.get("status") in {"present", "remote", "late", "absent"}:
            person[row["status"]] += 1
        person["worked_hours"] = round(person["worked_hours"] + (row.get("worked_minutes") or 0) / 60, 1)
    items = list(summary.values())
    return {"status": "ok" if items else "empty", "data": {"date_from": start, "date_to": end, "items": items[:80], "note": "Counts are working days per status."}}


# ─── CRM ────────────────────────────────────────────────────────────────────

PARTY_FIELDS = ("code", "name", "business_name", "party_type", "is_customer", "is_supplier", "email", "phone", "website", "location", "tags", "group_name", "responsible_name", "customer_since", "status", "credit_limit", "currency")
ACTIVITY_FIELDS = ("number", "party_name", "contact_name", "activity_at", "subject", "type_name", "is_important", "due_at", "responsible_name", "completed_at", "is_open", "is_overdue", "overdue_days", "expected_revenue", "currency", "project_name", "contract_title")


async def crm_search(db: AsyncSession, actor: ActorContext, data: schemas.CRMSearchInput) -> dict:
    from app.crm import activities as crm_activities, parties as crm_parties
    from app.crm.service import crm_module_enabled

    if not await crm_module_enabled(db, actor.organization_id):
        return {"status": "empty", "data": {"reason": "The CRM module is not enabled for this company."}}
    if data.resource == "summary":
        summary = await crm_activities.crm_summary(mine=data.mine_only, db=db, actor=actor)
        return {"status": "ok", "data": summary}
    if data.resource == "parties":
        result = await crm_parties.list_parties(
            search=data.query, kind=data.party_kind, group_id=None, parent_party_id=None,
            responsible_employee_id=actor.employee_id if data.mine_only else None, is_active=True,
            since_from=None, since_to=None, duplicates_only=False, page=1, page_size=data.limit, db=db, actor=actor,
        )
        items = [{key: row.get(key) for key in PARTY_FIELDS if row.get(key) not in (None, "", [])} for row in result["items"]]
        return {"status": "ok" if items else "empty", "data": {"items": items, "total": result["total"]}}
    result = await crm_activities.list_activities(
        search=data.query, party_id=None, include_children=False, type_id=None, status_id=None,
        responsible_employee_id=None, contract_id=None, project_id=None, mine=data.mine_only,
        state=data.state, overdue=data.overdue_only, important=False, is_active=True,
        date_from=None, date_to=None, due_from=None, due_to=None,
        sort="due_at" if data.state == "open" else "activity_at", page=1, page_size=data.limit, db=db, actor=actor,
    )
    items = []
    for row in result["items"]:
        item = {key: row.get(key) for key in ACTIVITY_FIELDS if row.get(key) not in (None, "", [])}
        status = row.get("status")
        if isinstance(status, dict):
            item["status"] = status.get("name")
        if row.get("body"):
            item["notes"] = _excerpt(row["body"], 400)
        items.append(item)
    return {"status": "ok" if items else "empty", "data": {"items": items, "total": result["total"]}}


# ─── Contracts ──────────────────────────────────────────────────────────────

async def contracts_search(db: AsyncSession, actor: ActorContext, data: schemas.ContractsSearchInput) -> dict:
    today = datetime.now(await _zone(db, actor)).date()
    filters = [chat_share_service._contract_clause(actor)]
    if data.query:
        filters.append(ContractDocument.title.ilike(f"%{data.query.strip()}%"))
    if data.status:
        filters.append(ContractDocument.status == data.status)
    if data.expiring_within_days:
        filters.append(and_(ContractDocument.effective_end_on >= today, ContractDocument.effective_end_on <= today + timedelta(days=data.expiring_within_days)))
    total = int(await db.scalar(select(func.count()).select_from(ContractDocument).where(*filters)) or 0)
    order = ContractDocument.effective_end_on.asc().nulls_last() if data.expiring_within_days else ContractDocument.updated_at.desc()
    rows = (await db.execute(
        select(ContractDocument, Employee.name).outerjoin(Employee, Employee.id == ContractDocument.author_employee_id)
        .where(*filters).order_by(order).limit(data.limit)
    )).all()
    items = [
        {
            "title": contract.title,
            "document_type": contract.document_type,
            "status": contract.status,
            "author": author,
            "effective_start_on": contract.effective_start_on,
            "effective_end_on": contract.effective_end_on,
            "days_until_end": (contract.effective_end_on - today).days if contract.effective_end_on else None,
            "signed_at": contract.signed_at,
            "updated_at": contract.updated_at,
            "open_url": _app_link(f"/contracts/{contract.public_id}"),
        }
        for contract, author in rows
    ]
    return {"status": "ok" if items else "empty", "data": {"items": items, "total": total}}


# ─── Plan ideas ─────────────────────────────────────────────────────────────

async def plan_ideas(db: AsyncSession, actor: ActorContext, data: schemas.ProjectsSearchInput) -> dict:
    ctx = await chat_share_service._ctx(db, actor)
    filters = [chat_share_service._idea_clause(ctx)]
    if data.date_from:
        filters.append(PlanIdea.plan_month >= data.date_from.replace(day=1))
    if data.date_to:
        filters.append(PlanIdea.plan_month <= data.date_to)
    rows = (await db.execute(
        select(PlanIdea, Employee.name).outerjoin(Employee, Employee.id == PlanIdea.submitted_by_employee_id)
        .where(*filters).order_by(PlanIdea.plan_month.desc(), PlanIdea.created_at.desc()).limit(data.limit)
    )).all()
    items = [
        {"title": idea.title, "content": _excerpt(idea.content, 500), "plan_month": idea.plan_month.strftime("%Y-%m"), "status": idea.status, "submitted_by": name, "suggested_due_date": idea.suggested_due_date,
         "open_url": _app_link(f"/plans?month={idea.plan_month.strftime('%Y-%m')}&idea={idea.id}")}
        for idea, name in rows
    ]
    return {"status": "ok" if items else "empty", "data": {"entity": "ideas", "items": items}}


# ─── Payroll ────────────────────────────────────────────────────────────────

async def payroll_summary(db: AsyncSession, actor: ActorContext, data: schemas.PayrollSummaryInput) -> dict:
    from app.erp.service import require_capability

    await require_capability(db, actor, "payroll", "view")
    months = (await db.execute(
        select(MonthlyPayrollMonth).where(MonthlyPayrollMonth.organization_id == actor.organization_id)
        .order_by(MonthlyPayrollMonth.year.desc(), MonthlyPayrollMonth.month.desc()).limit(24)
    )).scalars().all()
    if not months:
        return {"status": "empty", "data": {}}

    async def runs_for(month: MonthlyPayrollMonth) -> list[MonthlyPayrollRun]:
        return list((await db.execute(select(MonthlyPayrollRun).where(MonthlyPayrollRun.month_id == month.id).order_by(MonthlyPayrollRun.pay_date, MonthlyPayrollRun.run_type))).scalars().all())

    if data.view == "months":
        items = []
        for month in months[:12]:
            items.append({"month": f"{month.year}-{month.month:02d}", "status": month.status, "runs": [{"run_type": run.run_type, "pay_date": run.pay_date, "status": run.status} for run in await runs_for(month)]})
        return {"status": "ok", "data": {"items": items}}
    month = months[0]
    if data.month:
        year, number = (int(part) for part in data.month.split("-"))
        month = next((item for item in months if item.year == year and item.month == number), None)
        if month is None:
            return {"status": "empty", "data": {"reason": f"No payroll month {data.month}."}}
    runs = await runs_for(month)
    # The final run carries the month's full calculation; an advance-only
    # month falls back to its latest run.
    run = next((item for item in reversed(runs) if item.run_type == "final"), runs[-1] if runs else None)
    if run is None:
        return {"status": "empty", "data": {"month": f"{month.year}-{month.month:02d}", "month_status": month.status}}
    query = select(MonthlyPayrollRunRow, Employee.name).join(Employee, Employee.id == MonthlyPayrollRunRow.employee_id).where(MonthlyPayrollRunRow.run_id == run.id)
    target = _employee_id(actor, data.employee_reference)
    if target is not None:
        query = query.where(MonthlyPayrollRunRow.employee_id == target)
    rows = (await db.execute(query.order_by(Employee.name))).all()
    header = {"month": f"{month.year}-{month.month:02d}", "month_status": month.status, "run_type": run.run_type, "run_status": run.status, "pay_date": run.pay_date, "employee_count": len(rows), "currency": "MNT"}
    if data.view == "per_employee" or target is not None:
        items = [{"employee": name, "status": row.status, **{key: (row.result or {}).get(key) for key in ("gross", "total_deductions", "net_pay")}} for row, name in rows[:80]]
        return {"status": "ok" if items else "empty", "data": {**header, "items": items}}
    totals = {key: str(sum((_money((row.result or {}).get(key)) for row, _ in rows), Decimal(0))) for key in PAYROLL_TOTAL_KEYS}
    return {"status": "ok" if rows else "empty", "data": {**header, "totals": totals}}


async def run_guarded(operation) -> dict:
    """Map page-level access errors onto tool statuses."""
    try:
        return await operation
    except ToolDenied:
        return {"status": "denied", "data": {}}
    except HTTPException as exc:
        if exc.status_code in {401, 403, 404}:
            return {"status": "denied" if exc.status_code != 404 else "empty", "data": {}}
        if exc.status_code in {400, 409, 422}:
            return {"status": "denied", "data": {"reason": str(exc.detail)[:300]}}
        raise
