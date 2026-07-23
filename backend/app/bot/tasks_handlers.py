"""aiogram handlers задач: /task /mytasks /assigned /done /snooze /dashboard."""
import logging
import re
from datetime import datetime, timezone

import pytz
from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.db import get_all_active_employees, get_manager_settings
from app.bot.keyboards import task_actions_kb
from app.services import reminder_service, task_ai, task_service
from app.services.notification_policy import load_policy, next_allowed
from app.services.task_parser import parse_task_text, parse_when

log = logging.getLogger(__name__)
router = Router()

_PRIORITY_EMOJI = {1: "🔴", 2: "🟡", 3: "🟢"}


def _now_tz(tz: str | None) -> datetime:
    try:
        zone = pytz.timezone(tz or "Asia/Ulaanbaatar")
    except Exception:
        zone = pytz.timezone("Asia/Ulaanbaatar")
    return datetime.now(zone)


def _fmt_deadline(dt: datetime | None) -> str:
    if not dt:
        return "Хугацаагүй"
    return dt.astimezone(timezone.utc).strftime("%d.%m %H:%M UTC")


def _fmt_ub_deadline(dt: datetime | None) -> str:
    """Format a deadline for the task-draft confirmation in Ulaanbaatar time."""
    if not dt:
        return "Хугацаагүй"
    return dt.astimezone(pytz.timezone("Asia/Ulaanbaatar")).strftime("%d.%m %H:%M УБ")


def _fmt_task_line(t: dict, *, with_assignee: bool = False) -> str:
    em = _PRIORITY_EMOJI.get(t["priority"], "🟡")
    who = f" → {t['assignee_name']}" if with_assignee and t.get("assignee_name") else ""
    overdue = " ⚠️хугацаа хэтэрсэн" if t["status"] == "overdue" else ""
    return f"{em} #{t['id']} {t['title']}{who} — {_fmt_deadline(t['deadline_at'])}{overdue}"


# ─── /task ─────────────────────────────────────────────────────────────────────

async def _create_task_from_text(
    message: Message, text: str, *, employee, is_manager: bool, tg_id: str | None
) -> None:
    """Парсит фразу, резолвит исполнителя, создаёт задачу, планирует напоминания и
    уведомляет исполнителя. Используется и /task, и голосовым вводом."""
    tz = employee.timezone if employee else "Asia/Ulaanbaatar"
    parsed = parse_task_text(text, now=_now_tz(tz), tz=tz)

    assignee_id = None
    assignee_label = "та"
    if parsed.assignee_username:
        target = task_service.resolve_employee_by_username(parsed.assignee_username)
        if not target:
            await message.answer(f"❌ @{parsed.assignee_username} хэрэглэгчтэй ажилтан олдсонгүй. Username-ийг шалгана уу.")
            return
        if not is_manager and (not employee or target.id != employee.id):
            await message.answer("❌ Бусдад даалгавар өгөх эрх зөвхөн удирдлагад бий.")
            return
        assignee_id = target.id
        assignee_label = target.name
    else:
        if not employee:
            await message.answer("❌ Гүйцэтгэгчийг @username-аар заана уу. Та ажилтнаар бүртгэгдээгүй байна.")
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
        f"✅ Даалгавар үүслээ: <b>#{task['id']}</b>\n"
        f"«{task['title']}»\n"
        f"Гүйцэтгэгч: {assignee_label}\n"
        f"Тэргүүлэх зэрэг: {_PRIORITY_EMOJI.get(task['priority'], '🟡')}\n"
        f"Хугацаа: <b>{_fmt_deadline(task['deadline_at'])}</b>",
        parse_mode="HTML",
        reply_markup=task_actions_kb(task["id"]),
    )

    _enqueue_assignment_bot(task, tg_id)


def _iso(dt: datetime | None) -> str | None:
    return dt.astimezone(timezone.utc).isoformat() if dt else None


