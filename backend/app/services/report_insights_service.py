"""Management report exports and OYUNS summaries over a chosen period.

Exports are deterministic: one Markdown file for a single report, otherwise a
ZIP organised by worker or by department. Summaries ground the model only in
server-collected KPIs and report text; nothing is fetched by the model.
"""
from __future__ import annotations

import csv
import io
import logging
import re
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Department, Employee, EmployeeDetails, Task, WorkReport, WorkReportRevision, WorkTimeEntry
from app.services.ai_gateway import AIGateway, GatewayError

log = logging.getLogger(__name__)

EXPORT_ROLES = ("admin", "manager")
REPORT_TYPES = ("daily", "monthly", "next_month_plan")
MONTH_PERIOD_TYPES = {"monthly", "next_month_plan"}
MAX_PERIOD_DAYS = 3 * 366
NO_DEPARTMENT = "Хэлтэсгүй"
REPORT_TYPE_LABEL = {"daily": "Өдрийн тайлан", "monthly": "Сарын тайлан", "next_month_plan": "Дараа сарын төлөвлөгөө"}
REPORT_STATUS_LABEL = {"awaiting": "Хүлээгдэж буй", "draft": "Ноорог", "editing": "Засварлаж буй", "submitted": "Илгээсэн", "revision_requested": "Засвар хүссэн", "approved": "Батлагдсан"}
CONTEXT_CHAR_BUDGET = 60_000
GroupBy = Literal["worker", "department"]

_gateway = AIGateway()


class NoReportsFound(LookupError):
    pass


@dataclass(frozen=True)
class Person:
    employee: Employee
    department_id: int | None
    department: str | None


@dataclass(frozen=True)
class ReportRecord:
    report: WorkReport
    person: Person
    text: str


def validate_period(date_from: date, date_to: date) -> None:
    if date_to < date_from:
        raise ValueError("date_to must not precede date_from")
    if (date_to - date_from).days > MAX_PERIOD_DAYS:
        raise ValueError("period is limited to three years")


async def people(db: AsyncSession, organization_id: int, *, employee_ids: list[int] | None = None, department_ids: list[int] | None = None) -> dict[int, Person]:
    query = (
        select(Employee, EmployeeDetails.department_id, Department.name)
        .outerjoin(EmployeeDetails, (EmployeeDetails.employee_id == Employee.id) & (EmployeeDetails.organization_id == organization_id))
        .outerjoin(Department, Department.id == EmployeeDetails.department_id)
        .where(Employee.organization_id == organization_id, Employee.deleted_at.is_(None))
        .order_by(Employee.name)
    )
    if employee_ids:
        query = query.where(Employee.id.in_(set(employee_ids)))
    if department_ids:
        query = query.where(EmployeeDetails.department_id.in_(set(department_ids)))
    return {employee.id: Person(employee, department_id, department_name) for employee, department_id, department_name in (await db.execute(query)).all()}


async def scope_options(db: AsyncSession, organization_id: int) -> dict:
    everyone = await people(db, organization_id)
    departments = (await db.execute(select(Department).where(Department.organization_id == organization_id, Department.is_active.is_(True)).order_by(Department.name))).scalars().all()
    return {
        "employees": [{"id": item.employee.id, "name": item.employee.name, "department_id": item.department_id, "department": item.department, "is_active": item.employee.is_active} for item in everyone.values()],
        "departments": [{"id": item.id, "name": item.name} for item in departments],
    }


