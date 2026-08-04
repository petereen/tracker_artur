"""Telegram flow for daily work logs and monthly free-form reports."""
from __future__ import annotations

from datetime import date, datetime
from html import escape

import pytz
from aiogram import F, Router
from aiogram.filters import Command, Filter
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.models.models import WorkReport
from app.services import work_report_service

router = Router()


def _local_now(timezone_name: str | None) -> datetime:
    try:
        zone = pytz.timezone(timezone_name or "Asia/Ulaanbaatar")
    except Exception:
        zone = pytz.timezone("Asia/Ulaanbaatar")
    return datetime.now(zone)


def daily_prompt_keyboard(report_id: int) -> InlineKeyboardMarkup:
    """Legacy keyboard containing both actions.

    Keep this helper for existing integrations; the daily flow now sends one
    work-time prompt per action via ``work_time_keyboard``.
    """
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🟢 Одоо эхэллээ", callback_data=f"wrtime:{report_id}:start"),
        InlineKeyboardButton(text="🔴 Одоо дууслаа", callback_data=f"wrtime:{report_id}:end"),
    ]])


def work_time_keyboard(report_id: int, action: str) -> InlineKeyboardMarkup:
    if action == "start":
        text = "🟢 Одоо эхэллээ"
    elif action == "end":
        text = "🔴 Одоо дууслаа"
    else:
        raise ValueError("invalid work-time action")
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=text, callback_data=f"wrtime:{report_id}:{action}"),
    ]])


def draft_keyboard(report_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Батлах", callback_data=f"wrdraft:{report_id}:approve"),
        InlineKeyboardButton(text="✏️ Засах", callback_data=f"wrdraft:{report_id}:edit"),
        InlineKeyboardButton(text="🗑 Устгах", callback_data=f"wrdraft:{report_id}:delete"),
    ]])


def _prompt_text(report_type: str, prompt_type: str | None = None) -> str:
    test_prefix = "🧪 <b>ТЕСТ</b> — " if report_type.endswith("_test") else ""
    if report_type in {"daily", "daily_test"}:
        if prompt_type in {"daily_checkin", "test_daily_checkin"}:
            return (
                f"{test_prefix}⏰ <b>Өдрийн чек-ин</b>\n\n"
                "Чек-ин бөглөх бол /today гэж бичнэ үү."
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
        if prompt_type in {"daily_start", "test_daily_start"}:
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


def _draft_text(report: WorkReport, text: str) -> str:
    label = {
        "daily": "Өдрийн тайлан", "monthly": "Сарын тайлан", "next_month_plan": "Дараа сарын төлөвлөгөө",
        "daily_test": "Өдрийн тайлангийн тест", "monthly_test": "Сарын тайлангийн тест", "next_month_plan_test": "Дараа сарын төлөвлөгөөний тест",
    }[report.report_type]
    return f"📝 <b>{label} — ноорог</b>\n\n{escape(text)}\n\nДоорх товчоор батлах, засах эсвэл устгана уу."


class ReportPromptReply(Filter):
    async def __call__(self, message: Message, employee=None, **_) -> dict | bool:
        if not employee or not message.reply_to_message:
            return False
        report = work_report_service.report_for_reply(
            employee.id, str(message.chat.id), message.reply_to_message.message_id
        )
        return {"work_report": report} if report else False


class EditingReport(Filter):
    async def __call__(self, message: Message, employee=None, **_) -> dict | bool:
        if not employee:
            return False
        report = work_report_service.editing_report_for_employee(employee.id)
        return {"work_report": report} if report else False


@router.message(F.text & ~F.text.startswith("/"), ReportPromptReply())
async def report_prompt_reply(message: Message, work_report: WorkReport):
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
        _, report_id_raw, action = (cb.data or "").split(":", 2)
        report_id = int(report_id_raw)
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
    value = work_report_service.set_work_time(report_id, "started_at" if action == "start" else "ended_at")
    if not value:
        await cb.answer("Бүртгэх боломжгүй байна.", show_alert=True)
        return
    local_value = value.astimezone(_local_now(employee.timezone).tzinfo).strftime("%H:%M")
    label = "Эхэлсэн" if action == "start" else "Дууссан"
    await cb.answer(f"{label} цаг: {local_value}", show_alert=True)
    if action == "start":
        local_day = _local_now(employee.timezone).date()
        await send_report_prompt(
            cb.bot,
            report,
            telegram_chat_id=employee.telegram_id,
            prompt_type="test_daily_end" if report.report_type == "daily_test" else "daily_end",
            local_day=local_day,
        )


@router.callback_query(F.data.startswith("wrdraft:"))
async def report_draft_action(cb: CallbackQuery, employee=None):
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
    if approved.report_type in {"daily", "daily_test"}:
        local_day = _local_now(employee.timezone).date()
        await send_report_prompt(
            cb.bot,
            approved,
            telegram_chat_id=employee.telegram_id,
            prompt_type="test_daily_start" if approved.report_type == "daily_test" else "daily_start",
            local_day=local_day,
        )
    if approved.report_type in {"monthly", "monthly_test"}:
        local_day = _local_now(employee.timezone).date()
        plan_type = "next_month_plan_test" if approved.report_type == "monthly_test" else "next_month_plan"
        plan = work_report_service.get_or_create_report(employee.id, plan_type, local_day)
        await send_report_prompt(
            cb.bot,
            plan,
            telegram_chat_id=employee.telegram_id,
            prompt_type="next_month_plan_test" if plan_type.endswith("_test") else "next_month_plan",
            local_day=local_day,
        )


@router.message(Command("test_reports"))
async def cmd_test_reports(message: Message, employee=None, is_manager: bool = False):
    """Manager-only, isolated end-to-end test of the report Telegram flow."""
    if not is_manager:
        await message.answer("❌ Энэ команд зөвхөн удирдлагад зориулсан.")
        return
    if not employee or not employee.is_active:
        await message.answer("⚠️ Тест ажиллуулахын тулд удирдлага идэвхтэй ажилтнаар бүртгэгдсэн байх шаардлагатай.")
        return
    reset_count = work_report_service.reset_test_reports()
    local_day = _local_now(employee.timezone).date()
    sent_types: list[str] = []
    for report_type, prompt_type, label in (
        ("daily_test", "test_daily_checkin", "өдрийн чек-ин"),
        ("daily_test", "test_daily_report", "өдрийн тайлан"),
        ("daily_test", "test_daily_start", "ажил эхэлсэн цаг"),
        ("monthly_test", "test_monthly_report", "сарын тайлан"),
        ("next_month_plan_test", "test_next_month_plan", "дараа сарын төлөвлөгөө"),
    ):
        report = work_report_service.get_or_create_report(employee.id, report_type, local_day)
        if report.status == "approved":
            continue
        if await send_report_prompt(
            message.bot,
            report,
            telegram_chat_id=employee.telegram_id,
            prompt_type=prompt_type,
            local_day=local_day,
        ):
            sent_types.append(label)
    if sent_types:
        await message.answer(
            f"🧪 Өмнөх тестийн бүртгэлүүдийг цэвэрлэлээ ({reset_count}). "
            f"Шинэ тестийн мессеж илгээлээ: {', '.join(sent_types)}. "
            "Reply → ноорог → батлах урсгалаар шалгана уу."
        )
    else:
        await message.answer("🧪 Өнөөдрийн тестийн урсгал аль хэдийн илгээгдсэн эсвэл батлагдсан байна.")