def _enqueue_assignment_bot(task: dict, actor_tg: str | None) -> None:
    """Кладёт уведомление о назначении в outbox (дренит бот, с учётом тихих часов)."""
    if not task.get("assignee_tg") or str(task["assignee_tg"]) == str(actor_tg or ""):
        return
    policy = load_policy(get_manager_settings())
    nb = next_allowed(datetime.now(timezone.utc), task.get("assignee_tz") or "Asia/Ulaanbaatar", policy)
    task_service.enqueue_notification(
        task_id=task["id"], recipient_tg=task["assignee_tg"], kind="task_assigned",
        payload={"title": task["title"], "deadline_iso": _iso(task["deadline_at"])},
        not_before=nb, dedup_key=f"task_assigned:{task['id']}",
    )


@router.message(Command("task"))
async def cmd_task(message: Message, command: CommandObject, employee=None, is_manager: bool = False, tg_id: str | None = None):
    text = (command.args or "").strip()
    if not text:
        await message.answer(
            "📝 <b>Даалгавар үүсгэх</b>\n\n"
            "Хэлбэр: <code>/task [@гүйцэтгэгч] юу хийх [хэзээ]</code>\n"
            "Жишээ:\n"
            "• <code>/task харилцагч руу маргааш 15:00-д залгах</code>\n"
            "• <code>/task @bat баасан гарагт тайлан бэлдэх, яаралтай</code>\n\n"
            "🎙 Мөн дуу хоолойгоор хэлж болно.",
            parse_mode="HTML",
        )
        return
    await _create_task_from_text(message, text, employee=employee, is_manager=is_manager, tg_id=tg_id)


# ─── AI-постановка задач (текст + голос, черновик → подтверждение) ───────────────

class TaskDraft(StatesGroup):
    confirming = State()


def _roster() -> list[dict]:
    return [{"id": e.id, "name": e.name, "username": e.telegram_username} for e in get_all_active_employees()]


def _draft_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Үүсгэх", callback_data="taskdraft:confirm"),
        InlineKeyboardButton(text="✏️ Засах", callback_data="taskdraft:edit"),
        InlineKeyboardButton(text="❌ Цуцлах", callback_data="taskdraft:cancel"),
    ]])


async def _show_draft(message: Message, draft: dict) -> None:
    desc = f"\n📝 {draft['description']}" if draft.get("description") else ""
    await message.answer(
        f"🤖 <b>Даалгаврын ноорог</b>\n\n"
        f"<b>{draft['title']}</b>{desc}\n"
        f"👤 Гүйцэтгэгч: <b>{draft.get('assignee_name') or '—'}</b>\n"
        f"{_PRIORITY_EMOJI.get(draft.get('priority', 2), '🟡')} Тэргүүлэх зэрэг: {draft.get('priority', 2)}\n"
        f"🕒 Хугацаа: <b>{_fmt_ub_deadline(draft.get('deadline_at'))}</b>\n\n"
        f"Даалгаврыг үүсгэх үү?",
        parse_mode="HTML", reply_markup=_draft_kb(),
    )


_SELF_RE = re.compile(
    r"\b(я|мне|себе|мной|меня|самому|самой|i|me|myself|self|"
    r"надад|өөртөө|намайг|би(?: өөрөө)?)\b",
    re.IGNORECASE,
)
_ALL_WORKERS_RE = re.compile(
    r"(?:\ball\s+(?:workers?|employees?|staff|team|everyone|everybody)\b|"
    r"\b(?:everyone|everybody)\b|"
    r"бүх\s+(?:ажилт(?:ан|нууд)|ажилч(?:ин|ид)|баг(?:ийн\s+гишүүд)?)|"
    r"(?:бүгдэд|бүгд\s+нь)|"
    r"(?:всем|все(?:м)?\s+(?:сотрудник(?:ам|и)?|работник(?:ам|и)?|команд(?:е|ы))))",
    re.IGNORECASE,
)


def _targets_all_workers(text: str) -> bool:
    """Detect an explicit all-active-worker assignment in supported languages."""
    return bool(_ALL_WORKERS_RE.search(text or ""))


def _resolve_roster_name(text: str, roster: list[dict]) -> int | None:
    """Resolve an explicitly written full employee name, preferring the longest match."""
    normalized_text = re.sub(r"\s+", " ", text or "").casefold()
    matches: list[tuple[int, int]] = []
    for row in roster:
        name = re.sub(r"\s+", " ", str(row.get("name") or "")).strip().casefold()
        if not name:
            continue
        if re.search(rf"(?<!\w){re.escape(name)}(?:д|т)?(?!\w)", normalized_text):
            matches.append((len(name), int(row["id"])))
    if not matches:
        return None
    longest = max(length for length, _employee_id in matches)
    employee_ids = {employee_id for length, employee_id in matches if length == longest}
    return employee_ids.pop() if len(employee_ids) == 1 else None


