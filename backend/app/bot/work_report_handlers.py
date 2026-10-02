"""Telegram flow for daily work logs and monthly free-form reports."""
from __future__ import annotations

from datetime import date, datetime, timezone
from html import escape

import pytz
from aiogram import F, Router
from aiogram.filters import Command, Filter, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, Message, ReplyKeyboardMarkup, ReplyKeyboardRemove

from app.bot.db import get_manager_settings
from app.models.models import WorkReport
from app.services import work_report_service
from app.services.manager_recipients import manager_telegram_ids
from app.services.monthly_report_digest_service import (
    previous_month,
    seed_dummy_monthly_test_reports,
    try_send_monthly_report_digest,
)

router = Router()


class TestReportFlow(StatesGroup):
    daily_report = State()
    monthly_report = State()
    next_month_plan = State()


class DayStartFlow(StatesGroup):
    awaiting_location = State()


def _local_now(timezone_name: str | None) -> datetime:
    try:
        zone = pytz.timezone(timezone_name or "Asia/Ulaanbaatar")
    except Exception:
        zone = pytz.timezone("Asia/Ulaanbaatar")
    return datetime.now(zone)


def draft_keyboard(report_id: int, language: str = "mn") -> InlineKeyboardMarkup:
    labels = {
        "en": ("✅ Approve", "✏️ Edit", "🗑 Delete"),
        "ru": ("✅ Утвердить", "✏️ Изменить", "🗑 Удалить"),
    }.get(language, ("✅ Батлах", "✏️ Засах", "🗑 Устгах"))
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=labels[0], callback_data=f"wrdraft:{report_id}:approve"),
        InlineKeyboardButton(text=labels[1], callback_data=f"wrdraft:{report_id}:edit"),
        InlineKeyboardButton(text=labels[2], callback_data=f"wrdraft:{report_id}:delete"),
    ]])


def checkin_keyboard(is_test: bool = False, language: str = "mn") -> InlineKeyboardMarkup:
    """Start the scheduled check-in without asking the worker to type /today."""
    label = {"en": "📋 Start check-in", "ru": "📋 Начать опрос"}.get(language, "📋 Чек-ин бөглөх")
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text=label,
            callback_data="checkin:start:test" if is_test else "checkin:start",
        ),
    ]])


def day_start_location_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📍 Байршил илгээх", request_location=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder="Оффисын байршлаа илгээнэ үү",
    )


_REPORT_LABELS = {
    "weekly": {"en": "Weekly report", "ru": "Еженедельный отчёт"},
    "quarterly": {"en": "Quarterly report", "ru": "Квартальный отчёт"},
    "half_yearly": {"en": "Semiannual report", "ru": "Полугодовой отчёт"},
    "yearly": {"en": "Annual report", "ru": "Годовой отчёт"},
    "custom": {"en": "Custom-period report", "ru": "Отчёт за выбранный период"},
}


def _prompt_text(report_type: str, prompt_type: str | None = None, language: str = "mn") -> str:
    test_prefix = "🧪 <b>ТЕСТ</b> — " if report_type.endswith("_test") else ""
    if language in {"en", "ru"}:
        test_prefix = "🧪 <b>TEST</b> — " if language == "en" and report_type.endswith("_test") else "🧪 <b>ТЕСТ</b> — " if report_type.endswith("_test") else ""
        is_en = language == "en"
        if report_type in {"daily", "daily_test"}:
            if prompt_type in {"daily_checkin", "test_daily_checkin"}:
                return f"{test_prefix}⏰ <b>Daily check-in</b>\n\nTap the button below to answer today's questions."
            return f"{test_prefix}📝 <b>Daily work report</b>\n\nReply to this message with a summary of the work you completed today."
        if report_type in {"monthly", "monthly_test"}:
            heading = "Monthly report" if is_en else "Ежемесячный отчёт"
            body = "Reply to this message with your report for the month." if is_en else "Ответьте на это сообщение и напишите отчёт за месяц."
            return f"{test_prefix}📅 <b>{heading}</b>\n\n{body}"
        if report_type in _REPORT_LABELS:
            heading = _REPORT_LABELS[report_type][language]
            body = "Reply to this message with your report for the period." if is_en else "Ответьте на это сообщение и напишите отчёт за период."
            return f"📅 <b>{heading}</b>\n\n{body}"
        heading = "Next-month plan" if is_en else "План на следующий месяц"
        body = "Is there anything to include in next month's plan? Reply to this message." if is_en else "Что следует включить в план на следующий месяц? Ответьте на это сообщение."
        return f"{test_prefix}📌 <b>{heading}</b>\n\n{body}"
    if report_type in {"daily", "daily_test"}:
        if prompt_type in {"daily_checkin", "test_daily_checkin"}:
            return (
                f"{test_prefix}⏰ <b>Өдрийн чек-ин</b>\n\n"
                "Доорх товчийг дарж өнөөдрийн асуултуудад хариулна уу."
            )
        return (
            f"{test_prefix}📝 <b>Өдрийн ажлын тайлан</b>\n\n"
            "Өнөөдөр хийсэн ажлаа энэ мессежид <b>Reply</b> хийж бичнэ үү."
        )
    if report_type in {"monthly", "monthly_test"}:
        return f"{test_prefix}📅 <b>Сарын тайлан</b>\n\nСарын тайлангаа энэ мессежид <b>Reply</b> хийж бичнэ үү."
    if report_type in PERIODIC_LABELS:
        return f"📅 <b>{PERIODIC_LABELS[report_type]}</b>\n\nТайлангаа энэ мессежид <b>Reply</b> хийж бичнэ үү."
    return f"{test_prefix}📌 <b>Дараа сарын төлөвлөгөө</b>\n\nДараа сарын төлөвлөгөөнд тусгах зүйл байна уу? Энэ мессежид <b>Reply</b> хийж бичнэ үү."


