"""aiogram handlers задач: /task /mytasks /assigned /done /snooze /dashboard."""
import logging
from datetime import datetime, timezone

import pytz
from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards import task_actions_kb
from app.services import reminder_service, task_service, voice_service
from app.services.task_parser import parse_task_text, parse_when

log = logging.getLogger(__name__)
router = Router()

_PRIORITY_EMOJI = {1: "🔴", 2: "🟡", 3: "🟢"}


def _now_tz(tz: str | None) -> datetime:
    try:
        zone = pytz.timezone(tz or "Europe/Moscow")
    except Exception:
        zone = pytz.timezone("Europe/Moscow")
    return datetime.now(zone)


def _fmt_deadline(dt: datetime | None) -> str:
    if not dt:
        return "без срока"
    return dt.astimezone(timezone.utc).strftime("%d.%m %H:%M UTC")


def _fmt_task_line(t: dict, *, with_assignee: bool = False) -> str:
    em = _PRIORITY_EMOJI.get(t["priority"], "🟡")
    who = f" → {t['assignee_name']}" if with_assignee and t.get("assignee_name") else ""
    overdue = " ⚠️просрочено" if t["status"] == "overdue" else ""
    return f"{em} #{t['id']} {t['title']}{who} — {_fmt_deadline(t['deadline_at'])}{overdue}"


# ─── /task ─────────────────────────────────────────────────────────────────────

async def _create_task_from_text(
    message: Message, text: str, *, employee, is_manager: bool, tg_id: str | None
) -> None:
    """Парсит фразу, резолвит исполнителя, создаёт задачу, планирует напоминания и
    уведомляет исполнителя. Используется и /task, и голосовым вводом."""
    tz = employee.timezone if employee else "Europe/Moscow"
    parsed = parse_task_text(text, now=_now_tz(tz), tz=tz)

    assignee_id = None
    assignee_label = "тебе"
    if parsed.assignee_username:
        target = task_service.resolve_employee_by_username(parsed.assignee_username)
        if not target:
            await message.answer(f"❌ Не нашёл сотрудника @{parsed.assignee_username}. Проверь username.")
            return
        if not is_manager and (not employee or target.id != employee.id):
            await message.answer("❌ Назначать задачи другим может только руководитель.")
            return
        assignee_id = target.id
        assignee_label = target.name
    else:
        if not employee:
            await message.answer("❌ Укажи исполнителя через @username (ты не зарегистрирован как сотрудник).")
            return
        assignee_id = employee.id

    task = task_service.create_task(
        title=parsed.title,
        assignee_id=assignee_id,
        created_by_id=employee.id if employee else None,
        created_by_tg=tg_id,
        deadline_at=parsed.deadline_at,
        priority=parsed.priority,
    )
    try:
        reminder_service.schedule_task_reminders(task)
    except Exception:  # noqa: BLE001 — не валим создание из-за планировщика
        log.exception("Не удалось запланировать напоминания task=%s", task["id"])

    await message.answer(
        f"✅ Задача создана: <b>#{task['id']}</b>\n"
        f"«{task['title']}»\n"
        f"Исполнитель: {assignee_label}\n"
        f"Приоритет: {_PRIORITY_EMOJI.get(task['priority'], '🟡')}\n"
        f"Дедлайн: <b>{_fmt_deadline(task['deadline_at'])}</b>",
        parse_mode="HTML",
        reply_markup=task_actions_kb(task["id"]),
    )

    if task["assignee_tg"] and task["assignee_tg"] != tg_id:
        from app.bot.scheduler import _make_bot

        bot = _make_bot()
        try:
            await bot.send_message(
                task["assignee_tg"],
                f"📌 Тебе поставили задачу #{task['id']}:\n«{task['title']}»\n"
                f"Дедлайн: {_fmt_deadline(task['deadline_at'])}",
                reply_markup=task_actions_kb(task["id"]),
            )
        except Exception:  # noqa: BLE001
            log.exception("Не удалось уведомить исполнителя task=%s", task["id"])
        finally:
            await bot.session.close()


