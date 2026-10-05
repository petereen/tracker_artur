"""aiogram handlers — сотрудник и руководитель."""
import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, CallbackQuery, WebAppInfo

from sqlalchemy import func, select

from app.bot.db import (
    complete_session, create_session, get_manager_settings,
    canonical_checkin_complete, get_questions, get_session, get_streak, get_yesterday_summary,
    mirror_completed_session, bind_employee_invite, is_primary_tenant,
    mark_employee_onboarded, save_answer,
)
from app.core.config import settings
from app.models.models import Answer, Employee, Question, Streak, SurveySession
from app.services.survey_service import build_checkin_summary

log = logging.getLogger(__name__)
router = Router()


class Survey(StatesGroup):
    answering = State()


def mini_app_keyboard(organization_id: int | None = None, language: str = "mn") -> InlineKeyboardMarkup | None:
    """Return the launch button only when a public Mini App URL is configured.

    Each tenant's bot opens the Mini App on that tenant's own address."""
    from app.services.telegram_bots import mini_app_url_sync

    url = mini_app_url_sync(organization_id) if organization_id is not None else settings.MINI_APP_URL.strip()
    if not url:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text={"en": "📋 Open workspace", "ru": "📋 Открыть рабочее пространство"}.get(language, "📋 Самбар нээх"), web_app=WebAppInfo(url=url)),
    ]])


# ─── helpers ─────────────────────────────────────────────────────────────────

def _numeric_keyboard(question_text: str, *, optional: bool = False, language: str = "mn") -> InlineKeyboardMarkup:
    """Кнопки 0–15 для числовых вопросов."""
    rows = []
    for row_start in range(0, 16, 5):
        rows.append([InlineKeyboardButton(text=str(i), callback_data=f"ans:{i}") for i in range(row_start, min(row_start + 5, 16))])
    rows.append([InlineKeyboardButton(text={"en": "Other number ✏️", "ru": "Другое число ✏️"}.get(language, "Өөр тоо ✏️"), callback_data="ans:custom")])
    if optional:
        rows.append([InlineKeyboardButton(text={"en": "Skip", "ru": "Пропустить"}.get(language, "Алгасах"), callback_data="ans:skip")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _ask_question(message_or_cb, question, state: FSMContext, session_id: int, q_index: int, questions: list, language: str = "mn"):
    question_label = {"en": "Question", "ru": "Вопрос"}.get(language, "Асуулт")
    text = f"❓ {question_label} {q_index + 1}/{len(questions)}:\n\n<b>{question.text}</b>"
    target_message = message_or_cb.message if isinstance(message_or_cb, CallbackQuery) else message_or_cb

    if question.answer_type in ("integer", "decimal"):
        kb = _numeric_keyboard(question.text, optional=not question.is_required, language=language)
        await target_message.answer(text, reply_markup=kb, parse_mode="HTML")
    elif not question.is_required:
        await target_message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text={"en": "Skip", "ru": "Пропустить"}.get(language, "Алгасах"), callback_data="ans:skip")]]), parse_mode="HTML")
    else:
        await target_message.answer(text, parse_mode="HTML")

    await state.update_data(session_id=session_id, q_index=q_index, questions=[q.id for q in questions], language=language)