def _ambiguous_roster_names(text: str, roster: list[dict]) -> list[str]:
    """Return duplicate first-name matches so the model cannot pick one arbitrarily."""
    groups: dict[str, list[str]] = {}
    for row in roster:
        display_name = re.sub(r"\s+", " ", str(row.get("name") or "")).strip()
        if not display_name:
            continue
        first_name = display_name.split(" ", 1)[0].casefold()
        groups.setdefault(first_name, []).append(display_name)

    normalized_text = re.sub(r"\s+", " ", text or "").casefold()
    for first_name, display_names in groups.items():
        if len(display_names) < 2:
            continue
        # Common Mongolian dative endings cover forms such as "Анужинд".
        pattern = rf"(?<!\w){re.escape(first_name)}(?:д|т)?(?!\w)"
        if re.search(pattern, normalized_text):
            return display_names
    return []


def _structure_from_tool_arguments(
    arguments: dict | None,
    *,
    roster: list[dict],
    timezone_name: str,
) -> dict | None:
    """Convert validated native create_task arguments into the legacy draft shape."""
    if not arguments:
        return None
    title = arguments.get("title")
    if not isinstance(title, str) or not title.strip():
        return None

    priority = arguments.get("priority", 2)
    if priority not in {1, 2, 3}:
        priority = 2

    deadline_at = None
    deadline_iso = arguments.get("deadline_iso")
    if isinstance(deadline_iso, str) and deadline_iso.strip():
        try:
            deadline_at = datetime.fromisoformat(deadline_iso.strip().replace("Z", "+00:00"))
            if deadline_at.tzinfo is None:
                deadline_at = pytz.timezone(timezone_name).localize(deadline_at)
        except (ValueError, pytz.UnknownTimeZoneError):
            deadline_at = None

    assignee_id = None
    assignee = arguments.get("assignee")
    if isinstance(assignee, str) and assignee.strip():
        assignee_value = assignee.strip()
        if assignee_value.startswith("@"):
            target = task_service.resolve_employee_by_username(assignee_value[1:])
            assignee_id = target.id if target else None
        else:
            assignee_id = _resolve_roster_name(assignee_value, roster)

    description = arguments.get("description")
    if not isinstance(description, str) or not description.strip():
        description = None
    else:
        description = description.strip()

    return {
        "title": title.strip()[:200],
        "description": description,
        "assignee_id": assignee_id,
        "assign_to_all": arguments.get("assign_to_all") is True,
        "deadline_at": deadline_at,
        "priority": priority,
    }


