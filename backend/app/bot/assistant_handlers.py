"""Telegram intake for OYUNS: text and voice messages go to the shared agent.

Voice: Telegram audio → Chimege STT (OpenAI fallback) → the same agent turn
as text, flagged as a speech transcript → text answer plus an optional Chimege
TTS audio reply.
"""

from __future__ import annotations

import html
import logging
import re
from dataclasses import replace
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select

from app.bot.tasks_handlers import TaskDraft
from app.bot.work_report_handlers import claim_report_text
from app.core.database import AsyncSessionLocal
from app.core.enterprise_deps import actor_from_telegram_id, file_search_principal_from_telegram_id
from app.models.models import AssistantConversation, AssistantMessage
from app.services import enterprise_tools, voice_service
from app.services.ai_gateway import AIGateway, GatewayError
from app.services.assistant_text import detect_language
from app.services.attachment_storage import get_attachment
from app.services.file_search_service import FileSearchPrincipal, FileSearchServiceError, authorized_file, is_file_search_query, search_files
from app.services.mcp.references import resolve_action_reference

log = logging.getLogger(__name__)
router = Router()
ai_gateway = AIGateway()

TEXTS: dict[str, dict[str, str]] = {
    "unavailable": {
        "mn": "OYUNS одоогоор хариу өгөх боломжгүй байна. Түр хүлээгээд дахин оролдоно уу.",
        "ru": "OYUNS сейчас недоступен. Попробуйте чуть позже.",
        "en": "OYUNS is temporarily unavailable. Please try again shortly.",
    },
    "needs_account": {
        "mn": "OYUNS ашиглахын тулд идэвхтэй платформын бүртгэлтэй холбогдсон байх шаардлагатай.",
        "ru": "Для OYUNS нужна привязанная активная учётная запись платформы.",
        "en": "OYUNS requires a linked active platform account.",
    },
    "empty": {
        "mn": "Одоогоор хариулт боловсруулж чадсангүй. Дахин оролдоно уу.",
        "ru": "Не удалось сформировать ответ. Попробуйте ещё раз.",
        "en": "I could not generate a response right now. Please try again shortly.",
    },
    "recognizing": {
        "mn": "🎙 Дуут мессежийг таньж байна…",
        "ru": "🎙 Распознаю голосовое сообщение…",
        "en": "🎙 Recognizing your message…",
    },
    "recognized": {"mn": "Танигдсан текст", "ru": "Распознано", "en": "Recognized"},
    "stt_unavailable": {
        "mn": "Дуу хоолой таних үйлчилгээ тохируулагдаагүй байна. Хүсэлтээ текстээр бичнэ үү.",
        "ru": "Распознавание голоса не настроено. Отправьте запрос текстом.",
        "en": "Voice transcription is unavailable. Please send your request as text.",
    },
    "download_failed": {
        "mn": "Дуут мессежийг татаж чадсангүй. Дахин илгээх эсвэл текстээр бичнэ үү.",
        "ru": "Не удалось скачать аудио. Повторите или отправьте текст.",
        "en": "I could not download that audio. Please try again or send text.",
    },
    "not_understood": {
        "mn": "Бичлэгийг ойлгож чадсангүй. Дахин оролдоно уу.",
        "ru": "Не удалось разобрать запись. Попробуйте ещё раз.",
        "en": "I could not understand that recording. Please try again.",
    },
    "open_file": {"mn": "Файл нээх", "ru": "Открыть файл", "en": "Open protected file"},
    "file_unavailable": {
        "mn": "Файл олдсон боловч хавсралтыг одоогоор илгээх боломжгүй байна.",
        "ru": "Файл найден, но вложение сейчас недоступно.",
        "en": "I found the file, but its attachment is currently unavailable.",
    },
}


def _t(key: str, language: str) -> str:
    return TEXTS[key].get(language, TEXTS[key]["mn"])


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


_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_CODE_RE = re.compile(r"`([^`\n]+)`")
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+)$", re.M)


