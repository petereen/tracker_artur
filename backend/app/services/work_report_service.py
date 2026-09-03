"""Persistent work-report lifecycle used by the Telegram bot scheduler and handlers."""
from __future__ import annotations

import calendar
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.bot.db import get_session
from app.models.models import AttendanceLog, Employee, PlanIdea, UserAccount, WorkReport, WorkReportPrompt, WorkReportRevision, WorkTimeEntry
from app.services.attendance_service import apply_worktime_attendance


TEST_REPORT_TYPES = frozenset({"daily_test", "monthly_test", "next_month_plan_test"})
WORK_TIME_MODES = frozenset({"in_person", "remote"})


def _sync_worktime_attendance(s, employee: Employee, local_day: date, at: datetime) -> None:
    entries = s.execute(
        select(WorkTimeEntry)
        .where(
            WorkTimeEntry.employee_id == employee.id,
            WorkTimeEntry.local_work_date == local_day,
        )
        .order_by(WorkTimeEntry.started_at, WorkTimeEntry.id)
    ).scalars().all()
    log = s.execute(
        select(AttendanceLog)
        .where(
            AttendanceLog.organization_id == employee.organization_id,
            AttendanceLog.employee_id == employee.id,
            AttendanceLog.attendance_date == local_day,
        )
        .with_for_update()
    ).scalar_one_or_none()
    updated = apply_worktime_attendance(log, employee, local_day, entries, at=at)
    if log is None and updated is not None:
        s.add(updated)


def month_period(day: date) -> date:
    return day.replace(day=1)


def is_last_three_days(day: date) -> bool:
    return day.day >= calendar.monthrange(day.year, day.month)[1] - 2


def period_for(report_type: str, local_day: date) -> date:
    if report_type in {"daily", "daily_test"}:
        return local_day
    period = month_period(local_day)
    if report_type in {"next_month_plan", "next_month_plan_test"}:
        return date(period.year + int(period.month == 12), 1 if period.month == 12 else period.month + 1, 1)
    return period


def get_or_create_report(employee_id: int, report_type: str, local_day: date) -> WorkReport:
    period_date = period_for(report_type, local_day)
    with get_session() as s:
        report = s.execute(
            select(WorkReport).where(
                WorkReport.employee_id == employee_id,
                WorkReport.report_type == report_type,
                WorkReport.period_date == period_date,
            )
        ).scalar_one_or_none()
        if report is None:
            report = WorkReport(
                employee_id=employee_id,
                report_type=report_type,
                period_date=period_date,
                status="awaiting",
            )
            s.add(report)
            try:
                s.commit()
            except IntegrityError:
                s.rollback()
                report = s.execute(
                    select(WorkReport).where(
                        WorkReport.employee_id == employee_id,
                        WorkReport.report_type == report_type,
                        WorkReport.period_date == period_date,
                    )
                ).scalar_one()
            s.refresh(report)
        s.expunge(report)
        return report


def reset_test_reports(report_types: frozenset[str] = TEST_REPORT_TYPES) -> int:
    """Remove all isolated test runs and their prompts/revisions.

    Deleting through the ORM keeps the relationship cascades effective on
    databases where foreign-key cascades are not enabled by the driver.
    Returns the number of test report lifecycles removed.
    """
    with get_session() as s:
        reports = s.execute(
            select(WorkReport).where(WorkReport.report_type.in_(report_types))
        ).scalars().all()
        for report in reports:
            s.delete(report)
        s.commit()
        return len(reports)


def get_report(report_id: int) -> WorkReport | None:
    with get_session() as s:
        report = s.get(WorkReport, report_id)
        if report:
            s.expunge(report)
        return report


