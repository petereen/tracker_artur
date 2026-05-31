"""Бизнес-логика опросов — вынесена из bot/handlers.py."""
from sqlalchemy import select

from app.bot.db import get_session
from app.models.models import Answer, Question, Streak, SurveySession


def build_checkin_summary(session_id: int) -> str:
    """HTML-сводка по завершённому чек-ину: ответы + текущая серия."""
    with get_session() as s:
        answers = list(
            s.execute(select(Answer).where(Answer.session_id == session_id)).scalars()
        )
        lines = ["✅ <b>Чек-ин заполнен!</b> Сегодня ты:"]
        for a in answers:
            q = s.get(Question, a.question_id)
            if q and a.value_numeric is not None:
                lines.append(f"• {q.text[:35]}: <b>{int(a.value_numeric)}</b>")
            elif q and a.value_text:
                lines.append(f"• {q.text[:35]}: {a.value_text[:50]}")

        sess = s.get(SurveySession, session_id)
        if sess:
            streak = s.execute(
                select(Streak).where(Streak.employee_id == sess.employee_id)
            ).scalar_one_or_none()
            if streak and streak.current_streak > 1:
                lines.append(f"\n🔥 Серия: {streak.current_streak} дней подряд!")

    return "\n".join(lines)
