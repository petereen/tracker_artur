"""Telegram flow for daily work logs and monthly free-form reports."""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from html import escape

import pytz
from aiogram import F, Router
from aiogram.filters import Command, Filter, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.models.models import WorkReport
from app.services import work_report_service

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


def work_time_keyboard(report_id: int, action: str) -> InlineKeyboardMarkup:
    """Return the fixed half-hour choices used for daily start/end times."""
    if action not in {"start", "end"}:
        raise ValueError("invalid work-time action")
    slots = [
        time(hour, minute)
        for hour in range(6, 24)
        for minute in (0, 30)
        if (hour, minute) <= (23, 0)
    ]
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=slot.strftime("%H:%M"),
                callback_data=f"wrtime:{report_id}:{action}:{slot.strftime('%H%M')}",
            )
            for slot in slots[index:index + 4]
        ]
        for index in range(0, len(slots), 4)
    ])


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
        if prompt_type in {"daily_start", "test_daily_start"}:
            return (
                f"{test_prefix}🟢 <b>Ажил эхэлсэн цаг</b>\n\n"
                "Өнөөдөр ажлаа хэдэн цагт эхэлсэн бэ?"
            )
        if prompt_type in {"daily_end", "test_daily_end"}:
            return (
                f"{test_prefix}🔴 <b>Ажил дууссан цаг</b>\n\n"
                "Өнөөдөр ажлаа хэдэн цагт дууссан бэ?"
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
        elif prompt_type in {"daily_start", "test_daily_start"}:
            markup = work_time_keyboard(report.id, "start")
        elif prompt_type in {"daily_end", "test_daily_end"}:
            markup = work_time_keyboard(report.id, "end")
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
    """Send the daily check-in/report/time prompts in one canonical order.

    Both the scheduler and ``/test_reports`` use this function so their
    observable Telegram flows stay identical apart from the test prefix.
    """
    is_test = report.report_type == "daily_test"
    prefix = "test_" if is_test else ""
    sent: list[str] = []
    for suffix, label in (
        ("daily_checkin", "өдрийн чек-ин"),
        ("daily_report", "өдрийн тайлан"),
        ("daily_start", "ажил эхэлсэн цаг"),
        ("daily_end", "ажил дууссан цаг"),
    ):
        if await send_report_prompt(
            bot,
            report,
            telegram_chat_id=telegram_chat_id,
            prompt_type=f"{prefix}{suffix}",
            local_day=local_day,
        ):
            sent.append(label)
    return sent


async def send_test_daily_report_prompt(
    bot,
    *,
    state: FSMContext,
    employee_id: int,
    telegram_chat_id: str,
    local_day: date,
) -> bool:
    """Advance the isolated daily test after its test check-in is completed."""
    report = work_report_service.get_or_create_report(employee_id, "daily_test", local_day)
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


@router.message(StateFilter(TestReportFlow.daily_report), F.text & ~F.text.startswith("/"))
async def test_daily_report_text(message: Message, state: FSMContext, employee=None):
    report = work_report_service.awaiting_report_for_message(employee.id, str(message.chat.id)) if employee else None
    if not report or report.report_type != "daily_test":
        await state.clear()
        await message.answer("⚠️ Өдрийн тайлангийн тестийн хүсэлт олдсонгүй. /test_daily гэж дахин эхлүүлнэ үү.")
        return
    await _show_report_draft(message, report, state)


@router.message(StateFilter(TestReportFlow.monthly_report), F.text & ~F.text.startswith("/"))
async def test_monthly_report_text(message: Message, state: FSMContext, employee=None):
    report = work_report_service.awaiting_report_for_message(employee.id, str(message.chat.id)) if employee else None
    if not report or report.report_type != "monthly_test":
        await state.clear()
        await message.answer("⚠️ Сарын тайлангийн тестийн хүсэлт олдсонгүй. /test_monthly гэж дахин эхлүүлнэ үү.")
        return
    await _show_report_draft(message, report, state)


@router.message(StateFilter(TestReportFlow.next_month_plan), F.text & ~F.text.startswith("/"))
async def test_next_month_plan_text(message: Message, state: FSMContext, employee=None):
    report = work_report_service.awaiting_report_for_message(employee.id, str(message.chat.id)) if employee else None
    if not report or report.report_type != "next_month_plan_test":
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


@router.callback_query(F.data.startswith("wrtime:"))
async def set_report_time(cb: CallbackQuery, employee=None):
    try:
        _, report_id_raw, action, slot_raw = (cb.data or "").split(":", 3)
        report_id = int(report_id_raw)
        if len(slot_raw) != 4 or not slot_raw.isdigit():
            raise ValueError
        selected_time = time(int(slot_raw[:2]), int(slot_raw[2:]))
        if not (time(6, 0) <= selected_time <= time(23, 0)) or selected_time.minute not in {0, 30}:
            raise ValueError
    except (ValueError, AttributeError):
        await cb.answer("Буруу хүсэлт", show_alert=True)
        return
    report = work_report_service.get_report(report_id)
    if not employee or not report or report.employee_id != employee.id:
        await cb.answer("Энэ бүртгэл танд хамаарахгүй.", show_alert=True)
        return
    if action not in {"start", "end"}:
        await cb.answer("Буруу хүсэлт", show_alert=True)
        return
    try:
        zone = pytz.timezone(employee.timezone or "Asia/Ulaanbaatar")
    except Exception:
        zone = pytz.timezone("Asia/Ulaanbaatar")
    selected_at = zone.localize(datetime.combine(report.period_date, selected_time)).astimezone(timezone.utc)
    value = work_report_service.set_work_time(
        report_id,
        "started_at" if action == "start" else "ended_at",
        at=selected_at,
    )
    if not value:
        await cb.answer("Бүртгэх боломжгүй байна.", show_alert=True)
        return
    local_value = value.astimezone(_local_now(employee.timezone).tzinfo).strftime("%H:%M")
    label = "Эхэлсэн" if action == "start" else "Дууссан"
    await cb.answer(f"{label} цаг: {local_value}", show_alert=True)
    if action == "start" and report.report_type == "daily_test":
        await send_report_prompt(
            cb.bot,
            report,
            telegram_chat_id=employee.telegram_id,
            prompt_type="test_daily_end",
            local_day=_local_now(employee.timezone).date(),
        )


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
    if approved.report_type == "daily_test":
        local_day = _local_now(employee.timezone).date()
        await send_report_prompt(
            cb.bot,
            approved,
            telegram_chat_id=employee.telegram_id,
            prompt_type="test_daily_start",
            local_day=local_day,
        )
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
            "Эхлээд чек-ин бөглөнө үү. Дараа нь өдрийн тайлан, ажил эхэлсэн ба дууссан цагийн асуултууд нэг нэгээрээ ирнэ."
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


@router.message(Command("test_reports"))
async def cmd_test_reports(message: Message, is_manager: bool = False):
    """Point managers to the intentionally separate, sequential test flows."""
    if not is_manager:
        await message.answer("❌ Энэ команд зөвхөн удирдлагад зориулсан.")
        return
    await message.answer("🧪 Өдрийн урсгал: /test_daily\n📅 Сарын урсгал: /test_monthly")