# ─── /start ──────────────────────────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, employee=None, bot_tenant_id: int | None = None, language: str = "mn"):
    emp = employee
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) > 1 and parts[1].startswith("invite_"):
        bound, error = bind_employee_invite(parts[1][7:], message.from_user, bot_tenant_id)
        if error:
            messages = {
                "expired": {"mn": "❌ Урилга хүчингүй болсон байна. HR-ээс шинэ холбоос авна уу.", "ru": "❌ Срок действия приглашения истёк. Попросите HR отправить новую ссылку.", "en": "❌ This invitation has expired. Ask HR for a new link."},
                "used": {"mn": "ℹ️ Энэ урилга аль хэдийн ашиглагдсан байна.", "ru": "ℹ️ Это приглашение уже использовано.", "en": "ℹ️ This invitation has already been used."},
                "duplicate": {"mn": "❌ Таны Telegram бүртгэл өөр ажилтантай холбогдсон байна.", "ru": "❌ Ваш аккаунт Telegram уже связан с другим сотрудником.", "en": "❌ Your Telegram account is already linked to another employee."},
                "seat_limit": {"mn": "❌ Байгууллагын лицензийн хэрэглэгчийн хязгаар дүүрсэн байна. Админдаа хандана уу.", "ru": "❌ Достигнут лимит пользователей по лицензии организации. Обратитесь к администратору.", "en": "❌ The organization’s licensed user limit has been reached. Contact your administrator."},
            }
            await message.answer(messages.get(error, {}).get(language) or {
                "en": "❌ The invitation was not found or is no longer valid.",
                "ru": "❌ Приглашение не найдено или больше не действует.",
            }.get(language, "❌ Урилга олдсонгүй эсвэл хүчингүй байна."))
            return
        emp = bound
        linked = {"en": "✅ Your Telegram account is connected. Open your OYUNS workspace to get started.", "ru": "✅ Ваш аккаунт Telegram подключён. Откройте рабочее пространство OYUNS, чтобы начать."}.get(language, "✅ Telegram бүртгэл амжилттай холбогдлоо. OYUNS самбарыг нээж эхлүүлнэ үү.")
        await message.answer(linked, reply_markup=mini_app_keyboard(bot_tenant_id, language))
        return
    if not emp:
        # Unregistered users are answered by the middleware.
        return

    mark_employee_onboarded(emp.id)
    onboarding_mn = (
        f"👋 Сайн байна уу, {emp.name.split()[0]}!\n\n"
        f"Би OYUNS Agent байна.\n\n"
        f"Даалгавар, өдрийн төлөвлөгөө, компаний мэдээлэл эсвэл ажлын "
        f"бичвэрийн талаар энгийнээр бичиж, дуу хоолойгоор асууж болно.\n\n"
        f"Мөн би танд өдөр бүр богино асуулга илгээнэ.\n\n"
        f"📊 /my_stats — таны статистик\n"
        f"📋 /today — чек-ин бөглөх\n"
        f"🟢 /daystart — ажил эхэлсэн цаг\n"
        f"🔴 /dayend — ажил дууссан цаг\n"
        f"🏠 /remotestart — remote ажил эхэлсэн цаг\n"
        f"🏠 /remoteend — remote ажил дууссан цаг\n"
        f"⏸ /daypause — ажлын цаг түр зогсоох\n"
        f"📊 /worktime — өнөөдрийн ажлын цаг\n"
        f"🏆 /leaderboard — багийн чансаа\n"
        f"❓ /help — тусламж"
    )
    onboarding_text = onboarding_mn
    if language == "en":
        onboarding_text = (
            f"👋 Hello, {emp.name.split()[0]}!\\n\\nI’m the OYUNS Agent.\\n\\n"
            "You can ask me about tasks, daily plans, company information, and work writing in plain language or by voice.\\n\\n"
            "I’ll also send you a short questionnaire each day.\\n\\n"
            "📊 /my_stats — your statistics\\n📋 /today — daily check-in\\n"
            "🟢 /daystart — start work\\n🔴 /dayend — finish work\\n"
            "🏠 /remotestart — start remote work\\n🏠 /remoteend — finish remote work\\n"
            "⏸ /daypause — pause work time\\n📊 /worktime — today’s work time\\n"
            "🏆 /leaderboard — team leaderboard\\n❓ /help — help"
        )
    elif language == "ru":
        onboarding_text = (
            f"👋 Здравствуйте, {emp.name.split()[0]}!\\n\\nЯ OYUNS Agent.\\n\\n"
            "Вы можете задавать голосом или обычным текстом вопросы о задачах, планах на день, информации компании и рабочих текстах.\\n\\n"
            "Я также буду присылать короткий опрос каждый день.\\n\\n"
            "📊 /my_stats — ваша статистика\\n📋 /today — ежедневный опрос\\n"
            "🟢 /daystart — начать работу\\n🔴 /dayend — закончить работу\\n"
            "🏠 /remotestart — начать удалённую работу\\n🏠 /remoteend — закончить удалённую работу\\n"
            "⏸ /daypause — приостановить учёт времени\\n📊 /worktime — рабочее время за сегодня\\n"
            "🏆 /leaderboard — рейтинг команды\\n❓ /help — справка"
        )
    await message.answer(onboarding_text, reply_markup=mini_app_keyboard(bot_tenant_id, language))