PERIODIC_LABELS = {
    "weekly": "7 хоногийн тайлан",
    "quarterly": "Улирлын тайлан",
    "half_yearly": "Хагас жилийн тайлан",
    "yearly": "Жилийн тайлан",
    "custom": "Тусгай хугацааны тайлан",
}


def _report_prompt_text(report: WorkReport, prompt_type: str | None = None, language: str = "mn") -> str:
    text = _prompt_text(report.report_type, prompt_type, language)
    period_end = getattr(report, "period_end", None)
    if getattr(report, "department_id", None):
        department_label = {"en": " (department)", "ru": " (отдел)"}.get(language, " (хэлтсийн)")
        text = text.replace("</b>", f"{department_label}</b>", 1)
    if period_end and report.report_type in PERIODIC_LABELS:
        period_label = {"en": "Period", "ru": "Период"}.get(language, "Хугацаа")
        text += f"\n\n🗓 {period_label}: {report.period_date.isoformat()} – {period_end.isoformat()}"
    return text


async def send_report_prompt(
    bot,
    report: WorkReport,
    *,
    telegram_chat_id: str,
    prompt_type: str,
    local_day: date,
) -> bool:
    """Send at most one prompt per report/type/local date."""
    prompt = work_report_service.reserve_prompt(
        report.id,
        prompt_type=prompt_type,
        prompt_date=local_day,
        telegram_chat_id=str(telegram_chat_id),
    )
    if prompt is None:
        return False
    try:
        from app.bot.db import get_session
        from app.core.localization import resolve_language
        from app.core.tenancy import system_scope
        from app.models.models import Employee, UserAccount

        with system_scope(), get_session() as db:
            employee = db.get(Employee, report.employee_id)
            account = db.query(UserAccount).filter(
                UserAccount.employee_id == report.employee_id,
                UserAccount.organization_id == employee.organization_id if employee else False,
                UserAccount.status == "active",
            ).one_or_none()
            language = resolve_language(account.locale if account else None, employee.primary_language if employee else None)
        markup = None
        if prompt_type in {"daily_checkin", "test_daily_checkin"}:
            markup = checkin_keyboard(report.report_type == "daily_test", language)
        sent = await bot.send_message(
            telegram_chat_id,
            _report_prompt_text(report, prompt_type, language),
            parse_mode="HTML",
            reply_markup=markup,
        )
        work_report_service.set_prompt_message_id(prompt.id, sent.message_id)
        return True
    except Exception:
        work_report_service.release_reserved_prompt(prompt.id)
        raise


async def send_daily_prompts(
    bot,
    report: WorkReport,
    *,
    telegram_chat_id: str,
    local_day: date,
) -> list[str]:
    """Start the daily flow with only its first prompt.

    The remaining prompts are sent by the completion handlers.  Keeping the
    scheduler to one prompt prevents Telegram from receiving the whole flow
    as a burst before the employee has answered anything.
    """
    is_test = report.report_type == "daily_test"
    prefix = "test_" if is_test else ""
    label = "өдрийн чек-ин"
    if await send_report_prompt(
        bot,
        report,
        telegram_chat_id=telegram_chat_id,
        prompt_type=f"{prefix}daily_checkin",
        local_day=local_day,
    ):
        return [label]
    return []


async def send_test_daily_report_prompt(
    bot,
    *,
    state: FSMContext | None = None,
    employee_id: int,
    telegram_chat_id: str,
    local_day: date,
) -> bool:
    """Advance the isolated daily test after its test check-in is completed."""
    report = work_report_service.get_or_create_report(employee_id, "daily_test", local_day)
    if state is not None:
        await state.set_state(TestReportFlow.daily_report)
    return await send_report_prompt(
        bot,
        report,
        telegram_chat_id=telegram_chat_id,
        prompt_type="test_daily_report",
        local_day=local_day,
    )


