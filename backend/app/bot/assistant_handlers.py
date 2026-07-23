"""Unified free-text and voice intake for the OYUNS corporate assistant."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import pytz
from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.bot.tasks_handlers import begin_task_draft
from app.services import (
    assistant_ai,
    employee_directory_service,
    knowledge_service,
    task_service,
    voice_service,
)

log = logging.getLogger(__name__)
router = Router()


def _actor(employee, *, message: Message, is_manager: bool, tg_id: str | None) -> dict | None:
    if employee:
        if not employee.is_active and not is_manager:
            return None
        return {
            "id": employee.id,
            "name": employee.name,
            "timezone": employee.timezone or "Asia/Ulaanbaatar",
            "is_active": employee.is_active,
        }
    if is_manager and tg_id:
        user = message.from_user
        return task_service.ensure_employee(
            tg_id,
            name=user.full_name if user else "Удирдлага",
            username=user.username if user else None,
        )
    return None


def _now_in_timezone(timezone_name: str) -> datetime:
    try:
        zone = pytz.timezone(timezone_name)
    except Exception:
        zone = pytz.timezone("Asia/Ulaanbaatar")
    return datetime.now(zone)


async def _answer(message: Message, text: str) -> None:
    """Send plain text in Telegram-sized chunks so model output cannot become HTML."""
    remaining = text.strip()
    while remaining:
        if len(remaining) <= 3_900:
            chunk, remaining = remaining, ""
        else:
            split_at = remaining.rfind("\n", 0, 3_900)
            if split_at < 1:
                split_at = 3_900
            chunk, remaining = remaining[:split_at], remaining[split_at:].lstrip()
        await message.answer(chunk, parse_mode=None)


def _answer_with_knowledge_sources(
    answer: str,
    *,
    used_ids: list[int],
    knowledge: list[dict],
    language: assistant_ai.AssistantLanguage,
    voice_mode: bool,
) -> str:
    if voice_mode or not used_ids:
        return answer
    titles = [entry["title"] for entry in knowledge if entry["id"] in used_ids]
    if not titles:
        return answer
    source_label = {
        assistant_ai.AssistantLanguage.EN: "Sources",
        assistant_ai.AssistantLanguage.RU: "Источники",
        assistant_ai.AssistantLanguage.MN: "Эх сурвалж",
    }[language]
    return answer + f"\n\n{source_label}: " + "; ".join(titles)


def _capabilities(
    language: assistant_ai.AssistantLanguage,
    *,
    is_manager: bool,
) -> str:
    ai_on = assistant_ai.assistant_enabled()
    voice_on = voice_service.transcription_enabled()
    knowledge_on = knowledge_service.active_knowledge_count() > 0
    if language == assistant_ai.AssistantLanguage.EN:
        items = [
            "• Show and prioritize your assigned or created tasks.",
            "• Build a daily plan or break complex work into steps.",
            "• Create a confirmed task draft for you or a teammate.",
            "• Show the worker directory and active status.",
        ]
        if knowledge_on:
            items.append("• Answer questions from admin-managed company knowledge.")
        if ai_on:
            items.append("• Draft updates, summaries, and other workplace content.")
        if voice_on:
            items.append("• Understand voice messages and reply with concise text.")
        if is_manager:
            items.append("• Summarize team workload when you explicitly ask for it.")
        return "OYUNS Agent\n\n" + "\n".join(items)
    if language == assistant_ai.AssistantLanguage.RU:
        items = [
            "• Показывать и расставлять приоритеты ваших задач.",
            "• Составлять план дня и разбивать сложную работу на шаги.",
            "• Готовить подтверждаемый черновик задачи для вас или коллеги.",
            "• Показывать справочник сотрудников и их активность.",
        ]
        if knowledge_on:
            items.append("• Отвечать по базе знаний, которую ведёт администратор.")
        if ai_on:
            items.append("• Готовить обновления статуса, резюме и рабочие тексты.")
        if voice_on:
            items.append("• Понимать голосовые сообщения и отвечать кратким текстом.")
        if is_manager:
            items.append("• Сводить нагрузку команды по явному запросу руководителя.")
        return "OYUNS Agent\n\n" + "\n".join(items)

    items = [
        "• Танд оноосон болон таны үүсгэсэн даалгаврыг эрэмбэлж харуулна.",
        "• Өдрийн төлөвлөгөө гаргаж, төвөгтэй ажлыг алхам болгон задална.",
        "• Өөртөө эсвэл багийн гишүүнд баталгаажуулах ноорог даалгавар үүсгэнэ.",
        "• Ажилтны жагсаалт болон идэвхтэй эсэхийг харуулна.",
    ]
    if knowledge_on:
        items.append("• Админы оруулсан компанийн мэдлэгээс асуултад хариулна.")
    if ai_on:
        items.append("• Ажлын мэдээ, хураангуй болон бусад бичвэр бэлдэнэ.")
    if voice_on:
        items.append("• Дуут мессежийг ойлгож, товч текстээр хариулна.")
    if is_manager:
        items.append("• Удирдлагын тодорхой хүсэлтээр багийн ачааллыг нэгтгэнэ.")
    return "OYUNS Agent\n\n" + "\n".join(items)


def _task_relation(
    task: dict,
    actor_id: int,
    language: assistant_ai.AssistantLanguage,
) -> str:
    assigned = task.get("assignee_id") == actor_id
    created = task.get("created_by_id") == actor_id
    labels = {
        assistant_ai.AssistantLanguage.EN: ("assigned", "created", "assigned + created", "related"),
        assistant_ai.AssistantLanguage.RU: ("назначено мне", "создано мной", "моё", "связано"),
        assistant_ai.AssistantLanguage.MN: ("надад оноосон", "миний үүсгэсэн", "миний", "холбоотой"),
    }[language]
    if assigned and created:
        return labels[2]
    if assigned:
        return labels[0]
    if created:
        return labels[1]
    return labels[3]


def _format_deadline(
    value,
    timezone_name: str,
    language: assistant_ai.AssistantLanguage,
) -> str:
    if not value:
        return {
            assistant_ai.AssistantLanguage.EN: "no due date",
            assistant_ai.AssistantLanguage.RU: "без срока",
            assistant_ai.AssistantLanguage.MN: "хугацаагүй",
        }[language]
    try:
        return value.astimezone(pytz.timezone(timezone_name)).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _format_task_query(
    tasks: list[dict],
    *,
    actor_id: int,
    timezone_name: str,
    language: assistant_ai.AssistantLanguage,
) -> str:
    if not tasks:
        return {
            assistant_ai.AssistantLanguage.EN: "You have no matching tasks.",
            assistant_ai.AssistantLanguage.RU: "Подходящих задач нет.",
            assistant_ai.AssistantLanguage.MN: "Тохирох даалгавар алга.",
        }[language]

    headings = {
        assistant_ai.AssistantLanguage.EN: f"Your tasks ({len(tasks)}):",
        assistant_ai.AssistantLanguage.RU: f"Ваши задачи ({len(tasks)}):",
        assistant_ai.AssistantLanguage.MN: f"Таны даалгаврууд ({len(tasks)}):",
    }
    lines = [headings[language]]
    now_utc = datetime.now(timezone.utc)
    overdue_label = {
        assistant_ai.AssistantLanguage.EN: "OVERDUE · ",
        assistant_ai.AssistantLanguage.RU: "ПРОСРОЧЕНО · ",
        assistant_ai.AssistantLanguage.MN: "ХУГАЦАА ХЭТЭРСЭН · ",
    }[language]
    for task in tasks[:30]:
        overdue = bool(
            task.get("status") == "overdue"
            or (
                task.get("deadline_at")
                and task["deadline_at"] < now_utc
                and task.get("status") not in {"done", "cancelled"}
            )
        )
        marker = overdue_label if overdue else ""
        lines.append(
            f"{marker}P{task.get('priority', 2)} · #{task['id']} · "
            f"{task['title']} · "
            f"{_format_deadline(task.get('deadline_at'), timezone_name, language)} "
            f"· {_task_relation(task, actor_id, language)}"
        )
    if len(tasks) > 30:
        lines.append(f"… +{len(tasks) - 30}")
    return "\n".join(lines)


def _format_worker_directory(
    workers: list[dict],
    language: assistant_ai.AssistantLanguage,
    *,
    voice_mode: bool,
) -> str:
    if not workers:
        return {
            assistant_ai.AssistantLanguage.EN: "No workers are registered yet.",
            assistant_ai.AssistantLanguage.RU: "Зарегистрированных сотрудников пока нет.",
            assistant_ai.AssistantLanguage.MN: "Бүртгэлтэй ажилтан одоогоор алга.",
        }[language]
    heading = {
        assistant_ai.AssistantLanguage.EN: f"Workers ({len(workers)}):",
        assistant_ai.AssistantLanguage.RU: f"Сотрудники ({len(workers)}):",
        assistant_ai.AssistantLanguage.MN: f"Ажилтнууд ({len(workers)}):",
    }[language]
    labels = {
        assistant_ai.AssistantLanguage.EN: ("active", "inactive", "manager"),
        assistant_ai.AssistantLanguage.RU: ("активен", "неактивен", "руководитель"),
        assistant_ai.AssistantLanguage.MN: ("идэвхтэй", "идэвхгүй", "удирдлага"),
    }[language]
    lines = [heading]
    for worker in workers[:10 if voice_mode else 50]:
        username = f" · @{worker['telegram_username']}" if worker.get("telegram_username") else ""
        status = labels[0] if worker.get("is_active") else labels[1]
        role = f" · {labels[2]}" if worker.get("is_manager") else ""
        lines.append(f"• {worker['name']}{username} · {status}{role}")
    if len(workers) > (10 if voice_mode else 50):
        lines.append(f"… +{len(workers) - (10 if voice_mode else 50)}")
    return "\n".join(lines)


def _format_plan(
    plan: assistant_ai.WorkPlan,
    language: assistant_ai.AssistantLanguage,
) -> str:
    minute_label, next_label = {
        assistant_ai.AssistantLanguage.EN: ("min", "Next"),
        assistant_ai.AssistantLanguage.RU: ("мин", "Сейчас"),
        assistant_ai.AssistantLanguage.MN: ("мин", "Одоо"),
    }[language]
    lines = [plan.summary]
    for index, block in enumerate(plan.blocks, start=1):
        task = f" · #{block.task_id}" if block.task_id else ""
        lines.append(
            f"{index}. {block.label}{task} · {block.minutes} {minute_label}\n{block.action}"
        )
    lines.append(f"{next_label}: {plan.next_action}")
    return "\n\n".join(lines)


def _fallback_plan(
    tasks: list[dict],
    *,
    budget_minutes: int,
    language: assistant_ai.AssistantLanguage,
) -> str:
    intro = {
        assistant_ai.AssistantLanguage.EN: "Practical fallback plan:",
        assistant_ai.AssistantLanguage.RU: "Практичный резервный план:",
        assistant_ai.AssistantLanguage.MN: "Хэрэгжүүлэх энгийн төлөвлөгөө:",
    }[language]
    next_label = {
        assistant_ai.AssistantLanguage.EN: "Next",
        assistant_ai.AssistantLanguage.RU: "Сейчас",
        assistant_ai.AssistantLanguage.MN: "Одоо",
    }[language]
    if not tasks:
        focus = max(15, budget_minutes - 15)
        empty_steps = {
            assistant_ai.AssistantLanguage.EN: (
                f"1. Define the result · 15 min\n2. Focused execution · {focus} min\n"
                f"{next_label}: write the first concrete deliverable."
            ),
            assistant_ai.AssistantLanguage.RU: (
                f"1. Определить результат · 15 мин\n2. Сфокусированная работа · {focus} мин\n"
                f"{next_label}: сформулируйте первый конкретный результат."
            ),
            assistant_ai.AssistantLanguage.MN: (
                f"1. Үр дүнгээ тодорхойлох · 15 мин\n2. Төвлөрч гүйцэтгэх · {focus} мин\n"
                f"{next_label}: эхний бодит үр дүнгээ нэг өгүүлбэрээр бич."
            ),
        }
        return f"{intro}\n{empty_steps[language]}"

    remaining = budget_minutes
    lines = [intro]
    minute_label = "min" if language == assistant_ai.AssistantLanguage.EN else "мин"
    for index, task in enumerate(tasks[:6], start=1):
        if remaining < 15:
            break
        minutes = min(60, remaining)
        lines.append(f"{index}. #{task['id']} {task['title']} · {minutes} {minute_label}")
        remaining -= minutes
    next_text = {
        assistant_ai.AssistantLanguage.EN: f"start #{tasks[0]['id']} now.",
        assistant_ai.AssistantLanguage.RU: f"начните задачу #{tasks[0]['id']}.",
        assistant_ai.AssistantLanguage.MN: f"#{tasks[0]['id']} даалгаврыг эхлүүл.",
    }[language]
    lines.append(f"{next_label}: {next_text}")
    return "\n".join(lines)


def _general_fallback(
    tasks: list[dict],
    knowledge: list[dict],
    language: assistant_ai.AssistantLanguage,
    *,
    actor_id: int,
    timezone_name: str,
) -> str:
    if knowledge:
        heading = {
            assistant_ai.AssistantLanguage.EN: "Relevant company knowledge:",
            assistant_ai.AssistantLanguage.RU: "Подходящие материалы компании:",
            assistant_ai.AssistantLanguage.MN: "Холбогдох компанийн мэдээлэл:",
        }[language]
        lines = [heading]
        for entry in knowledge:
            excerpt = " ".join(entry["content"].split())[:350]
            lines.append(f"• {entry['title']}: {excerpt}")
        return "\n".join(lines)
    if tasks:
        return _format_task_query(
            tasks,
            actor_id=actor_id,
            timezone_name=timezone_name,
            language=language,
        )
    return {
        assistant_ai.AssistantLanguage.EN: "I cannot generate that response right now. Please try again shortly.",
        assistant_ai.AssistantLanguage.RU: "Сейчас не удалось подготовить ответ. Попробуйте ещё раз чуть позже.",
        assistant_ai.AssistantLanguage.MN: "Одоогоор хариулт бэлдэж чадсангүй. Түр хүлээгээд дахин оролдоно уу.",
    }[language]


async def route_and_respond(
    message: Message,
    state: FSMContext,
    text: str,
    *,
    employee,
    is_manager: bool,
    tg_id: str | None,
    voice_mode: bool,
) -> None:
    started = time.monotonic()
    actor = _actor(employee, message=message, is_manager=is_manager, tg_id=tg_id)
    if not actor:
        language = assistant_ai.detect_language(text)
        denial = {
            assistant_ai.AssistantLanguage.EN: "OYUNS access requires an active registered employee account.",
            assistant_ai.AssistantLanguage.RU: "Для доступа к OYUNS нужна активная учётная запись сотрудника.",
            assistant_ai.AssistantLanguage.MN: "OYUNS ашиглахын тулд идэвхтэй ажилтнаар бүртгүүлсэн байх шаардлагатай.",
        }[language]
        await _answer(message, denial)
        return

    # The directory is resolved before intent classification so it continues to
    # work when the LLM is disabled and is never confused with a task request.
    if assistant_ai.is_worker_directory_query(text):
        language = assistant_ai.detect_language(text)
        workers = employee_directory_service.list_workers()
        await _answer(
            message,
            _format_worker_directory(workers, language, voice_mode=voice_mode),
        )
        log.info(
            "assistant.directory channel=%s worker_count=%d latency_ms=%d",
            "voice" if voice_mode else "text",
            len(workers),
            int((time.monotonic() - started) * 1_000),
        )
        return

    # A relevant active article wins over broad capability classification. This
    # prevents questions such as "Чөлөө хэрхэн авах вэ?" from being answered
    # with the generic OYUNS feature list.
    direct_knowledge = knowledge_service.search_knowledge([text], limit=5)
    if direct_knowledge and assistant_ai.is_information_question(text):
        language = assistant_ai.detect_language(text)
        reply = await assistant_ai.generate_general_reply(
            user_text=text,
            language=language,
            tasks=[],
            knowledge=direct_knowledge,
            workers=[],
            voice_mode=voice_mode,
        )
        # A direct knowledge answer must identify its source. If the model does
        # not return a validated source ID, use the deterministic article
        # excerpt instead of risking a generic or ungrounded response.
        answer = (
            _answer_with_knowledge_sources(
                reply.answer,
                used_ids=reply.used_knowledge_ids,
                knowledge=direct_knowledge,
                language=language,
                voice_mode=voice_mode,
            )
            if reply and reply.used_knowledge_ids
            else _general_fallback(
                [],
                direct_knowledge,
                language,
                actor_id=actor["id"],
                timezone_name=actor.get("timezone") or "Asia/Ulaanbaatar",
            )
        )
        log.info(
            "assistant.knowledge_direct article_count=%d channel=%s latency_ms=%d",
            len(direct_knowledge),
            "voice" if voice_mode else "text",
            int((time.monotonic() - started) * 1_000),
        )
        await _answer(message, answer)
        return

    timezone_name = actor.get("timezone") or "Asia/Ulaanbaatar"
    decision = await assistant_ai.classify_intent(
        text,
        now=_now_in_timezone(timezone_name),
        timezone_name=timezone_name,
        is_manager=is_manager,
    )
    log.info(
        "assistant.route intent=%s confidence=%.2f language=%s channel=%s latency_ms=%d",
        decision.intent.value,
        decision.confidence,
        decision.language.value,
        "voice" if voice_mode else "text",
        int((time.monotonic() - started) * 1_000),
    )

    if decision.confidence < 0.55 and decision.clarification:
        await _answer(message, decision.clarification)
        return

    if decision.intent == assistant_ai.AssistantIntent.DELEGATE_TASK:
        await begin_task_draft(
            message,
            state,
            text,
            employee=employee,
            is_manager=is_manager,
            tg_id=tg_id,
        )
        return

    if decision.intent == assistant_ai.AssistantIntent.DISCOVER_CAPABILITIES:
        await _answer(
            message,
            _capabilities(decision.language, is_manager=is_manager),
        )
        return

    if decision.intent == assistant_ai.AssistantIntent.QUERY_MY_TASKS:
        start_at, end_at, include_overdue = task_service.local_date_bounds(
            decision.date_range.value,
            tz=timezone_name,
            start_date=decision.start_date,
            end_date=decision.end_date,
        )
        scope = decision.task_scope.value
        if scope == "team" and not is_manager:
            scope = "both"
        tasks = task_service.list_for_actor(
            employee_id=actor["id"],
            tg_id=tg_id,
            scope=scope,
            include_completed=decision.include_completed,
            start_at=start_at,
            end_at=end_at,
            include_overdue_before_start=include_overdue,
        )
        await _answer(
            message,
            _format_task_query(
                tasks,
                actor_id=actor["id"],
                timezone_name=timezone_name,
                language=decision.language,
            ),
        )
        return

    if decision.intent == assistant_ai.AssistantIntent.PLAN_WORK:
        tasks = task_service.list_for_actor(
            employee_id=actor["id"],
            tg_id=tg_id,
            scope="assigned",
        )
        budget = decision.time_budget_minutes or 480
        plan = await assistant_ai.generate_work_plan(
            user_text=text,
            language=decision.language,
            tasks=tasks,
            budget_minutes=budget,
            voice_mode=voice_mode,
        )
        await _answer(
            message,
            _format_plan(plan, decision.language)
            if plan
            else _fallback_plan(tasks, budget_minutes=budget, language=decision.language),
        )
        return

    scope = decision.task_scope.value
    if scope == "team" and not is_manager:
        scope = "both"
    tasks = task_service.list_for_actor(
        employee_id=actor["id"],
        tg_id=tg_id,
        scope=scope,
        include_completed=decision.include_completed,
    )
    knowledge = knowledge_service.search_knowledge(
        decision.knowledge_terms or [text],
        limit=5,
    )
    log.info(
        "assistant.knowledge_context intent=%s article_count=%d channel=%s",
        decision.intent.value,
        len(knowledge),
        "voice" if voice_mode else "text",
    )
    reply = await assistant_ai.generate_general_reply(
        user_text=text,
        language=decision.language,
        tasks=tasks,
        knowledge=knowledge,
        workers=[],
        voice_mode=voice_mode,
    )
    if reply:
        answer = _answer_with_knowledge_sources(
            reply.answer,
            used_ids=reply.used_knowledge_ids,
            knowledge=knowledge,
            language=decision.language,
            voice_mode=voice_mode,
        )
    else:
        answer = _general_fallback(
            tasks,
            knowledge,
            decision.language,
            actor_id=actor["id"],
            timezone_name=timezone_name,
        )
    await _answer(message, answer)


@router.message(StateFilter(None), F.voice)
async def msg_assistant_voice(
    message: Message,
    state: FSMContext,
    employee=None,
    is_manager: bool = False,
    tg_id: str | None = None,
):
    if not voice_service.transcription_enabled():
        await _answer(message, "Voice transcription is unavailable. Please send your request as text.")
        return
    await _answer(message, "🎙 Recognizing your message…")
    try:
        buffer = await message.bot.download(message.voice)
        audio = buffer.read()
    except Exception:
        log.exception("assistant.voice_download_failed")
        await _answer(message, "I could not download that audio. Please try again or send text.")
        return
    text, error = await voice_service.transcribe(audio)
    if not text:
        await _answer(message, error or "I could not understand that recording. Please try again.")
        return
    recognized_label = {
        assistant_ai.AssistantLanguage.EN: "Recognized",
        assistant_ai.AssistantLanguage.RU: "Распознано",
        assistant_ai.AssistantLanguage.MN: "Танигдсан текст",
    }[assistant_ai.detect_language(text)]
    await _answer(message, f"{recognized_label}: {text}")
    await route_and_respond(
        message,
        state,
        text,
        employee=employee,
        is_manager=is_manager,
        tg_id=tg_id,
        voice_mode=True,
    )


@router.message(StateFilter(None), F.text & ~F.text.startswith("/"))
async def msg_assistant_text(
    message: Message,
    state: FSMContext,
    employee=None,
    is_manager: bool = False,
    tg_id: str | None = None,
):
    await route_and_respond(
        message,
        state,
        message.text or "",
        employee=employee,
        is_manager=is_manager,
        tg_id=tg_id,
        voice_mode=False,
    )
