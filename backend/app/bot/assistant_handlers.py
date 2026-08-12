"""Unified free-text and voice intake for the OYUNS corporate assistant."""

from __future__ import annotations

import logging
import html
import time
from collections import defaultdict, deque
from datetime import datetime, timezone

import pytz
from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.work_report_handlers import claim_report_text
from app.bot.tasks_handlers import TaskDraft, begin_task_draft, task_draft_keyboard, task_draft_text
from app.services import (
    assistant_ai,
    employee_directory_service,
    exchange_rate_service,
    knowledge_service,
    task_service,
    unknown_request_service,
    voice_service,
)
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.enterprise_deps import actor_from_telegram_id
from app.models.models import AssistantConversation, AssistantMessage, CompanyLibraryItem
from app.services import enterprise_tools
from app.services.ai_gateway import AIGateway, GatewayError, GatewayRequest
from app.services.attachment_storage import get_attachment
from sqlalchemy import select

log = logging.getLogger(__name__)
router = Router()
_conversation_history: dict[str, deque[dict]] = defaultdict(lambda: deque(maxlen=12))
ai_gateway = AIGateway()


def _history_key(message: Message, tg_id: str | None) -> str:
    chat = getattr(message, "chat", None)
    return str(tg_id or getattr(chat, "id", "anonymous"))


def _remember(history_key: str, user_text: str, assistant_text: str) -> None:
    history = _conversation_history[history_key]
    history.append({"role": "user", "content": user_text})
    history.append({"role": "assistant", "content": assistant_text})


def _replied_message_context(message: Message) -> dict | None:
    """Turn Telegram's replied-to message into safe conversational context."""
    replied = getattr(message, "reply_to_message", None)
    if not replied:
        return None
    content = (getattr(replied, "text", None) or getattr(replied, "caption", None) or "").strip()
    if not content:
        return None
    sender = getattr(replied, "from_user", None)
    role = "assistant" if bool(getattr(sender, "is_bot", False)) else "user"
    if role == "assistant" and "Даалгаврын ноорог" in content:
        label = "task draft being edited"
    else:
        label = "previous assistant reply" if role == "assistant" else "replied user message"
    return {
        "role": role,
        "content": f"<{label}>\n{content[:4_000]}\n</{label}>",
    }


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


async def _answer(message: Message, text: str, *, reply_markup=None, parse_mode=None) -> None:
    """Send Telegram-sized chunks; model output remains plain text by default."""
    remaining = text.strip()
    while remaining:
        if len(remaining) <= 3_900:
            chunk, remaining = remaining, ""
        else:
            split_at = remaining.rfind("\n", 0, 3_900)
            if split_at < 1:
                split_at = 3_900
            chunk, remaining = remaining[:split_at], remaining[split_at:].lstrip()
        await message.answer(
            chunk,
            parse_mode=parse_mode,
            reply_markup=reply_markup if not remaining else None,
        )