def telegram_html(text: str) -> str:
    """Render the model's light Markdown as Telegram HTML (escaped first)."""
    escaped = html.escape(text, quote=False)
    escaped = _HEADING_RE.sub(r"<b>\1</b>", escaped)
    escaped = _BOLD_RE.sub(r"<b>\1</b>", escaped)
    escaped = _CODE_RE.sub(r"<code>\1</code>", escaped)
    return re.sub(r"^(\s*)[-*]\s+", r"\1• ", escaped, flags=re.M)


async def _answer(message: Message, text: str, *, reply_markup=None, parse_mode=None, language: str = "mn") -> None:
    """Send Telegram-sized chunks; fall back to plain text if HTML is rejected."""
    remaining = (text or "").strip()
    if not remaining:
        log.warning("assistant.telegram_empty_response")
        remaining = _t("empty", language)
    while remaining:
        if len(remaining) <= 3_900:
            chunk, remaining = remaining, ""
        else:
            split_at = remaining.rfind("\n", 0, 3_900)
            if split_at < 1:
                split_at = 3_900
            chunk, remaining = remaining[:split_at], remaining[split_at:].lstrip()
        markup = reply_markup if not remaining else None
        if parse_mode == "HTML":
            try:
                await message.answer(telegram_html(chunk), parse_mode="HTML", reply_markup=markup)
                continue
            except TelegramBadRequest:
                log.warning("assistant.telegram_html_rejected")
        await message.answer(chunk, parse_mode=None, reply_markup=markup)


async def _send_voice_answer(message: Message, text: str) -> None:
    """Add a Chimege TTS audio reply after the text answer when enabled."""
    if not voice_service.tts_answers_enabled() or not await voice_service.synthesis_available():
        return
    audio, error = await voice_service.synthesize(text)
    if not audio:
        log.warning("assistant.answer_tts_failed: %s", error)
        return
    await message.answer_audio(BufferedInputFile(audio, filename="oyuns-answer.wav"), title="OYUNS хариулт", performer="OYUNS")


async def _deliver_company_file_attachment(message: Message, db, principal: FileSearchPrincipal, delivery: dict, *, language: str = "mn") -> None:
    """Deliver one already-authorized file without replacing the AI answer on failure."""
    try:
        item_id = int(delivery["item_id"])
        resolved = await authorized_file(db, principal, item_id)
    except Exception:
        log.exception("assistant.telegram_attachment_authorization_failed")
        await _answer(message, _t("file_unavailable", language))
        return
    if not resolved:
        # Do not reveal whether a stale or revoked delivery reference exists.
        log.warning("assistant.telegram_attachment_not_authorized")
        return
    item = resolved[0]
    if not item.storage_key:
        log.warning("assistant.telegram_attachment_missing_storage_key item_id=%s", item.id)
        await _answer(message, _t("file_unavailable", language))
        return
    try:
        content = await get_attachment(item.storage_key)
        await message.answer_document(BufferedInputFile(content, filename=item.name))
    except (OSError, RuntimeError, ValueError):
        log.warning("assistant.telegram_attachment_storage_failed item_id=%s", item.id, exc_info=True)
        await _answer(message, _t("file_unavailable", language))
    except Exception:
        log.exception("assistant.telegram_attachment_delivery_failed item_id=%s", item.id)
        await _answer(message, _t("file_unavailable", language))


async def _employee_only_file_search(message: Message, db, principal: FileSearchPrincipal, text: str, language: str) -> None:
    """Company file discovery for employees linked in Telegram without a platform account."""
    request = type("FileRequest", (), {
        "operation": "search", "query": text[:500], "search_mode": "hybrid",
        "folder_id": None, "file_types": [], "limit": 5,
        "delivery": "attachment" if enterprise_tools.wants_file_attachment(text) else "none",
    })()
    try:
        result = await search_files(db, principal, request)
    except FileSearchServiceError:
        await _answer(message, _t("unavailable", language))
        return
    rows = result.get("data", {}).get("results", [])
    if rows and result.get("status") not in {"unavailable", "denied"}:
        lines = []
        for row in rows:
            state = row.get("content_state")
            suffix = f" ({state})" if state in {"indexing", "empty", "failed"} else ""
            lines.append(f"• {row.get('title') or 'file'}{suffix}")
        await _answer(message, "\n".join(lines))
    else:
        await _answer(message, _t("unavailable" if result.get("status") == "unavailable" else "needs_account", language))
    for delivery in result.get("deliveries", []):
        if delivery.get("kind") == "company_file_attachment":
            await _deliver_company_file_attachment(message, db, principal, delivery, language=language)