async def collect_reports(
    db: AsyncSession,
    organization_id: int,
    date_from: date,
    date_to: date,
    *,
    employee_ids: list[int] | None = None,
    department_ids: list[int] | None = None,
    report_types: tuple[str, ...] | list[str] = REPORT_TYPES,
    approved_only: bool = False,
) -> list[ReportRecord]:
    scoped = await people(db, organization_id, employee_ids=employee_ids, department_ids=department_ids)
    if not scoped:
        return []
    types = [item for item in report_types if item in REPORT_TYPES] or list(REPORT_TYPES)
    # Month-based reports are stored on the first day of their month, so a
    # period starting mid-month still includes that month's report.
    month_from = date_from.replace(day=1)
    query = select(WorkReport).where(
        WorkReport.employee_id.in_(list(scoped)),
        WorkReport.report_type.in_(types),
        WorkReport.period_date <= date_to,
        ((WorkReport.report_type == "daily") & (WorkReport.period_date >= date_from))
        | ((WorkReport.report_type != "daily") & (WorkReport.period_date >= month_from)),
    )
    if approved_only:
        query = query.where(WorkReport.status == "approved")
    reports = list((await db.execute(query.order_by(WorkReport.period_date, WorkReport.id))).scalars().all())
    if not reports:
        return []
    revisions = (await db.execute(
        select(WorkReportRevision)
        .where(WorkReportRevision.report_id.in_([item.id for item in reports]), WorkReportRevision.status != "deleted")
        .order_by(WorkReportRevision.id.desc())
    )).scalars().all()
    by_id = {item.id: item for item in revisions}
    latest: dict[int, WorkReportRevision] = {}
    for revision in revisions:
        latest.setdefault(revision.report_id, revision)
    records = []
    for report in reports:
        revision = by_id.get(report.approved_revision_id) if report.approved_revision_id else None
        revision = revision or latest.get(report.id)
        text = (revision.text if revision else "") or ""
        if text.strip():
            records.append(ReportRecord(report, scoped[report.employee_id], text.strip()))
    records.sort(key=lambda item: ((item.person.department or NO_DEPARTMENT).casefold(), item.person.employee.name.casefold(), item.report.period_date, item.report.report_type))
    return records


# ─── Export ──────────────────────────────────────────────────────────────────

_UNSAFE = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')


def safe_name(value: str | None, fallback: str = "Нэргүй") -> str:
    cleaned = " ".join(_UNSAFE.sub(" ", value or "").split()).strip(" .")
    return cleaned[:80] or fallback


def _period_label(report: WorkReport) -> str:
    return report.period_date.strftime("%Y-%m") if report.report_type in MONTH_PERIOD_TYPES else report.period_date.isoformat()


def report_markdown(record: ReportRecord) -> str:
    report, person = record.report, record.person
    type_label = REPORT_TYPE_LABEL.get(report.report_type, report.report_type)
    lines = [
        f"# {report.title or type_label}",
        "",
        f"- **Ажилтан:** {person.employee.name}",
        f"- **Хэлтэс:** {person.department or NO_DEPARTMENT}",
        f"- **Төрөл:** {type_label}",
        f"- **Хугацаа:** {_period_label(report)}",
        f"- **Төлөв:** {REPORT_STATUS_LABEL.get(report.status, report.status)}",
    ]
    if report.submitted_at:
        lines.append(f"- **Илгээсэн:** {report.submitted_at.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC")
    lines += ["", "---", "", record.text, ""]
    return "\n".join(lines)


def _report_filename(record: ReportRecord) -> str:
    report = record.report
    return f"{_period_label(report)}_{report.report_type}_{report.id}.md"


def _report_path(record: ReportRecord, group_by: GroupBy) -> str:
    worker = safe_name(record.person.employee.name)
    if group_by == "department":
        return f"{safe_name(record.person.department, NO_DEPARTMENT)}/{worker}/{_report_filename(record)}"
    return f"{worker}/{_report_filename(record)}"


def build_export(records: list[ReportRecord], *, group_by: GroupBy, date_from: date, date_to: date) -> tuple[bytes, str, str]:
    """Return ``(content, filename, media_type)``; a single report stays a plain file."""
    if not records:
        raise NoReportsFound()
    if len(records) == 1:
        record = records[0]
        name = f"{safe_name(record.person.employee.name)}_{_report_filename(record)}"
        return report_markdown(record).encode("utf-8"), name, "text/markdown; charset=utf-8"
    root = f"reports_{date_from.isoformat()}_{date_to.isoformat()}"
    buffer = io.BytesIO()
    manifest = io.StringIO()
    writer = csv.writer(manifest)
    writer.writerow(["report_id", "employee", "department", "report_type", "period", "status", "path"])
    used: set[str] = set()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for record in records:
            path = _report_path(record, group_by)
            if path in used:  # identical sanitized worker names
                path = path.replace(".md", f"_{record.person.employee.id}.md")
            used.add(path)
            archive.writestr(f"{root}/{path}", report_markdown(record))
            report = record.report
            writer.writerow([report.id, record.person.employee.name, record.person.department or NO_DEPARTMENT, report.report_type, _period_label(report), report.status, path])
        # UTF-8 BOM so spreadsheet apps read Cyrillic names correctly.
        archive.writestr(f"{root}/manifest.csv", "﻿" + manifest.getvalue())
    return buffer.getvalue(), f"{root}_{group_by}.zip", "application/zip"


