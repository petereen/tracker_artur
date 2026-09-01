"""Sync DB helpers used only inside bot (runs in separate process)."""
from datetime import date, datetime, timezone
import hashlib
import secrets

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_account_password
from app.models.models import (
    Answer, Checkin, CheckinAnswer, CheckinQuestion, CheckinTemplate, Employee, EmployeeQuestion,
    ManagerSettings, Question, Schedule, Streak, SurveySession, UserAccount, WorkerInvite, EmployeeDetails, RoleAssignment,
)

engine = create_engine(settings.SYNC_DATABASE_URL)


def get_session():
    return Session(engine)


def get_employee_by_tg(tg_id: str) -> Employee | None:
    with get_session() as s:
        return s.execute(select(Employee).where(Employee.telegram_id == tg_id)).scalar_one_or_none()


def bind_employee_invite(raw_token: str, user) -> tuple[Employee | None, str | None]:
    """Consume a one-time HR invite from the trusted bot update identity."""
    telegram_id = str(getattr(user, "id", ""))
    if not telegram_id.isdigit():
        return None, "invalid_identity"
    now = datetime.now(timezone.utc)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    with get_session() as s:
        invite = s.execute(select(WorkerInvite).where(WorkerInvite.token_hash == token_hash).with_for_update()).scalar_one_or_none()
        if not invite:
            return None, "not_found"
        if invite.used_at:
            return None, "used"
        if invite.revoked_at or invite.expires_at <= now:
            return None, "expired"
        duplicate = s.execute(select(Employee.id).where(Employee.telegram_id == telegram_id, Employee.id != invite.employee_id)).scalar_one_or_none()
        if duplicate:
            return None, "duplicate"
        employee = s.execute(select(Employee).where(Employee.id == invite.employee_id, Employee.organization_id == invite.organization_id).with_for_update()).scalar_one_or_none()
        if not employee:
            return None, "not_found"
        employee.telegram_id = telegram_id
        employee.telegram_username = getattr(user, "username", None) or employee.telegram_username
        employee.first_name = getattr(user, "first_name", None) or employee.first_name
        employee.last_name = getattr(user, "last_name", None) or employee.last_name
        employee.photo_url = getattr(user, "photo_url", None) or employee.photo_url
        display_name = " ".join(part for part in (employee.first_name, employee.last_name) if part)
        if display_name:
            employee.name = display_name
        employee.is_active = True
        employee.onboarded_at = employee.onboarded_at or now
        details = s.execute(select(EmployeeDetails).where(EmployeeDetails.employee_id == employee.id)).scalar_one_or_none()
        if details:
            details.employment_status = "active"
        invite.used_at = now
        invite.bound_telegram_id = telegram_id
        account = s.execute(select(UserAccount).where(UserAccount.employee_id == employee.id).with_for_update()).scalar_one_or_none()
        if not account:
            account = UserAccount(organization_id=invite.organization_id, employee_id=employee.id, email=f"telegram-{telegram_id}", password_hash=hash_account_password(secrets.token_urlsafe(48)), status="active", locale=employee.primary_language or "mn", must_change_password=True)
            s.add(account); s.flush()
        else:
            account.status = "active"
        if not s.execute(select(RoleAssignment.id).where(RoleAssignment.account_id == account.id, RoleAssignment.role == "member")).scalar_one_or_none():
            s.add(RoleAssignment(account_id=account.id, role="member"))
        s.commit()
        s.refresh(employee)
        return employee, None


def link_employee_telegram(username: str | None, tg_id: str) -> Employee | None:
    """Фолбэк: ищет сотрудника по telegram_username и автопроставляет числовой
    telegram_id при первом контакте (чтобы заводить сотрудников по @username)."""
    uname = (username or "").lstrip("@")
    if not uname:
        return None
    with get_session() as s:
        emp = s.execute(
            select(Employee).where(Employee.telegram_username.ilike(uname))
        ).scalar_one_or_none()
        if emp and emp.telegram_id != tg_id:
            emp.telegram_id = tg_id
            s.commit()
            s.refresh(emp)
        return emp


def get_all_active_employees() -> list[Employee]:
    with get_session() as s:
        return list(s.execute(select(Employee).where(Employee.is_active == True)).scalars())


def get_questions(employee_id: int | None = None) -> list[Question]:
    with get_session() as s:
        return _get_questions_in_session(s, employee_id)