async def _enterprise_route(
    message: Message,
    state: FSMContext,
    text: str,
    *,
    employee,
    is_manager: bool,
    tg_id: str | None,
    voice_mode: bool = False,
    language: str = "mn",
) -> bool:
    """Run one Telegram turn through the shared OYUNS agent."""
    del state, employee, is_manager
    if not tg_id:
        return False
    detected = detect_language(text).value
    interface_language = language if language in {"mn", "ru", "en"} else "mn"
    async with AsyncSessionLocal() as db:
        actor = await actor_from_telegram_id(tg_id, db)
        if not actor:
            principal = await file_search_principal_from_telegram_id(tg_id, db)
            if principal and is_file_search_query(text):
                await _employee_only_file_search(message, db, principal, text, interface_language)
                return True
            await _answer(message, _t("needs_account", interface_language))
            return True
        chat = getattr(message, "chat", None)
        thread_key = str(getattr(chat, "id", tg_id))
        conversation = await db.scalar(select(AssistantConversation).where(AssistantConversation.account_id == actor.account_id, AssistantConversation.channel == "telegram", AssistantConversation.external_thread_key == thread_key))
        if not conversation:
            conversation = AssistantConversation(account_id=actor.account_id, organization_id=actor.organization_id, channel="telegram", external_thread_key=thread_key, title=text[:120])
            db.add(conversation); await db.flush()
        rows = (await db.execute(select(AssistantMessage).where(AssistantMessage.conversation_id == conversation.id).order_by(AssistantMessage.id.desc()).limit(12))).scalars().all()
        history = [{"role": row.role, "content": row.content} for row in reversed(rows)]
        # A reply to an earlier message (for example a task draft being
        # edited) makes that message the immediate context of this request.
        replied = _replied_message_context(message)
        if replied:
            history.append(replied)
        db.add(AssistantMessage(conversation_id=conversation.id, role="user", content=text))
        actor = replace(actor, channel="telegram", detected_language=detected)
        try:
            routed = await ai_gateway.execute_turn(
                db, actor, [*history, {"role": "user", "content": text}], conversation_id=conversation.id,
                memory=list(getattr(conversation, "mcp_context", None) or []),
                input_mode="voice" if voice_mode else "text",
            )
        except GatewayError:
            await db.rollback()
            await _answer(message, _t("unavailable", interface_language))
            return True
        tool_sources: list[dict] = []
        tool_deliveries: list[dict] = list(routed.deliveries)
        pending_action = None
        for tool_result in routed.tool_results:
            tool_sources.extend(tool_result.get("sources", []))
            tool_deliveries.extend(tool_result.get("deliveries", []))
            action_data = tool_result.get("data", {}).get("pending_action")
            pending_action = action_data or pending_action
        principal = FileSearchPrincipal.from_actor(actor)
        validated_deliveries: list[dict] = []
        for delivery in tool_deliveries:
            try:
                item_id = int(delivery.get("item_id"))
            except (AttributeError, TypeError, ValueError):
                source_id = str(delivery.get("source_id", ""))
                if not source_id.startswith("company_file:"):
                    continue
                try:
                    item_id = int(source_id.split(":", 1)[1])
                except (IndexError, ValueError):
                    continue
            if await authorized_file(db, principal, item_id):
                validated_deliveries.append({**delivery, "item_id": item_id})
        action = {"type": "task_action_preview", "payload": pending_action} if pending_action else None
        source_map = {str(item.get("id") or item.get("reference")): item for item in [*tool_sources, *routed.sources] if item.get("id") or item.get("reference")}
        attachments = enterprise_tools.attachment_metadata(validated_deliveries)
        db.add(AssistantMessage(conversation_id=conversation.id, role="assistant", content=routed.answer, action=action, sources=list(source_map.values()), attachments=attachments))
        conversation.mcp_context = routed.memory
        conversation.updated_at = datetime.now(timezone.utc)
        await db.commit()
        action_reference = (pending_action or {}).get("action_reference")
        if action_reference:
            try:
                # Telegram callback payloads are capped at 64 bytes. Resolve
                # the MCP-only encrypted reference inside the trusted bot,
                # then send the compact pending-action token only to Telegram
                # (never back to the model or the conversation record).
                callback_token = resolve_action_reference(actor, action_reference, channel="telegram")
            except ValueError:
                callback_token = None
        else:
            callback_token = (pending_action or {}).get("token")
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Баталгаажуулах" if interface_language == "mn" else "✅ Confirm" if interface_language == "en" else "✅ Подтвердить", callback_data=f"ac:{callback_token}"),
            InlineKeyboardButton(text="❌ Татгалзах" if interface_language == "mn" else "❌ Reject" if interface_language == "en" else "❌ Отклонить", callback_data=f"ar:{callback_token}"),
            InlineKeyboardButton(text="✏️ Засах" if interface_language == "mn" else "✏️ Edit" if interface_language == "en" else "✏️ Изменить", callback_data=f"ae:{callback_token}"),
        ]]) if callback_token else None
        await _answer(message, routed.answer, reply_markup=keyboard, parse_mode="HTML", language=interface_language)
        if voice_mode and not pending_action and not routed.degraded:
            await _send_voice_answer(message, routed.answer)
        protected_links = [delivery.get("url") for delivery in validated_deliveries if delivery.get("kind") == "authenticated_link" and delivery.get("url")]
        if protected_links:
            await _answer(message, f"{_t('open_file', interface_language)}: " + "\n".join(protected_links))
        for delivery in validated_deliveries:
            if delivery.get("kind") == "company_file_attachment":
                await _deliver_company_file_attachment(message, db, principal, delivery, language=interface_language)
    return True