@router.message(Command("app"))
async def cmd_app(message: Message, employee=None, is_manager: bool = False, bot_tenant_id: int | None = None, language: str = "mn"):
    """Open the Telegram Mini App from the command menu or a typed /app."""
    if not employee and not is_manager:
        await message.answer({"en": "❌ You are not registered in the system. Contact your administrator.", "ru": "❌ Вы не зарегистрированы в системе. Обратитесь к администратору."}.get(language, "❌ Та системд бүртгэгдээгүй байна. Удирдлагадаа хандана уу."))
        return
    keyboard = mini_app_keyboard(bot_tenant_id)
    if not keyboard:
        await message.answer({"en": "⚠️ The Mini App link is not configured. Ask an administrator to set MINI_APP_URL to an HTTPS address.", "ru": "⚠️ Ссылка Mini App не настроена. Попросите администратора указать HTTPS-адрес в MINI_APP_URL."}.get(language, "⚠️ Mini App холбоос тохируулагдаагүй байна. Админ MINI_APP_URL-г HTTPS хаягаар тохируулна уу."))
        return
    titles = {"en": ("👔 Management workspace", "📋 My task workspace"), "ru": ("👔 Рабочее пространство руководителя", "📋 Мои задачи")}
    title = titles.get(language, ("👔 Удирдлагын самбар", "📋 Миний даалгаврын самбар"))[0 if is_manager else 1]
    prompt = {"en": "Open it in Telegram using the button below.", "ru": "Откройте его в Telegram с помощью кнопки ниже."}.get(language, "Доорх товчоор Telegram дотор нээнэ үү.")
    await message.answer(f"{title}\n{prompt}", reply_markup=keyboard)


# ─── /today (опрос) ───────────────────────────────────────────────────────────

@router.message(Command("today"))
async def cmd_today(message: Message, state: FSMContext, employee=None, language: str = "mn"):
    await _begin_checkin(message, state, employee, language=language)


@router.callback_query(F.data.startswith("checkin:start"))
async def cb_start_checkin(cb: CallbackQuery, state: FSMContext, employee=None, language: str = "mn"):
    await cb.answer()
    await _begin_checkin(cb, state, employee, session_type="daily_test" if (cb.data or "").endswith(":test") else "evening", language=language)


async def _begin_checkin(message_or_cb: Message | CallbackQuery, state: FSMContext, employee=None, session_type: str = "evening", language: str = "mn"):
    """Launch the same questionnaire from /today and scheduled prompts."""
    emp = employee
    target = message_or_cb.message if isinstance(message_or_cb, CallbackQuery) else message_or_cb
    if not emp:
        await target.answer({"en": "❌ You are not registered in the system.", "ru": "❌ Вы не зарегистрированы в системе."}.get(language, "❌ Та бүртгэгдээгүй байна."))
        return

    daily_report_reminders_enabled = getattr(get_manager_settings(), "daily_report_reminders_enabled", True)

    questions = get_questions(emp.id)
    if not questions:
        from app.bot.work_report_handlers import send_report_prompt
        from app.services import work_report_service

        local_day = datetime.now(ZoneInfo(emp.timezone)).date()
        report_type = "daily_test" if session_type == "daily_test" else "daily"
        report = work_report_service.get_or_create_report(emp.id, report_type, local_day)
        if report_type == "daily_test" or (daily_report_reminders_enabled and work_report_service.daily_reports_enabled(emp.id)):
            await send_report_prompt(
                target.bot, report, telegram_chat_id=str(target.chat.id),
                prompt_type="test_daily_report" if report_type == "daily_test" else "daily_report",
                local_day=local_day,
            )
        return

    local_day = datetime.now(ZoneInfo(emp.timezone)).date()
    if session_type == "evening" and canonical_checkin_complete(emp.id, local_day):
        await target.answer({"en": "✅ Today's check-in is already complete.", "ru": "✅ Вы уже прошли сегодняшний опрос."}.get(language, "✅ Өнөөдрийн чек-ин аль хэдийн бөглөгдсөн байна."))
        return
    sess = create_session(emp.id, session_type=session_type, local_day=local_day)
    if sess.status == "completed":
        await target.answer({"en": "✅ Today's check-in is already complete.", "ru": "✅ Вы уже прошли сегодняшний опрос."}.get(language, "✅ Өнөөдрийн чек-ин аль хэдийн бөглөгдсөн байна."))
        return
    await state.set_state(Survey.answering)
    await state.update_data(session_type=session_type, employee_id=emp.id, language=language)
    await _ask_question(message_or_cb, questions[0], state, sess.id, 0, questions, language)