async def _enterprise_route(
    message: Message,
    state: FSMContext,
    text: str,
    *,
    employee,
    is_manager: bool,
    tg_id: str | None,
) -> bool:
    """Route Telegram task intake to the legacy draft controls.

    The Web assistant keeps the enterprise preview/action contract. Telegram
    already has a richer, familiar draft state with confirm, edit, and delete
    callbacks, so task-intake messages should enter that workflow directly.
    """
    if not tg_id:
        return False
    if assistant_ai.is_task_creation_request(text):
        async with AsyncSessionLocal() as db:
            actor = await actor_from_telegram_id(tg_id, db)
            if not actor:
                await _answer(message, "OYUNS access requires a linked active platform account.")
                return True
        await begin_task_draft(
            message,
            state,
            text,
            employee=employee,
            is_manager=is_manager,
            tg_id=tg_id,
            show_preview=True,
            allow_ai_structuring=True,
        )
        return True
    async with AsyncSessionLocal() as db:
        actor = await actor_from_telegram_id(tg_id, db)
        if not actor:
            await _answer(message, "OYUNS enterprise tools require a linked active platform account.")
            return True
        thread_key = str(getattr(message.chat, "id", tg_id))
        conversation = await db.scalar(select(AssistantConversation).where(AssistantConversation.account_id == actor.account_id, AssistantConversation.channel == "telegram", AssistantConversation.external_thread_key == thread_key))
        if not conversation:
            conversation = AssistantConversation(account_id=actor.account_id, organization_id=actor.organization_id, channel="telegram", external_thread_key=thread_key, title=text[:120])
            db.add(conversation); await db.flush()
        rows = (await db.execute(select(AssistantMessage).where(AssistantMessage.conversation_id == conversation.id).order_by(AssistantMessage.id.desc()).limit(12))).scalars().all()
        history = [{"role": row.role, "content": row.content} for row in reversed(rows)]
        db.add(AssistantMessage(conversation_id=conversation.id, role="user", content=text))
        grounding = await enterprise_tools.retrieve_turn_context(db, actor, text, channel="telegram", conversation_id=conversation.id)
        tool_sources: list[dict] = list(grounding.get("sources", []))
        tool_deliveries: list[dict] = []
        pending_action = None

        async def execute_gateway_tool(name: str, arguments: dict) -> dict:
            nonlocal pending_action
            if name == "file_search_tool" and enterprise_tools.wants_file_attachment(text):
                arguments = {**arguments, "delivery": "attachment"}
            result = await enterprise_tools.execute(db, actor, name, arguments, channel="telegram", prompt=text, conversation_id=conversation.id)
            tool_sources.extend(result.get("sources", []))
            tool_deliveries.extend(result.get("deliveries", []))
            pending_action = result.get("data", {}).get("pending_action") or pending_action
            return result

        try:
            routed = await ai_gateway.respond(db, GatewayRequest(text=text, history=history, channel="telegram", language_hint="mn", tools=enterprise_tools.tool_specs(), execute_tool=execute_gateway_tool, conversation_id=conversation.id, grounding_context=grounding.get("context"), grounding_sources=grounding.get("sources", [])))
        except GatewayError:
            await db.rollback()
            await _answer(message, "OYUNS live AI service is temporarily unavailable. Please try again shortly.")
            return True
        action = {"type": "task_action_preview", "payload": pending_action} if pending_action else None
        source_map = {item["id"]: item for item in [*tool_sources, *routed.sources] if item.get("id")}
        result = {"answer": routed.answer, "action": pending_action, "sources": list(source_map.values()), "deliveries": tool_deliveries}
        attachments = enterprise_tools.attachment_metadata(tool_deliveries)
        db.add(AssistantMessage(conversation_id=conversation.id, role="assistant", content=routed.answer, action=action, sources=result["sources"], attachments=attachments))
        conversation.updated_at = datetime.now(timezone.utc)
        await db.commit()
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Confirm task", callback_data=f"assistant-confirm:{result['action']['token']}")]]) if result.get("action") else None
        await _answer(message, html.escape(result["answer"]), reply_markup=keyboard, parse_mode="HTML")
        protected_links = [delivery.get("url") for delivery in result.get("deliveries", []) if delivery.get("kind") == "authenticated_link" and delivery.get("url")]
        if protected_links:
            await _answer(message, "Open protected file: " + "\n".join(protected_links), parse_mode=None)
        for delivery in result.get("deliveries", []):
            if delivery.get("kind") != "company_file_attachment":
                continue
            item = await db.get(CompanyLibraryItem, int(delivery["item_id"]))
            if item and item.storage_key:
                await message.answer_document(BufferedInputFile(await get_attachment(item.storage_key), filename=item.name))
    return True


def _should_answer_in_voice(
    decision: assistant_ai.RouteDecision,
    *,
    text: str,
) -> bool:
    """Voice is for questions/answers, never for task creation or editing."""
    if decision.selected_tool == assistant_ai.AssistantToolName.CREATE_TASK_DRAFT:
        return False
    if decision.selected_tool in {
        assistant_ai.AssistantToolName.GET_USER_TASKS,
        assistant_ai.AssistantToolName.SEARCH_COMPANY_KNOWLEDGE,
        assistant_ai.AssistantToolName.GET_EXCHANGE_RATE,
    }:
        return True
    if decision.router_intent in {
        assistant_ai.RouterIntent.VIEW_MY_TASKS,
        assistant_ai.RouterIntent.COMPANY_INFO,
        assistant_ai.RouterIntent.AGENT_CAPABILITIES,
    }:
        return True
    return bool(decision.direct_answer and assistant_ai.is_information_question(text))