def _draft_text(report: WorkReport, text: str, language: str = "mn") -> str:
    label = {
        "daily": "Өдрийн тайлан", "monthly": "Сарын тайлан", "next_month_plan": "Дараа сарын төлөвлөгөө",
        "daily_test": "Өдрийн тайлангийн тест", "monthly_test": "Сарын тайлангийн тест", "next_month_plan_test": "Дараа сарын төлөвлөгөөний тест",
        **PERIODIC_LABELS,
    }.get(report.report_type, "Тайлан")
    if language in {"en", "ru"}:
        localized = {
            "daily": {"en": "Daily report", "ru": "Ежедневный отчёт"},
            "monthly": {"en": "Monthly report", "ru": "Ежемесячный отчёт"},
            "next_month_plan": {"en": "Next-month plan", "ru": "План на следующий месяц"},
            "daily_test": {"en": "Daily report test", "ru": "Тест ежедневного отчёта"},
            "monthly_test": {"en": "Monthly report test", "ru": "Тест ежемесячного отчёта"},
            "next_month_plan_test": {"en": "Next-month plan test", "ru": "Тест плана на следующий месяц"},
        }
        label = localized.get(report.report_type, _REPORT_LABELS.get(report.report_type, {}).get(language, "Report" if language == "en" else "Отчёт"))
        heading_suffix = "draft" if language == "en" else "черновик"
        action_hint = "Use the buttons below to approve, edit, or delete this draft." if language == "en" else "Используйте кнопки ниже, чтобы утвердить, изменить или удалить черновик."
        return f"📝 <b>{label} — {heading_suffix}</b>\n\n{escape(text)}\n\n{action_hint}"
    return f"📝 <b>{label} — ноорог</b>\n\n{escape(text)}\n\nДоорх товчоор батлах, засах эсвэл устгана уу."


class ReportPromptReply(Filter):
    async def __call__(self, message: Message, employee=None, **_) -> dict | bool:
        if not employee:
            return False
        if message.reply_to_message:
            report = work_report_service.report_for_reply(
                employee.id, str(message.chat.id), message.reply_to_message.message_id
            ) or work_report_service.awaiting_report_for_message(employee.id, str(message.chat.id))
        else:
            report = work_report_service.awaiting_report_for_message(employee.id, str(message.chat.id))
        return {"work_report": report} if report else False


class EditingReport(Filter):
    async def __call__(self, message: Message, employee=None, **_) -> dict | bool:
        if not employee:
            return False
        report = work_report_service.editing_report_for_employee(employee.id)
        return {"work_report": report} if report else False


async def _show_report_draft(message: Message, report: WorkReport, state: FSMContext, language: str = "mn") -> None:
    revision = work_report_service.add_draft(report.id, message.text or "")
    if not revision:
        await message.answer({"en": "⚠️ The report text cannot be empty.", "ru": "⚠️ Текст отчёта не может быть пустым."}.get(language, "⚠️ Тайлангийн текст хоосон байна."))
        return
    await state.clear()
    await message.answer(_draft_text(report, revision.text, language), parse_mode="HTML", reply_markup=draft_keyboard(report.id, language))


async def claim_report_text(message: Message, state: FSMContext, employee=None, language: str = "mn") -> bool:
    """Claim report text before the general assistant can process it.

    The report router normally claims these messages through ``ReportPromptReply``.
    This explicit entry point is also used by the assistant router as a safety
    net for Telegram updates where reply metadata is missing or the nested
    router did not run. It uses the same DB lookup and never guesses from text.
    """
    if not employee or not message.text or message.text.startswith("/"):
        return False
    if message.reply_to_message:
        report = work_report_service.report_for_reply(
            employee.id, str(message.chat.id), message.reply_to_message.message_id
        ) or work_report_service.awaiting_report_for_message(employee.id, str(message.chat.id))
    else:
        report = work_report_service.awaiting_report_for_message(employee.id, str(message.chat.id))
    if report:
        await _show_report_draft(message, report, state, language)
        return True

    editing = work_report_service.editing_report_for_employee(employee.id)
    if editing:
        await _show_report_draft(message, editing, state, language)
        return True
    return False


@router.message(StateFilter(TestReportFlow.daily_report), F.text & ~F.text.startswith("/"))
async def test_daily_report_text(message: Message, state: FSMContext, employee=None, language: str = "mn"):
    report = work_report_service.awaiting_report_for_employee_type(employee.id, "daily_test") if employee else None
    if not report:
        await state.clear()
        await message.answer({"en": "⚠️ No daily report test is waiting. Start again with /test_daily.", "ru": "⚠️ Тест ежедневного отчёта не найден. Запустите его командой /test_daily."}.get(language, "⚠️ Өдрийн тайлангийн тестийн хүсэлт олдсонгүй. /test_daily гэж дахин эхлүүлнэ үү."))
        return
    await _show_report_draft(message, report, state, language)


@router.message(StateFilter(TestReportFlow.monthly_report), F.text & ~F.text.startswith("/"))
async def test_monthly_report_text(message: Message, state: FSMContext, employee=None, language: str = "mn"):
    report = work_report_service.awaiting_report_for_employee_type(employee.id, "monthly_test") if employee else None
    if not report:
        await state.clear()
        await message.answer({"en": "⚠️ No monthly report test is waiting. Start again with /test_monthly.", "ru": "⚠️ Тест ежемесячного отчёта не найден. Запустите его командой /test_monthly."}.get(language, "⚠️ Сарын тайлангийн тестийн хүсэлт олдсонгүй. /test_monthly гэж дахин эхлүүлнэ үү."))
        return
    await _show_report_draft(message, report, state, language)


@router.message(StateFilter(TestReportFlow.next_month_plan), F.text & ~F.text.startswith("/"))
async def test_next_month_plan_text(message: Message, state: FSMContext, employee=None, language: str = "mn"):
    report = work_report_service.awaiting_report_for_employee_type(employee.id, "next_month_plan_test") if employee else None
    if not report:
        await state.clear()
        await message.answer({"en": "⚠️ No plan test is waiting. Start again with /test_monthly.", "ru": "⚠️ Тест плана не найден. Запустите его командой /test_monthly."}.get(language, "⚠️ Төлөвлөгөөний тестийн хүсэлт олдсонгүй. /test_monthly гэж дахин эхлүүлнэ үү."))
        return
    await _show_report_draft(message, report, state, language)


