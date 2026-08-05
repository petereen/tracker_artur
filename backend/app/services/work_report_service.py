"""Persistent work-report lifecycle used by the Telegram bot scheduler and handlers."""
from __future__ import annotations

import calendar
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.bot.db import get_session
from app.models.models import WorkReport, WorkReportPrompt, WorkReportRevision, WorkTimeEntry


TEST_REPORT_TYPES = frozenset({"daily_test", "monthly_test", "next_month_plan_test"})
WORK_TIME_MODES = frozenset({"in_person", "remote"})


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


def _active_time_entry(s, report_id: int, mode: str | None = None) -> WorkTimeEntry | None:
    query = select(WorkTimeEntry).where(
        WorkTimeEntry.report_id == report_id,
        WorkTimeEntry.ended_at.is_(None),
    )
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
        active = _active_time_entry(s, report.id)
        if active:
            return ("already_active" if active.mode == mode else "other_active", active)
        entry = WorkTimeEntry(report_id=report.id, mode=mode, started_at=started_at)
        s.add(entry)
        s.commit()
        s.refresh(entry)
        s.expunge(entry)
        return "started", entry


def end_work_time(
    employee_id: int, local_day: date, mode: str, at: datetime | None = None
) -> tuple[str, WorkTimeEntry | None]:
    """End only the requested mode; reject a mismatched open mode."""
    if mode not in WORK_TIME_MODES:
        raise ValueError("invalid work-time mode")
    report = get_or_create_report(employee_id, "daily", local_day)
    ended_at = at or datetime.now(timezone.utc)
    with get_session() as s:
        active = _active_time_entry(s, report.id)
        if not active:
            return "not_started", None
        if active.mode != mode:
            return "other_active", active
        active.ended_at = ended_at
        s.commit()
        s.refresh(active)
        s.expunge(active)
        return "ended", active


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


def summarize_work_time(entries: list[WorkTimeEntry], now: datetime | None = None) -> dict:
    """Return total, mode totals, and detailed intervals in minutes."""
    current = now or datetime.now(timezone.utc)
    totals = {"remote": 0, "in_person": 0}
    details = []
    complete_entries = 0
    for entry in entries:
        end = entry.ended_at or current
        seconds = max(0, (end - entry.started_at).total_seconds())
        minutes = round(seconds / 60)
        totals[entry.mode] = totals.get(entry.mode, 0) + minutes
        if entry.ended_at is not None:
            complete_entries += 1
        details.append({
            "id": entry.id,
            "mode": entry.mode,
            "started_at": entry.started_at,
            "ended_at": entry.ended_at,
            "minutes": minutes,
            "open": entry.ended_at is None,
        })
    return {
        "total_minutes": totals["remote"] + totals["in_person"],
        "remote_minutes": totals["remote"],
        "in_person_minutes": totals["in_person"],
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