def reserve_prompt(
    report_id: int, *, prompt_type: str, prompt_date: date, telegram_chat_id: str
) -> WorkReportPrompt | None:
    """Reserve one prompt per report/type/day before a Telegram send.

    The unique constraint makes retries and scheduler restarts harmless.
    """
    with get_session() as s:
        existing = s.execute(
            select(WorkReportPrompt).where(
                WorkReportPrompt.report_id == report_id,
                WorkReportPrompt.prompt_type == prompt_type,
                WorkReportPrompt.prompt_date == prompt_date,
            )
        ).scalar_one_or_none()
        if existing:
            return None
        prompt = WorkReportPrompt(
            report_id=report_id,
            prompt_type=prompt_type,
            prompt_date=prompt_date,
            telegram_chat_id=str(telegram_chat_id),
        )
        s.add(prompt)
        try:
            s.commit()
        except IntegrityError:
            s.rollback()
            return None
        s.refresh(prompt)
        s.expunge(prompt)
        return prompt


def release_reserved_prompt(prompt_id: int) -> None:
    with get_session() as s:
        prompt = s.get(WorkReportPrompt, prompt_id)
        if prompt and prompt.telegram_message_id is None:
            s.delete(prompt)
            s.commit()


def set_prompt_message_id(prompt_id: int, message_id: int) -> None:
    with get_session() as s:
        prompt = s.get(WorkReportPrompt, prompt_id)
        if prompt:
            prompt.telegram_message_id = message_id
            s.commit()


def report_for_reply(employee_id: int, telegram_chat_id: str, message_id: int) -> WorkReport | None:
    with get_session() as s:
        prompt = s.execute(
            select(WorkReportPrompt).where(
                WorkReportPrompt.telegram_chat_id == str(telegram_chat_id),
                WorkReportPrompt.telegram_message_id == message_id,
                WorkReportPrompt.prompt_type.in_({
                    "daily_report", "test_daily_report",
                    "monthly_report", "test_monthly_report",
                    "next_month_plan", "test_next_month_plan",
                }),
            )
        ).scalar_one_or_none()
        if not prompt:
            return None
        report = s.get(WorkReport, prompt.report_id)
        if not report or report.employee_id != employee_id or report.status == "approved":
            return None
        s.expunge(report)
        return report


def awaiting_report_for_message(employee_id: int, telegram_chat_id: str) -> WorkReport | None:
    """Return one unambiguous report that can accept a non-reply text.

    Reply matching remains the normal path. This fallback prevents the general
    assistant from consuming a worker's report when Telegram's reply context
    is absent, but deliberately refuses to guess when more than one report is
    awaiting text.
    """
    report_prompt_types = {
        "daily_report", "test_daily_report",
        "monthly_report", "test_monthly_report",
        "next_month_plan", "test_next_month_plan",
    }
    with get_session() as s:
        # Test flows are explicitly started and strictly sequential. They do
        # not need Telegram reply metadata, and must win over the assistant.
        active_test_reports = s.execute(
            select(WorkReport)
            .where(
                WorkReport.employee_id == employee_id,
                WorkReport.status == "awaiting",
                WorkReport.report_type.in_(TEST_REPORT_TYPES),
            )
            .order_by(WorkReport.updated_at.desc(), WorkReport.id.desc())
        ).scalars().all()
        if len(active_test_reports) == 1:
            s.expunge(active_test_reports[0])
            return active_test_reports[0]
        if len(active_test_reports) > 1:
            return None

        reports = s.execute(
            select(WorkReport)
            .join(WorkReportPrompt, WorkReportPrompt.report_id == WorkReport.id)
            .where(
                WorkReport.employee_id == employee_id,
                WorkReport.status == "awaiting",
                WorkReportPrompt.telegram_chat_id == str(telegram_chat_id),
                WorkReportPrompt.prompt_type.in_(report_prompt_types),
            )
            .distinct()
        ).scalars().all()
        if len(reports) == 1:
            chosen = reports[0]
        else:
            # A deliberately started test flow is the one safe exception to
            # the ambiguity rule: it should remain usable even if a normal
            # production report is also awaiting text.
            test_reports = [report for report in reports if report.report_type in TEST_REPORT_TYPES]
            if len(test_reports) != 1:
                return None
            chosen = test_reports[0]
        s.expunge(chosen)
        return chosen