def export_preview(records: list[ReportRecord], *, group_by: GroupBy) -> dict:
    groups: dict[str, int] = {}
    for record in records:
        key = (record.person.department or NO_DEPARTMENT) if group_by == "department" else record.person.employee.name
        groups[key] = groups.get(key, 0) + 1
    return {
        "report_count": len(records),
        "format": "zip" if len(records) > 1 else ("md" if records else None),
        "groups": [{"name": name, "count": count} for name, count in sorted(groups.items(), key=lambda pair: pair[0].casefold())],
    }


# ─── KPIs and summaries ──────────────────────────────────────────────────────


def _day_start(value: date) -> datetime:
    return datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc)


async def compute_kpis(db: AsyncSession, organization_id: int, scoped: dict[int, Person], date_from: date, date_to: date) -> dict:
    ids = list(scoped)
    per: dict[int, dict] = {
        employee_id: {"employee": person.employee.name, "department": person.department or NO_DEPARTMENT, "tasks_due": 0, "tasks_completed": 0, "tasks_overdue_open": 0, "worked_minutes": 0, "reports": 0, "reports_submitted": 0}
        for employee_id, person in scoped.items()
    }
    if not ids:
        return {"per_employee": [], "totals": {}}
    start, end = _day_start(date_from), _day_start(date_to) + timedelta(days=1)
    now = datetime.now(timezone.utc)
    task_base = [Task.organization_id == organization_id, Task.is_archived.is_(False), Task.assignee_id.in_(ids)]
    for employee_id, count in (await db.execute(select(Task.assignee_id, func.count()).where(*task_base, Task.deadline_at >= start, Task.deadline_at < end).group_by(Task.assignee_id))).all():
        per[employee_id]["tasks_due"] = int(count)
    for employee_id, count in (await db.execute(select(Task.assignee_id, func.count()).where(*task_base, Task.completed_at >= start, Task.completed_at < end).group_by(Task.assignee_id))).all():
        per[employee_id]["tasks_completed"] = int(count)
    for employee_id, count in (await db.execute(select(Task.assignee_id, func.count()).where(*task_base, Task.deadline_at < min(end, now), Task.workflow_status.notin_(("done", "cancelled", "review"))).group_by(Task.assignee_id))).all():
        per[employee_id]["tasks_overdue_open"] = int(count)
    worked = (await db.execute(
        select(WorkTimeEntry.employee_id, func.coalesce(func.sum(func.extract("epoch", WorkTimeEntry.ended_at - WorkTimeEntry.started_at) / 60), 0))
        .where(WorkTimeEntry.employee_id.in_(ids), WorkTimeEntry.entry_type == "work", WorkTimeEntry.ended_at.isnot(None), WorkTimeEntry.local_work_date >= date_from, WorkTimeEntry.local_work_date <= date_to)
        .group_by(WorkTimeEntry.employee_id)
    )).all()
    for employee_id, minutes in worked:
        per[employee_id]["worked_minutes"] = round(float(minutes or 0))
    report_rows = (await db.execute(
        select(WorkReport.employee_id, WorkReport.status, func.count())
        .where(WorkReport.employee_id.in_(ids), WorkReport.report_type.in_(REPORT_TYPES), WorkReport.period_date >= date_from.replace(day=1), WorkReport.period_date <= date_to)
        .group_by(WorkReport.employee_id, WorkReport.status)
    )).all()
    for employee_id, status, count in report_rows:
        per[employee_id]["reports"] += int(count)
        if status in {"submitted", "approved"}:
            per[employee_id]["reports_submitted"] += int(count)
    rows = sorted(per.values(), key=lambda item: (item["department"].casefold(), item["employee"].casefold()))
    totals = {key: sum(item[key] for item in rows) for key in ("tasks_due", "tasks_completed", "tasks_overdue_open", "worked_minutes", "reports", "reports_submitted")}
    totals["employees"] = len(rows)
    totals["task_completion_rate"] = round(totals["tasks_completed"] * 100 / max(totals["tasks_due"], 1), 1)
    totals["report_submission_rate"] = round(totals["reports_submitted"] * 100 / max(totals["reports"], 1), 1)
    return {"per_employee": rows, "totals": totals}