@router.message(F.text & ~F.text.startswith("/"), ReportPromptReply())
async def report_prompt_reply(message: Message, work_report: WorkReport, language: str = "mn"):
    # Normal report flows are not FSM-bound; preserve their existing behavior.
    revision = work_report_service.add_draft(work_report.id, message.text or "")
    if not revision:
        await message.answer({"en": "⚠️ The report text cannot be empty.", "ru": "⚠️ Текст отчёта не может быть пустым."}.get(language, "⚠️ Тайлангийн текст хоосон байна."))
        return
    await message.answer(_draft_text(work_report, revision.text, language), parse_mode="HTML", reply_markup=draft_keyboard(work_report.id, language))


@router.message(F.text & ~F.text.startswith("/"), EditingReport())
async def edit_report_text(message: Message, work_report: WorkReport, language: str = "mn"):
    revision = work_report_service.add_draft(work_report.id, message.text or "")
    if not revision:
        await message.answer({"en": "⚠️ The revision text cannot be empty.", "ru": "⚠️ Текст исправления не может быть пустым."}.get(language, "⚠️ Засварын текст хоосон байна."))
        return
    await message.answer(_draft_text(work_report, revision.text, language), parse_mode="HTML", reply_markup=draft_keyboard(work_report.id, language))


def _mode_label(mode: str, language: str = "mn") -> str:
    return {"en": "office" if mode == "in_person" else "remote", "ru": "офис" if mode == "in_person" else "удалённая"}.get(language, "оффис" if mode == "in_person" else "remote")


def _work_time_summary_text(summary: dict, tz, language: str = "mn") -> str:
    labels = {
        "en": {"today": "Today's work time", "office": "Office", "remote": "Remote", "details": "Details", "break": "Break", "now": "now", "hours": "h", "minutes": "m"},
        "ru": {"today": "Рабочее время за сегодня", "office": "Офис", "remote": "Удалённо", "details": "Подробности", "break": "Перерыв", "now": "сейчас", "hours": "ч", "minutes": "мин"},
        "mn": {"today": "Өнөөдрийн ажлын цаг", "office": "Оффис", "remote": "Remote", "details": "Дэлгэрэнгүй", "break": "завсарлага", "now": "одоо", "hours": "ц", "minutes": "м"},
    }[language if language in {"en", "ru"} else "mn"]
    def duration(minutes: int) -> str:
        return f"{minutes // 60}{labels['hours']} {minutes % 60}{labels['minutes']}"
    lines = [
        f"📊 <b>{labels['today']}</b>: {duration(summary['total_minutes'])}",
        f"🏢 {labels['office']}: {duration(summary['in_person_minutes'])}",
        f"🏠 {labels['remote']}: {duration(summary['remote_minutes'])}",
    ]
    if summary["entries"]:
        lines.append(f"\n<b>{labels['details']}:</b>")
        for entry in summary["entries"]:
            start = entry["started_at"].astimezone(tz).strftime("%H:%M")
            end = entry["ended_at"].astimezone(tz).strftime("%H:%M") if entry["ended_at"] else labels["now"]
            label = labels["break"] if entry.get("entry_type") == "break" else _mode_label(entry["mode"], language)
            lines.append(f"• {label}: {start}–{end} ({entry['minutes']}{labels['minutes']})")
    return "\n".join(lines)