def _get_questions_in_session(s: Session, employee_id: int | None = None) -> list[Question]:
    query = select(Question).order_by(Question.sort_order, Question.id)
    if employee_id is not None:
        assigned = select(EmployeeQuestion.question_id).where(EmployeeQuestion.employee_id == employee_id)
        query = query.where(Question.id.in_(assigned) | Question.id.not_in(select(EmployeeQuestion.question_id)))
    return list(s.execute(query).scalars())


def get_schedule(employee_id: int) -> Schedule | None:
    with get_session() as s:
        return s.execute(select(Schedule).where(Schedule.employee_id == employee_id)).scalar_one_or_none()


def get_manager_settings() -> ManagerSettings | None:
    with get_session() as s:
        return s.execute(select(ManagerSettings)).scalar_one_or_none()


def get_streak(employee_id: int) -> Streak | None:
    with get_session() as s:
        return s.execute(select(Streak).where(Streak.employee_id == employee_id)).scalar_one_or_none()


def create_session(employee_id: int, session_type: str = "evening", local_day: date | None = None) -> SurveySession:
    today = local_day or date.today()
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


def canonical_checkin_complete(employee_id: int, local_day: date) -> bool:
    with get_session() as s:
        return bool(s.execute(select(Checkin.id).where(Checkin.employee_id == employee_id, Checkin.local_date == local_day, Checkin.status == "submitted")).scalars().first())


def mirror_completed_session(session_id: int, source: str = "telegram") -> None:
    """Mirror a completed legacy questionnaire into the canonical check-in."""
    with get_session() as s:
        session = s.get(SurveySession, session_id)
        if not session:
            return
        account = s.execute(select(UserAccount).where(UserAccount.employee_id == session.employee_id)).scalar_one_or_none()
        if not account:
            return
        legacy_questions = _get_questions_in_session(s, session.employee_id)
        if not legacy_questions:
            return
        template_name = f"Daily check-in [employee:{session.employee_id}]"
        template = s.execute(select(CheckinTemplate).where(CheckinTemplate.organization_id == account.organization_id, CheckinTemplate.name == template_name)).scalar_one_or_none()
        if not template:
            template = CheckinTemplate(organization_id=account.organization_id, name=template_name, cadence="daily")
            s.add(template)
            s.flush()
        canonical = s.execute(select(CheckinQuestion).where(CheckinQuestion.template_id == template.id)).scalars().all()
        by_source = {
            int(item.prompt["source_question_id"]): item
            for item in canonical
            if isinstance(item.prompt, dict) and item.prompt.get("source_question_id") is not None
        }
        for position, question in enumerate(legacy_questions):
            canonical_question = by_source.get(question.id)
            if canonical_question is None:
                canonical_question = CheckinQuestion(template_id=template.id)
                s.add(canonical_question)
            canonical_question.prompt = {"mn": question.text, "source_question_id": question.id}
            canonical_question.answer_type = question.answer_type
            canonical_question.choices = question.options or []
            canonical_question.is_required = bool(question.is_required)
            canonical_question.position = position
        s.flush()
        checkin = s.execute(select(Checkin).where(Checkin.employee_id == session.employee_id, Checkin.template_id == template.id, Checkin.local_date == session.date)).scalar_one_or_none()
        if not checkin:
            checkin = Checkin(employee_id=session.employee_id, template_id=template.id, local_date=session.date, source=source, started_at=session.started_at)
            s.add(checkin)
            s.flush()
        if checkin.status == "submitted":
            return
        legacy_answers = s.execute(select(Answer).where(Answer.session_id == session.id).order_by(Answer.id)).scalars().all()
        questions = s.execute(select(CheckinQuestion).where(CheckinQuestion.template_id == template.id).order_by(CheckinQuestion.position)).scalars().all()
        current_by_source = {question.prompt.get("source_question_id"): question for question in questions if isinstance(question.prompt, dict)}
        for legacy_question, answer in zip(legacy_questions, legacy_answers):
            question = current_by_source.get(legacy_question.id)
            if question is None:
                continue
            existing = s.execute(select(CheckinAnswer).where(CheckinAnswer.checkin_id == checkin.id, CheckinAnswer.question_id == question.id)).scalar_one_or_none()
            if not existing:
                s.add(CheckinAnswer(checkin_id=checkin.id, question_id=question.id, value_text=answer.value_text, value_numeric=answer.value_numeric))
        checkin.status = "submitted"
        checkin.submitted_at = session.completed_at or datetime.now(timezone.utc)
        s.commit()


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