def awaiting_report_for_employee_type(employee_id: int, report_type: str) -> WorkReport | None:
    """Get the most recent awaiting report of one explicit type.

    Sequential test states call this instead of inferring intent from all
    outstanding test records.
    """
    with get_session() as s:
        report = s.execute(
            select(WorkReport)
            .where(
                WorkReport.employee_id == employee_id,
                WorkReport.report_type == report_type,
                WorkReport.status == "awaiting",
            )
            .order_by(WorkReport.period_date.desc(), WorkReport.id.desc())
        ).scalars().first()
        if report:
            s.expunge(report)
        return report


def _current_draft(s, report_id: int) -> WorkReportRevision | None:
    return s.execute(
        select(WorkReportRevision)
        .where(WorkReportRevision.report_id == report_id, WorkReportRevision.status == "draft")
        .order_by(WorkReportRevision.id.desc())
    ).scalars().first()


def add_draft(report_id: int, text: str) -> WorkReportRevision | None:
    text = text.strip()
    if not text:
        return None
    with get_session() as s:
        report = s.get(WorkReport, report_id)
        if not report or report.status == "approved":
            return None
        old = _current_draft(s, report_id)
        if old:
            old.status = "superseded"
        revision = WorkReportRevision(report_id=report_id, text=text[:10_000], status="draft")
        s.add(revision)
        report.status = "draft"
        s.commit()
        s.refresh(revision)
        s.expunge(revision)
        return revision


def begin_edit(report_id: int) -> bool:
    with get_session() as s:
        report = s.get(WorkReport, report_id)
        if not report or report.status != "draft" or not _current_draft(s, report_id):
            return False
        report.status = "editing"
        s.commit()
        return True


def editing_report_for_employee(employee_id: int) -> WorkReport | None:
    with get_session() as s:
        report = s.execute(
            select(WorkReport)
            .where(WorkReport.employee_id == employee_id, WorkReport.status == "editing")
            .order_by(WorkReport.updated_at.desc(), WorkReport.id.desc())
        ).scalars().first()
        if report:
            s.expunge(report)
        return report


def delete_draft(report_id: int) -> bool:
    with get_session() as s:
        report = s.get(WorkReport, report_id)
        if not report or report.status not in {"draft", "editing"}:
            return False
        revision = _current_draft(s, report_id)
        if not revision:
            return False
        revision.status = "deleted"
        report.status = "awaiting"
        s.commit()
        return True


def approve_draft(report_id: int) -> WorkReport | None:
    with get_session() as s:
        report = s.get(WorkReport, report_id)
        if not report or report.status != "draft":
            return None
        revision = _current_draft(s, report_id)
        if not revision:
            return None
        revision.status = "approved"
        report.status = "approved"
        report.approved_revision_id = revision.id
        s.commit()
        s.refresh(report)
        s.expunge(report)
        return report


def plan_idea_fields(text: str) -> tuple[str, str | None] | None:
    lines = [line.strip() for line in text.strip().splitlines()]
    first_index = next((index for index, line in enumerate(lines) if line), None)
    if first_index is None:
        return None
    return lines[first_index][:1000], "\n".join(lines[first_index + 1:]).strip() or None


def create_plan_idea_from_report(report_id: int) -> PlanIdea | None:
    """Mirror an approved Telegram next-month plan into the web Plans inbox once."""
    with get_session() as s:
        report = s.get(WorkReport, report_id)
        if not report or report.report_type != "next_month_plan" or report.status != "approved":
            return None
        existing = s.execute(select(PlanIdea).where(PlanIdea.source_report_id == report.id)).scalar_one_or_none()
        if existing:
            s.expunge(existing)
            return existing
        revision = s.get(WorkReportRevision, report.approved_revision_id) if report.approved_revision_id else None
        text = (revision.text if revision else "").strip()
        if not text:
            return None
        account = s.get(UserAccount, report.submitted_by_account_id) if report.submitted_by_account_id else None
        if not account:
            account = s.execute(
                select(UserAccount).where(UserAccount.employee_id == report.employee_id, UserAccount.status == "active").order_by(UserAccount.id)
            ).scalars().first()
        if not account or not account.organization_id:
            return None
        fields = plan_idea_fields(text)
        if not fields:
            return None
        title, content = fields
        idea = PlanIdea(
            organization_id=account.organization_id,
            submitted_by_account_id=account.id,
            submitted_by_employee_id=report.employee_id,
            source_report_id=report.id,
            plan_month=report.period_date,
            title=title,
            content=content,
        )
        s.add(idea)
        try:
            s.commit()
        except IntegrityError:
            s.rollback()
            idea = s.execute(select(PlanIdea).where(PlanIdea.source_report_id == report.id)).scalar_one_or_none()
            if not idea:
                return None
        s.refresh(idea)
        s.expunge(idea)
        return idea