async def _change_work_time(message: Message, employee, mode: str, action: str, *, latitude: float | None = None, longitude: float | None = None, clear_location_keyboard: bool = False, language: str = "mn") -> None:
    reply_markup = ReplyKeyboardRemove() if clear_location_keyboard else None
    if not employee:
        await message.answer({"en": "❌ You are not registered in the system.", "ru": "❌ Вы не зарегистрированы в системе."}.get(language, "❌ Та бүртгэгдээгүй байна."), reply_markup=reply_markup)
        return
    local_now = _local_now(employee.timezone)
    at = local_now.astimezone(timezone.utc)
    if action == "start":
        result, entry = work_report_service.start_work_time(employee.id, local_now.date(), mode, at, latitude=latitude, longitude=longitude)
    else:
        result, entry = work_report_service.end_work_time(employee.id, local_now.date(), mode, at)
    other_end = "/dayend" if mode == "remote" else "/remoteend"
    matching_start = "/daystart" if mode == "in_person" else "/remotestart"
    if result == "worktime_geofence_not_configured":
        await message.answer({"en": "⚠️ Ask an administrator to save the office location in settings before starting work.", "ru": "⚠️ Попросите администратора сохранить местоположение офиса в настройках, прежде чем начинать работу."}.get(language, "⚠️ Оффисын байршлыг админ тохиргоонд хадгалсны дараа ажил эхлүүлнэ үү."), reply_markup=reply_markup)
        return
    if result == "worktime_location_disabled":
        await message.answer({"en": "⚠️ Location check-in is disabled. Scan the office QR code in OYUNS Worktime to start your shift.", "ru": "⚠️ Отметка по местоположению отключена. Отсканируйте офисный QR-код в OYUNS Worktime, чтобы начать работу."}.get(language, "⚠️ Байршлаар бүртгэх боломжийг хаасан байна. Оффисын QR кодыг OYUNS Worktime-аар уншуулж ажлаа эхлүүлнэ үү."), reply_markup=reply_markup)
        return
    if result == "worktime_location_required":
        await message.answer({"en": "⚠️ Use Telegram's location-sharing button to start work.", "ru": "⚠️ Чтобы начать работу, отправьте местоположение с помощью кнопки Telegram."}.get(language, "⚠️ Ажил эхлүүлэхийн тулд Telegram-ийн байршил илгээх товчийг ашиглана уу."), reply_markup=reply_markup)
        return
    if result == "outside_worktime_geofence":
        await message.answer({"en": "⚠️ You are outside the office's allowed area. Move within the area and run /daystart again.", "ru": "⚠️ Вы находитесь за пределами разрешённой зоны офиса. Перейдите в эту зону и повторите команду /daystart."}.get(language, "⚠️ Та оффисын тохируулсан периметрээс хол байна. Периметр дотор очоод /daystart командыг дахин ашиглана уу."), reply_markup=reply_markup)
        return
    if result == "other_active":
        await message.answer(
            ({"en": f"⚠️ Your {_mode_label(entry.mode, language)} work session is already active. End it with <b>{other_end}</b> first.", "ru": f"⚠️ Ваша {_mode_label(entry.mode, language)} рабочая сессия уже активна. Сначала завершите её командой <b>{other_end}</b>."}.get(language) or f"⚠️ {_mode_label(entry.mode).capitalize()} ажил одоо үргэлжилж байна. Эхлээд <b>{other_end}</b> командаар дуусгана уу."), parse_mode="HTML", reply_markup=reply_markup
        )
        return
    if result == "already_active":
        await message.answer(
            ({"en": f"ℹ️ Your {_mode_label(mode, language)} work session has already started. Use <b>{other_end}</b> when you finish.", "ru": f"ℹ️ Ваша рабочая сессия ({_mode_label(mode, language)}) уже началась. Завершите её командой <b>{other_end}</b>."}.get(language) or f"ℹ️ {_mode_label(mode).capitalize()} ажил аль хэдийн эхэлсэн байна. Дуусгахдаа <b>{other_end}</b> ашиглана уу."), parse_mode="HTML", reply_markup=reply_markup
        )
        return
    if result == "not_started":
        await message.answer(
            ({"en": f"⚠️ Your {_mode_label(mode, language)} work session has not started today. Start it with <b>{matching_start}</b> first.", "ru": f"⚠️ Сегодня ваша рабочая сессия ({_mode_label(mode, language)}) ещё не началась. Сначала используйте <b>{matching_start}</b>."}.get(language) or f"⚠️ Өнөөдөр {_mode_label(mode)} ажил эхлээгүй байна. Эхлээд <b>{matching_start}</b> командыг ашиглана уу."), parse_mode="HTML", reply_markup=reply_markup
        )
        return
    summary = work_report_service.summarize_work_time(
        work_report_service.work_time_entries(entry.report_id), now=at
    )
    if action == "start":
        await message.answer(
            ({"en": f"✅ Your {_mode_label(mode, language)} work session started at <b>{local_now:%H:%M}</b>.", "ru": f"✅ Рабочая сессия ({_mode_label(mode, language)}) началась в <b>{local_now:%H:%M}</b>."}.get(language) or f"✅ {_mode_label(mode).capitalize()} ажил эхэллээ: <b>{local_now:%H:%M}</b>"),
            parse_mode="HTML", reply_markup=reply_markup,
        )
    else:
        await message.answer(
            ({"en": f"✅ Your {_mode_label(mode, language)} work session ended at <b>{local_now:%H:%M}</b>.\n\n{_work_time_summary_text(summary, local_now.tzinfo, language)}", "ru": f"✅ Рабочая сессия ({_mode_label(mode, language)}) завершена в <b>{local_now:%H:%M}</b>.\n\n{_work_time_summary_text(summary, local_now.tzinfo, language)}"}.get(language) or f"✅ {_mode_label(mode).capitalize()} ажил дууслаа: <b>{local_now:%H:%M}</b>\n\n{_work_time_summary_text(summary, local_now.tzinfo, language)}"),
            parse_mode="HTML", reply_markup=reply_markup,
        )


async def _show_work_time(message: Message, employee=None, language: str = "mn") -> None:
    if not employee:
        await message.answer({"en": "❌ You are not registered in the system.", "ru": "❌ Вы не зарегистрированы в системе."}.get(language, "❌ Та бүртгэгдээгүй байна."))
        return
    local_now = _local_now(employee.timezone)
    report = work_report_service.get_or_create_report(employee.id, "daily", local_now.date())
    summary = work_report_service.summarize_work_time(
        work_report_service.work_time_entries(report.id),
        now=local_now.astimezone(timezone.utc),
    )
    await message.answer(_work_time_summary_text(summary, local_now.tzinfo, language), parse_mode="HTML")