async def _answer_question(
    message: Message,
    text: str,
    *,
    decision: assistant_ai.RouteDecision,
    reply_markup=None,
) -> None:
    """Send a question answer as Chimege audio, with a text fallback."""
    if (
        not _should_answer_in_voice(decision, text=text)
        or not voice_service.tts_answers_enabled()
        or not voice_service.synthesis_enabled()
    ):
        await _answer(message, text, reply_markup=reply_markup)
        return
    audio, error = await voice_service.synthesize(text)
    if audio:
        await _answer(message, text, reply_markup=reply_markup)
        await message.answer_audio(
            BufferedInputFile(audio, filename="oyuns-answer.wav"),
            title="OYUNS хариулт",
            performer="OYUNS",
        )
        return
    log.warning("assistant.answer_tts_failed: %s", error)
    await _answer(message, text, reply_markup=reply_markup)


async def _synthesize(
    decision: assistant_ai.RouteDecision,
    *,
    raw_result,
    voice_mode: bool,
) -> str | None:
    if not (
        decision.react_messages
        and decision.assistant_tool_message
        and decision.tool_call_id
    ):
        return None
    return await assistant_ai.synthesize_tool_result(
        request_messages=decision.react_messages,
        assistant_message=decision.assistant_tool_message,
        tool_call_id=decision.tool_call_id,
        raw_result=raw_result,
        voice_mode=voice_mode,
    )


def _task_raw_data(tasks: list[dict], *, timezone_name: str) -> dict:
    """Return only useful, privacy-safe records for the synthesis model."""
    try:
        zone = pytz.timezone(timezone_name)
    except Exception:
        zone = pytz.timezone("Asia/Ulaanbaatar")
    records = []
    for task in tasks[:50]:
        deadline = task.get("deadline_at")
        records.append(
            {
                "title": task.get("title"),
                "description": task.get("description"),
                "status": task.get("status"),
                "priority": task.get("priority"),
                "assignee_name": task.get("assignee_name"),
                "deadline_local": (
                    deadline.astimezone(zone).isoformat()
                    if getattr(deadline, "astimezone", None)
                    else None
                ),
            }
        )
    return {"count": len(tasks), "tasks": records, "timezone": zone.zone}


def _knowledge_raw_data(entries: list[dict], *, query: str) -> dict:
    return {
        "query": query,
        "count": len(entries),
        "documents": [
            {
                "title": entry.get("title"),
                "category": entry.get("category"),
                "content": entry.get("content"),
            }
            for entry in entries
        ],
    }


async def execute_tool(
    tool_name: assistant_ai.AssistantToolName,
    arguments: dict,
    *,
    message: Message,
    state: FSMContext,
    text: str,
    employee,
    actor: dict,
    is_manager: bool,
    tg_id: str | None,
    timezone_name: str,
) -> tuple[dict, object | None, str | None]:
    """Execute one validated assistant function and return raw data + UI controls."""
    if tool_name == assistant_ai.AssistantToolName.CREATE_TASK_DRAFT:
        result = await begin_task_draft(
            message,
            state,
            text,
            employee=employee,
            is_manager=is_manager,
            tg_id=tg_id,
            tool_arguments=arguments,
            show_preview=False,
            allow_ai_structuring=False,
        )
        keyboard = task_draft_keyboard() if result.get("ok") else None
        presentation = result.pop("_presentation", None)
        return result, keyboard, presentation

    if tool_name == assistant_ai.AssistantToolName.GET_USER_TASKS:
        date_range = {
            "today": "today",
            "this_week": "this_week",
            "all": "none",
        }[arguments["timeframe"]]
        start_at, end_at, include_overdue = task_service.local_date_bounds(
            date_range,
            tz=timezone_name,
        )
        tasks = task_service.list_for_actor(
            employee_id=actor["id"],
            tg_id=tg_id,
            scope="assigned",
            include_completed=False,
            start_at=start_at,
            end_at=end_at,
            include_overdue_before_start=include_overdue,
        )
        return _task_raw_data(tasks, timezone_name=timezone_name), None, None

    if tool_name == assistant_ai.AssistantToolName.SEARCH_COMPANY_KNOWLEDGE:
        query = arguments["query"]
        entries = knowledge_service.search_knowledge([query], limit=5)
        return _knowledge_raw_data(entries, query=query), None, None

    if tool_name == assistant_ai.AssistantToolName.GET_EXCHANGE_RATE:
        return await exchange_rate_service.get_exchange_rate(
            provider=arguments["provider"],
            pair=arguments["pair"],
            force_refresh=arguments.get("force_refresh", False),
            request_type=arguments.get("request_type", "single"),
        ), None, None

    raise ValueError(f"Unsupported assistant tool: {tool_name}")


