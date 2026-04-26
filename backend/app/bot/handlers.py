"""aiogram handlers — сотрудник и руководитель."""
import logging
from datetime import date, timedelta

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, CallbackQuery

from app.bot.db import (
    complete_session, create_session, get_employee_by_tg, get_manager_settings,
    get_questions, get_streak, get_yesterday_summary, mark_employee_onboarded, save_answer,
)
from app.core.config import settings

log = logging.getLogger(__name__)
router = Router()


class Survey(StatesGroup):
    answering = State()


# ─── helpers ─────────────────────────────────────────────────────────────────

def _is_manager(tg_id: str) -> bool:
    return tg_id == settings.MANAGER_TG_ID


def _numeric_keyboard(question_text: str) -> InlineKeyboardMarkup:
    """Кнопки 0–15 для числовых вопросов."""
    rows = []
    for row_start in range(0, 16, 5):
        rows.append([InlineKeyboardButton(text=str(i), callback_data=f"ans:{i}") for i in range(row_start, min(row_start + 5, 16))])
    rows.append([InlineKeyboardButton(text="Другое число ✏️", callback_data="ans:custom")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _ask_question(message_or_cb, question, state: FSMContext, session_id: int, q_index: int, questions: list):
    text = f"❓ Вопрос {q_index + 1}/{len(questions)}:\n\n<b>{question.text}</b>"

    if question.answer_type in ("integer", "decimal"):
        kb = _numeric_keyboard(question.text)
        if hasattr(message_or_cb, "answer"):
            await message_or_cb.message.answer(text, reply_markup=kb, parse_mode="HTML")
        else:
            await message_or_cb.answer(text, reply_markup=kb, parse_mode="HTML")
    else:
        if hasattr(message_or_cb, "answer"):
            await message_or_cb.message.answer(text, parse_mode="HTML")
        else:
            await message_or_cb.answer(text, parse_mode="HTML")

    await state.update_data(session_id=session_id, q_index=q_index, questions=[q.id for q in questions])


# ─── /start ──────────────────────────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    tg_id = str(message.from_user.id)
    emp = get_employee_by_tg(tg_id)

    if not emp:
        await message.answer("❌ Вы не зарегистрированы в системе. Обратитесь к руководителю.")
        return

    mark_employee_onboarded(emp.id)
    ms = get_manager_settings()
    onboarding_text = (
        f"👋 Привет, {emp.name.split()[0]}!\n\n"
        f"Я — бот трекера активности отдела продаж.\n\n"
        f"Каждый день я буду присылать тебе короткий опрос из нескольких вопросов.\n\n"
        f"📊 /my_stats — твоя статистика\n"
        f"📋 /today — заполнить чек-ин\n"
        f"🏆 /leaderboard — рейтинг отдела\n"
        f"❓ /help — помощь"
    )
    await message.answer(onboarding_text)


# ─── /today (опрос) ───────────────────────────────────────────────────────────

@router.message(Command("today"))
async def cmd_today(message: Message, state: FSMContext):
    tg_id = str(message.from_user.id)
    emp = get_employee_by_tg(tg_id)
    if not emp:
        await message.answer("❌ Вы не зарегистрированы.")
        return

    questions = get_questions()
    if not questions:
        await message.answer("⚠️ Вопросы ещё не настроены.")
        return

    sess = create_session(emp.id)
    await state.set_state(Survey.answering)
    await _ask_question(message, questions[0], state, sess.id, 0, questions)


# ─── inline-ответ на число ───────────────────────────────────────────────────

@router.callback_query(F.data.startswith("ans:"), Survey.answering)
async def cb_answer(cb: CallbackQuery, state: FSMContext):
    value_raw = cb.data.split(":", 1)[1]
    data = await state.get_data()
    session_id = data["session_id"]
    q_index = data["q_index"]
    question_ids = data["questions"]

    if value_raw == "custom":
        await cb.message.answer("Введи число вручную:")
        await state.update_data(waiting_custom=True)
        await cb.answer()
        return

    await cb.answer()
    await _process_answer(cb.message, state, session_id, q_index, question_ids, value_raw)


@router.message(Survey.answering)
async def msg_answer(message: Message, state: FSMContext):
    data = await state.get_data()
    session_id = data["session_id"]
    q_index = data["q_index"]
    question_ids = data["questions"]
    await _process_answer(message, state, session_id, q_index, question_ids, message.text or "")


async def _process_answer(message: Message, state: FSMContext, session_id: int, q_index: int, question_ids: list, value: str):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as OrmSession
    from app.models.models import Question
    from app.core.config import settings as cfg
    from sqlalchemy import select

    eng = create_engine(cfg.SYNC_DATABASE_URL)
    with OrmSession(eng) as s:
        q = s.get(Question, question_ids[q_index])
        if not q:
            return

    value_text = None
    value_numeric = None
    if q.answer_type in ("integer", "decimal"):
        try:
            value_numeric = float(value.replace(",", "."))
        except ValueError:
            await message.answer("Введи число, например: 12")
            return
    else:
        value_text = value.strip()

    save_answer(session_id, q.id, value_text, value_numeric)

    next_index = q_index + 1
    if next_index < len(question_ids):
        eng = create_engine(settings.SYNC_DATABASE_URL)
        with OrmSession(eng) as s:
            next_q = s.get(Question, question_ids[next_index])
        await state.update_data(q_index=next_index)
        all_qs_eng = create_engine(settings.SYNC_DATABASE_URL)
        with OrmSession(all_qs_eng) as s:
            from sqlalchemy import select as sel
            all_qs = list(s.execute(sel(Question).order_by(Question.sort_order)).scalars())
        await _ask_question(message, next_q, state, session_id, next_index, all_qs)
    else:
        complete_session(session_id)
        await state.clear()

        # Итоговая сводка
        from sqlalchemy import create_engine as ce
        from sqlalchemy.orm import Session as S2
        from app.models.models import Answer, Question as Q2
        from sqlalchemy import select as sel2
        eng2 = ce(settings.SYNC_DATABASE_URL)
        with S2(eng2) as s:
            answers = list(s.execute(sel2(Answer).where(Answer.session_id == session_id)).scalars())
            lines = ["✅ <b>Чек-ин заполнен!</b> Сегодня ты:"]
            for a in answers:
                ques = s.get(Q2, a.question_id)
                if ques and a.value_numeric is not None:
                    lines.append(f"• {ques.text[:35]}: <b>{int(a.value_numeric)}</b>")
                elif ques and a.value_text:
                    lines.append(f"• {ques.text[:35]}: {a.value_text[:50]}")

        streak = get_streak(
            next(e.employee_id for e in [type('X', (), {'employee_id': session_id})()]) if False else None
        )
        from sqlalchemy import create_engine as ce3
        from sqlalchemy.orm import Session as S3
        from app.models.models import SurveySession
        eng3 = ce3(settings.SYNC_DATABASE_URL)
        with S3(eng3) as s:
            sess_obj = s.get(SurveySession, session_id)
            if sess_obj:
                from app.models.models import Streak as StreakModel
                streak_obj = s.execute(sel2(StreakModel).where(StreakModel.employee_id == sess_obj.employee_id)).scalar_one_or_none()
                if streak_obj and streak_obj.current_streak > 1:
                    lines.append(f"\n🔥 Серия: {streak_obj.current_streak} дней подряд!")

        await message.answer("\n".join(lines), parse_mode="HTML")


# ─── /my_stats ────────────────────────────────────────────────────────────────

@router.message(Command("my_stats"))
async def cmd_stats(message: Message):
    tg_id = str(message.from_user.id)
    emp = get_employee_by_tg(tg_id)
    if not emp:
        await message.answer("❌ Вы не зарегистрированы.")
        return

    streak = get_streak(emp.id)
    from sqlalchemy import create_engine, func, select
    from sqlalchemy.orm import Session
    from app.models.models import SurveySession, Answer, Question

    eng = create_engine(settings.SYNC_DATABASE_URL)
    with Session(eng) as s:
        week_ago = date.today() - timedelta(days=7)
        month_ago = date.today() - timedelta(days=30)

        week_sessions = s.execute(
            select(func.count()).where(SurveySession.employee_id == emp.id, SurveySession.date >= week_ago, SurveySession.status == "completed")
        ).scalar()
        month_sessions = s.execute(
            select(func.count()).where(SurveySession.employee_id == emp.id, SurveySession.date >= month_ago, SurveySession.status == "completed")
        ).scalar()
        total_sessions = s.execute(
            select(func.count()).where(SurveySession.employee_id == emp.id)
        ).scalar()

    text = (
        f"📊 <b>Статистика {emp.name.split()[0]}</b>\n\n"
        f"📅 Заполнено за неделю: <b>{week_sessions}</b>\n"
        f"📅 Заполнено за месяц: <b>{month_sessions}</b>\n"
        f"📋 Всего сессий: <b>{total_sessions}</b>\n"
    )
    if streak:
        text += f"\n🔥 Текущая серия: <b>{streak.current_streak} дн.</b>\n"
        text += f"🏆 Рекорд серии: <b>{streak.longest_streak} дн.</b>"

    await message.answer(text, parse_mode="HTML")


# ─── /leaderboard ────────────────────────────────────────────────────────────

@router.message(Command("leaderboard"))
async def cmd_leaderboard(message: Message):
    ms = get_manager_settings()
    if ms and not ms.gamification_enabled:
        await message.answer("🏆 Рейтинг временно отключён администратором.")
        return

    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session
    from app.models.models import Employee, Streak

    eng = create_engine(settings.SYNC_DATABASE_URL)
    with Session(eng) as s:
        rows = list(s.execute(
            select(Employee, Streak)
            .outerjoin(Streak, Streak.employee_id == Employee.id)
            .where(Employee.is_active == True)
            .order_by(Streak.current_streak.desc().nullslast())
            .limit(3)
        ).all())

    medals = ["🥇", "🥈", "🥉"]
    lines = ["🏆 <b>Топ-3 отдела (серия дней)</b>\n"]
    for i, (emp, streak) in enumerate(rows):
        cur = streak.current_streak if streak else 0
        lines.append(f"{medals[i]} {emp.name} — {cur} дн.")

    await message.answer("\n".join(lines), parse_mode="HTML")


# ─── /help ────────────────────────────────────────────────────────────────────

@router.message(Command("help"))
async def cmd_help(message: Message):
    tg_id = str(message.from_user.id)
    if _is_manager(tg_id):
        text = (
            "👔 <b>Команды руководителя</b>\n\n"
            "/summary — сводка за вчера\n"
            "/week — статистика за 7 дней\n"
            "/blockers — топ блокеров\n"
        )
    else:
        text = (
            "📋 <b>Команды</b>\n\n"
            "/today — заполнить чек-ин\n"
            "/my_stats — моя статистика\n"
            "/leaderboard — рейтинг отдела\n"
            "/help — эта справка"
        )
    await message.answer(text, parse_mode="HTML")


# ─── Команды руководителя ────────────────────────────────────────────────────

@router.message(Command("summary"))
async def cmd_summary(message: Message):
    if not _is_manager(str(message.from_user.id)):
        await message.answer("❌ Только для руководителя.")
        return
    data = get_yesterday_summary()
    lines = [f"📊 <b>Сводка за {data['date']}</b>\n"]
    for q_text, val in data["totals"].items():
        lines.append(f"• {q_text[:35]}: <b>{val}</b>")
    if data["missed"]:
        lines.append(f"\n⚠️ Не заполнили: {', '.join(data['missed'])}")
    await message.answer("\n".join(lines) or "Нет данных за вчера.", parse_mode="HTML")


@router.message(Command("week"))
async def cmd_week(message: Message):
    if not _is_manager(str(message.from_user.id)):
        await message.answer("❌ Только для руководителя.")
        return

    from sqlalchemy import create_engine, func, select
    from sqlalchemy.orm import Session
    from app.models.models import Employee, SurveySession

    eng = create_engine(settings.SYNC_DATABASE_URL)
    with Session(eng) as s:
        week_ago = date.today() - timedelta(days=7)
        rows = list(s.execute(
            select(Employee.name, func.count(SurveySession.id).label("cnt"))
            .join(SurveySession, SurveySession.employee_id == Employee.id)
            .where(SurveySession.date >= week_ago, SurveySession.status == "completed")
            .group_by(Employee.name)
            .order_by(func.count(SurveySession.id).desc())
        ).all())

    lines = ["📅 <b>Заполнения за 7 дней</b>\n"]
    for name, cnt in rows:
        lines.append(f"• {name}: {cnt} из 7")
    await message.answer("\n".join(lines) or "Нет данных.", parse_mode="HTML")


@router.message(Command("blockers"))
async def cmd_blockers(message: Message):
    if not _is_manager(str(message.from_user.id)):
        await message.answer("❌ Только для руководителя.")
        return

    from sqlalchemy import create_engine, func, select
    from sqlalchemy.orm import Session
    from app.models.models import Answer, Question

    eng = create_engine(settings.SYNC_DATABASE_URL)
    with Session(eng) as s:
        month_ago = date.today() - timedelta(days=30)
        from app.models.models import SurveySession
        text_qs = list(s.execute(select(Question).where(Question.answer_type == "text")).scalars())
        if not text_qs:
            await message.answer("Текстовых вопросов нет.")
            return
        q_ids = [q.id for q in text_qs]
        rows = list(s.execute(
            select(Answer.value_text, func.count().label("cnt"))
            .join(SurveySession, Answer.session_id == SurveySession.id)
            .where(Answer.question_id.in_(q_ids), Answer.value_text.isnot(None), SurveySession.date >= month_ago)
            .group_by(Answer.value_text)
            .order_by(func.count().desc())
            .limit(5)
        ).all())

    lines = ["🚧 <b>Топ блокеров за месяц</b>\n"]
    for text_val, cnt in rows:
        lines.append(f"• {text_val[:50]} — {cnt}×")
    await message.answer("\n".join(lines) or "Нет данных.", parse_mode="HTML")