@router.message(Command("daystart"))
async def cmd_daystart(message: Message, state: FSMContext, employee=None, language: str = "mn"):
    if not employee:
        await message.answer({"en": "❌ You are not registered in the system.", "ru": "❌ Вы не зарегистрированы в системе."}.get(language, "❌ Та бүртгэгдээгүй байна."))
        return
    await state.set_state(DayStartFlow.awaiting_location)
    await message.answer(
        {"en": "📍 To start working at the office, use the button below to share your current location.", "ru": "📍 Чтобы начать работу в офисе, отправьте своё текущее местоположение с помощью кнопки ниже."}.get(language, "📍 Оффисын ажил эхлүүлэхийн тулд доорх товчийг дарж одоогийн байршлаа илгээнэ үү."),
        reply_markup=day_start_location_keyboard(),
    )


@router.message(DayStartFlow.awaiting_location, F.location)
async def msg_daystart_location(message: Message, state: FSMContext, employee=None, language: str = "mn"):
    location = message.location
    await state.clear()
    await _change_work_time(
        message,
        employee,
        "in_person",
        "start",
        latitude=location.latitude if location else None,
        longitude=location.longitude if location else None,
        clear_location_keyboard=True,
        language=language,
    )


@router.message(Command("dayend"))
async def cmd_dayend(message: Message, employee=None, language: str = "mn"):
    await _change_work_time(message, employee, "in_person", "end", language=language)


@router.message(Command("remotestart"))
async def cmd_remotestart(message: Message, employee=None, language: str = "mn"):
    await _change_work_time(message, employee, "remote", "start", language=language)


@router.message(Command("remoteend"))
async def cmd_remoteend(message: Message, employee=None, language: str = "mn"):
    await _change_work_time(message, employee, "remote", "end", language=language)


@router.message(Command("daypause"))
async def cmd_daypause(message: Message, employee=None, language: str = "mn"):
    if not employee:
        await message.answer({"en": "❌ You are not registered in the system.", "ru": "❌ Вы не зарегистрированы в системе."}.get(language, "❌ Та бүртгэгдээгүй байна."))
        return
    local_now = _local_now(employee.timezone)
    result, _ = work_report_service.pause_work_time(employee.id, local_now.date(), local_now.astimezone(timezone.utc))
    if result == "not_started":
        await message.answer({"en": "⚠️ Start your work session first with /daystart or /remotestart.", "ru": "⚠️ Сначала начните рабочую сессию командой /daystart или /remotestart."}.get(language, "⚠️ Эхлээд /daystart эсвэл /remotestart ашиглана уу."))
    elif result == "already_paused":
        await message.answer({"en": "ℹ️ Work time is already paused.", "ru": "ℹ️ Учёт рабочего времени уже приостановлен."}.get(language, "ℹ️ Ажлын цаг аль хэдийн түр зогссон байна."))
    else:
        await message.answer({"en": "⏸ Work time paused. Resume with /daystart or /remotestart.", "ru": "⏸ Учёт времени приостановлен. Продолжите командой /daystart или /remotestart."}.get(language, "⏸ Ажлын цаг түр зогслоо. /daystart эсвэл /remotestart командаар үргэлжлүүлнэ үү."))


@router.message(Command("worktime"))
async def cmd_worktime(message: Message, employee=None, language: str = "mn"):
    await _show_work_time(message, employee, language)


@router.callback_query(F.data.startswith("wrdraft:"))
async def report_draft_action(cb: CallbackQuery, state: FSMContext, employee=None, language: str = "mn"):
    copy = {
        "en": {"invalid": "Invalid request", "owner": "This draft does not belong to you.", "edit_prompt": "✏️ Send your revised report now.", "edit_missing": "Draft not found for editing.", "deleted": "Draft deleted.", "delete_body": "🗑 Draft deleted. Reply to the original reminder to submit it again.", "delete_missing": "Draft not found for deletion.", "approve_missing": "Draft not found for approval.", "approved": "Report approved.", "saved": "✅ Report saved."},
        "ru": {"invalid": "Неверный запрос", "owner": "Этот черновик принадлежит не вам.", "edit_prompt": "✏️ Отправьте исправленный отчёт.", "edit_missing": "Черновик для редактирования не найден.", "deleted": "Черновик удалён.", "delete_body": "🗑 Черновик удалён. Ответьте на исходное напоминание, чтобы отправить отчёт снова.", "delete_missing": "Черновик для удаления не найден.", "approve_missing": "Черновик для утверждения не найден.", "approved": "Отчёт утверждён.", "saved": "✅ Отчёт сохранён."},
    }.get(language, {"invalid": "Буруу хүсэлт", "owner": "Энэ ноорог танд хамаарахгүй.", "edit_prompt": "✏️ Зассан тайлангаа одоо бичиж илгээнэ үү.", "edit_missing": "Засах ноорог олдсонгүй.", "deleted": "Ноорог устгагдлаа.", "delete_body": "🗑 Ноорог устгагдлаа. Анхны сануулга мессежид Reply хийж дахин бичиж болно.", "delete_missing": "Устгах ноорог олдсонгүй.", "approve_missing": "Батлах ноорог олдсонгүй.", "approved": "Тайлан батлагдлаа.", "saved": "✅ Тайлан хадгалагдлаа."})
    try:
        _, report_id_raw, action = (cb.data or "").split(":", 2)
        report_id = int(report_id_raw)
    except (ValueError, AttributeError):
        await cb.answer(copy["invalid"], show_alert=True)
        return
    report = work_report_service.get_report(report_id)
    if not employee or not report or report.employee_id != employee.id:
        await cb.answer(copy["owner"], show_alert=True)
        return
    if action == "edit":
        if work_report_service.begin_edit(report_id):
            await cb.answer()
            await cb.message.answer(copy["edit_prompt"])
        else:
            await cb.answer(copy["edit_missing"], show_alert=True)
        return
    if action == "delete":
        if work_report_service.delete_draft(report_id):
            await cb.answer(copy["deleted"])
            await cb.message.answer(copy["delete_body"])
        else:
            await cb.answer(copy["delete_missing"], show_alert=True)
        return
    if action != "approve":
        await cb.answer(copy["invalid"], show_alert=True)
        return
    approved = work_report_service.approve_draft(report_id)
    if not approved:
        await cb.answer(copy["approve_missing"], show_alert=True)
        return
    await cb.answer(copy["approved"])
    await cb.message.answer(copy["saved"])
    if approved.report_type == "next_month_plan":
        work_report_service.create_plan_idea_from_report(approved.id)
    if approved.report_type in {"monthly", "monthly_test"}:
        local_day = _local_now(employee.timezone).date()
        plan_type = "next_month_plan_test" if approved.report_type == "monthly_test" else "next_month_plan"
        plan = work_report_service.get_or_create_report(employee.id, plan_type, local_day)
        if approved.report_type == "monthly_test":
            await state.set_state(TestReportFlow.next_month_plan)
        await send_report_prompt(
            cb.bot,
            plan,
            telegram_chat_id=employee.telegram_id,
            prompt_type="next_month_plan_test" if plan_type.endswith("_test") else "next_month_plan",
            local_day=local_day,
        )