# ─── inline-ответ на число ───────────────────────────────────────────────────

@router.callback_query(F.data.startswith("ans:"), Survey.answering)
async def cb_answer(cb: CallbackQuery, state: FSMContext, language: str = "mn"):
    value_raw = cb.data.split(":", 1)[1]
    data = await state.get_data()
    session_id = data["session_id"]
    q_index = data["q_index"]
    question_ids = data["questions"]

    if value_raw == "custom":
        await cb.message.answer({"en": "Enter a number:", "ru": "Введите число:"}.get(language, "Тоог гараар оруулна уу:"))
        await state.update_data(waiting_custom=True)
        await cb.answer()
        return

    await cb.answer()
    await _process_answer(cb.message, state, session_id, q_index, question_ids, value_raw)


@router.message(Survey.answering, F.text & ~F.text.startswith("/"))
async def msg_answer(message: Message, state: FSMContext):
    data = await state.get_data()
    session_id = data["session_id"]
    q_index = data["q_index"]
    question_ids = data["questions"]
    await _process_answer(message, state, session_id, q_index, question_ids, message.text or "")


async def _process_answer(message: Message, state: FSMContext, session_id: int, q_index: int, question_ids: list, value: str):
    data = await state.get_data()
    with get_session() as s:
        q = s.get(Question, question_ids[q_index])
    if not q:
        return

    value_text = None
    value_numeric = None
    if value == "skip" and not q.is_required:
        pass
    elif q.answer_type in ("integer", "decimal"):
        try:
            value_numeric = float(value.replace(",", "."))
        except ValueError:
            language = data.get("language", "mn")
            await message.answer({"en": "Enter a number, for example: 12", "ru": "Введите число, например: 12"}.get(language, "Тоог оруулна уу. Жишээ нь: 12"))
            return
    else:
        value_text = value.strip()

    save_answer(session_id, q.id, value_text, value_numeric)

    next_index = q_index + 1
    if next_index < len(question_ids):
        with get_session() as s:
            next_q = s.get(Question, question_ids[next_index])
            all_qs = get_questions(data.get("employee_id"))
        await state.update_data(q_index=next_index)
        await _ask_question(message, next_q, state, session_id, next_index, all_qs, data.get("language", "mn"))
    else:
        complete_session(session_id)
        mirror_completed_session(session_id)
        data = await state.get_data()
        session_type = data.get("session_type")
        employee_id = data.get("employee_id")
        await state.clear()
        await message.answer(build_checkin_summary(session_id, data.get("language", "mn")), parse_mode="HTML")
        if session_type == "daily_test":
            from app.bot.work_report_handlers import send_test_daily_report_prompt

            await send_test_daily_report_prompt(
                message.bot,
                state=state,
                employee_id=data["employee_id"],
                telegram_chat_id=str(message.chat.id),
                local_day=date.today(),
            )
        elif session_type == "evening" and employee_id and getattr(get_manager_settings(), "daily_report_reminders_enabled", True):
            from app.bot.work_report_handlers import send_report_prompt
            from app.services import work_report_service

            if not work_report_service.daily_reports_enabled(employee_id):
                return
            report = work_report_service.get_or_create_report(
                employee_id, "daily", date.today()
            )
            await send_report_prompt(
                message.bot,
                report,
                telegram_chat_id=str(message.chat.id),
                prompt_type="daily_report",
                local_day=date.today(),
            )


# ─── /my_stats ────────────────────────────────────────────────────────────────