async def begin_task_draft(
    message: Message,
    state: FSMContext,
    text: str,
    *,
    employee,
    is_manager: bool,
    tg_id,
    tool_arguments: dict | None = None,
):
    # Себя гарантируем как Employee — руководитель тоже может быть исполнителем.
    if employee:
        self_emp = {"id": employee.id, "name": employee.name, "timezone": employee.timezone}
    elif tg_id:
        u = message.from_user
        self_emp = task_service.ensure_employee(
            tg_id, name=(u.full_name if u else None), username=(u.username if u else None)
        )
    else:
        self_emp = None
    tz = (self_emp.get("timezone") if self_emp else None) or "Asia/Ulaanbaatar"

    roster = _roster()
    all_active_assignee_ids = [row["id"] for row in roster]
    if self_emp and not any(r["id"] == self_emp["id"] for r in roster):
        roster.append({"id": self_emp["id"], "name": f"{self_emp['name']} (та өөрөө)", "username": self_emp.get("telegram_username")})

    now = _now_tz(tz)
    parsed = parse_task_text(text, now=now, tz=tz)
    structured = _structure_from_tool_arguments(
        tool_arguments,
        roster=roster,
        timezone_name=tz,
    )
    if structured is None and task_ai.ai_enabled():
        structured = await task_ai.structure_task(text, roster=roster, now=now, tz=tz)
    if structured is None:  # fallback на детерминированный парсер
        a_id = None
        if parsed.assignee_username:
            t = task_service.resolve_employee_by_username(parsed.assignee_username)
            a_id = t.id if t else None
        structured = {"title": parsed.title, "description": None, "assignee_id": a_id,
                      "assign_to_all": False, "deadline_at": parsed.deadline_at, "priority": parsed.priority}
    elif parsed.deadline_at is not None:
        # Mongolian relative dates/times are deterministic and timezone-aware;
        # prefer them over a model-generated ISO value that may assume UTC.
        structured["deadline_at"] = parsed.deadline_at

    assignee_id = structured.get("assignee_id")
    exact_name_id = _resolve_roster_name(text, roster)
    if exact_name_id is not None:
        # An exact stored full name is more reliable than a model selection.
        assignee_id = exact_name_id
    elif is_manager:
        ambiguous_names = _ambiguous_roster_names(text, roster)
        if ambiguous_names:
            options = "\n".join(f"• {name}" for name in ambiguous_names)
            await message.answer(
                f"🤔 Ижил нэртэй хэд хэдэн ажилтан байна:\n{options}\n"
                "Аль ажилтныг сонгохоо бүтэн нэрээр бичнэ үү.",
                parse_mode=None,
            )
            return
    assign_to_all = is_manager and (
        bool(structured.get("assign_to_all")) or _targets_all_workers(text)
    )
    # Самоназначение: рядовой сотрудник всегда себе; явное «мне/себе» — себе у любого.
    if self_emp and (not is_manager or (not assignee_id and _SELF_RE.search(text or ""))):
        assignee_id = self_emp["id"]

    if assign_to_all and not all_active_assignee_ids:
        await message.answer("👥 Идэвхтэй ажилтан алга байна. Эхлээд админ самбараас ажилтан нэмнэ үү.")
        return

    if not assign_to_all and not assignee_id:
        others = [r for r in roster if not self_emp or r["id"] != self_emp["id"]]
        if not others:
            await message.answer("👥 Одоогоор даалгавар өгөх өөр хүн алга. «Надад даалгавар өг» гэж бичих эсвэл админ самбараас ажилтан нэмнэ үү.")
        else:
            await message.answer("🤔 Хэнд даалгавар өгөхийг ойлгосонгүй. Гүйцэтгэгчийн @username эсвэл нэрийг бичнэ үү.")
        return

    name = next((e["name"] for e in roster if e["id"] == assignee_id), None)
    if name:
        name = name.replace(" (та өөрөө)", "")
    draft = {
        "title": structured["title"], "description": structured.get("description"),
        "assignee_id": assignee_id, "assignee_ids": all_active_assignee_ids if assign_to_all else [assignee_id],
        "assign_to_all": assign_to_all,
        "assignee_name": f"Бүх идэвхтэй ажилтан ({len(all_active_assignee_ids)})" if assign_to_all else name,
        "deadline_at": structured.get("deadline_at"), "priority": structured.get("priority", 2),
        "created_by_id": self_emp["id"] if self_emp else None, "created_by_tg": tg_id,
    }
    await state.set_state(TaskDraft.confirming)
    await state.update_data(draft=draft)
    await _show_draft(message, draft)


@router.callback_query(F.data == "taskdraft:confirm", TaskDraft.confirming)
async def cb_draft_confirm(cb: CallbackQuery, state: FSMContext, tg_id: str | None = None):
    d = (await state.get_data()).get("draft")
    await state.clear()
    if not d:
        await cb.answer("Ноорогийн хугацаа дууссан", show_alert=True)
        return
    tasks = task_service.create_tasks_for_assignees(
        title=d["title"], assignee_ids=d.get("assignee_ids") or [d["assignee_id"]],
        created_by_id=d["created_by_id"], created_by_tg=d["created_by_tg"],
        deadline_at=d["deadline_at"], priority=d["priority"], description=d.get("description"),
    )
    for task in tasks:
        try:
            reminder_service.schedule_task_reminders(task)
        except Exception:  # noqa: BLE001
            log.exception("draft: не удалось запланировать напоминания task=%s", task["id"])
        _enqueue_assignment_bot(task, tg_id)
    if d.get("assign_to_all"):
        await cb.message.answer(
            f"✅ <b>{len(tasks)}</b> ажилтанд «{d['title']}» даалгавар үүслээ.",
            parse_mode="HTML",
        )
    else:
        task = tasks[0]
        await cb.message.answer(
            f"✅ <b>#{task['id']}</b> даалгавар үүслээ: «{task['title']}» → {d.get('assignee_name') or '—'}",
            parse_mode="HTML", reply_markup=task_actions_kb(task["id"]),
        )
    await cb.answer("Боллоо ✅")