def set_work_time(report_id: int, field: str, at: datetime | None = None) -> datetime | None:
    """Set a selected daily start/end timestamp only once and return it."""
    if field not in {"started_at", "ended_at"}:
        raise ValueError("invalid work-time field")
    with get_session() as s:
        report = s.get(WorkReport, report_id)
        if not report or report.report_type not in {"daily", "daily_test"}:
            return None
        current = getattr(report, field)
        if current is None:
            current = at or datetime.now(timezone.utc)
            setattr(report, field, current)
            s.commit()
        return current


def _active_time_entry(
    s, report_id: int | None = None, mode: str | None = None, employee_id: int | None = None
) -> WorkTimeEntry | None:
    query = select(WorkTimeEntry).where(WorkTimeEntry.ended_at.is_(None))
    if employee_id is not None:
        query = query.where(WorkTimeEntry.employee_id == employee_id)
    elif report_id is not None:
        query = query.where(WorkTimeEntry.report_id == report_id)
    if mode:
        query = query.where(WorkTimeEntry.mode == mode)
    return s.execute(query.order_by(WorkTimeEntry.started_at.desc(), WorkTimeEntry.id.desc())).scalars().first()


def start_work_time(
    employee_id: int, local_day: date, mode: str, at: datetime | None = None
) -> tuple[str, WorkTimeEntry | None]:
    """Start a mode only when no other mode is currently open.

    Returns ``started``, ``already_active`` or ``other_active`` so Telegram
    can tell the worker which matching end command is required.
    """
    if mode not in WORK_TIME_MODES:
        raise ValueError("invalid work-time mode")
    report = get_or_create_report(employee_id, "daily", local_day)
    started_at = at or datetime.now(timezone.utc)
    with get_session() as s:
        active = _active_time_entry(s, report.id, employee_id=employee_id)
        employee = s.get(Employee, employee_id)
        if active and active.entry_type == "work":
            _sync_worktime_attendance(s, employee, local_day, started_at)
            s.commit()
            return ("already_active" if active.mode == mode else "other_active", active)
        if active and active.entry_type == "break":
            active.ended_at = started_at
            s.flush()
        entry = WorkTimeEntry(
            report_id=report.id,
            employee_id=employee_id,
            local_work_date=local_day,
            timezone=(employee.timezone if employee else "Asia/Ulaanbaatar"),
            entry_type="work",
            source_channel="telegram",
            mode=mode,
            started_at=started_at,
        )
        s.add(entry)
        s.flush()
        _sync_worktime_attendance(s, employee, local_day, started_at)
        s.commit()
        s.refresh(entry)
        s.expunge(entry)
        return "started", entry


def end_work_time(
    employee_id: int, local_day: date, mode: str, at: datetime | None = None
) -> tuple[str, WorkTimeEntry | None]:
    """End the current day even when the worker is paused."""
    if mode not in WORK_TIME_MODES:
        raise ValueError("invalid work-time mode")
    report = get_or_create_report(employee_id, "daily", local_day)
    ended_at = at or datetime.now(timezone.utc)
    with get_session() as s:
        active = _active_time_entry(s, report.id, employee_id=employee_id)
        if not active:
            return "not_started", None
        active.ended_at = ended_at
        employee = s.get(Employee, employee_id)
        _sync_worktime_attendance(s, employee, local_day, ended_at)
        s.commit()
        s.refresh(active)
        s.expunge(active)
        return "ended", active