async def _test_manager_ready(message: Message, employee, is_manager: bool, language: str = "mn") -> bool:
    if not is_manager:
        await message.answer({"en": "❌ This command is for managers only.", "ru": "❌ Эта команда доступна только руководителям."}.get(language, "❌ Энэ команд зөвхөн удирдлагад зориулсан."))
        return False
    if not employee or not employee.is_active:
        await message.answer({"en": "⚠️ To run this test, the manager must also be registered as an active employee.", "ru": "⚠️ Чтобы запустить тест, руководитель должен быть зарегистрирован как действующий сотрудник."}.get(language, "⚠️ Тест ажиллуулахын тулд удирдлага идэвхтэй ажилтнаар бүртгэгдсэн байх шаардлагатай."))
        return False
    return True


@router.message(Command("test_daily"))
async def cmd_test_daily(message: Message, state: FSMContext, employee=None, is_manager: bool = False, language: str = "mn"):
    """Start only the sequential daily test: check-in → report → times."""
    if not await _test_manager_ready(message, employee, is_manager, language):
        return
    reset_count = work_report_service.reset_test_reports(frozenset({"daily_test"}))
    local_day = _local_now(employee.timezone).date()
    daily_report = work_report_service.get_or_create_report(employee.id, "daily_test", local_day)
    sent = await send_report_prompt(
        message.bot,
        daily_report,
        telegram_chat_id=employee.telegram_id,
        prompt_type="test_daily_checkin",
        local_day=local_day,
    )
    if sent:
        text = f"🧪 Cleared {reset_count} previous daily test(s). Complete the check-in first. Use /daystart, /dayend, /remotestart, and /remoteend to test work-time tracking." if language == "en" else f"🧪 Предыдущие тесты за день очищены ({reset_count}). Сначала пройдите опрос. Для проверки учёта времени используйте /daystart, /dayend, /remotestart и /remoteend." if language == "ru" else f"🧪 Өмнөх өдрийн тестийг цэвэрлэлээ ({reset_count}). Эхлээд чек-ин бөглөнө үү. Ажлын цаг бүртгэхдээ /daystart, /dayend, /remotestart, /remoteend командыг ашиглана уу."
        await message.answer(text)


@router.message(Command("test_monthly"))
async def cmd_test_monthly(message: Message, state: FSMContext, employee=None, is_manager: bool = False, language: str = "mn"):
    """Start only the sequential monthly report → next-month-plan test."""
    if not await _test_manager_ready(message, employee, is_manager, language):
        return
    reset_count = work_report_service.reset_test_reports(frozenset({"monthly_test", "next_month_plan_test"}))
    local_day = _local_now(employee.timezone).date()
    monthly_report = work_report_service.get_or_create_report(employee.id, "monthly_test", local_day)
    await state.set_state(TestReportFlow.monthly_report)
    sent = await send_report_prompt(
        message.bot,
        monthly_report,
        telegram_chat_id=employee.telegram_id,
        prompt_type="test_monthly_report",
        local_day=local_day,
    )
    if sent:
        text = f"🧪 Cleared {reset_count} previous monthly test(s). Check the monthly report reply → draft → approval flow. The next-month plan follows approval." if language == "en" else f"🧪 Предыдущие месячные тесты очищены ({reset_count}). Проверьте процесс: ответ на месячный отчёт → черновик → утверждение. После утверждения придёт план на следующий месяц." if language == "ru" else f"🧪 Өмнөх сарын тестийг цэвэрлэлээ ({reset_count}). Сарын тайлангийн Reply → ноорог → батлах урсгалыг шалгана уу. Баталсны дараа дараа сарын төлөвлөгөө ирнэ."
        await message.answer(text)