def _hours(minutes: int) -> str:
    return f"{minutes / 60:.1f}"


def kpi_markdown(kpis: dict, *, max_rows: int = 60) -> str:
    totals = kpis.get("totals") or {}
    if not totals:
        return "KPI өгөгдөл алга."
    lines = [
        f"- Ажилтан: {totals['employees']}",
        f"- Хугацаа нь энэ үед байсан даалгавар: {totals['tasks_due']}, дууссан: {totals['tasks_completed']} ({totals['task_completion_rate']}%), хэтэрсэн нээлттэй: {totals['tasks_overdue_open']}",
        f"- Ажилласан цаг: {_hours(totals['worked_minutes'])}",
        f"- Тайлан: {totals['reports_submitted']}/{totals['reports']} илгээсэн ({totals['report_submission_rate']}%)",
        "",
        "| Ажилтан | Хэлтэс | Даалгавар (хугацаа/дууссан/хэтэрсэн) | Ажилласан цаг | Тайлан (илгээсэн/нийт) |",
        "|---|---|---|---|---|",
    ]
    rows = kpis["per_employee"]
    for row in rows[:max_rows]:
        lines.append(f"| {row['employee']} | {row['department']} | {row['tasks_due']}/{row['tasks_completed']}/{row['tasks_overdue_open']} | {_hours(row['worked_minutes'])} | {row['reports_submitted']}/{row['reports']} |")
    if len(rows) > max_rows:
        lines.append(f"| … өөр {len(rows) - max_rows} ажилтан | | | | |")
    return "\n".join(lines)