async def route_and_respond(
    message: Message,
    state: FSMContext,
    text: str,
    *,
    employee,
    is_manager: bool,
    tg_id: str | None,
    voice_mode: bool,
    language: str = "mn",
) -> None:
    language = language if language in {"mn", "ru", "en"} else "mn"
    try:
        handled = await _enterprise_route(message, state, text, employee=employee, is_manager=is_manager, tg_id=tg_id, voice_mode=voice_mode, language=language)
    except Exception:
        log.exception("assistant.telegram_route_failed", extra={"telegram_id": tg_id})
        await _answer(message, _t("unavailable", language))
        return
    if not handled:
        # A Telegram message without a verified identity never reaches the agent.
        await _answer(message, _t("needs_account", language))


@router.callback_query(F.data.startswith("assistant-confirm:"))
@router.callback_query(F.data.startswith("ap1."))
@router.callback_query(F.data.startswith("ap2."))
@router.callback_query(F.data.startswith("ac:"))
@router.callback_query(F.data.startswith("ar:"))
@router.callback_query(F.data.startswith("ae:"))
async def confirm_enterprise_task_update(callback: CallbackQuery, tg_id: str | None = None, language: str = "mn"):
    language = language if language in {"mn", "ru", "en"} else "mn"
    copy = {
        "mn": {"access": "Хандах боломжгүй", "link": "Эхлээд байгууллагын бүртгэлээ холбоно уу", "edit": "Ноорогийг засахын тулд доорх зааврын дагуу хариу бичнэ үү.", "reply": "✏️ Даалгаврын ноорогийг засахын тулд энэ мессежид reply хийж өөрчлөлтөө бичнэ үү. Жишээ: “гарчгийг Борлуулалтын тайлан болго”.", "rejected": "Ноорог татгалзагдлаа", "created": "Даалгавар үүслээ", "updated": "Даалгавар шинэчлэгдлээ", "cancelled": "❌ Даалгаврын ноорог үүсгэлгүй цуцаллаа.", "failed": "Үйлдлийг гүйцэтгэж чадсангүй."},
        "ru": {"access": "Нет доступа", "link": "Сначала свяжите аккаунт организации", "edit": "Чтобы изменить черновик, ответьте на сообщение с новыми данными.", "reply": "✏️ Ответьте на это сообщение, чтобы изменить черновик задачи. Например: «изменить название на Отчёт по продажам»." , "rejected": "Черновик отклонён", "created": "Задача создана", "updated": "Задача обновлена", "cancelled": "❌ Черновик задачи отменён без создания.", "failed": "Не удалось выполнить действие."},
        "en": {"access": "Access unavailable", "link": "Link your organization account first", "edit": "Reply below with the changes you want to make to the draft.", "reply": "✏️ Reply to this message with your changes to the task draft. For example: “change the title to Sales report”.", "rejected": "Draft rejected", "created": "Task created", "updated": "Task updated", "cancelled": "❌ The task draft was cancelled without creating a task.", "failed": "Could not complete the action."},
    }[language]
    data = callback.data or ""
    operation = "confirm"
    if data.startswith("ar:"):
        operation = "reject"
    elif data.startswith("ae:"):
        operation = "edit"
    token = data.split(":", 1)[-1]
    if not tg_id:
        await callback.answer(copy["access"], show_alert=True); return
    async with AsyncSessionLocal() as db:
        actor = await actor_from_telegram_id(tg_id, db)
        if not actor:
            await callback.answer(copy["link"], show_alert=True); return
        if operation == "edit":
            result = None
        elif operation == "reject":
            result = await enterprise_tools.reject_task_action(db, actor, token, channel="telegram")
        else:
            result = await enterprise_tools.confirm_task_update(db, actor, token, channel="telegram")
        await db.commit()
    if operation == "edit":
        await callback.answer(copy["edit"])
        if callback.message:
            await callback.message.answer(copy["reply"])
        return
    assert result is not None
    outcome = result.get("data", {}).get("created") or result.get("data", {}).get("updated")
    if operation == "reject":
        success_text = copy["rejected"]
    else:
        success_text = copy["created"] if result.get("data", {}).get("created") else copy["updated"]
    await callback.answer(success_text if result["status"] == "ok" else copy["failed"], show_alert=result["status"] != "ok")
    if callback.message and result["status"] == "ok":
        title = outcome.get("title") if isinstance(outcome, dict) else None
        if operation == "reject":
            await callback.message.answer(copy["cancelled"])
        else:
            await callback.message.answer(f"✅ {success_text}: {title}" if title else f"✅ {success_text}.")


