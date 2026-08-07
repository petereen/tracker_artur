"""Telegram flow for daily work logs and monthly free-form reports."""
from __future__ import annotations

from datetime import date, datetime, timezone
from html import escape

import pytz
from aiogram import F, Router
from aiogram.filters import Command, Filter, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.models.models import WorkReport
from app.services import work_report_service
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


def _local_now(timezone_name: str | None) -> datetime:
    try:
        zone = pytz.timezone(timezone_name or "Asia/Ulaanbaatar")
    except Exception:
        zone = pytz.timezone("Asia/Ulaanbaatar")
    return datetime.now(zone)


def draft_keyboard(report_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Батлах", callback_data=f"wrdraft:{report_id}:approve"),
        InlineKeyboardButton(text="✏️ Засах", callback_data=f"wrdraft:{report_id}:edit"),
        InlineKeyboardButton(text="🗑 Устгах", callback_data=f"wrdraft:{report_id}:delete"),
    ]])


def checkin_keyboard(is_test: bool = False) -> InlineKeyboardMarkup:
    """Start the scheduled check-in without asking the worker to type /today."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="📋 Чек-ин бөглөх",
            callback_data="checkin:start:test" if is_test else "checkin:start",
        ),
    ]])


def _prompt_text(report_type: str, prompt_type: str | None = None) -> str:
    test_prefix = "🧪 <b>ТЕСТ</b> — " if report_type.endswith("_test") else ""
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
    return f"{test_prefix}📌 <b>Дараа сарын төлөвлөгөө</b>\n\nДараа сарын төлөвлөгөөнд тусгах зүйл байна уу? Энэ мессежид <b>Reply</b> хийж бичнэ үү."


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
        markup = None
        if prompt_type in {"daily_checkin", "test_daily_checkin"}:
            markup = checkin_keyboard(report.report_type == "daily_test")
        sent = await bot.send_message(
            telegram_chat_id,
            _prompt_text(report.report_type, prompt_type),
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


def _draft_text(report: WorkReport, text: str) -> str:
    label = {
        "daily": "Өдрийн тайлан", "monthly": "Сарын тайлан", "next_month_plan": "Дараа сарын төлөвлөгөө",
        "daily_test": "Өдрийн тайлангийн тест", "monthly_test": "Сарын тайлангийн тест", "next_month_plan_test": "Дараа сарын төлөвлөгөөний тест",
    }[report.report_type]
    return f"📝 <b>{label} — ноорог</b>\n\n{escape(text)}\n\nДоорх товчоор батлах, засах эсвэл устгана уу."


class ReportPromptReply(Filter):
    async def __call__(self, message: Message, employee=None, **_) -> dict | bool:
        if not employee:
            return False
        if message.reply_to_message:
            report = work_report_service.report_for_reply(
                employee.id, str(message.chat.id), message.reply_to_message.message_id
            )
        else:
            report = work_report_service.awaiting_report_for_message(employee.id, str(message.chat.id))
        return {"work_report": report} if report else False


class EditingReport(Filter):
    async def __call__(self, message: Message, employee=None, **_) -> dict | bool:
        if not employee:
            return False
        report = work_report_service.editing_report_for_employee(employee.id)
        return {"work_report": report} if report else False


async def _show_report_draft(message: Message, report: WorkReport, state: FSMContext) -> None:
    revision = work_report_service.add_draft(report.id, message.text or "")
    if not revision:
        await message.answer("⚠️ Тайлангийн текст хоосон байна.")
        return
    await state.clear()
    await message.answer(_draft_text(report, revision.text), parse_mode="HTML", reply_markup=draft_keyboard(report.id))


async def claim_report_text(message: Message, state: FSMContext, employee=None) -> bool:
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
        )
    else:
        report = work_report_service.awaiting_report_for_message(employee.id, str(message.chat.id))
    if report:
        await _show_report_draft(message, report, state)
        return True

    editing = work_report_service.editing_report_for_employee(employee.id)
    if editing:
        await _show_report_draft(message, editing, state)
        return True
    return False


@router.message(StateFilter(TestReportFlow.daily_report), F.text & ~F.text.startswith("/"))
async def test_daily_report_text(message: Message, state: FSMContext, employee=None):
    report = work_report_service.awaiting_report_for_employee_type(employee.id, "daily_test") if employee else None
    if not report:
        await state.clear()
        await message.answer("⚠️ Өдрийн тайлангийн тестийн хүсэлт олдсонгүй. /test_daily гэж дахин эхлүүлнэ үү.")
        return
    await _show_report_draft(message, report, state)


@router.message(StateFilter(TestReportFlow.monthly_report), F.text & ~F.text.startswith("/"))
async def test_monthly_report_text(message: Message, state: FSMContext, employee=None):
    report = work_report_service.awaiting_report_for_employee_type(employee.id, "monthly_test") if employee else None
    if not report:
        await state.clear()
        await message.answer("⚠️ Сарын тайлангийн тестийн хүсэлт олдсонгүй. /test_monthly гэж дахин эхлүүлнэ үү.")
        return
    await _show_report_draft(message, report, state)


@router.message(StateFilter(TestReportFlow.next_month_plan), F.text & ~F.text.startswith("/"))
async def test_next_month_plan_text(message: Message, state: FSMContext, employee=None):
    report = work_report_service.awaiting_report_for_employee_type(employee.id, "next_month_plan_test") if employee else None
    if not report:
        await state.clear()
        await message.answer("⚠️ Төлөвлөгөөний тестийн хүсэлт олдсонгүй. /test_monthly гэж дахин эхлүүлнэ үү.")
        return
    await _show_report_draft(message, report, state)


@router.message(F.text & ~F.text.startswith("/"), ReportPromptReply())
async def report_prompt_reply(message: Message, work_report: WorkReport):
    # Normal report flows are not FSM-bound; preserve their existing behavior.
    revision = work_report_service.add_draft(work_report.id, message.text or "")
    if not revision:
        await message.answer("⚠️ Тайлангийн текст хоосон байна.")
        return
    await message.answer(_draft_text(work_report, revision.text), parse_mode="HTML", reply_markup=draft_keyboard(work_report.id))


@router.message(F.text & ~F.text.startswith("/"), EditingReport())
async def edit_report_text(message: Message, work_report: WorkReport):
    revision = work_report_service.add_draft(work_report.id, message.text or "")
    if not revision:
        await message.answer("⚠️ Засварын текст хоосон байна.")
        return
    await message.answer(_draft_text(work_report, revision.text), parse_mode="HTML", reply_markup=draft_keyboard(work_report.id))


def _mode_label(mode: str) -> str:
    return "оффис" if mode == "in_person" else "remote"


def _work_time_summary_text(summary: dict, tz) -> str:
    lines = [
        f"📊 <b>Өнөөдрийн ажлын цаг</b>: {summary['total_minutes'] // 60}ц {summary['total_minutes'] % 60}м",
        f"🏢 Оффис: {summary['in_person_minutes'] // 60}ц {summary['in_person_minutes'] % 60}м",
        f"🏠 Remote: {summary['remote_minutes'] // 60}ц {summary['remote_minutes'] % 60}м",
    ]
    if summary["entries"]:
        lines.append("\n<b>Дэлгэрэнгүй:</b>")
        for entry in summary["entries"]:
            start = entry["started_at"].astimezone(tz).strftime("%H:%M")
            end = entry["ended_at"].astimezone(tz).strftime("%H:%M") if entry["ended_at"] else "одоо"
            label = "завсарлага" if entry.get("entry_type") == "break" else _mode_label(entry["mode"])
            lines.append(f"• {label}: {start}–{end} ({entry['minutes']}м)")
    return "\n".join(lines)


async def _change_work_time(message: Message, employee, mode: str, action: str) -> None:
    if not employee:
        await message.answer("❌ Та бүртгэгдээгүй байна.")
        return
    local_now = _local_now(employee.timezone)
    at = local_now.astimezone(timezone.utc)
    result, entry = (
        work_report_service.start_work_time(employee.id, local_now.date(), mode, at)
        if action == "start"
        else work_report_service.end_work_time(employee.id, local_now.date(), mode, at)
    )
    other_end = "/dayend" if mode == "remote" else "/remoteend"
    matching_start = "/daystart" if mode == "in_person" else "/remotestart"
    if result == "other_active":
        await message.answer(
            f"⚠️ {_mode_label(entry.mode).capitalize()} ажил одоо үргэлжилж байна. "
            f"Эхлээд <b>{other_end}</b> командаар дуусгана уу.", parse_mode="HTML"
        )
        return
    if result == "already_active":
        await message.answer(
            f"ℹ️ {_mode_label(mode).capitalize()} ажил аль хэдийн эхэлсэн байна. "
            f"Дуусгахдаа <b>{other_end}</b> ашиглана уу.", parse_mode="HTML"
        )
        return
    if result == "not_started":
        await message.answer(
            f"⚠️ Өнөөдөр {_mode_label(mode)} ажил эхлээгүй байна. "
            f"Эхлээд <b>{matching_start}</b> командыг ашиглана уу.", parse_mode="HTML"
        )
        return
    summary = work_report_service.summarize_work_time(
        work_report_service.work_time_entries(entry.report_id), now=at
    )
    if action == "start":
        await message.answer(
            f"✅ {_mode_label(mode).capitalize()} ажил эхэллээ: <b>{local_now:%H:%M}</b>",
            parse_mode="HTML",
        )
    else:
        await message.answer(
            f"✅ {_mode_label(mode).capitalize()} ажил дууслаа: <b>{local_now:%H:%M}</b>\n\n"
            f"{_work_time_summary_text(summary, local_now.tzinfo)}",
            parse_mode="HTML",
        )


async def _show_work_time(message: Message, employee=None) -> None:
    if not employee:
        await message.answer("❌ Та бүртгэгдээгүй байна.")
        return
    local_now = _local_now(employee.timezone)
    report = work_report_service.get_or_create_report(employee.id, "daily", local_now.date())
    summary = work_report_service.summarize_work_time(
        work_report_service.work_time_entries(report.id),
        now=local_now.astimezone(timezone.utc),
    )
    await message.answer(_work_time_summary_text(summary, local_now.tzinfo), parse_mode="HTML")


@router.message(Command("daystart"))
async def cmd_daystart(message: Message, employee=None):
    await _change_work_time(message, employee, "in_person", "start")


@router.message(Command("dayend"))
async def cmd_dayend(message: Message, employee=None):
    await _change_work_time(message, employee, "in_person", "end")


@router.message(Command("remotestart"))
async def cmd_remotestart(message: Message, employee=None):
    await _change_work_time(message, employee, "remote", "start")


@router.message(Command("remoteend"))
async def cmd_remoteend(message: Message, employee=None):
    await _change_work_time(message, employee, "remote", "end")


@router.message(Command("daypause"))
async def cmd_daypause(message: Message, employee=None):
    if not employee:
        await message.answer("❌ Та бүртгэгдээгүй байна.")
        return
    local_now = _local_now(employee.timezone)
    result, _ = work_report_service.pause_work_time(employee.id, local_now.date(), local_now.astimezone(timezone.utc))
    if result == "not_started":
        await message.answer("⚠️ Эхлээд /daystart эсвэл /remotestart ашиглана уу.")
    elif result == "already_paused":
        await message.answer("ℹ️ Ажлын цаг аль хэдийн түр зогссон байна.")
    else:
        await message.answer("⏸ Ажлын цаг түр зогслоо. /daystart эсвэл /remotestart командаар үргэлжлүүлнэ үү.")


@router.message(Command("worktime"))
async def cmd_worktime(message: Message, employee=None):
    await _show_work_time(message, employee)


@router.callback_query(F.data.startswith("wrdraft:"))
async def report_draft_action(cb: CallbackQuery, state: FSMContext, employee=None):
    try:
        _, report_id_raw, action = (cb.data or "").split(":", 2)
        report_id = int(report_id_raw)
    except (ValueError, AttributeError):
        await cb.answer("Буруу хүсэлт", show_alert=True)
        return
    report = work_report_service.get_report(report_id)
    if not employee or not report or report.employee_id != employee.id:
        await cb.answer("Энэ ноорог танд хамаарахгүй.", show_alert=True)
        return
    if action == "edit":
        if work_report_service.begin_edit(report_id):
            await cb.answer()
            await cb.message.answer("✏️ Зассан тайлангаа одоо бичиж илгээнэ үү.")
        else:
            await cb.answer("Засах ноорог олдсонгүй.", show_alert=True)
        return
    if action == "delete":
        if work_report_service.delete_draft(report_id):
            await cb.answer("Ноорог устгагдлаа.")
            await cb.message.answer("🗑 Ноорог устгагдлаа. Анхны сануулга мессежид Reply хийж дахин бичиж болно.")
        else:
            await cb.answer("Устгах ноорог олдсонгүй.", show_alert=True)
        return
    if action != "approve":
        await cb.answer("Буруу хүсэлт", show_alert=True)
        return
    approved = work_report_service.approve_draft(report_id)
    if not approved:
        await cb.answer("Батлах ноорог олдсонгүй.", show_alert=True)
        return
    await cb.answer("Тайлан батлагдлаа.")
    await cb.message.answer("✅ Тайлан хадгалагдлаа.")
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


async def _test_manager_ready(message: Message, employee, is_manager: bool) -> bool:
    if not is_manager:
        await message.answer("❌ Энэ команд зөвхөн удирдлагад зориулсан.")
        return False
    if not employee or not employee.is_active:
        await message.answer("⚠️ Тест ажиллуулахын тулд удирдлага идэвхтэй ажилтнаар бүртгэгдсэн байх шаардлагатай.")
        return False
    return True


@router.message(Command("test_daily"))
async def cmd_test_daily(message: Message, state: FSMContext, employee=None, is_manager: bool = False):
    """Start only the sequential daily test: check-in → report → times."""
    if not await _test_manager_ready(message, employee, is_manager):
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
        await message.answer(
            f"🧪 Өмнөх өдрийн тестийг цэвэрлэлээ ({reset_count}). "
            "Эхлээд чек-ин бөглөнө үү. Ажлын цаг бүртгэхдээ /daystart, /dayend, /remotestart, /remoteend командыг ашиглана уу."
        )


@router.message(Command("test_monthly"))
async def cmd_test_monthly(message: Message, state: FSMContext, employee=None, is_manager: bool = False):
    """Start only the sequential monthly report → next-month-plan test."""
    if not await _test_manager_ready(message, employee, is_manager):
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
        await message.answer(
            f"🧪 Өмнөх сарын тестийг цэвэрлэлээ ({reset_count}). "
            "Сарын тайлангийн Reply → ноорог → батлах урсгалыг шалгана уу. Баталсны дараа дараа сарын төлөвлөгөө ирнэ."
        )


@router.message(Command("seed_monthly_digest"))
async def cmd_seed_monthly_digest(message: Message, is_manager: bool = False):
    """Create dummy approved monthly-test reports without sending a digest."""
    if not is_manager:
        await message.answer("❌ Энэ команд зөвхөн удирдлагад зориулсан.")
        return

    today = date.today()
    period = previous_month(today)
    worker_count = seed_dummy_monthly_test_reports(period)
    await message.answer(
        f"🧪 {worker_count} dummy тайлан үүсгэлээ ({period.year}-{period.month:02d}).\n"
        "Одоо /test_monthly_digest командыг ажиллуулна уу."
    )


@router.message(Command("test_monthly_digest"))
async def cmd_test_monthly_digest(message: Message, is_manager: bool = False):
    """Send the real digest logic for already-seeded dummy reports."""
    if not is_manager:
        await message.answer("❌ Энэ команд зөвхөн удирдлагад зориулсан.")
        return

    sent = await try_send_monthly_report_digest(
        date.today(),
        report_type="monthly_test",
        reserve=False,
        recipients=[str(message.chat.id)],
        test_mode=True,
    )
    if not sent:
        await message.answer(
            "⚠️ Dummy тайлан олдсонгүй эсвэл бүх идэвхтэй ажилтны тайлан бэлэн биш байна. "
            "Эхлээд /seed_monthly_digest ажиллуулна уу."
        )


@router.message(Command("test_reports"))
async def cmd_test_reports(message: Message, is_manager: bool = False):
    """Point managers to the intentionally separate, sequential test flows."""
    if not is_manager:
        await message.answer("❌ Энэ команд зөвхөн удирдлагад зориулсан.")
        return
    await message.answer(
        "🧪 Өдрийн урсгал: /test_daily\n"
        "📅 Сарын урсгал: /test_monthly\n"
        "📊 Dummy тайлан үүсгэх: /seed_monthly_digest\n"
        "📊 Dummy хураангуй ажиллуулах: /test_monthly_digest"
    )