def reports_context(records: list[ReportRecord], budget: int = CONTEXT_CHAR_BUDGET) -> tuple[str, int]:
    """Fit report text into a character budget; monthly/plan reports first."""
    if not records:
        return "Энэ хугацаанд тайлан алга.", 0
    ordered = sorted(records, key=lambda item: (item.report.report_type == "daily", -item.report.period_date.toordinal()))
    per_report = max(400, min(4_000, budget // max(len(ordered), 1)))
    parts: list[str] = []
    used = 0
    included = 0
    for record in ordered:
        report, person = record.report, record.person
        text = record.text if len(record.text) <= per_report else f"{record.text[:per_report].rstrip()}…"
        block = f"### {person.employee.name} · {person.department or NO_DEPARTMENT} · {REPORT_TYPE_LABEL.get(report.report_type, report.report_type)} · {_period_label(report)} · {REPORT_STATUS_LABEL.get(report.status, report.status)}\n{text}"
        if used + len(block) > budget:
            break
        parts.append(block)
        used += len(block)
        included += 1
    omitted = len(ordered) - included
    if omitted:
        parts.append(f"(Хэмжээ хэтэрсэн тул {omitted} хуучин/өдрийн тайлан орхигдсон.)")
    return "\n\n".join(parts), included


SUMMARY_INSTRUCTIONS = """Та OYUNS Agent — компанийн удирдлагад (админ, менежер) зориулсан бизнесийн шинжээч.
Дүрэм:
- Зөвхөн доор өгсөн KPI болон ажилтнуудын тайлангийн өгөгдөлд тулгуурла. Гадны мэдээлэл бүү зохио.
- Ашиг, зардал, орлого, ROI зэрэг санхүүгийн тоо тайланд тодорхой бичигдсэн бол л ашигла, эх ажилтнаар нь иш тат. Байхгүй бол "өгөгдөлд байхгүй" гэж шууд хэлээд, ямар өгөгдөл хэрэгтэйг зөвлө. Тооцоолол хийсэн бол томьёог товч харуул.
- Ажилтан, хэлтсийн нэрийг тодорхой дурд. Эрсдэл, саад, анхаарах зүйлийг тусад нь онцол.
- Markdown ашигла: ## гарчиг, товч bullet, шаардлагатай бол хүснэгт. Хэт урт бүү бич.
- Хэрэглэгчийн асуултын хэлээр хариул (Монгол асуултад Монголоор)."""

DEFAULT_SUMMARY_PROMPT = (
    "Энэ хугацааны тайлан ба KPI-г нэгтгэн хураангуй гарга: "
    "1) Гол үр дүн, 2) KPI дүгнэлт (гүйцэтгэл, ачаалал, тайлангийн идэвх), "
    "3) Санхүүгийн дурдагдсан үзүүлэлт (ашиг, зардал, ROI — байгаа бол), "
    "4) Эрсдэл ба саад, 5) Удирдлагын анхаарах зүйл, 6) Дараагийн алхам."
)


def fallback_summary(scope_label: str, date_from: date, date_to: date, kpis: dict, records: list[ReportRecord]) -> str:
    lines = [f"## {scope_label} · {date_from.isoformat()} – {date_to.isoformat()}", "", "_AI түр ашиглах боломжгүй тул өгөгдлийн автомат нэгтгэлийг харуулж байна._", "", "## KPI", kpi_markdown(kpis), "", "## Тайлангийн товч"]
    latest: dict[int, ReportRecord] = {}
    for record in records:
        current = latest.get(record.person.employee.id)
        if not current or (record.report.report_type != "daily", record.report.period_date) > (current.report.report_type != "daily", current.report.period_date):
            latest[record.person.employee.id] = record
    if not latest:
        lines.append("Энэ хугацаанд тайлан алга.")
    for record in sorted(latest.values(), key=lambda item: item.person.employee.name.casefold()):
        compact = " ".join(record.text.split())
        lines.append(f"- **{record.person.employee.name}** ({REPORT_TYPE_LABEL.get(record.report.report_type)}, {_period_label(record.report)}): {compact[:280]}{'…' if len(compact) > 280 else ''}")
    return "\n".join(lines)


async def generate_summary(
    db: AsyncSession,
    organization_id: int,
    *,
    date_from: date,
    date_to: date,
    scope_label: str,
    employee_ids: list[int] | None,
    department_ids: list[int] | None,
    prompt: str | None,
    history: list[dict],
    report_types: tuple[str, ...] | list[str] = REPORT_TYPES,
) -> dict:
    scoped = await people(db, organization_id, employee_ids=employee_ids, department_ids=department_ids)
    records = await collect_reports(db, organization_id, date_from, date_to, employee_ids=list(scoped) or [-1], report_types=report_types)
    kpis = await compute_kpis(db, organization_id, scoped, date_from, date_to)
    context, included = reports_context(records)
    data_block = (
        f"# Өгөгдөл\nХугацаа: {date_from.isoformat()} – {date_to.isoformat()}\nХамрах хүрээ: {scope_label}\n\n"
        f"## KPI\n{kpi_markdown(kpis)}\n\n## Тайлангууд ({included}/{len(records)})\n{context}"
    )
    question = (prompt or "").strip() or DEFAULT_SUMMARY_PROMPT
    input_items = [{"role": "user", "content": data_block}]
    for item in history[-10:]:
        if item.get("role") in {"user", "assistant"} and str(item.get("content") or "").strip():
            input_items.append({"role": item["role"], "content": str(item["content"])[:6_000]})
    input_items.append({"role": "user", "content": question[:2_000]})
    degraded = False
    try:
        answer = await _gateway.generate_text(instructions=SUMMARY_INSTRUCTIONS, input_items=input_items, model_key="terra", max_output_tokens=2_500)
    except GatewayError:
        log.warning("report_insights.summary_fallback", exc_info=True)
        answer = fallback_summary(scope_label, date_from, date_to, kpis, records)
        degraded = True
    return {
        "answer": answer,
        "degraded": degraded,
        "scope_label": scope_label,
        "date_from": date_from,
        "date_to": date_to,
        "report_count": len(records),
        "reports_in_context": included,
        "kpis": kpis["totals"],
    }