@router.message(StateFilter(None, TaskDraft.confirming), F.voice | F.audio | F.video_note)
async def msg_assistant_voice(
    message: Message,
    state: FSMContext,
    employee=None,
    is_manager: bool = False,
    tg_id: str | None = None,
    language: str = "mn",
):
    """Voice → Chimege speech-to-text → the same agent turn as a text message."""
    language = language if language in {"mn", "ru", "en"} else "mn"
    if not await voice_service.transcription_available():
        await _answer(message, _t("stt_unavailable", language))
        return
    await _answer(message, _t("recognizing", language))
    media = message.voice or message.audio or message.video_note
    try:
        buffer = await message.bot.download(media)
        audio = buffer.read()
    except Exception:
        log.exception("assistant.voice_download_failed")
        await _answer(message, _t("download_failed", language))
        return
    text, error = await voice_service.transcribe(audio)
    if not text:
        await _answer(message, error or _t("not_understood", language))
        return
    await _answer(message, f"{_t('recognized', language)}: {text}")
    await route_and_respond(message, state, text, employee=employee, is_manager=is_manager, tg_id=tg_id, voice_mode=True, language=language)


@router.message(StateFilter(None, TaskDraft.confirming), F.text & ~F.text.startswith("/"))
async def msg_assistant_text(
    message: Message,
    state: FSMContext,
    employee=None,
    is_manager: bool = False,
    tg_id: str | None = None,
    language: str = "mn",
):
    language = language if language in {"mn", "ru", "en"} else "mn"
    # Report replies are workflow input, not conversational prompts. Keep this
    # guard immediately before AI routing as a fallback for updates that were
    # not claimed by the report router above.
    if await claim_report_text(message, state, employee=employee, language=language):
        return
    await route_and_respond(message, state, message.text or "", employee=employee, is_manager=is_manager, tg_id=tg_id, voice_mode=False, language=language)