@router.message(Command("task"))
async def cmd_task(message: Message, command: CommandObject, employee=None, is_manager: bool = False, tg_id: str | None = None):
    text = (command.args or "").strip()
    if not text:
        await message.answer(
            "📝 <b>Поставить задачу</b>\n\n"
            "Формат: <code>/task [@исполнитель] что сделать [когда]</code>\n"
            "Примеры:\n"
            "• <code>/task позвонить клиенту завтра в 15:00</code>\n"
            "• <code>/task @ivan подготовить отчёт к пятнице, срочно</code>\n\n"
            "🎙 Можно надиктовать голосовым.",
            parse_mode="HTML",
        )
        return
    await _create_task_from_text(message, text, employee=employee, is_manager=is_manager, tg_id=tg_id)


@router.message(F.voice)
async def cmd_voice_task(message: Message, employee=None, is_manager: bool = False, tg_id: str | None = None):
    if not voice_service.transcription_enabled():
        await message.answer("🎙 Голосовые задачи пока не подключены. Напиши текстом: <code>/task …</code>", parse_mode="HTML")
        return
    await message.answer("🎙 Распознаю голосовое…")
    try:
        buf = await message.bot.download(message.voice)
        audio = buf.read()
    except Exception:  # noqa: BLE001
        log.exception("Не удалось скачать голосовое")
        await message.answer("❌ Не смог получить аудио. Напиши задачу текстом: <code>/task …</code>", parse_mode="HTML")
        return
    text = await voice_service.transcribe(audio)
    if not text:
        await message.answer("❌ Не разобрал голосовое. Напиши задачу текстом: <code>/task …</code>", parse_mode="HTML")
        return
    await message.answer(f"📝 Распознано: «{text}»")
    await _create_task_from_text(message, text, employee=employee, is_manager=is_manager, tg_id=tg_id)


# ─── /mytasks ───────────────────────────────────────────────────────────────────

@router.message(Command("mytasks"))
async def cmd_mytasks(message: Message, employee=None):
    if not employee:
        await message.answer("❌ Ты не зарегистрирован как сотрудник.")
        return
    tasks = task_service.list_assigned_to(employee.id, only_active=True)
    if not tasks:
        await message.answer("✨ У тебя нет активных задач.")
        return
    lines = [f"📋 <b>Твои задачи ({len(tasks)})</b>\n"]
    lines += [_fmt_task_line(t) for t in tasks]
    lines.append("\nОтметить: /done &lt;id&gt; · Перенести: /snooze &lt;id&gt; &lt;время&gt;")
    await message.answer("\n".join(lines), parse_mode="HTML")


# ─── /assigned (задачи, которые я поставил) ──────────────────────────────────────

@router.message(Command("assigned"))
async def cmd_assigned(message: Message, employee=None, tg_id: str | None = None):
    tasks = task_service.list_created_by(
        employee_id=employee.id if employee else None, tg_id=tg_id, only_active=True
    )
    if not tasks:
        await message.answer("📭 Ты пока не ставил активных задач другим.")
        return
    lines = [f"📤 <b>Поставленные тобой ({len(tasks)})</b>\n"]
    lines += [_fmt_task_line(t, with_assignee=True) for t in tasks]
    await message.answer("\n".join(lines), parse_mode="HTML")


# ─── /done <id> ──────────────────────────────────────────────────────────────────

@router.message(Command("done"))
async def cmd_done(message: Message, command: CommandObject, employee=None, is_manager: bool = False, tg_id: str | None = None):
    arg = (command.args or "").strip()
    if not arg.isdigit():
        await message.answer("Формат: <code>/done &lt;id&gt;</code>", parse_mode="HTML")
        return
    await _complete_task(message, int(arg), employee, is_manager, tg_id)


async def _complete_task(target, task_id: int, employee, is_manager: bool, tg_id: str | None):
    task = task_service.get_task(task_id)
    if not task:
        await target.answer("❌ Задача не найдена.")
        return
    if not task_service.can_modify(task, employee_id=employee.id if employee else None, tg_id=tg_id, is_manager=is_manager):
        await target.answer("❌ Нет прав на эту задачу.")
        return
    task_service.set_status(task_id, "done", by_employee_id=employee.id if employee else None)
    reminder_service.cancel_task_jobs(task_id)
    await target.answer(f"✅ Задача #{task_id} «{task['title']}» отмечена выполненной.")


# ─── /snooze <id> <время> ────────────────────────────────────────────────────────