@router.message(Command("my_stats"))
async def cmd_stats(message: Message, employee=None, language: str = "mn"):
    emp = employee
    if not emp:
        await message.answer({"en": "❌ You are not registered in the system.", "ru": "❌ Вы не зарегистрированы в системе."}.get(language, "❌ Та бүртгэгдээгүй байна."))
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

    if language == "en":
        text = f"📊 <b>{emp.name.split()[0]}'s statistics</b>\n\n📅 Completed this week: <b>{week_sessions}</b>\n📅 Completed this month: <b>{month_sessions}</b>\n📋 Total sessions: <b>{total_sessions}</b>\n"
    elif language == "ru":
        text = f"📊 <b>Статистика: {emp.name.split()[0]}</b>\n\n📅 За неделю: <b>{week_sessions}</b>\n📅 За месяц: <b>{month_sessions}</b>\n📋 Всего сессий: <b>{total_sessions}</b>\n"
    else:
        text = f"📊 <b>{emp.name.split()[0]}-ийн статистик</b>\n\n📅 7 хоногт бөглөсөн: <b>{week_sessions}</b>\n📅 Сард бөглөсөн: <b>{month_sessions}</b>\n📋 Нийт сесс: <b>{total_sessions}</b>\n"
    if streak:
        if language == "en":
            text += f"\n🔥 Current streak: <b>{streak.current_streak} days</b>\n🏆 Longest streak: <b>{streak.longest_streak} days</b>"
        elif language == "ru":
            text += f"\n🔥 Текущая серия: <b>{streak.current_streak} дн.</b>\n🏆 Самая длинная серия: <b>{streak.longest_streak} дн.</b>"
        else:
            text += f"\n🔥 Одоогийн цуврал: <b>{streak.current_streak} өдөр</b>\n🏆 Хамгийн урт цуврал: <b>{streak.longest_streak} өдөр</b>"

    await message.answer(text, parse_mode="HTML")


# ─── /leaderboard ────────────────────────────────────────────────────────────

@router.message(Command("leaderboard"))
async def cmd_leaderboard(message: Message, bot_tenant_id: int | None = None, language: str = "mn"):
    ms = get_manager_settings(bot_tenant_id)
    if ms and not ms.gamification_enabled:
        await message.answer({"en": "🏆 The administrator has temporarily disabled the leaderboard.", "ru": "🏆 Администратор временно отключил таблицу лидеров."}.get(language, "🏆 Чансааг администратор түр хаасан байна."))
        return

    with get_session() as s:
        query = (
            select(Employee, Streak)
            .outerjoin(Streak, Streak.employee_id == Employee.id)
            .where(Employee.is_active == True)
        )
        if bot_tenant_id is not None:
            query = query.where(Employee.organization_id == bot_tenant_id)
        rows = list(s.execute(
            query
            .order_by(Streak.current_streak.desc().nullslast())
            .limit(3)
        ).all())

    medals = ["🥇", "🥈", "🥉"]
    lines = [{"en": "🏆 <b>Team top 3 (daily streak)</b>\n", "ru": "🏆 <b>Топ-3 команды (ежедневная серия)</b>\n"}.get(language, "🏆 <b>Багийн топ-3 (өдрийн цуврал)</b>\n")]
    for i, (emp, streak) in enumerate(rows):
        cur = streak.current_streak if streak else 0
        suffix = "days" if language == "en" else "дн." if language == "ru" else "өдөр"
        lines.append(f"{medals[i]} {emp.name} — {cur} {suffix}")

    await message.answer("\n".join(lines), parse_mode="HTML")


# ─── /help ────────────────────────────────────────────────────────────────────

@router.message(Command("myid"))
async def cmd_myid(message: Message, employee=None, language: str = "mn"):
    u = message.from_user
    uname = f"@{u.username}" if u.username else "—"
    if employee:
        reg = f"\n✅ Registered employee: <b>{employee.name}</b>" if language == "en" else f"\n✅ Вы зарегистрированы: <b>{employee.name}</b>" if language == "ru" else f"\n✅ Та бүртгэгдсэн: <b>{employee.name}</b>"
    else:
        reg = {"en": "\n❗️You are not registered. Share this ID with your administrator.", "ru": "\n❗️Вы не зарегистрированы. Передайте этот ID администратору."}.get(language, "\n❗️Та бүртгэгдээгүй байна. Энэ ID-г удирдлагадаа өгнө үү.")
    heading = {"en": "🆔 Your Telegram ID", "ru": "🆔 Ваш Telegram ID"}.get(language, "🆔 Таны Telegram ID")
    username_label = {"en": "Username", "ru": "Имя пользователя"}.get(language, "Username")
    await message.answer(
        f"{heading}: <code>{u.id}</code>\n{username_label}: {uname}{reg}",
        parse_mode="HTML",
    )


