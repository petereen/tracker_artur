from datetime import date, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import Answer, Employee, Question, SurveySession, Streak, WorkReport

router = APIRouter()


def _date_range(period: int, date_from: Optional[date], date_to: Optional[date], all_time: bool):
    """Resolve dashboard date controls into an optional inclusive range."""
    if all_time:
        return None, date_to
    return date_from or (date.today() - timedelta(days=period - 1)), date_to or date.today()


@router.get("/summary")
async def dashboard_summary(
    period: int = Query(30, ge=1), date_from: Optional[date] = None, date_to: Optional[date] = None,
    all_time: bool = False, db: AsyncSession = Depends(get_db), _=Depends(get_current_user),
):
    since, until = _date_range(period, date_from, date_to, all_time)
    session_range = ([SurveySession.date >= since] if since else []) + ([SurveySession.date <= until] if until else [])

    sessions_q = await db.execute(
        select(SurveySession).where(*session_range)
    )
    sessions = sessions_q.scalars().all()

    total = len(sessions)
    completed = sum(1 for s in sessions if s.status in ("completed", "partial"))
    fill_rate = round(completed / total * 100) if total else 0

    calls_q = await db.execute(
        select(func.sum(Answer.value_numeric))
        .join(SurveySession, Answer.session_id == SurveySession.id)
        .join(Question, Answer.question_id == Question.id)
        .where(*session_range, Question.sort_order == 0)
    )
    meetings_q = await db.execute(
        select(func.sum(Answer.value_numeric))
        .join(SurveySession, Answer.session_id == SurveySession.id)
        .join(Question, Answer.question_id == Question.id)
        .where(*session_range, Question.sort_order == 1)
    )
    emails_q = await db.execute(
        select(func.sum(Answer.value_numeric))
        .join(SurveySession, Answer.session_id == SurveySession.id)
        .join(Question, Answer.question_id == Question.id)
        .where(*session_range, Question.sort_order == 3)
    )

    return {
        "calls": int(calls_q.scalar() or 0),
        "meetings": int(meetings_q.scalar() or 0),
        "emails": int(emails_q.scalar() or 0),
        "fill_rate": fill_rate,
        "date_from": str(since) if since else None,
        "date_to": str(until) if until else None,
    }


@router.get("/metrics")
async def dashboard_metrics(
    metric: str = Query("calls"),
    period: int = Query(30, ge=1),
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    all_time: bool = False,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    since, until = _date_range(period, date_from, date_to, all_time)
    session_range = ([SurveySession.date >= since] if since else []) + ([SurveySession.date <= until] if until else [])
    metric_order = {"calls": 0, "meetings": 1, "emails": 3, "zoom": 2}
    sort_order = metric_order.get(metric, 0)

    result = await db.execute(
        select(SurveySession.date, func.sum(Answer.value_numeric).label("value"))
        .join(Answer, Answer.session_id == SurveySession.id)
        .join(Question, Answer.question_id == Question.id)
        .where(*session_range, Question.sort_order == sort_order)
        .group_by(SurveySession.date)
        .order_by(SurveySession.date)
    )
    rows = result.all()
    return [{"date": str(r.date), "value": int(r.value or 0)} for r in rows]


@router.get("/top-employees")
async def top_employees(db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    result = await db.execute(
        select(Employee, Streak)
        .outerjoin(Streak, Streak.employee_id == Employee.id)
        .where(Employee.is_active == True)
        .order_by(Streak.current_streak.desc().nullslast())
        .limit(5)
    )
    rows = result.all()
    return [
        {
            "id": emp.id,
            "name": emp.name,
            "telegram_username": emp.telegram_username,
            "current_streak": streak.current_streak if streak else 0,
            "longest_streak": streak.longest_streak if streak else 0,
        }
        for emp, streak in rows
    ]


@router.get("/work-performance")
async def work_performance(
    period: int = Query(30, ge=1), date_from: Optional[date] = None, date_to: Optional[date] = None,
    all_time: bool = False, db: AsyncSession = Depends(get_db), _=Depends(get_current_user),
):
    since, until = _date_range(period, date_from, date_to, all_time)
    active_count = (await db.execute(select(func.count()).where(Employee.is_active == True))).scalar() or 0
    daily = (await db.execute(
        select(WorkReport).where(
            WorkReport.report_type == "daily",
            *([WorkReport.period_date >= since] if since else []),
            *([WorkReport.period_date <= until] if until else []),
        )
    )).scalars().all()
    approved_daily = [r for r in daily if r.status == "approved"]
    effective_days = period if since else ((date.today() - min((r.period_date for r in daily), default=date.today())).days + 1)
    expected_daily = active_count * effective_days
    monthly_approved = (await db.execute(
        select(func.count()).where(
            WorkReport.report_type == "monthly",
            WorkReport.status == "approved",
            *([WorkReport.period_date >= since] if since else []),
            *([WorkReport.period_date <= until] if until else []),
        )
    )).scalar() or 0
    monthly_start = since or (await db.execute(
        select(func.min(WorkReport.period_date)).where(WorkReport.report_type == "monthly")
    )).scalar() or date.today()
    monthly_end = until or date.today()
    expected_months = max(1, (monthly_end.year - monthly_start.year) * 12 + monthly_end.month - monthly_start.month + 1)
    return {
        "date_from": str(since) if since else None,
        "date_to": str(until) if until else None,
        "daily_report_rate": round(len(approved_daily) / expected_daily * 100) if expected_daily else 0,
        "approved_daily_reports": len(approved_daily),
        "work_time_entries": sum(1 for r in daily if r.started_at is not None or r.ended_at is not None),
        "monthly_report_rate": round(monthly_approved / (active_count * expected_months) * 100) if active_count else 0,
        "approved_monthly_reports": monthly_approved,
    }