@router.callback_query(F.data == "taskdraft:edit", TaskDraft.confirming)
async def cb_draft_edit(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.answer("✏️ За, даалгавраа текст эсвэл дуу хоолойгоор дахин илгээнэ үү.")
    await cb.answer()


@router.callback_query(F.data == "taskdraft:cancel", TaskDraft.confirming)
async def cb_draft_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.answer("❌ Цуцлагдлаа.")
    await cb.answer()


# ─── /mytasks ───────────────────────────────────────────────────────────────────

@router.message(Command("mytasks"))
async def cmd_mytasks(message: Message, employee=None):
    if not employee:
        await message.answer("❌ Та ажилтнаар бүртгэгдээгүй байна.")
        return
    tasks = task_service.list_assigned_to(employee.id, only_active=True)
    if not tasks:
        await message.answer("✨ Танд идэвхтэй даалгавар алга.")
        return
    lines = [f"📋 <b>Миний даалгаврууд ({len(tasks)})</b>\n"]
    lines += [_fmt_task_line(t) for t in tasks]
    lines.append("\nДуусгах: /done &lt;id&gt; · Хугацаа хойшлуулах: /snooze &lt;id&gt; &lt;цаг&gt;")
    await message.answer("\n".join(lines), parse_mode="HTML")


# ─── /assigned (задачи, которые я поставил) ──────────────────────────────────────

@router.message(Command("assigned"))
async def cmd_assigned(message: Message, employee=None, tg_id: str | None = None):
    tasks = task_service.list_created_by(
        employee_id=employee.id if employee else None, tg_id=tg_id, only_active=True
    )
    if not tasks:
        await message.answer("📭 Та бусдад идэвхтэй даалгавар өгөөгүй байна.")
        return
    lines = [f"📤 <b>Миний өгсөн даалгаврууд ({len(tasks)})</b>\n"]
    lines += [_fmt_task_line(t, with_assignee=True) for t in tasks]
    await message.answer("\n".join(lines), parse_mode="HTML")


# ─── /done <id> ──────────────────────────────────────────────────────────────────

@router.message(Command("done"))
async def cmd_done(message: Message, command: CommandObject, employee=None, is_manager: bool = False, tg_id: str | None = None):
    arg = (command.args or "").strip()
    if not arg.isdigit():
        await message.answer("Хэлбэр: <code>/done &lt;id&gt;</code>", parse_mode="HTML")
        return
    await _complete_task(message, int(arg), employee, is_manager, tg_id)


async def _complete_task(target, task_id: int, employee, is_manager: bool, tg_id: str | None):
    task = task_service.get_task(task_id)
    if not task:
        await target.answer("❌ Даалгавар олдсонгүй.")
        return
    if not task_service.can_modify(task, employee_id=employee.id if employee else None, tg_id=tg_id, is_manager=is_manager):
        await target.answer("❌ Энэ даалгаварт хандах эрх алга.")
        return
    task_service.set_status(task_id, "done", by_employee_id=employee.id if employee else None)
    reminder_service.cancel_task_jobs(task_id)
    await target.answer(f"✅ #{task_id} «{task['title']}» даалгаврыг дууссанд тэмдэглэлээ.")


# ─── /snooze <id> <время> ────────────────────────────────────────────────────────

@router.message(Command("snooze"))
async def cmd_snooze(message: Message, command: CommandObject, employee=None, is_manager: bool = False, tg_id: str | None = None):
    parts = (command.args or "").strip().split(maxsplit=1)
    if len(parts) < 2 or not parts[0].isdigit():
        await message.answer("Хэлбэр: <code>/snooze &lt;id&gt; &lt;цаг&gt;</code>, жишээ нь <code>/snooze 12 маргааш 10:00</code>", parse_mode="HTML")
        return
    task_id = int(parts[0])
    task = task_service.get_task(task_id)
    if not task:
        await message.answer("❌ Даалгавар олдсонгүй.")
        return
    if not task_service.can_modify(task, employee_id=employee.id if employee else None, tg_id=tg_id, is_manager=is_manager):
        await message.answer("❌ Энэ даалгаварт хандах эрх алга.")
        return
    tz = employee.timezone if employee else "Asia/Ulaanbaatar"
    new_dt = parse_when(parts[1], now=_now_tz(tz), tz=tz)
    if not new_dt:
        await message.answer("❌ Хугацааг ойлгосонгүй. Жишээ: «маргааш 10:00», «2 хоногийн дараа», «баасан гарагт 18:00».")
        return
    updated = task_service.snooze(task_id, new_dt)
    reminder_service.schedule_task_reminders(updated)
    await message.answer(f"⏰ #{task_id} даалгаврын хугацааг <b>{_fmt_deadline(new_dt)}</b> болгон хойшлууллаа.", parse_mode="HTML")


# ─── /dashboard ──────────────────────────────────────────────────────────────────

@router.message(Command("dashboard"))
async def cmd_dashboard(message: Message, employee=None, is_manager: bool = False, tg_id: str | None = None):
    if is_manager:
        groups = task_service.all_active_grouped_by_assignee()
        if not groups:
            await message.answer("✨ Идэвхтэй даалгавар алга.")
            return
        total = sum(len(v) for v in groups.values())
        overdue = sum(1 for v in groups.values() for t in v if t["status"] == "overdue")
        lines = [f"👔 <b>Идэвхтэй даалгаврууд ({total})</b>\n"]
        for name, items in groups.items():
            lines.append(f"\n👤 <b>{name}</b> ({len(items)}):")
            lines += [f"  {_fmt_task_line(t)}" for t in items]
        if overdue:
            lines.append(f"\n⚠️ Хугацаа хэтэрсэн: {overdue}")
        await message.answer("\n".join(lines), parse_mode="HTML")
        return

    # Сотрудник: мои задачи + что я поставил
    mine = task_service.list_assigned_to(employee.id, only_active=True) if employee else []
    created = task_service.list_created_by(
        employee_id=employee.id if employee else None, tg_id=tg_id, only_active=True
    )
    lines = ["📊 <b>Миний хянах самбар</b>\n", f"\n📋 Надад оноосон ({len(mine)}):"]
    lines += [f"  {_fmt_task_line(t)}" for t in mine] or ["  —"]
    lines.append(f"\n📤 Миний өгсөн ({len(created)}):")
    lines += [f"  {_fmt_task_line(t, with_assignee=True)}" for t in created] or ["  —"]
    await message.answer("\n".join(lines), parse_mode="HTML")


# ─── callbacks с inline-кнопок ───────────────────────────────────────────────────

@router.callback_query(F.data.startswith("task:done:"))
async def cb_task_done(cb: CallbackQuery, employee=None, is_manager: bool = False, tg_id: str | None = None):
    task_id = int(cb.data.split(":")[2])
    await _complete_task(cb.message, task_id, employee, is_manager, tg_id)
    await cb.answer("Боллоо ✅")


@router.callback_query(F.data.startswith("task:snooze:"))
async def cb_task_snooze(cb: CallbackQuery, employee=None, is_manager: bool = False, tg_id: str | None = None):
    _, _, task_id_s, mins_s = cb.data.split(":")
    task_id, mins = int(task_id_s), int(mins_s)
    task = task_service.get_task(task_id)
    if not task:
        await cb.answer("Даалгавар олдсонгүй", show_alert=True)
        return
    if not task_service.can_modify(task, employee_id=employee.id if employee else None, tg_id=tg_id, is_manager=is_manager):
        await cb.answer("Хандах эрх алга", show_alert=True)
        return
    from datetime import timedelta

    base = task["deadline_at"] or datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    new_dt = base + timedelta(minutes=mins)
    updated = task_service.snooze(task_id, new_dt)
    reminder_service.schedule_task_reminders(updated)
    await cb.answer(f"Хугацааг {_fmt_deadline(new_dt)} болгон хойшлууллаа")