@router.message(Command("help"))
async def cmd_help(message: Message, is_manager: bool = False, language: str = "mn"):
    if language == "en":
        tasks_block = (
            "\\n🤖 <b>OYUNS Agent</b>\\nAsk about tasks, plans, company information, or work writing in text or by voice.\\n\\n"
            "📝 <b>Tasks</b>\\n/task [@assignee] task description [when] — create task\\n"
            "/mytasks — my tasks\\n/assigned — tasks I assigned\\n/dashboard — task dashboard\\n"
            "/app — open workspace in Telegram\\n/done &lt;id&gt; — mark complete\\n"
            "/snooze &lt;id&gt; &lt;hours&gt; — postpone\\n/myid — my Telegram ID\\n"
        )
        text = ("👔 <b>Manager commands</b>\\n\\n/summary — yesterday’s summary\\n/week — weekly statistics\\n"
                "/blockers — key blockers\\n/monthly_digest — previous month’s report summary\\n" if is_manager else
                "📋 <b>Commands</b>\\n\\n/today — daily check-in\\n/daystart, /dayend — office work time\\n"
                "/remotestart, /remoteend — remote work time\\n/daypause — pause work time\\n"
                "/worktime — today’s work time\\n/my_stats — my statistics\\n/leaderboard — team leaderboard\\n/help — help\\n") + tasks_block
        await message.answer(text, parse_mode="HTML")
        return
    if language == "ru":
        tasks_block = (
            "\\n🤖 <b>OYUNS Agent</b>\\nЗадавайте текстом или голосом вопросы о задачах, планах, информации компании и рабочих текстах.\\n\\n"
            "📝 <b>Задачи</b>\\n/task [@исполнитель] описание задачи [срок] — создать задачу\\n"
            "/mytasks — мои задачи\\n/assigned — назначенные мной задачи\\n/dashboard — панель задач\\n"
            "/app — открыть рабочее пространство в Telegram\\n/done &lt;id&gt; — отметить выполненной\\n"
            "/snooze &lt;id&gt; &lt;часы&gt; — отложить\\n/myid — мой Telegram ID\\n"
        )
        text = ("👔 <b>Команды руководителя</b>\\n\\n/summary — сводка за вчера\\n/week — статистика за неделю\\n"
                "/blockers — основные проблемы\\n/monthly_digest — сводка отчётов за прошлый месяц\\n" if is_manager else
                "📋 <b>Команды</b>\\n\\n/today — ежедневный опрос\\n/daystart, /dayend — учёт работы в офисе\\n"
                "/remotestart, /remoteend — удалённая работа\\n/daypause — приостановить учёт времени\\n"
                "/worktime — рабочее время за сегодня\\n/my_stats — моя статистика\\n/leaderboard — рейтинг команды\\n/help — справка\\n") + tasks_block
        await message.answer(text, parse_mode="HTML")
        return
    tasks_block = (
        "\n🤖 <b>OYUNS agent</b>\n"
        "Энгийн текст эсвэл дуу хоолойгоор даалгавар, төлөвлөгөө, "
        "компаний мэдээлэл болон ажлын бичвэр хүсэж болно.\n\n"
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
            "/monthly_digest — өмнөх сарын тайлангийн хураангуй\n"
            + tasks_block
        )
    else:
        text = (
            "📋 <b>Командууд</b>\n\n"
            "/today — чек-ин бөглөх\n"
            "/daystart, /dayend — оффисын ажлын цаг\n"
            "/remotestart, /remoteend — remote ажлын цаг\n"
            "/daypause — ажлын цаг түр зогсоох\n"
            "/worktime — өнөөдрийн ажлын цагийн дэлгэрэнгүй\n"
            "/my_stats — миний статистик\n"
            "/leaderboard — багийн чансаа\n"
            "/help — энэ тусламж\n"
            + tasks_block
        )
    await message.answer(text, parse_mode="HTML")


# ─── Команды руководителя ────────────────────────────────────────────────────

CHECKIN_ONLY_PRIMARY = "ℹ️ Check-in асуулгын статистик танай байгууллагад идэвхгүй. Ажлын тайлан, даалгаврыг /dashboard, /app-аар харна уу."
CHECKIN_ONLY_PRIMARY_EN = "ℹ️ Check-in survey statistics are unavailable for your organization. View work reports and tasks with /dashboard or /app."
CHECKIN_ONLY_PRIMARY_RU = "ℹ️ Статистика опросов недоступна для вашей организации. Смотрите отчёты и задачи через /dashboard или /app."


