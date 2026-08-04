"""AI-assisted monthly report digest, delivered once after every active worker submits."""
from __future__ import annotations

import asyncio
import html
import logging
import os
from datetime import date

import aiohttp
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.bot.db import get_manager_settings, get_session
from app.models.models import Employee, MonthlyReportDigest, WorkReport, WorkReportRevision
from app.services.manager_recipients import manager_telegram_ids

log = logging.getLogger(__name__)
OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"


def previous_month(today: date) -> date:
    return date(today.year - int(today.month == 1), 12 if today.month == 1 else today.month - 1, 1)


def _reports_for_period(
    period: date, report_type: str = "monthly"
) -> tuple[list[str], list[tuple[str, str]]]:
    """Return all active names and approved report text for a report type."""
    with get_session() as session:
        workers = session.execute(
            select(Employee).where(Employee.is_active.is_(True)).order_by(Employee.name)
        ).scalars().all()
        approved = session.execute(
            select(Employee.name, WorkReportRevision.text)
            .join(WorkReport, WorkReport.employee_id == Employee.id)
            .join(WorkReportRevision, WorkReportRevision.id == WorkReport.approved_revision_id)
            .where(
                Employee.is_active.is_(True),
                WorkReport.report_type == report_type,
                WorkReport.period_date == period,
                WorkReport.status == "approved",
            )
            .order_by(Employee.name)
        ).all()
    return [worker.name for worker in workers], [(name, text or "") for name, text in approved]


def seed_dummy_monthly_test_reports(period: date) -> int:
    """Create approved dummy reports for the manager-only Telegram test command."""
    with get_session() as session:
        workers = session.execute(
            select(Employee).where(Employee.is_active.is_(True)).order_by(Employee.name)
        ).scalars().all()
        for index, worker in enumerate(workers, start=1):
            report = session.execute(
                select(WorkReport).where(
                    WorkReport.employee_id == worker.id,
                    WorkReport.report_type == "monthly_test",
                    WorkReport.period_date == period,
                )
            ).scalar_one_or_none()
            if report is None:
                report = WorkReport(
                    employee_id=worker.id,
                    report_type="monthly_test",
                    period_date=period,
                )
                session.add(report)
                session.flush()

            revision = WorkReportRevision(
                report_id=report.id,
                status="approved",
                text=(
                    f"{worker.name} нь {period.year} оны {period.month:02d}-р сард "
                    f"тестийн {index}-р ажлын үр дүнг амжилттай гүйцэтгэсэн. "
                    "Дараагийн сард гүйцэтгэлийг сайжруулах нэг арга хэмжээг төлөвлөсөн."
                ),
            )
            session.add(revision)
            session.flush()
            report.status = "approved"
            report.approved_revision_id = revision.id
        session.commit()
    return len(workers)


async def _ai_summary(reports: list[tuple[str, str]]) -> str | None:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None
    report_text = "\n\n".join(
        f"[{name}]\n{text[:6000]}" for name, text in reports
    )
    payload = {
        "model": os.getenv("OPENAI_MONTHLY_DIGEST_MODEL", "").strip() or os.getenv("OPENAI_ASSISTANT_MODEL", "gpt-5-mini"),
        "messages": [
            {"role": "system", "content": "Та Монгол хэлээр удирдлагад зориулсан сар тутмын ажлын тайлангийн хураангуй бичнэ. Товч, баримтад тулгуурласан байдлаар: гол үр дүн, эрсдэл/саад, дараагийн сарын анхаарах зүйлсийг жагсаа. Тайлангаас гадуурх зүйл бүү зохиогоорой. HTML бүү ашигла."},
            {"role": "user", "content": f"Дараах ажилтнуудын батлагдсан тайланг нэгтгэ:\n\n{report_text}"},
        ],
        "temperature": 0.2,
        "max_tokens": 650,
    }
    try:
        timeout = aiohttp.ClientTimeout(total=45)
        async with aiohttp.ClientSession(timeout=timeout) as client:
            async with client.post(OPENAI_CHAT_URL, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, json=payload) as response:
                if response.status != 200:
                    log.warning("monthly digest AI returned %s: %s", response.status, (await response.text())[:300])
                    return None
                data = await response.json()
        return (data.get("choices") or [{}])[0].get("message", {}).get("content", "").strip() or None
    except Exception:
        log.exception("monthly digest AI request failed")
        return None


def _fallback_summary(reports: list[tuple[str, str]]) -> str:
    lines = []
    for name, text in reports:
        compact = " ".join(text.split())
        lines.append(f"• {name}: {compact[:280]}{'…' if len(compact) > 280 else ''}")
    return "\n".join(lines)


def _reserve(period: date) -> bool:
    """Claim the period before sending so concurrent scheduler runs cannot duplicate it."""
    with get_session() as session:
        session.add(MonthlyReportDigest(period_date=period))
        try:
            session.commit()
            return True
        except IntegrityError:
            session.rollback()
            return False


async def try_send_monthly_report_digest(
    today: date | None = None,
    *,
    report_type: str = "monthly",
    reserve: bool = True,
    recipients: list[str] | None = None,
    test_mode: bool = False,
) -> bool:
    """Send a digest once all active workers have approved the period's reports."""
    period = previous_month(today or date.today())
    worker_names, reports = _reports_for_period(period, report_type)
    if not worker_names or len(reports) != len(worker_names):
        return False
    if recipients is None:
        recipients = manager_telegram_ids(get_manager_settings())
    if not recipients or (reserve and not _reserve(period)):
        return False

    analysis = await _ai_summary(reports) or _fallback_summary(reports)
    submitted_names = ", ".join(html.escape(name) for name, _ in reports)
    message = (
        f"{'🧪 ТЕСТ — ' if test_mode else ''}📅 <b>{period.year} оны {period.month:02d}-р сарын AI хураангуй</b>\n\n"
        f"✅ Тайлан баталсан: <b>{len(reports)}/{len(worker_names)}</b> ажилтан\n"
        f"👥 Илгээсэн: {submitted_names}\n\n"
        f"<b>Нэгтгэл</b>\n{html.escape(analysis)}"
    )
    # Telegram permits at most 4096 characters per message. Keep the useful
    # deterministic completion information even for unusually large reports.
    if len(message) > 4000:
        message = f"{message[:3999]}…"

    from app.bot.scheduler import _make_bot
    bot = _make_bot()
    try:
        results = await asyncio.gather(*(bot.send_message(recipient, message) for recipient in recipients), return_exceptions=True)
        for recipient, result in zip(recipients, results):
            if isinstance(result, Exception):
                log.exception("monthly digest send failed for recipient=%s", recipient, exc_info=result)
    finally:
        await bot.session.close()
    return True
