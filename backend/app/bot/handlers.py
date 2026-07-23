"""aiogram handlers — сотрудник и руководитель."""
import logging
from datetime import date, timedelta

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, CallbackQuery, WebAppInfo

from sqlalchemy import func, select

from app.bot.db import (
    complete_session, create_session, get_manager_settings,
    get_questions, get_session, get_streak, get_yesterday_summary,
    mark_employee_onboarded, save_answer,
)
from app.core.config import settings
from app.models.models import Answer, Employee, Question, Streak, SurveySession
from app.services.survey_service import build_checkin_summary

log = logging.getLogger(__name__)
router = Router()


class Survey(StatesGroup):
    answering = State()


def mini_app_keyboard() -> InlineKeyboardMarkup | None:
    """Return the launch button only when a public Mini App URL is configured."""
    url = settings.MINI_APP_URL.strip()
    if not url:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="📋 Самбар нээх", web_app=WebAppInfo(url=url)),
    ]])


# ─── helpers ─────────────────────────────────────────────────────────────────

def _numeric_keyboard(question_text: str) -> InlineKeyboardMarkup:
    """Кнопки 0–15 для числовых вопросов."""
    rows = []
    for row_start in range(0, 16, 5):
        rows.append([InlineKeyboardButton(text=str(i), callback_data=f"ans:{i}") for i in range(row_start, min(row_start + 5, 16))])
    rows.append([InlineKeyboardButton(text="Өөр тоо ✏️", callback_data="ans:custom")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _ask_question(message_or_cb, question, state: FSMContext, session_id: int, q_index: int, questions: list):
    text = f"❓ Асуулт {q_index + 1}/{len(questions)}:\n\n<b>{question.text}</b>"

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
async def cmd_start(message: Message, state: FSMContext, employee=None):
    emp = employee
    if not emp:
        await message.answer("❌ Та системд бүртгэгдээгүй байна. Удирдлагадаа хандана уу.")
        return

    mark_employee_onboarded(emp.id)
    ms = get_manager_settings()
    onboarding_text = (
        f"👋 Сайн байна уу, {emp.name.split()[0]}!\n\n"
        f"Би OYUNS Agent байна.\n\n"
        f"Даалгавар, өдрийн төлөвлөгөө, компанийн мэдээлэл эсвэл ажлын "
        f"бичвэрийн талаар энгийнээр бичиж, дуу хоолойгоор асууж болно.\n\n"
        f"Мөн би танд өдөр бүр богино асуулга илгээнэ.\n\n"
        f"📊 /my_stats — таны статистик\n"
        f"📋 /today — чек-ин бөглөх\n"
        f"🏆 /leaderboard — багийн чансаа\n"
        f"❓ /help — тусламж"
    )
    await message.answer(onboarding_text, reply_markup=mini_app_keyboard())


@router.message(Command("app"))
async def cmd_app(message: Message, employee=None, is_manager: bool = False):
    """Open the Telegram Mini App from the command menu or a typed /app."""
    if not employee and not is_manager:
        await message.answer("❌ Та системд бүртгэгдээгүй байна. Удирдлагадаа хандана уу.")
        return
    keyboard = mini_app_keyboard()
    if not keyboard:
        await message.answer("⚠️ Mini App холбоос тохируулагдаагүй байна. Админ MINI_APP_URL-г HTTPS хаягаар тохируулна уу.")
        return
    title = "👔 Удирдлагын самбар" if is_manager else "📋 Миний даалгаврын самбар"
    await message.answer(f"{title}\nДоорх товчоор Telegram дотор нээнэ үү.", reply_markup=keyboard)


# ─── /today (опрос) ───────────────────────────────────────────────────────────

@router.message(Command("today"))
async def cmd_today(message: Message, state: FSMContext, employee=None):
    emp = employee
    if not emp:
        await message.answer("❌ Та бүртгэгдээгүй байна.")
        return

    questions = get_questions()
    if not questions:
        await message.answer("⚠️ Асуултууд тохируулагдаагүй байна.")
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
        await cb.message.answer("Тоог гараар оруулна уу:")
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
    with get_session() as s:
        q = s.get(Question, question_ids[q_index])
    if not q:
        return

    value_text = None
    value_numeric = None
    if q.answer_type in ("integer", "decimal"):
        try:
            value_numeric = float(value.replace(",", "."))
        except ValueError:
            await message.answer("Тоог оруулна уу. Жишээ нь: 12")
            return
    else:
        value_text = value.strip()

    save_answer(session_id, q.id, value_text, value_numeric)

    next_index = q_index + 1
    if next_index < len(question_ids):
        with get_session() as s:
            next_q = s.get(Question, question_ids[next_index])
            all_qs = list(s.execute(select(Question).order_by(Question.sort_order)).scalars())
        await state.update_data(q_index=next_index)
        await _ask_question(message, next_q, state, session_id, next_index, all_qs)
    else:
        complete_session(session_id)
        await state.clear()
        await message.answer(build_checkin_summary(session_id), parse_mode="HTML")


# ─── /my_stats ────────────────────────────────────────────────────────────────

@router.message(Command("my_stats"))
async def cmd_stats(message: Message, employee=None):
    emp = employee
    if not emp:
        await message.answer("❌ Та бүртгэгдээгүй байна.")
        return

    streak = get_streak(emp.id)
    with get_session() as s:
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
        f"📊 <b>{emp.name.split()[0]}-ийн статистик</b>\n\n"
        f"📅 7 хоногт бөглөсөн: <b>{week_sessions}</b>\n"
        f"📅 Сард бөглөсөн: <b>{month_sessions}</b>\n"
        f"📋 Нийт сесс: <b>{total_sessions}</b>\n"
    )
    if streak:
        text += f"\n🔥 Одоогийн цуврал: <b>{streak.current_streak} өдөр</b>\n"
        text += f"🏆 Хамгийн урт цуврал: <b>{streak.longest_streak} өдөр</b>"

    await message.answer(text, parse_mode="HTML")


# ─── /leaderboard ────────────────────────────────────────────────────────────

@router.message(Command("leaderboard"))
async def cmd_leaderboard(message: Message):
    ms = get_manager_settings()
    if ms and not ms.gamification_enabled:
        await message.answer("🏆 Чансааг администратор түр хаасан байна.")
        return

    with get_session() as s:
        rows = list(s.execute(
            select(Employee, Streak)
            .outerjoin(Streak, Streak.employee_id == Employee.id)
            .where(Employee.is_active == True)
            .order_by(Streak.current_streak.desc().nullslast())
            .limit(3)
        ).all())

    medals = ["🥇", "🥈", "🥉"]
    lines = ["🏆 <b>Багийн топ-3 (өдрийн цуврал)</b>\n"]
    for i, (emp, streak) in enumerate(rows):
        cur = streak.current_streak if streak else 0
        lines.append(f"{medals[i]} {emp.name} — {cur} өдөр")

    await message.answer("\n".join(lines), parse_mode="HTML")


# ─── /help ────────────────────────────────────────────────────────────────────

@router.message(Command("myid"))
async def cmd_myid(message: Message, employee=None):
    u = message.from_user
    uname = f"@{u.username}" if u.username else "—"
    if employee:
        reg = f"\n✅ Та бүртгэгдсэн: <b>{employee.name}</b>"
    else:
        reg = "\n❗️Та бүртгэгдээгүй байна. Энэ ID-г удирдлагадаа өгнө үү."
    await message.answer(
        f"🆔 Таны Telegram ID: <code>{u.id}</code>\nUsername: {uname}{reg}",
        parse_mode="HTML",
    )


@router.message(Command("help"))
async def cmd_help(message: Message, is_manager: bool = False):
    tasks_block = (
        "\n🤖 <b>OYUNS туслах</b>\n"
        "Энгийн текст эсвэл дуу хоолойгоор даалгавар, төлөвлөгөө, "
        "компанийн мэдээлэл болон ажлын бичвэр хүсэж болно.\n\n"
        "📝 <b>Даалгавар</b>\n"
        "/task [@гүйцэтгэгч] юу хийх [хэзээ] — даалгавар үүсгэх\n"
        "/mytasks — миний даалгаврууд\n"
        "/assigned — миний өгсөн даалгаврууд\n"
        "/dashboard — хянах самбар\n"
        "/app — Telegram доторх самбар\n"
        "/done &lt;id&gt; — дууссанд тэмдэглэх\n"
        "/snooze &lt;id&gt; &lt;цаг&gt; — хугацаа хойшлуулах\n"
        "/myid — миний Telegram ID\n"
    )
    if is_manager:
        text = (
            "👔 <b>Удирдлагын командууд</b>\n\n"
            "/summary — өчигдрийн хураангуй\n"
            "/week — 7 хоногийн статистик\n"
            "/blockers — гол саад бэрхшээлүүд\n"
            + tasks_block
        )
    else:
        text = (
            "📋 <b>Командууд</b>\n\n"
            "/today — чек-ин бөглөх\n"
            "/my_stats — миний статистик\n"
            "/leaderboard — багийн чансаа\n"
            "/help — энэ тусламж\n"
            + tasks_block
        )
    await message.answer(text, parse_mode="HTML")


# ─── Команды руководителя ────────────────────────────────────────────────────

@router.message(Command("summary"))
async def cmd_summary(message: Message, is_manager: bool = False):
    if not is_manager:
        await message.answer("❌ Зөвхөн удирдлагад зориулсан команд.")
        return
    data = get_yesterday_summary()
    lines = [f"📊 <b>{data['date']}-ны хураангуй</b>\n"]
    for q_text, val in data["totals"].items():
        lines.append(f"• {q_text[:35]}: <b>{val}</b>")
    if data["missed"]:
        lines.append(f"\n⚠️ Бөглөөгүй: {', '.join(data['missed'])}")
    await message.answer("\n".join(lines) or "Өчигдрийн мэдээлэл алга.", parse_mode="HTML")


@router.message(Command("week"))
async def cmd_week(message: Message, is_manager: bool = False):
    if not is_manager:
        await message.answer("❌ Зөвхөн удирдлагад зориулсан команд.")
        return

    with get_session() as s:
        week_ago = date.today() - timedelta(days=7)
        rows = list(s.execute(
            select(Employee.name, func.count(SurveySession.id).label("cnt"))
            .join(SurveySession, SurveySession.employee_id == Employee.id)
            .where(SurveySession.date >= week_ago, SurveySession.status == "completed")
            .group_by(Employee.name)
            .order_by(func.count(SurveySession.id).desc())
        ).all())

    lines = ["📅 <b>Сүүлийн 7 хоногийн бөглөлт</b>\n"]
    for name, cnt in rows:
        lines.append(f"• {name}: 7-оос {cnt}")
    await message.answer("\n".join(lines) or "Мэдээлэл алга.", parse_mode="HTML")


@router.message(Command("blockers"))
async def cmd_blockers(message: Message, is_manager: bool = False):
    if not is_manager:
        await message.answer("❌ Зөвхөн удирдлагад зориулсан команд.")
        return

    with get_session() as s:
        month_ago = date.today() - timedelta(days=30)
        text_qs = list(s.execute(select(Question).where(Question.answer_type == "text")).scalars())
        if not text_qs:
            await message.answer("Текстэн асуулт алга.")
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

    lines = ["🚧 <b>Сарын гол саад бэрхшээлүүд</b>\n"]
    for text_val, cnt in rows:
        lines.append(f"• {text_val[:50]} — {cnt}×")
    await message.answer("\n".join(lines) or "Мэдээлэл алга.", parse_mode="HTML")