def pause_work_time(employee_id: int, local_day: date, at: datetime | None = None) -> tuple[str, WorkTimeEntry | None]:
    report = get_or_create_report(employee_id, "daily", local_day)
    paused_at = at or datetime.now(timezone.utc)
    with get_session() as s:
        active = _active_time_entry(s, report.id, employee_id=employee_id)
        if not active:
            return "not_started", None
        if active.entry_type == "break":
            s.expunge(active)
            return "already_paused", active
        active.ended_at = paused_at
        employee = s.get(Employee, employee_id)
        pause = WorkTimeEntry(report_id=report.id, employee_id=employee_id, local_work_date=local_day, timezone=employee.timezone if employee else "Asia/Ulaanbaatar", entry_type="break", mode=None, started_at=paused_at, source_channel="telegram")
        s.add(pause)
        s.flush()
        _sync_worktime_attendance(s, employee, local_day, paused_at)
        s.commit()
        s.refresh(pause)
        s.expunge(pause)
        return "paused", pause


def work_time_entries(report_id: int) -> list[WorkTimeEntry]:
    with get_session() as s:
        entries = s.execute(
            select(WorkTimeEntry)
            .where(WorkTimeEntry.report_id == report_id)
            .order_by(WorkTimeEntry.started_at, WorkTimeEntry.id)
        ).scalars().all()
        for entry in entries:
            s.expunge(entry)
        return entries


def work_time_status(employee_id: int, local_day: date) -> dict[str, str | bool | None]:
    """Return whether a worker has started work and whether an interval is open."""
    with get_session() as s:
        entries = s.execute(
            select(WorkTimeEntry)
            .where(
                WorkTimeEntry.employee_id == employee_id,
                WorkTimeEntry.local_work_date == local_day,
            )
            .order_by(WorkTimeEntry.started_at.desc(), WorkTimeEntry.id.desc())
        ).scalars().all()
        active = next((entry for entry in entries if entry.ended_at is None), None)
        return {
            "started": bool(entries),
            "active": active is not None,
            "mode": active.mode if active and active.entry_type == "work" else "break" if active else None,
        }


def summarize_work_time(entries: list[WorkTimeEntry], now: datetime | None = None) -> dict:
    """Return total, mode totals, and detailed intervals in minutes."""
    current = now or datetime.now(timezone.utc)
    totals = {"remote": 0, "in_person": 0, "break": 0}
    details = []
    complete_entries = 0
    for entry in entries:
        end = entry.ended_at or current
        seconds = max(0, (end - entry.started_at).total_seconds())
        minutes = round(seconds / 60)
        entry_type = getattr(entry, "entry_type", "work") or "work"
        if entry_type == "break":
            totals["break"] += minutes
        elif entry.mode in {"remote", "in_person"}:
            totals[entry.mode] += minutes
        if entry.ended_at is not None:
            complete_entries += 1
        details.append({
            "id": entry.id,
            "mode": entry.mode,
            "entry_type": entry_type,
            "started_at": entry.started_at,
            "ended_at": entry.ended_at,
            "minutes": minutes,
            "open": entry.ended_at is None,
        })
    return {
        "total_minutes": totals["remote"] + totals["in_person"],
        "remote_minutes": totals["remote"],
        "in_person_minutes": totals["in_person"],
        "break_minutes": totals["break"],
        "complete_entries": complete_entries,
        "incomplete_entries": len(entries) - complete_entries,
        "entries": details,
    }


def report_is_approved(employee_id: int, report_type: str, local_day: date) -> bool:
    with get_session() as s:
        return bool(s.execute(
            select(WorkReport.id).where(
                WorkReport.employee_id == employee_id,
                WorkReport.report_type == report_type,
                WorkReport.period_date == period_for(report_type, local_day),
                WorkReport.status == "approved",
            )
        ).scalar_one_or_none())


def report_needs_submission(employee_id: int, report_type: str, local_day: date) -> bool:
    """Return whether the owner still needs to submit this reporting period.

    Scheduler-created awaiting rows and saved drafts remain actionable. Only a
    formal submission (or its approved successor) suppresses reminders.
    """
    with get_session() as s:
        report = s.execute(
            select(WorkReport.status).where(
                WorkReport.employee_id == employee_id,
                WorkReport.report_type == report_type,
                WorkReport.period_date == period_for(report_type, local_day),
            )
        ).scalar_one_or_none()
        return report not in {"submitted", "approved"}
