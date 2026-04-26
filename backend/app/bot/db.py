"""Sync DB helpers used only inside bot (runs in separate process)."""
from datetime import date, datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.models import Answer, Employee, ManagerSettings, Question, Schedule, Streak, SurveySession

engine = create_engine(settings.SYNC_DATABASE_URL)


def get_session():
    return Session(engine)


def get_employee_by_tg(tg_id: str) -> Employee | None:
    with get_session() as s:
        return s.execute(select(Employee).where(Employee.telegram_id == tg_id)).scalar_one_or_none()


def get_all_active_employees() -> list[Employee]:
    with get_session() as s:
        return list(s.execute(select(Employee).where(Employee.is_active == True)).scalars())


def get_questions() -> list[Question]:
    with get_session() as s:
        return list(s.execute(select(Question).order_by(Question.sort_order)).scalars())


def get_schedule(employee_id: int) -> Schedule | None:
    with get_session() as s:
        return s.execute(select(Schedule).where(Schedule.employee_id == employee_id)).scalar_one_or_none()


def get_manager_settings() -> ManagerSettings | None:
    with get_session() as s:
        return s.execute(select(ManagerSettings)).scalar_one_or_none()


def get_streak(employee_id: int) -> Streak | None:
    with get_session() as s:
        return s.execute(select(Streak).where(Streak.employee_id == employee_id)).scalar_one_or_none()


def create_session(employee_id: int, session_type: str = "evening") -> SurveySession:
    today = date.today()
    with get_session() as s:
        existing = s.execute(
            select(SurveySession).where(
                SurveySession.employee_id == employee_id,
                SurveySession.date == today,
                SurveySession.type == session_type,
            )
        ).scalar_one_or_none()
        if existing:
            return existing
        sess = SurveySession(
            employee_id=employee_id,
            date=today,
            type=session_type,
            status="pending",
            started_at=datetime.now(timezone.utc),
        )
        s.add(sess)
        s.commit()
        s.refresh(sess)
        return sess


def save_answer(session_id: int, question_id: int, value_text: str | None, value_numeric=None):
    with get_session() as s:
        existing = s.execute(
            select(Answer).where(Answer.session_id == session_id, Answer.question_id == question_id)
        ).scalar_one_or_none()
        if existing:
            existing.value_text = value_text
            existing.value_numeric = value_numeric
        else:
            s.add(Answer(session_id=session_id, question_id=question_id, value_text=value_text, value_numeric=value_numeric))
        s.commit()


def complete_session(session_id: int, status: str = "completed"):
    with get_session() as s:
        sess = s.get(SurveySession, session_id)
        if sess:
            sess.status = status
            sess.completed_at = datetime.now(timezone.utc)
            s.commit()
            _update_streak(s, sess.employee_id)


def _update_streak(s: Session, employee_id: int):
    streak = s.execute(select(Streak).where(Streak.employee_id == employee_id)).scalar_one_or_none()
    if not streak:
        streak = Streak(employee_id=employee_id)
        s.add(streak)
    today = date.today()
    if streak.last_filled_date == today:
        return
    from datetime import timedelta
    if streak.last_filled_date and (today - streak.last_filled_date).days == 1:
        streak.current_streak += 1
    else:
        streak.current_streak = 1
    if streak.current_streak > streak.longest_streak:
        streak.longest_streak = streak.current_streak
    streak.last_filled_date = today
    s.commit()


def mark_session_missed(employee_id: int):
    today = date.today()
    with get_session() as s:
        sess = s.execute(
            select(SurveySession).where(
                SurveySession.employee_id == employee_id,
                SurveySession.date == today,
                SurveySession.status == "pending",
            )
        ).scalar_one_or_none()
        if sess:
            sess.status = "missed"
            s.commit()
        streak = s.execute(select(Streak).where(Streak.employee_id == employee_id)).scalar_one_or_none()
        if streak and streak.last_filled_date != today:
            streak.current_streak = 0
            s.commit()


def mark_employee_onboarded(employee_id: int):
    with get_session() as s:
        emp = s.get(Employee, employee_id)
        if emp:
            emp.onboarded_at = datetime.now(timezone.utc)
            s.commit()


def get_yesterday_summary() -> dict:
    from datetime import timedelta
    yesterday = date.today() - timedelta(days=1)
    with get_session() as s:
        sessions = list(s.execute(
            select(SurveySession).where(SurveySession.date == yesterday)
        ).scalars())
        questions = list(s.execute(select(Question).order_by(Question.sort_order)).scalars())
        q_map = {q.id: q for q in questions}

        totals: dict[str, int] = {}
        missed_names = []
        for sess in sessions:
            if sess.status == "missed":
                emp = s.get(Employee, sess.employee_id)
                if emp:
                    missed_names.append(emp.name)
                continue
            answers = list(s.execute(select(Answer).where(Answer.session_id == sess.id)).scalars())
            for a in answers:
                q = q_map.get(a.question_id)
                if q and a.value_numeric is not None:
                    totals[q.text] = totals.get(q.text, 0) + int(a.value_numeric)

        return {"date": str(yesterday), "totals": totals, "missed": missed_names}