def _checkin_only_primary(language: str) -> str:
    return {"en": CHECKIN_ONLY_PRIMARY_EN, "ru": CHECKIN_ONLY_PRIMARY_RU}.get(language, CHECKIN_ONLY_PRIMARY)


@router.message(Command("summary"))
async def cmd_summary(message: Message, is_manager: bool = False, bot_tenant_id: int | None = None, language: str = "mn"):
    if not is_manager:
        await message.answer({"en": "❌ This command is for managers only.", "ru": "❌ Эта команда доступна только руководителям."}.get(language, "❌ Зөвхөн удирдлагад зориулсан команд."))
        return
    if not is_primary_tenant(bot_tenant_id):
        await message.answer(_checkin_only_primary(language))
        return
    data = get_yesterday_summary(bot_tenant_id)
    heading = {"en": "summary", "ru": "сводка"}.get(language, "хураангуй")
    lines = [f"📊 <b>{data['date']} {heading}</b>\n"]
    for q_text, val in data["totals"].items():
        lines.append(f"• {q_text[:35]}: <b>{val}</b>")
    if data["missed"]:
        missing_label = {"en": "Not completed", "ru": "Не заполнено"}.get(language, "Бөглөөгүй")
        lines.append(f"\n⚠️ {missing_label}: {', '.join(data['missed'])}")
    empty = {"en": "No data for yesterday.", "ru": "За вчерашний день данных нет."}.get(language, "Өчигдрийн мэдээлэл алга.")
    await message.answer("\n".join(lines) or empty, parse_mode="HTML")


@router.message(Command("week"))
async def cmd_week(message: Message, is_manager: bool = False, bot_tenant_id: int | None = None, language: str = "mn"):
    if not is_manager:
        await message.answer({"en": "❌ This command is for managers only.", "ru": "❌ Эта команда доступна только руководителям."}.get(language, "❌ Зөвхөн удирдлагад зориулсан команд."))
        return
    if not is_primary_tenant(bot_tenant_id):
        await message.answer(_checkin_only_primary(language))
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

    lines = [{"en": "📅 <b>Check-ins completed in the last 7 days</b>\n", "ru": "📅 <b>Опросы за последние 7 дней</b>\n"}.get(language, "📅 <b>Сүүлийн 7 хоногийн бөглөлт</b>\n")]
    for name, cnt in rows:
        lines.append(f"• {name}: {cnt}/7" if language in {"en", "ru"} else f"• {name}: 7-оос {cnt}")
    await message.answer("\n".join(lines) or {"en": "No data.", "ru": "Нет данных."}.get(language, "Мэдээлэл алга."), parse_mode="HTML")


@router.message(Command("blockers"))
async def cmd_blockers(message: Message, is_manager: bool = False, bot_tenant_id: int | None = None, language: str = "mn"):
    if not is_manager:
        await message.answer({"en": "❌ This command is for managers only.", "ru": "❌ Эта команда доступна только руководителям."}.get(language, "❌ Зөвхөн удирдлагад зориулсан команд."))
        return
    if not is_primary_tenant(bot_tenant_id):
        await message.answer(_checkin_only_primary(language))
        return

    with get_session() as s:
        month_ago = date.today() - timedelta(days=30)
        text_qs = list(s.execute(select(Question).where(Question.answer_type == "text")).scalars())
        if not text_qs:
            await message.answer({"en": "No text questions are configured.", "ru": "Текстовые вопросы не настроены."}.get(language, "Текстэн асуулт алга."))
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

    lines = [{"en": "🚧 <b>Top blockers this month</b>\n", "ru": "🚧 <b>Основные препятствия за месяц</b>\n"}.get(language, "🚧 <b>Сарын гол саад бэрхшээлүүд</b>\n")]
    for text_val, cnt in rows:
        lines.append(f"• {text_val[:50]} — {cnt}×")
    await message.answer("\n".join(lines) or {"en": "No data.", "ru": "Нет данных."}.get(language, "Мэдээлэл алга."), parse_mode="HTML")