def _unknown_response(language: assistant_ai.AssistantLanguage) -> str:
    return {
        assistant_ai.AssistantLanguage.EN: (
            "I could not classify that request yet. I saved it for review so OYUNS can be improved."
        ),
        assistant_ai.AssistantLanguage.RU: (
            "Я пока не смог классифицировать этот запрос. Я сохранил его для проверки, чтобы улучшить OYUNS."
        ),
        assistant_ai.AssistantLanguage.MN: (
            "Энэ хүсэлтийг одоогоор ангилж чадсангүй. OYUNS-ийг сайжруулахын тулд хяналтанд хадгаллаа."
        ),
    }[language]


def _generation_unavailable(language: assistant_ai.AssistantLanguage) -> str:
    """Explain an unavailable AI path without rendering static tool records."""
    if not assistant_ai.assistant_enabled():
        return {
            assistant_ai.AssistantLanguage.EN: (
                "OYUNS AI is not configured yet. Please ask an administrator to set OPENAI_API_KEY."
            ),
            assistant_ai.AssistantLanguage.RU: (
                "OYUNS AI пока не настроен. Попросите администратора задать OPENAI_API_KEY."
            ),
            assistant_ai.AssistantLanguage.MN: (
                "OYUNS AI одоогоор тохируулагдаагүй байна. Админаас OPENAI_API_KEY тохируулж өгөхийг хүснэ үү."
            ),
        }[language]
    return {
        assistant_ai.AssistantLanguage.EN: "I could not generate the response right now. Please try again shortly.",
        assistant_ai.AssistantLanguage.RU: "Сейчас не удалось сформировать ответ. Попробуйте ещё раз чуть позже.",
        assistant_ai.AssistantLanguage.MN: "Одоогоор хариулт боловсруулж чадсангүй. Түр хүлээгээд дахин оролдоно уу.",
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
    if await _enterprise_route(
        message,
        state,
        text,
        employee=employee,
        is_manager=is_manager,
        tg_id=tg_id,
    ):
        return
    # Telegram messages without a verified platform identity cannot safely be
    # sent to the assistant. Do not drop into the historical heuristic router.
    await _answer(message, "OYUNS access requires a linked active platform account.")
    return

    # Legacy implementation retained below temporarily for source-compatible
    # imports/tests; the guarded return above makes it unreachable in
    # production. It can be removed once downstream integrations stop
    # importing its helpers.
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

    timezone_name = actor.get("timezone") or "Asia/Ulaanbaatar"
    workers = employee_directory_service.list_workers()
    history_key = _history_key(message, tg_id)
    reply_context = _replied_message_context(message)
    chat_history = list(_conversation_history[history_key])
    if reply_context:
        chat_history.append(reply_context)
    learned_contexts = unknown_request_service.active_context_examples()
    decision = await assistant_ai.classify_intent(
        text,
        now=_now_in_timezone(timezone_name),
        timezone_name=timezone_name,
        is_manager=is_manager,
        workers=workers,
        voice_mode=voice_mode,
        chat_history=chat_history,
        learned_contexts=learned_contexts,
    )
    log.info(
        "assistant.route intent=%s router_intent=%s tool=%s confidence=%.2f "
        "language=%s channel=%s latency_ms=%d",
        decision.intent.value,
        decision.router_intent.value,
        decision.selected_tool.value if decision.selected_tool else "direct_or_fallback",
        decision.confidence,
        decision.language.value,
        "voice" if voice_mode else "text",
        int((time.monotonic() - started) * 1_000),
    )

    if decision.confidence < 0.55 and decision.clarification:
        await _answer(message, decision.clarification)
        return

    # True two-pass ReAct path: execute the selected function, append its raw
    # JSON to the original OpenAI message chain, and let pass two write the
    # only user-facing prose.
    if decision.selected_tool:
        raw_result, reply_markup, presentation = await execute_tool(
            decision.selected_tool,
            decision.tool_arguments,
            message=message,
            state=state,
            text=text,
            employee=employee,
            actor=actor,
            is_manager=is_manager,
            tg_id=tg_id,
            timezone_name=timezone_name,
        )
        # Rate-service failures have precise, safe user messages. Do not send
        # them through the model, which could accidentally invent a rate.
        if (
            decision.selected_tool == assistant_ai.AssistantToolName.GET_EXCHANGE_RATE
            and not raw_result.get("ok")
        ):
            answer = raw_result["user_message"]
            await _answer_question(message, answer, decision=decision)
            _remember(history_key, text, answer)
            return
        if presentation:
            # A task draft has a known, confirmation-oriented layout. Rendering
            # it locally avoids an unnecessary second model round trip and
            # prevents translation drift such as “Тасалын төсөл”.
            answer = presentation
            await _answer(message, answer, reply_markup=reply_markup, parse_mode="HTML")
        else:
            answer = await _synthesize(
                decision,
                raw_result=raw_result,
                voice_mode=voice_mode,
            )
            if not answer:
                answer = (
                    assistant_ai.knowledge_fallback_answer(raw_result, decision.language)
                    if decision.selected_tool == assistant_ai.AssistantToolName.SEARCH_COMPANY_KNOWLEDGE
                    else _generation_unavailable(decision.language)
                )
            await _answer_question(
                message,
                answer,
                decision=decision,
                reply_markup=reply_markup,
            )
        _remember(history_key, text, answer)
        return

    if decision.direct_answer:
        deterministic = assistant_ai.fallback_route(text, is_manager=is_manager)
        if deterministic.confidence <= 0.5:
            unknown_request_service.record_unknown_request(
                text=text,
                language=decision.language.value,
                channel="voice" if voice_mode else "text",
                reason="model_direct_answer_without_confident_fallback",
            )
            log.info(
                "assistant.unknown_direct_response_stored channel=%s",
                "voice" if voice_mode else "text",
            )
        await _answer_question(message, decision.direct_answer, decision=decision)
        _remember(history_key, text, decision.direct_answer)
        return

    if (
        decision.router_intent == assistant_ai.RouterIntent.UNKNOWN
        and decision.intent != assistant_ai.AssistantIntent.PLAN_WORK
    ):
        unknown_request_service.record_unknown_request(
            text=text,
            language=decision.language.value,
            channel="voice" if voice_mode else "text",
            reason="no_confident_route",
        )
        log.info("assistant.unknown_request_stored channel=%s", "voice" if voice_mode else "text")
        await _answer(message, _unknown_response(decision.language))
        return

    # The deterministic router is only an availability/safety fallback. It may
    # still prepare a confirmation draft, but it never renders DB or knowledge
    # records as static strings.
    if decision.intent == assistant_ai.AssistantIntent.DELEGATE_TASK:
        await begin_task_draft(
            message,
            state,
            text,
            employee=employee,
            is_manager=is_manager,
            tg_id=tg_id,
            tool_arguments=decision.tool_arguments,
            allow_ai_structuring=False,
        )
        return

    answer = _generation_unavailable(decision.language)
    await _answer(message, answer)
    _remember(history_key, text, answer)


@router.callback_query(F.data.startswith("assistant-confirm:"))
async def confirm_enterprise_task_update(callback: CallbackQuery, tg_id: str | None = None):
    token = (callback.data or "").split(":", 1)[-1]
    if not tg_id:
        await callback.answer("Access unavailable", show_alert=True); return
    async with AsyncSessionLocal() as db:
        actor = await actor_from_telegram_id(tg_id, db)
        if not actor:
            await callback.answer("Link an enterprise account first", show_alert=True); return
        result = await enterprise_tools.confirm_task_update(db, actor, token, channel="telegram")
        await db.commit()
    outcome = result.get("data", {}).get("created") or result.get("data", {}).get("updated")
    success_text = "Task created" if result.get("data", {}).get("created") else "Task updated"
    await callback.answer(success_text if result["status"] == "ok" else result["data"].get("reason", "Action unavailable"), show_alert=result["status"] != "ok")
    if callback.message and result["status"] == "ok":
        title = outcome.get("title") if isinstance(outcome, dict) else None
        await callback.message.answer(("Task created: " + title) if result.get("data", {}).get("created") and title else success_text + ".")


@router.message(StateFilter(None, TaskDraft.confirming), F.voice)
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


@router.message(StateFilter(None, TaskDraft.confirming), F.text & ~F.text.startswith("/"))
async def msg_assistant_text(
    message: Message,
    state: FSMContext,
    employee=None,
    is_manager: bool = False,
    tg_id: str | None = None,
):
    # Report replies are workflow input, not conversational prompts. Keep this
    # guard immediately before AI routing as a fallback for updates that were
    # not claimed by the report router above.
    if await claim_report_text(message, state, employee=employee):
        return
    await route_and_respond(
        message,
        state,
        message.text or "",
        employee=employee,
        is_manager=is_manager,
        tg_id=tg_id,
        voice_mode=False,
    )