@router.message(Command("seed_monthly_digest"))
async def cmd_seed_monthly_digest(message: Message, is_manager: bool = False, language: str = "mn"):
    """Create dummy approved monthly-test reports without sending a digest."""
    if not is_manager:
        await message.answer({"en": "❌ This command is for managers only.", "ru": "❌ Эта команда доступна только руководителям."}.get(language, "❌ Энэ команд зөвхөн удирдлагад зориулсан."))
        return

    today = date.today()
    period = previous_month(today)
    worker_count = seed_dummy_monthly_test_reports(period)
    status = f"🧪 Created {worker_count} sample report(s) for {period.year}-{period.month:02d}.\nRun /test_monthly_digest next." if language == "en" else f"🧪 Создано тестовых отчётов: {worker_count} ({period.year}-{period.month:02d}).\nТеперь запустите /test_monthly_digest." if language == "ru" else f"🧪 {worker_count} dummy тайлан үүсгэлээ ({period.year}-{period.month:02d}).\nОдоо /test_monthly_digest командыг ажиллуулна уу."
    await message.answer(status)


@router.message(Command("test_monthly_digest"))
async def cmd_test_monthly_digest(message: Message, is_manager: bool = False, language: str = "mn"):
    """Send the real digest logic for already-seeded dummy reports."""
    if not is_manager:
        await message.answer({"en": "❌ This command is for managers only.", "ru": "❌ Эта команда доступна только руководителям."}.get(language, "❌ Энэ команд зөвхөн удирдлагад зориулсан."))
        return

    sent = await try_send_monthly_report_digest(
        date.today(),
        report_type="monthly_test",
        reserve=False,
        recipients=[str(message.chat.id)],
        test_mode=True,
    )
    if not sent:
        await message.answer({"en": "⚠️ No sample reports were found, or reports are not ready for all active employees. Run /seed_monthly_digest first.", "ru": "⚠️ Тестовые отчёты не найдены или отчёты готовы не для всех действующих сотрудников. Сначала выполните /seed_monthly_digest."}.get(language, "⚠️ Dummy тайлан олдсонгүй эсвэл бүх идэвхтэй ажилтны тайлан бэлэн биш байна. Эхлээд /seed_monthly_digest ажиллуулна уу."))


@router.message(Command("monthly_digest"))
async def cmd_monthly_digest(message: Message, is_manager: bool = False, language: str = "mn"):
    """Generate and send the real previous-month digest on demand.

    Authorization follows the caller's ERP role; delivery goes to the caller
    and the tenant's configured management recipients. ``reserve=False`` makes
    this an on-demand read; the scheduled once-per-period delivery guard does
    not prevent a manager from requesting the current digest again.
    """
    from app.bot.db import is_primary_tenant
    from app.core.tenancy import current_tenant_id

    if not is_manager:
        await message.answer({"en": "❌ This command is for managers only.", "ru": "❌ Эта команда доступна только руководителям."}.get(language, "❌ Энэ команд зөвхөн удирдлагад зориулсан."))
        return
    configured = manager_telegram_ids(get_manager_settings(), primary=is_primary_tenant(current_tenant_id()))
    recipients = list(dict.fromkeys([str(message.chat.id), *configured]))

    sent = await try_send_monthly_report_digest(
        date.today(),
        recipients=recipients,
        reserve=False,
    )
    if not sent:
        await message.answer({"en": "⚠️ Approved reports are not yet available for every active employee for the previous month.", "ru": "⚠️ Ещё не готовы утверждённые отчёты за прошлый месяц для всех действующих сотрудников."}.get(language, "⚠️ Өмнөх сарын бүх идэвхтэй ажилтны батлагдсан тайлан бэлэн болоогүй байна."))


@router.message(Command("test_reports"))
async def cmd_test_reports(message: Message, is_manager: bool = False, language: str = "mn"):
    """Point managers to the intentionally separate, sequential test flows."""
    if not is_manager:
        await message.answer({"en": "❌ This command is for managers only.", "ru": "❌ Эта команда доступна только руководителям."}.get(language, "❌ Энэ команд зөвхөн удирдлагад зориулсан."))
        return
    text = "🧪 Daily flow: /test_daily\n📅 Monthly flow: /test_monthly\n📊 Create sample reports: /seed_monthly_digest\n📊 Send sample digest: /test_monthly_digest" if language == "en" else "🧪 Ежедневный сценарий: /test_daily\n📅 Ежемесячный сценарий: /test_monthly\n📊 Создать тестовые отчёты: /seed_monthly_digest\n📊 Отправить тестовую сводку: /test_monthly_digest" if language == "ru" else "🧪 Өдрийн урсгал: /test_daily\n📅 Сарын урсгал: /test_monthly\n📊 Dummy тайлан үүсгэх: /seed_monthly_digest\n📊 Dummy хураангуй ажиллуулах: /test_monthly_digest"
    await message.answer(text)