@router.message(Command("snooze"))
async def cmd_snooze(message: Message, command: CommandObject, employee=None, is_manager: bool = False, tg_id: str | None = None):
    parts = (command.args or "").strip().split(maxsplit=1)
    if len(parts) < 2 or not parts[0].isdigit():
        await message.answer("Формат: <code>/snooze &lt;id&gt; &lt;время&gt;</code>, напр. <code>/snooze 12 завтра 10:00</code>", parse_mode="HTML")
        return
    task_id = int(parts[0])
    task = task_service.get_task(task_id)
    if not task:
        await message.answer("❌ Задача не найдена.")
        return
    if not task_service.can_modify(task, employee_id=employee.id if employee else None, tg_id=tg_id, is_manager=is_manager):
        await message.answer("❌ Нет прав на эту задачу.")
        return
    tz = employee.timezone if employee else "Europe/Moscow"
    new_dt = parse_when(parts[1], now=_now_tz(tz), tz=tz)
    if not new_dt:
        await message.answer("❌ Не понял время. Примеры: «завтра 10:00», «через 2 дня», «в пятницу 18:00».")
        return
    updated = task_service.snooze(task_id, new_dt)
    reminder_service.schedule_task_reminders(updated)
    await message.answer(f"⏰ Дедлайн #{task_id} перенесён на <b>{_fmt_deadline(new_dt)}</b>.", parse_mode="HTML")


# ─── /dashboard ──────────────────────────────────────────────────────────────────

@router.message(Command("dashboard"))
async def cmd_dashboard(message: Message, employee=None, is_manager: bool = False, tg_id: str | None = None):
    if is_manager:
        groups = task_service.all_active_grouped_by_assignee()
        if not groups:
            await message.answer("✨ Активных задач нет.")
            return
        total = sum(len(v) for v in groups.values())
        overdue = sum(1 for v in groups.values() for t in v if t["status"] == "overdue")
        lines = [f"👔 <b>Активные задачи ({total})</b>\n"]
        for name, items in groups.items():
            lines.append(f"\n👤 <b>{name}</b> ({len(items)}):")
            lines += [f"  {_fmt_task_line(t)}" for t in items]
        if overdue:
            lines.append(f"\n⚠️ Просрочено: {overdue}")
        await message.answer("\n".join(lines), parse_mode="HTML")
        return

    # Сотрудник: мои задачи + что я поставил
    mine = task_service.list_assigned_to(employee.id, only_active=True) if employee else []
    created = task_service.list_created_by(
        employee_id=employee.id if employee else None, tg_id=tg_id, only_active=True
    )
    lines = ["📊 <b>Твой дашборд</b>\n", f"\n📋 На тебе ({len(mine)}):"]
    lines += [f"  {_fmt_task_line(t)}" for t in mine] or ["  —"]
    lines.append(f"\n📤 Поставил ({len(created)}):")
    lines += [f"  {_fmt_task_line(t, with_assignee=True)}" for t in created] or ["  —"]
    await message.answer("\n".join(lines), parse_mode="HTML")


# ─── callbacks с inline-кнопок ───────────────────────────────────────────────────

@router.callback_query(F.data.startswith("task:done:"))
async def cb_task_done(cb: CallbackQuery, employee=None, is_manager: bool = False, tg_id: str | None = None):
    task_id = int(cb.data.split(":")[2])
    await _complete_task(cb.message, task_id, employee, is_manager, tg_id)
    await cb.answer("Готово ✅")


@router.callback_query(F.data.startswith("task:snooze:"))
async def cb_task_snooze(cb: CallbackQuery, employee=None, is_manager: bool = False, tg_id: str | None = None):
    _, _, task_id_s, mins_s = cb.data.split(":")
    task_id, mins = int(task_id_s), int(mins_s)
    task = task_service.get_task(task_id)
    if not task:
        await cb.answer("Задача не найдена", show_alert=True)
        return
    if not task_service.can_modify(task, employee_id=employee.id if employee else None, tg_id=tg_id, is_manager=is_manager):
        await cb.answer("Нет прав", show_alert=True)
        return
    from datetime import timedelta

    base = task["deadline_at"] or datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    new_dt = base + timedelta(minutes=mins)
    updated = task_service.snooze(task_id, new_dt)
    reminder_service.schedule_task_reminders(updated)
    await cb.answer(f"Перенёс на {_fmt_deadline(new_dt)}")
