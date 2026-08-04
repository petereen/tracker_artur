from datetime import date, timedelta
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import Answer, Employee, Question, SurveySession, Streak, WorkReport

router = APIRouter()


@router.get("/summary")
async def dashboard_summary(period: int = Query(30), db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    since = date.today() - timedelta(days=period)

    sessions_q = await db.execute(
        select(SurveySession).where(SurveySession.date >= since)
    )
    sessions = sessions_q.scalars().all()

    total = len(sessions)
    completed = sum(1 for s in sessions if s.status in ("completed", "partial"))
    fill_rate = round(completed / total * 100) if total else 0

    calls_q = await db.execute(
        select(func.sum(Answer.value_numeric))
        .join(SurveySession, Answer.session_id == SurveySession.id)
        .join(Question, Answer.question_id == Question.id)
        .where(SurveySession.date >= since, Question.sort_order == 0)
    )
    meetings_q = await db.execute(
        select(func.sum(Answer.value_numeric))
        .join(SurveySession, Answer.session_id == SurveySession.id)
        .join(Question, Answer.question_id == Question.id)
        .where(SurveySession.date >= since, Question.sort_order == 1)
    )
    emails_q = await db.execute(
        select(func.sum(Answer.value_numeric))
        .join(SurveySession, Answer.session_id == SurveySession.id)
        .join(Question, Answer.question_id == Question.id)
        .where(SurveySession.date >= since, Question.sort_order == 3)
    )

    return {
        "calls": int(calls_q.scalar() or 0),
        "meetings": int(meetings_q.scalar() or 0),
        "emails": int(emails_q.scalar() or 0),
        "fill_rate": fill_rate,
        "period": period,
    }


@router.get("/metrics")
async def dashboard_metrics(
    metric: str = Query("calls"),
    period: int = Query(30),
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    since = date.today() - timedelta(days=period)
    metric_order = {"calls": 0, "meetings": 1, "emails": 3, "zoom": 2}
    sort_order = metric_order.get(metric, 0)

    result = await db.execute(
        select(SurveySession.date, func.sum(Answer.value_numeric).label("value"))
        .join(Answer, Answer.session_id == SurveySession.id)
        .join(Question, Answer.question_id == Question.id)
        .where(SurveySession.date >= since, Question.sort_order == sort_order)
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
async def work_performance(period: int = Query(30), db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    since = date.today() - timedelta(days=period - 1)
    active_count = (await db.execute(select(func.count()).where(Employee.is_active == True))).scalar() or 0
    daily = (await db.execute(
        select(WorkReport).where(WorkReport.report_type == "daily", WorkReport.period_date >= since)
    )).scalars().all()
    approved_daily = [r for r in daily if r.status == "approved"]
    expected_daily = active_count * period
    month_start = date.today().replace(day=1)
    monthly_approved = (await db.execute(
        select(func.count()).where(
            WorkReport.report_type == "monthly",
            WorkReport.period_date == month_start,
            WorkReport.status == "approved",
        )
    )).scalar() or 0
    return {
        "period": period,
        "daily_report_rate": round(len(approved_daily) / expected_daily * 100) if expected_daily else 0,
        "approved_daily_reports": len(approved_daily),
        "work_time_entries": sum(1 for r in daily if r.started_at is not None or r.ended_at is not None),
        "monthly_report_rate": round(monthly_approved / active_count * 100) if active_count else 0,
        "approved_monthly_reports": monthly_approved,
    }
