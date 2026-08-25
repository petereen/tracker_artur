from __future__ import annotations

import hashlib
import mimetypes
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import exists, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.enterprise_deps import ActorContext, get_actor
from app.core.security import hash_account_password
from app.models.models import (
    ChatAttachment,
    ChatConversation,
    ChatMessage,
    ChatMessageHidden,
    ChatMessagePin,
    ChatMessageReaction,
    ChatMessageReceipt,
    ChatMessageStar,
    ChatParticipant,
    Employee,
    JobQueue,
    UserAccount,
    WorkspacePresence,
)
from app.services.attachment_storage import delete_attachment, get_attachment, put_attachment
from app.services.enterprise_events import record_change
from app.services.malware_scanner import MalwareDetected, scan_upload
from app.services.ai_gateway import AIGateway, GatewayError
from app.services import assistant_ai
from app.services import enterprise_tools
from app.services.file_search_service import FileSearchPrincipal, authorized_file


router = APIRouter()
ai_gateway = AIGateway()
OYUNS_AGENT_EMAIL_PREFIX = "oyuns-agent+"
ONLINE_WINDOW = timedelta(seconds=60)
MAX_GROUP_MEMBERS = 100
MAX_MESSAGE_ATTACHMENTS = 10
MAX_MESSAGE_ATTACHMENT_BYTES = 100 * 1024 * 1024
MESSAGE_ACTION_WINDOW = timedelta(minutes=15)
STAGED_UPLOAD_TTL = timedelta(hours=24)
REACTIONS = {"👍", "❤️", "😂", "🎉", "😮", "😢"}
MUTE_DURATIONS = {
    "1h": timedelta(hours=1),
    "8h": timedelta(hours=8),
    "1w": timedelta(days=7),
    "forever": timedelta(days=36500),
}
ALLOWED_MEDIA_TYPES = {
    "image/jpeg": "image", "image/png": "image", "image/webp": "image", "image/gif": "image", "image/heic": "image",
    "video/mp4": "video", "video/webm": "video", "video/quicktime": "video",
    "audio/webm": "audio", "audio/mpeg": "audio", "audio/mp4": "audio", "audio/ogg": "audio", "audio/wav": "audio", "audio/x-wav": "audio", "audio/aac": "audio",
    "application/pdf": "document", "text/plain": "document", "text/csv": "document", "text/markdown": "document",
    "application/msword": "document", "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "document",
    "application/vnd.ms-excel": "document", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "document",
    "application/vnd.ms-powerpoint": "document", "application/vnd.openxmlformats-officedocument.presentationml.presentation": "document",
}


def _file_signature_matches(content_type: str, content: bytes) -> bool:
    """Reject obvious extension/content spoofing without trusting browser MIME metadata."""
    head = content[:32]
    if content_type == "image/jpeg":
        return head.startswith(b"\xff\xd8\xff")
    if content_type == "image/png":
        return head.startswith(b"\x89PNG\r\n\x1a\n")
    if content_type == "image/gif":
        return head.startswith((b"GIF87a", b"GIF89a"))
    if content_type == "image/webp":
        return head.startswith(b"RIFF") and head[8:12] == b"WEBP"
    if content_type == "image/heic":
        return head[4:8] == b"ftyp" and head[8:12] in {b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1"}
    if content_type in {"video/mp4", "video/quicktime", "audio/mp4"}:
        return head[4:8] == b"ftyp"
    if content_type in {"video/webm", "audio/webm"}:
        return head.startswith(b"\x1a\x45\xdf\xa3")
    if content_type == "audio/ogg":
        return head.startswith(b"OggS")
    if content_type in {"audio/wav", "audio/x-wav"}:
        return head.startswith(b"RIFF") and head[8:12] == b"WAVE"
    if content_type == "audio/mpeg":
        return head.startswith(b"ID3") or (len(head) >= 2 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0)
    if content_type == "audio/aac":
        return len(head) >= 2 and head[0] == 0xFF and head[1] & 0xF6 == 0xF0
    if content_type == "application/pdf":
        return head.startswith(b"%PDF-")
    if content_type in {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    }:
        return head.startswith(b"PK\x03\x04")
    if content_type in {"application/msword", "application/vnd.ms-excel", "application/vnd.ms-powerpoint"}:
        return head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
    if content_type in {"text/plain", "text/csv", "text/markdown"}:
        if b"\x00" in content[:8192] or head.startswith((b"MZ", b"\x7fELF")):
            return False
        try:
            content[:8192].decode("utf-8")
        except UnicodeDecodeError:
            return False
        return True
    return False


class DirectConversationIn(BaseModel):
    account_id: int | None = None
    employee_id: int | None = None
    agent: bool = False


class GroupConversationIn(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    member_account_ids: list[int]


class GroupTitleIn(BaseModel):
    title: str = Field(min_length=1, max_length=80)


class GroupMembersIn(BaseModel):
    account_ids: list[int]


class MessageIn(BaseModel):
    body: str | None = Field(default=None, max_length=4000)
    client_nonce: UUID
    upload_ids: list[UUID] = Field(default_factory=list, max_length=MAX_MESSAGE_ATTACHMENTS)
    reply_to_message_id: int | None = None


class MessageEditIn(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


class ConversationPreferencesIn(BaseModel):
    pinned: bool | None = None
    archived: bool | None = None
    mute_for: Literal["1h", "8h", "1w", "forever", "off"] | None = None


class ReactionIn(BaseModel):
    emoji: str = Field(min_length=1, max_length=16)


class ForwardDestination(BaseModel):
    conversation_public_id: UUID
    client_nonce: UUID


class ForwardIn(BaseModel):
    destinations: list[ForwardDestination] = Field(min_length=1, max_length=10)


class ReceiptIn(BaseModel):
    message_id: int
    status: Literal["delivered", "read"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clean_group_title(value: str) -> str:
    title = value.strip()
    if not title:
        raise HTTPException(status_code=422, detail="Group title cannot be empty")
    return title


def _is_muted(participant: ChatParticipant, now: datetime | None = None) -> bool:
    return bool(participant.muted_until and participant.muted_until > (now or _now()))


def _attachment_out(item: ChatAttachment, public_id: UUID) -> dict:
    return {
        "id": item.id,
        "public_id": str(item.public_id),
        "filename": item.filename,
        "content_type": item.content_type,
        "media_kind": item.media_kind,
        "size": item.size,
        "duration_seconds": item.duration_seconds,
        "scan_status": item.scan_status,
        "download_url": f"/v1/chat/conversations/{public_id}/attachments/{item.public_id}",
    }


async def _identity_map(db: AsyncSession, account_ids: list[int]) -> dict[int, dict]:
    if not account_ids:
        return {}
    rows = (
        await db.execute(
            select(UserAccount, Employee, WorkspacePresence)
            .outerjoin(Employee, Employee.id == UserAccount.employee_id)
            .outerjoin(WorkspacePresence, WorkspacePresence.account_id == UserAccount.id)
            .where(UserAccount.id.in_(set(account_ids)))
        )
    ).all()
    cutoff = _now() - ONLINE_WINDOW
    return {
        account.id: {
            "account_id": account.id,
            "employee_id": account.employee_id,
            "name": "OYUNS Agent" if account.email.startswith(OYUNS_AGENT_EMAIL_PREFIX) else (employee.name if employee else account.email),
            "email": "AI туслах" if account.email.startswith(OYUNS_AGENT_EMAIL_PREFIX) else account.email,
            "avatar_url": (employee.metadata_json or {}).get("avatar_url") if employee else None,
            "is_online": account.email.startswith(OYUNS_AGENT_EMAIL_PREFIX) or bool(presence and presence.last_seen_at >= cutoff),
            "last_seen_at": presence.last_seen_at if presence else None,
            "is_agent": account.email.startswith(OYUNS_AGENT_EMAIL_PREFIX),
        }
        for account, employee, presence in rows
    }


async def _ensure_oyuns_agent(db: AsyncSession, organization_id: int) -> UserAccount:
    agent = await db.scalar(
        select(UserAccount).where(
            UserAccount.organization_id == organization_id,
            UserAccount.email == f"{OYUNS_AGENT_EMAIL_PREFIX}{organization_id}@oyuns.ai",
        )
    )
    if agent:
        return agent
    agent = UserAccount(
        organization_id=organization_id,
        email=f"{OYUNS_AGENT_EMAIL_PREFIX}{organization_id}@oyuns.ai",
        password_hash=hash_account_password(secrets.token_urlsafe(48)),
        status="active",
        locale="mn",
        preferences={"system_agent": "oyuns"},
    )
    db.add(agent)
    await db.flush()
    return agent


async def _send_oyuns_reply(
    db: AsyncSession,
    actor: ActorContext,
    conversation: ChatConversation,
    agent: UserAccount,
) -> None:
    rows = list(
        (
            await db.execute(
                select(ChatMessage)
                .where(ChatMessage.conversation_id == conversation.id, ChatMessage.deleted_at.is_(None))
                .order_by(ChatMessage.id.desc())
                .limit(12)
            )
        ).scalars().all()
    )
    history = [
        {"role": "assistant" if item.sender_account_id == agent.id else "user", "content": item.body or ""}
        for item in reversed(rows)
        if item.body
    ]
    if not history or history[-1]["role"] != "user":
        return
    text = history[-1]["content"]
    routed_actor = actor
    routed = None
    try:
        from dataclasses import replace
        routed_actor = replace(actor, channel="web", detected_language=assistant_ai.detect_language(text).value)
        routed = await ai_gateway.execute_turn(db, routed_actor, history, conversation_id=conversation.id)
        answer = routed.answer.strip()
    except GatewayError:
        answer = "Уучлаарай, OYUNS Agent одоогоор хариу өгөх боломжгүй байна. Түр хүлээгээд дахин илгээнэ үү."
    if not answer:
        return
    delivery_rows = list(getattr(routed, "deliveries", [])) if routed else []
    if routed:
        for tool_result in routed.tool_results:
            delivery_rows.extend(tool_result.get("deliveries", []))
    response = ChatMessage(
        conversation_id=conversation.id,
        sender_account_id=agent.id,
        client_nonce=uuid.uuid4(),
        body=answer[:4000],
        company_file_attachments=enterprise_tools.attachment_metadata(delivery_rows),
    )
    db.add(response)
    await db.flush()
    participants = await _active_participants(db, conversation.id)
    recipient_ids = [item.account_id for item in participants if item.account_id != agent.id]
    db.add_all(ChatMessageReceipt(message_id=response.id, account_id=recipient_id) for recipient_id in recipient_ids)
    conversation.updated_at = _now()
    await _emit(
        db,
        actor,
        conversation,
        "message_sent",
        aggregate_type="chat_message",
        aggregate_id=response.id,
        recipient_ids=recipient_ids,
        extra={
            "message_id": response.id,
            "sender_account_id": agent.id,
            "sender_name": "OYUNS Agent",
            "preview": answer[:160],
            "target_url": f"/chat/{conversation.public_id}?message={response.id}",
        },
    )


async def _membership(
    db: AsyncSession,
    actor: ActorContext,
    public_id: UUID,
    *,
    owner: bool = False,
) -> tuple[ChatConversation, ChatParticipant]:
    row = (
        await db.execute(
            select(ChatConversation, ChatParticipant)
            .join(ChatParticipant, ChatParticipant.conversation_id == ChatConversation.id)
            .where(
                ChatConversation.public_id == public_id,
                ChatConversation.organization_id == actor.organization_id,
                ChatConversation.archived_at.is_(None),
                ChatParticipant.account_id == actor.account_id,
                ChatParticipant.left_at.is_(None),
            )
        )
    ).one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Conversation not found")
    conversation, participant = row
    if owner and (conversation.kind != "group" or participant.role != "owner"):
        raise HTTPException(status_code=403, detail="Only the group owner can manage this conversation")
    return conversation, participant


async def _active_participants(db: AsyncSession, conversation_id: int) -> list[ChatParticipant]:
    return list(
        (
            await db.execute(
                select(ChatParticipant)
                .where(ChatParticipant.conversation_id == conversation_id, ChatParticipant.left_at.is_(None))
                .order_by(ChatParticipant.joined_at, ChatParticipant.id)
            )
        ).scalars().all()
    )


async def _message_for_actor(
    db: AsyncSession,
    actor: ActorContext,
    public_id: UUID,
    message_id: int,
    *,
    include_hidden: bool = False,
) -> tuple[ChatConversation, ChatParticipant, ChatMessage]:
    conversation, participant = await _membership(db, actor, public_id)
    message = await db.scalar(select(ChatMessage).where(ChatMessage.id == message_id, ChatMessage.conversation_id == conversation.id))
    if not message or (participant.visible_after_message_id is not None and message.id <= participant.visible_after_message_id):
        raise HTTPException(status_code=404, detail="Message not found")
    if not include_hidden and await db.scalar(select(ChatMessageHidden.id).where(ChatMessageHidden.message_id == message.id, ChatMessageHidden.account_id == actor.account_id)):
        raise HTTPException(status_code=404, detail="Message not found")
    return conversation, participant, message


async def _receipt_summary(db: AsyncSession, message_id: int) -> dict[str, int]:
    total, delivered, read = (
        await db.execute(
            select(
                func.count(ChatMessageReceipt.id),
                func.count(ChatMessageReceipt.delivered_at),
                func.count(ChatMessageReceipt.read_at),
            ).where(ChatMessageReceipt.message_id == message_id)
        )
    ).one()
    return {"total": int(total or 0), "delivered": int(delivered or 0), "read": int(read or 0)}


async def _message_out(db: AsyncSession, message: ChatMessage, actor: ActorContext) -> dict:
    identities = await _identity_map(db, [message.sender_account_id] if message.sender_account_id else [])
    receipts = await _receipt_summary(db, message.id)
    status = None
    if message.sender_account_id == actor.account_id:
        if receipts["total"] and receipts["read"] == receipts["total"]:
            status = "read"
        elif receipts["total"] and receipts["delivered"] == receipts["total"]:
            status = "delivered"
        else:
            status = "sent"
    attachments = []
    if message.deleted_at is None:
        conversation_public_id = await db.scalar(select(ChatConversation.public_id).where(ChatConversation.id == message.conversation_id))
        rows = list((await db.execute(select(ChatAttachment).where(ChatAttachment.message_id == message.id).order_by(ChatAttachment.id))).scalars().all())
        attachments = [_attachment_out(item, conversation_public_id) for item in rows]
        company_file_attachments = []
        for delivery in getattr(message, "company_file_attachments", None) or []:
            try:
                item_id = int(delivery.get("item_id"))
            except (AttributeError, TypeError, ValueError):
                continue
            resolved = await authorized_file(db, FileSearchPrincipal.from_actor(actor), item_id)
            if not resolved:
                continue
            item = resolved[0]
            company_file_attachments.append({
                "item_id": item.id,
                "filename": item.name,
                "content_type": item.content_type,
                "size": item.size,
                "download_url": f"/v1/company-files/{item.id}/download",
            })
    else:
        company_file_attachments = []
    reaction_rows = (
        await db.execute(
            select(ChatMessageReaction.emoji, func.count(ChatMessageReaction.id))
            .where(ChatMessageReaction.message_id == message.id)
            .group_by(ChatMessageReaction.emoji)
            .order_by(ChatMessageReaction.emoji)
        )
    ).all()
    mine = set((await db.execute(select(ChatMessageReaction.emoji).where(ChatMessageReaction.message_id == message.id, ChatMessageReaction.account_id == actor.account_id))).scalars().all())
    starred = bool(await db.scalar(select(ChatMessageStar.id).where(ChatMessageStar.message_id == message.id, ChatMessageStar.account_id == actor.account_id)))
    pinned = bool(await db.scalar(select(ChatMessagePin.id).where(ChatMessagePin.message_id == message.id)))
    thread_count = int(await db.scalar(select(func.count(ChatMessage.id)).where(ChatMessage.thread_root_message_id == message.id)) or 0)
    reply_preview = None
    if message.reply_to_message_id:
        reply = await db.get(ChatMessage, message.reply_to_message_id)
        if reply:
            reply_identity = (await _identity_map(db, [reply.sender_account_id] if reply.sender_account_id else [])).get(reply.sender_account_id)
            reply_preview = {
                "id": reply.id,
                "body": None if reply.deleted_at else reply.body,
                "sender_name": reply_identity["name"] if reply_identity else None,
                "is_deleted": reply.deleted_at is not None,
            }
    within_window = message.created_at >= _now() - MESSAGE_ACTION_WINDOW
    can_change = message.sender_account_id == actor.account_id and message.deleted_at is None and within_window
    return {
        "id": message.id,
        "conversation_id": message.conversation_id,
        "sender": identities.get(message.sender_account_id),
        "sender_account_id": message.sender_account_id,
        "client_nonce": str(message.client_nonce),
        "body": None if message.deleted_at else message.body,
        "attachments": attachments,
        "company_file_attachments": company_file_attachments,
        "reply_to_message_id": message.reply_to_message_id,
        "thread_root_message_id": message.thread_root_message_id,
        "reply_preview": reply_preview,
        "thread_reply_count": thread_count,
        "forwarded_from_message_id": message.forwarded_from_message_id,
        "forwarded_sender_name": message.forwarded_sender_name,
        "reactions": [{"emoji": emoji, "count": int(count), "reacted": emoji in mine} for emoji, count in reaction_rows],
        "is_starred": starred,
        "is_pinned": pinned,
        "is_deleted": message.deleted_at is not None,
        "edited_at": message.edited_at,
        "deleted_at": message.deleted_at,
        "created_at": message.created_at,
        "is_mine": message.sender_account_id == actor.account_id,
        "status": status,
        "receipts": receipts,
        "capabilities": {
            "can_edit": can_change and bool(message.body),
            "can_delete_everyone": can_change,
            "can_delete_self": message.deleted_at is None,
            "can_forward": message.deleted_at is None,
            "can_react": message.deleted_at is None,
            "can_pin": message.deleted_at is None,
        },
    }


async def _conversation_summary(db: AsyncSession, conversation: ChatConversation, actor: ActorContext) -> dict:
    participants = await _active_participants(db, conversation.id)
    identity_by_id = await _identity_map(db, [participant.account_id for participant in participants])
    member_rows = [
        {**identity_by_id[participant.account_id], "role": participant.role}
        for participant in participants
        if participant.account_id in identity_by_id
    ]
    own_membership = next((participant for participant in participants if participant.account_id == actor.account_id), None)
    message_filters = [ChatMessage.conversation_id == conversation.id]
    if own_membership and own_membership.visible_after_message_id is not None:
        message_filters.append(ChatMessage.id > own_membership.visible_after_message_id)
    hidden_message = exists(select(ChatMessageHidden.id).where(ChatMessageHidden.message_id == ChatMessage.id, ChatMessageHidden.account_id == actor.account_id))
    last_message = await db.scalar(select(ChatMessage).where(*message_filters, ~hidden_message).order_by(ChatMessage.id.desc()).limit(1))
    unread = await db.scalar(
        select(func.count(ChatMessageReceipt.id))
        .join(ChatMessage, ChatMessage.id == ChatMessageReceipt.message_id)
        .where(
            ChatMessage.conversation_id == conversation.id,
            ChatMessageReceipt.account_id == actor.account_id,
            ChatMessageReceipt.read_at.is_(None),
            ChatMessage.deleted_at.is_(None),
            ~hidden_message,
        )
    ) or 0
    if conversation.kind == "direct":
        counterpart = next((item for item in member_rows if item["account_id"] != actor.account_id), None)
        title = counterpart["name"] if counterpart else "Direct chat"
        avatar_urls = [counterpart["avatar_url"]] if counterpart and counterpart["avatar_url"] else []
        presence = "online" if counterpart and counterpart["is_online"] else "offline"
    else:
        title = conversation.title or "Group"
        avatar_urls = [item["avatar_url"] for item in member_rows if item["avatar_url"]][:3]
        presence = None
    sender_identity = None
    if last_message and last_message.sender_account_id:
        sender_identity = (await _identity_map(db, [last_message.sender_account_id])).get(last_message.sender_account_id)
    last_attachment_count = int(await db.scalar(select(func.count(ChatAttachment.id)).where(ChatAttachment.message_id == last_message.id)) or 0) if last_message else 0
    pinned_message_count = int(await db.scalar(select(func.count(ChatMessagePin.id)).where(ChatMessagePin.conversation_id == conversation.id)) or 0)
    return {
        "id": conversation.id,
        "public_id": str(conversation.public_id),
        "kind": conversation.kind,
        "title": title,
        "avatar_urls": avatar_urls,
        "presence": presence,
        "members": member_rows,
        "member_count": len(member_rows),
        "can_manage": bool(own_membership and own_membership.role == "owner" and conversation.kind == "group"),
        "last_message": ({
            "id": last_message.id,
            "body": "Message deleted" if last_message.deleted_at else (last_message.body or ("Attachment" if last_attachment_count else "")),
            "attachment_count": last_attachment_count,
            "sender_account_id": last_message.sender_account_id,
            "sender_name": sender_identity["name"] if sender_identity else None,
            "created_at": last_message.created_at,
        } if last_message else None),
        "unread_count": int(unread),
        "is_pinned": bool(own_membership and own_membership.pinned_at),
        "pinned_at": own_membership.pinned_at if own_membership else None,
        "is_archived": bool(own_membership and own_membership.archived_at),
        "archived_at": own_membership.archived_at if own_membership else None,
        "is_muted": bool(own_membership and _is_muted(own_membership)),
        "muted_until": own_membership.muted_until if own_membership else None,
        "pinned_message_count": pinned_message_count,
        "created_at": conversation.created_at,
        "updated_at": conversation.updated_at,
    }


async def _emit(
    db: AsyncSession,
    actor: ActorContext,
    conversation: ChatConversation,
    operation: str,
    *,
    aggregate_type: str = "chat_conversation",
    aggregate_id: int | None = None,
    recipient_ids: list[int] | None = None,
    extra: dict | None = None,
) -> None:
    recipients = recipient_ids
    if recipients is None:
        recipients = [participant.account_id for participant in await _active_participants(db, conversation.id)]
    await record_change(
        db,
        actor=actor,
        topic="chat",
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id or conversation.id,
        operation=operation,
        after={
            "conversation_public_id": str(conversation.public_id),
            "recipient_account_ids": sorted(set(recipients)),
            **(extra or {}),
        },
    )


@router.get("/contacts")
async def contacts(
    q: str = "",
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    agent = await _ensure_oyuns_agent(db, actor.organization_id)
    await db.commit()
    statement = (
        select(UserAccount.id)
        .outerjoin(Employee, Employee.id == UserAccount.employee_id)
        .where(
            UserAccount.organization_id == actor.organization_id,
            UserAccount.status == "active",
            UserAccount.id != actor.account_id,
            UserAccount.id != agent.id,
        )
        .order_by(func.coalesce(Employee.name, UserAccount.email))
        .limit(limit)
    )
    if q.strip():
        term = f"%{q.strip()}%"
        statement = statement.where(func.coalesce(Employee.name, UserAccount.email).ilike(term))
    ids = list((await db.execute(statement)).scalars().all())
    agent_identity = (await _identity_map(db, [agent.id])).get(agent.id)
    identities = await _identity_map(db, ids)
    results = [identities[account_id] for account_id in ids if account_id in identities]
    if not q.strip() or "oyuns" in q.lower() or "agent" in q.lower():
        return [agent_identity, *results] if agent_identity else results
    return results


@router.get("/conversations")
async def conversations(
    q: str = "",
    kind_filter: Literal["all", "unread", "groups", "direct", "archived"] = Query("all", alias="filter"),
    cursor: int = Query(0, ge=0),
    limit: int = Query(30, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    rows = list(
        (
            await db.execute(
                select(ChatConversation)
                .join(ChatParticipant, ChatParticipant.conversation_id == ChatConversation.id)
                .where(
                    ChatConversation.organization_id == actor.organization_id,
                    ChatConversation.archived_at.is_(None),
                    ChatParticipant.account_id == actor.account_id,
                    ChatParticipant.left_at.is_(None),
                )
                .order_by(ChatConversation.updated_at.desc(), ChatConversation.id.desc())
            )
        ).scalars().all()
    )
    summaries = [await _conversation_summary(db, conversation, actor) for conversation in rows]
    if kind_filter == "archived":
        summaries = [item for item in summaries if item["is_archived"]]
    else:
        summaries = [item for item in summaries if not item["is_archived"]]
        if kind_filter == "unread":
            summaries = [item for item in summaries if item["unread_count"] > 0]
        elif kind_filter == "groups":
            summaries = [item for item in summaries if item["kind"] == "group"]
        elif kind_filter == "direct":
            summaries = [item for item in summaries if item["kind"] == "direct"]
    if q.strip():
        term = q.strip().casefold()
        summaries = [
            item for item in summaries
            if term in item["title"].casefold()
            or any(term in member["name"].casefold() for member in item["members"])
        ]
    summaries.sort(key=lambda item: (bool(item["is_pinned"]), item["updated_at"], item["id"]), reverse=True)
    page = summaries[cursor:cursor + limit]
    next_cursor = cursor + limit if cursor + limit < len(summaries) else None
    return {"items": page, "next_cursor": next_cursor}


@router.get("/unread-count")
async def unread_count(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    hidden_message = exists(select(ChatMessageHidden.id).where(ChatMessageHidden.message_id == ChatMessage.id, ChatMessageHidden.account_id == actor.account_id))
    total = await db.scalar(
        select(func.count(ChatMessageReceipt.id))
        .join(ChatMessage, ChatMessage.id == ChatMessageReceipt.message_id)
        .join(ChatParticipant, ChatParticipant.conversation_id == ChatMessage.conversation_id)
        .where(
            ChatMessageReceipt.account_id == actor.account_id,
            ChatMessageReceipt.read_at.is_(None),
            ChatParticipant.account_id == actor.account_id,
            ChatParticipant.left_at.is_(None),
            ChatMessage.deleted_at.is_(None),
            ~hidden_message,
        )
    ) or 0
    return {"unread_count": int(total)}


@router.post("/conversations/direct")
async def open_direct(
    data: DirectConversationIn,
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    if data.agent:
        if data.account_id or data.employee_id:
            raise HTTPException(status_code=422, detail="Agent conversations cannot include a worker identifier")
        target = await _ensure_oyuns_agent(db, actor.organization_id)
    elif bool(data.account_id) == bool(data.employee_id):
        raise HTTPException(status_code=422, detail="Provide exactly one account_id or employee_id")
    else:
        target = None
        if data.account_id:
            target = await db.get(UserAccount, data.account_id)
        elif data.employee_id:
            target = await db.scalar(select(UserAccount).where(UserAccount.employee_id == data.employee_id))
    if not target or target.organization_id != actor.organization_id or target.status != "active":
        raise HTTPException(status_code=409, detail="This worker cannot receive workspace chat messages")
    if target.id == actor.account_id:
        raise HTTPException(status_code=409, detail="You cannot start a direct conversation with yourself")
    direct_key = ":".join(str(item) for item in sorted((actor.account_id, target.id)))
    conversation = await db.scalar(
        select(ChatConversation).where(
            ChatConversation.organization_id == actor.organization_id,
            ChatConversation.direct_key == direct_key,
        )
    )
    if conversation:
        return await _conversation_summary(db, conversation, actor)
    conversation = ChatConversation(
        organization_id=actor.organization_id,
        kind="direct",
        direct_key=direct_key,
        created_by_account_id=actor.account_id,
    )
    db.add(conversation)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        conversation = await db.scalar(select(ChatConversation).where(ChatConversation.organization_id == actor.organization_id, ChatConversation.direct_key == direct_key))
        if not conversation:
            raise
        return await _conversation_summary(db, conversation, actor)
    db.add_all([
        ChatParticipant(conversation_id=conversation.id, account_id=actor.account_id, role="member"),
        ChatParticipant(conversation_id=conversation.id, account_id=target.id, role="member"),
    ])
    await db.flush()
    await _emit(db, actor, conversation, "conversation_created", recipient_ids=[actor.account_id, target.id])
    await db.commit()
    await db.refresh(conversation)
    return await _conversation_summary(db, conversation, actor)


@router.post("/conversations/groups")
async def create_group(
    data: GroupConversationIn,
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    member_ids = sorted(set(data.member_account_ids) - {actor.account_id})
    if len(member_ids) < 2:
        raise HTTPException(status_code=422, detail="A group requires at least two other members")
    if len(member_ids) + 1 > MAX_GROUP_MEMBERS:
        raise HTTPException(status_code=422, detail="A group can contain at most 100 members")
    valid_ids = set(
        (
            await db.execute(
                select(UserAccount.id).where(
                    UserAccount.id.in_(member_ids),
                    UserAccount.organization_id == actor.organization_id,
                    UserAccount.status == "active",
                )
            )
        ).scalars().all()
    )
    if valid_ids != set(member_ids):
        raise HTTPException(status_code=422, detail="Every group member must be an active workspace account")
    conversation = ChatConversation(
        organization_id=actor.organization_id,
        kind="group",
        title=_clean_group_title(data.title),
        created_by_account_id=actor.account_id,
    )
    db.add(conversation)
    await db.flush()
    db.add(ChatParticipant(conversation_id=conversation.id, account_id=actor.account_id, role="owner"))
    db.add_all(ChatParticipant(conversation_id=conversation.id, account_id=account_id, role="member") for account_id in member_ids)
    await db.flush()
    await _emit(db, actor, conversation, "conversation_created", recipient_ids=[actor.account_id, *member_ids])
    await db.commit()
    await db.refresh(conversation)
    return await _conversation_summary(db, conversation, actor)


@router.get("/conversations/{public_id}")
async def conversation_detail(
    public_id: UUID,
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    conversation, _ = await _membership(db, actor, public_id)
    return await _conversation_summary(db, conversation, actor)


@router.patch("/conversations/{public_id}/preferences")
async def update_conversation_preferences(
    public_id: UUID,
    data: ConversationPreferencesIn,
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    conversation, participant = await _membership(db, actor, public_id)
    now = _now()
    if data.pinned is not None:
        participant.pinned_at = now if data.pinned else None
    if data.archived is not None:
        participant.archived_at = now if data.archived else None
    if data.mute_for is not None:
        participant.muted_until = None if data.mute_for == "off" else now + MUTE_DURATIONS[data.mute_for]
    await _emit(db, actor, conversation, "conversation_preferences_updated", recipient_ids=[actor.account_id])
    await db.commit()
    return await _conversation_summary(db, conversation, actor)


@router.patch("/conversations/{public_id}")
async def rename_group(
    public_id: UUID,
    data: GroupTitleIn,
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    conversation, _ = await _membership(db, actor, public_id, owner=True)
    conversation.title = _clean_group_title(data.title)
    conversation.updated_at = _now()
    await _emit(db, actor, conversation, "conversation_updated")
    await db.commit()
    return await _conversation_summary(db, conversation, actor)


@router.post("/conversations/{public_id}/members")
async def add_group_members(
    public_id: UUID,
    data: GroupMembersIn,
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    conversation, _ = await _membership(db, actor, public_id, owner=True)
    before = await _active_participants(db, conversation.id)
    active_ids = {item.account_id for item in before}
    requested = sorted(set(data.account_ids) - active_ids)
    if not requested:
        return await _conversation_summary(db, conversation, actor)
    if len(active_ids) + len(requested) > MAX_GROUP_MEMBERS:
        raise HTTPException(status_code=422, detail="A group can contain at most 100 members")
    valid = set((await db.execute(select(UserAccount.id).where(UserAccount.id.in_(requested), UserAccount.organization_id == actor.organization_id, UserAccount.status == "active"))).scalars().all())
    if valid != set(requested):
        raise HTTPException(status_code=422, detail="Every group member must be an active workspace account")
    last_message_id = await db.scalar(select(func.max(ChatMessage.id)).where(ChatMessage.conversation_id == conversation.id))
    existing = {
        item.account_id: item
        for item in (
            await db.execute(select(ChatParticipant).where(ChatParticipant.conversation_id == conversation.id, ChatParticipant.account_id.in_(requested)))
        ).scalars().all()
    }
    joined_at = _now()
    for account_id in requested:
        participant = existing.get(account_id)
        if participant:
            participant.role = "member"
            participant.left_at = None
            participant.joined_at = joined_at
            participant.visible_after_message_id = last_message_id
        else:
            db.add(ChatParticipant(conversation_id=conversation.id, account_id=account_id, role="member", joined_at=joined_at, visible_after_message_id=last_message_id))
    conversation.updated_at = joined_at
    await db.flush()
    await _emit(db, actor, conversation, "members_added", recipient_ids=[*active_ids, *requested], extra={"account_ids": requested})
    await db.commit()
    return await _conversation_summary(db, conversation, actor)


@router.delete("/conversations/{public_id}/members/{account_id}")
async def remove_group_member(
    public_id: UUID,
    account_id: int,
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    conversation, _ = await _membership(db, actor, public_id, owner=True)
    if account_id == actor.account_id:
        raise HTTPException(status_code=422, detail="Use the leave action to leave your group")
    before = await _active_participants(db, conversation.id)
    participant = next((item for item in before if item.account_id == account_id), None)
    if not participant:
        raise HTTPException(status_code=404, detail="Group member not found")
    participant.left_at = _now()
    conversation.updated_at = participant.left_at
    await _emit(db, actor, conversation, "member_removed", recipient_ids=[item.account_id for item in before], extra={"account_id": account_id})
    await db.commit()
    return {"removed": True}


@router.post("/conversations/{public_id}/leave")
async def leave_group(
    public_id: UUID,
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    conversation, participant = await _membership(db, actor, public_id)
    if conversation.kind != "group":
        raise HTTPException(status_code=422, detail="Direct conversations cannot be left")
    before = await _active_participants(db, conversation.id)
    participant.left_at = _now()
    remaining = [item for item in before if item.account_id != actor.account_id]
    if participant.role == "owner" and remaining:
        remaining[0].role = "owner"
    if not remaining:
        conversation.archived_at = participant.left_at
    conversation.updated_at = participant.left_at
    await _emit(db, actor, conversation, "member_left", recipient_ids=[item.account_id for item in before], extra={"account_id": actor.account_id})
    await db.commit()
    return {"left": True, "archived": not remaining}


@router.post("/conversations/{public_id}/uploads", status_code=status.HTTP_201_CREATED)
async def stage_chat_upload(
    public_id: UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    conversation, _ = await _membership(db, actor, public_id)
    content = await file.read(settings.ATTACHMENT_MAX_BYTES + 1)
    if len(content) > settings.ATTACHMENT_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Chat attachment exceeds the 25 MB limit")
    if not content:
        raise HTTPException(status_code=400, detail="Chat attachment is empty")
    filename = Path((file.filename or "attachment").replace("\\", "/")).name.strip()[:240] or "attachment"
    guessed_type = mimetypes.guess_type(filename)[0]
    content_type = (file.content_type or guessed_type or "application/octet-stream").split(";", 1)[0].lower()
    if content_type == "application/octet-stream" and guessed_type:
        content_type = guessed_type
    media_kind = ALLOWED_MEDIA_TYPES.get(content_type)
    if not media_kind:
        raise HTTPException(status_code=415, detail="Unsupported chat attachment type")
    if guessed_type in ALLOWED_MEDIA_TYPES and guessed_type != content_type:
        raise HTTPException(status_code=415, detail="Attachment extension does not match its media type")
    if not _file_signature_matches(content_type, content):
        raise HTTPException(status_code=415, detail="Attachment content does not match its declared media type")
    try:
        scan_status = await scan_upload(content)
    except MalwareDetected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if scan_status != "accepted":
        raise HTTPException(status_code=503, detail="Attachment malware scanning is temporarily unavailable")
    storage_key = f"{actor.organization_id}/chat/{conversation.id}/staged/{uuid.uuid4().hex}"
    await put_attachment(storage_key, content, content_type)
    attachment = ChatAttachment(
        organization_id=actor.organization_id,
        conversation_id=conversation.id,
        staged_by_account_id=actor.account_id,
        storage_key=storage_key,
        filename=filename,
        content_type=content_type,
        media_kind=media_kind,
        size=len(content),
        checksum=hashlib.sha256(content).hexdigest(),
        scan_status=scan_status,
        expires_at=_now() + STAGED_UPLOAD_TTL,
    )
    db.add(attachment)
    try:
        await db.commit()
        await db.refresh(attachment)
    except Exception:
        await delete_attachment(storage_key)
        raise
    return _attachment_out(attachment, public_id)


@router.delete("/conversations/{public_id}/uploads/{upload_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_chat_upload(
    public_id: UUID,
    upload_id: UUID,
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    conversation, _ = await _membership(db, actor, public_id)
    item = await db.scalar(select(ChatAttachment).where(
        ChatAttachment.public_id == upload_id,
        ChatAttachment.conversation_id == conversation.id,
        ChatAttachment.staged_by_account_id == actor.account_id,
        ChatAttachment.message_id.is_(None),
    ))
    if not item:
        raise HTTPException(status_code=404, detail="Staged upload not found")
    storage_key = item.storage_key
    await db.delete(item)
    await db.commit()
    await delete_attachment(storage_key)


@router.get("/conversations/{public_id}/attachments/{attachment_id}")
async def download_chat_attachment(
    public_id: UUID,
    attachment_id: UUID,
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    conversation, _ = await _membership(db, actor, public_id)
    item = await db.scalar(select(ChatAttachment).where(ChatAttachment.public_id == attachment_id, ChatAttachment.conversation_id == conversation.id))
    if not item:
        raise HTTPException(status_code=404, detail="Chat attachment not found")
    if item.message_id is None:
        if item.staged_by_account_id != actor.account_id or not item.expires_at or item.expires_at <= _now():
            raise HTTPException(status_code=404, detail="Chat attachment not found")
    else:
        message = await db.get(ChatMessage, item.message_id)
        hidden = await db.scalar(select(ChatMessageHidden.id).where(ChatMessageHidden.message_id == item.message_id, ChatMessageHidden.account_id == actor.account_id))
        if not message or message.deleted_at or hidden:
            raise HTTPException(status_code=404, detail="Chat attachment not found")
    content = await get_attachment(item.storage_key)
    disposition = "inline" if item.media_kind in {"image", "video", "audio"} or item.content_type == "application/pdf" else "attachment"
    encoded_name = item.filename.replace('"', "")
    return Response(content, media_type=item.content_type, headers={
        "Content-Disposition": f'{disposition}; filename="{encoded_name}"',
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, max-age=300",
    })


@router.get("/conversations/{public_id}/messages")
async def messages(
    public_id: UUID,
    before_id: int | None = None,
    around_id: int | None = None,
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    conversation, participant = await _membership(db, actor, public_id)
    filters = [ChatMessage.conversation_id == conversation.id]
    if participant.visible_after_message_id is not None:
        filters.append(ChatMessage.id > participant.visible_after_message_id)
    hidden_message = exists(select(ChatMessageHidden.id).where(ChatMessageHidden.message_id == ChatMessage.id, ChatMessageHidden.account_id == actor.account_id))
    filters.append(~hidden_message)
    if before_id and around_id:
        raise HTTPException(status_code=422, detail="Use either before_id or around_id")
    if around_id:
        target = await db.scalar(select(ChatMessage).where(*filters, ChatMessage.id == around_id))
        if not target:
            raise HTTPException(status_code=404, detail="Message not found")
        older = list((await db.execute(select(ChatMessage).where(*filters, ChatMessage.id < around_id).order_by(ChatMessage.id.desc()).limit(limit // 2))).scalars().all())
        newer = list((await db.execute(select(ChatMessage).where(*filters, ChatMessage.id >= around_id).order_by(ChatMessage.id).limit(limit - len(older)))).scalars().all())
        page = [*reversed(older), *newer]
        return {"items": [await _message_out(db, message, actor) for message in page], "next_before_id": page[0].id if older and len(older) == limit // 2 else None, "anchor_message_id": around_id}
    if before_id:
        filters.append(ChatMessage.id < before_id)
    rows = list((await db.execute(select(ChatMessage).where(*filters).order_by(ChatMessage.id.desc()).limit(limit + 1))).scalars().all())
    has_more = len(rows) > limit
    page = rows[:limit]
    return {
        "items": [await _message_out(db, message, actor) for message in reversed(page)],
        "next_before_id": page[-1].id if has_more and page else None,
    }


@router.post("/conversations/{public_id}/messages")
async def send_message(
    public_id: UUID,
    data: MessageIn,
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    conversation, _ = await _membership(db, actor, public_id)
    body = data.body.strip() if data.body else None
    if body == "":
        body = None
    upload_ids = list(dict.fromkeys(data.upload_ids))
    uploads = list((await db.execute(select(ChatAttachment).where(
        ChatAttachment.public_id.in_(upload_ids),
        ChatAttachment.conversation_id == conversation.id,
        ChatAttachment.staged_by_account_id == actor.account_id,
        ChatAttachment.message_id.is_(None),
        ChatAttachment.expires_at > _now(),
    ))).scalars().all()) if upload_ids else []
    if len(uploads) != len(upload_ids):
        raise HTTPException(status_code=422, detail="One or more staged uploads are invalid or expired")
    if sum(item.size for item in uploads) > MAX_MESSAGE_ATTACHMENT_BYTES:
        raise HTTPException(status_code=413, detail="Message attachments exceed the 100 MB combined limit")
    if not body and not uploads:
        raise HTTPException(status_code=422, detail="Message must contain text or an attachment")
    existing = await db.scalar(select(ChatMessage).where(ChatMessage.conversation_id == conversation.id, ChatMessage.sender_account_id == actor.account_id, ChatMessage.client_nonce == data.client_nonce))
    if existing:
        return await _message_out(db, existing, actor)
    reply_to = None
    thread_root_id = None
    if data.reply_to_message_id:
        reply_to = await db.scalar(select(ChatMessage).where(ChatMessage.id == data.reply_to_message_id, ChatMessage.conversation_id == conversation.id, ChatMessage.deleted_at.is_(None)))
        if not reply_to:
            raise HTTPException(status_code=404, detail="Reply target not found")
        thread_root_id = reply_to.thread_root_message_id or reply_to.id
    message = ChatMessage(
        conversation_id=conversation.id,
        sender_account_id=actor.account_id,
        client_nonce=data.client_nonce,
        body=body,
        reply_to_message_id=reply_to.id if reply_to else None,
        thread_root_message_id=thread_root_id,
    )
    db.add(message)
    await db.flush()
    for item in uploads:
        item.message_id = message.id
        item.expires_at = None
    participants = await _active_participants(db, conversation.id)
    participant_ids = [item.account_id for item in participants]
    db.add_all(ChatMessageReceipt(message_id=message.id, account_id=account_id) for account_id in participant_ids if account_id != actor.account_id)
    now = _now()
    conversation.updated_at = now
    for participant in participants:
        participant.archived_at = None
        if participant.account_id != actor.account_id and not _is_muted(participant, now):
            db.add(JobQueue(
                job_type="chat_push",
                payload={"message_id": message.id, "recipient_account_id": participant.account_id},
                dedup_key=f"chat-push:{message.id}:{participant.account_id}",
            ))
    await db.flush()
    sender = (await _identity_map(db, [actor.account_id])).get(actor.account_id)
    preview = body or (f"{len(uploads)} attachment" if len(uploads) > 1 else "Attachment")
    await _emit(db, actor, conversation, "message_sent", aggregate_type="chat_message", aggregate_id=message.id, recipient_ids=participant_ids, extra={
        "message_id": message.id,
        "sender_account_id": actor.account_id,
        "sender_name": sender["name"] if sender else actor.email,
        "conversation_title": conversation.title if conversation.kind == "group" else None,
        "preview": preview[:160],
        "target_url": f"/chat/{public_id}?message={message.id}",
    })
    await db.commit()
    await db.refresh(message)
    agent = await db.scalar(
        select(UserAccount).join(ChatParticipant, ChatParticipant.account_id == UserAccount.id).where(
            ChatParticipant.conversation_id == conversation.id,
            UserAccount.email.like(f"{OYUNS_AGENT_EMAIL_PREFIX}%"),
            ChatParticipant.left_at.is_(None),
        )
    )
    if agent and body:
        await _send_oyuns_reply(db, actor, conversation, agent)
        await db.commit()
    return await _message_out(db, message, actor)


@router.patch("/conversations/{public_id}/messages/{message_id}")
async def edit_message(
    public_id: UUID,
    message_id: int,
    data: MessageEditIn,
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    conversation, _, message = await _message_for_actor(db, actor, public_id, message_id)
    if message.deleted_at or message.sender_account_id != actor.account_id:
        raise HTTPException(status_code=403, detail="Only the message author can edit this message")
    if message.created_at < _now() - MESSAGE_ACTION_WINDOW:
        raise HTTPException(status_code=409, detail="The 15-minute edit window has expired")
    body = data.body.strip()
    if not body:
        raise HTTPException(status_code=422, detail="Edited message cannot be empty")
    before = {"body": message.body}
    message.body = body
    message.edited_at = _now()
    await _emit(db, actor, conversation, "message_edited", aggregate_type="chat_message", aggregate_id=message.id, extra={"message_id": message.id})
    await record_change(db, actor=actor, topic="chat_audit", aggregate_type="chat_message", aggregate_id=message.id, operation="message_content_edited", before=before, after={"body": body})
    await db.commit()
    return await _message_out(db, message, actor)


@router.delete("/conversations/{public_id}/messages/{message_id}")
async def delete_message(
    public_id: UUID,
    message_id: int,
    scope: Literal["self", "everyone"] = Query("self"),
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    conversation, _, message = await _message_for_actor(db, actor, public_id, message_id, include_hidden=True)
    if scope == "self":
        existing = await db.scalar(select(ChatMessageHidden).where(ChatMessageHidden.message_id == message.id, ChatMessageHidden.account_id == actor.account_id))
        if not existing:
            db.add(ChatMessageHidden(message_id=message.id, account_id=actor.account_id))
            await _emit(db, actor, conversation, "message_hidden", aggregate_type="chat_message", aggregate_id=message.id, recipient_ids=[actor.account_id], extra={"message_id": message.id})
            await db.commit()
        return {"deleted": True, "scope": "self"}
    if message.deleted_at:
        return {"deleted": True, "scope": "everyone"}
    if message.sender_account_id != actor.account_id:
        raise HTTPException(status_code=403, detail="Only the message author can delete it for everyone")
    if message.created_at < _now() - MESSAGE_ACTION_WINDOW:
        raise HTTPException(status_code=409, detail="The 15-minute delete window has expired")
    storage_keys = list((await db.execute(select(ChatAttachment.storage_key).where(ChatAttachment.message_id == message.id))).scalars().all())
    before = {"body": message.body, "attachment_count": len(storage_keys)}
    message.body = None
    message.deleted_at = _now()
    message.deleted_by_account_id = actor.account_id
    pin = await db.scalar(select(ChatMessagePin).where(ChatMessagePin.message_id == message.id))
    if pin:
        await db.delete(pin)
    await _emit(db, actor, conversation, "message_deleted", aggregate_type="chat_message", aggregate_id=message.id, extra={"message_id": message.id})
    await record_change(db, actor=actor, topic="chat_audit", aggregate_type="chat_message", aggregate_id=message.id, operation="message_content_deleted", before=before, after={"deleted_at": message.deleted_at})
    await db.commit()
    for storage_key in storage_keys:
        await delete_attachment(storage_key)
    return {"deleted": True, "scope": "everyone"}


@router.put("/conversations/{public_id}/messages/{message_id}/reaction")
async def add_reaction(
    public_id: UUID,
    message_id: int,
    data: ReactionIn,
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    conversation, _, message = await _message_for_actor(db, actor, public_id, message_id)
    if message.deleted_at:
        raise HTTPException(status_code=409, detail="Deleted messages cannot be reacted to")
    if data.emoji not in REACTIONS:
        raise HTTPException(status_code=422, detail="Unsupported reaction")
    existing = await db.scalar(select(ChatMessageReaction).where(ChatMessageReaction.message_id == message.id, ChatMessageReaction.account_id == actor.account_id, ChatMessageReaction.emoji == data.emoji))
    if not existing:
        db.add(ChatMessageReaction(message_id=message.id, account_id=actor.account_id, emoji=data.emoji))
        await _emit(db, actor, conversation, "reaction_added", aggregate_type="chat_message", aggregate_id=message.id, extra={"message_id": message.id, "emoji": data.emoji})
        await db.commit()
    return await _message_out(db, message, actor)


@router.delete("/conversations/{public_id}/messages/{message_id}/reaction")
async def remove_reaction(
    public_id: UUID,
    message_id: int,
    data: ReactionIn,
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    conversation, _, message = await _message_for_actor(db, actor, public_id, message_id)
    existing = await db.scalar(select(ChatMessageReaction).where(ChatMessageReaction.message_id == message.id, ChatMessageReaction.account_id == actor.account_id, ChatMessageReaction.emoji == data.emoji))
    if existing:
        await db.delete(existing)
        await _emit(db, actor, conversation, "reaction_removed", aggregate_type="chat_message", aggregate_id=message.id, extra={"message_id": message.id, "emoji": data.emoji})
        await db.commit()
    return await _message_out(db, message, actor)


@router.put("/conversations/{public_id}/messages/{message_id}/star")
async def star_message(public_id: UUID, message_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    conversation, _, message = await _message_for_actor(db, actor, public_id, message_id)
    existing = await db.scalar(select(ChatMessageStar).where(ChatMessageStar.message_id == message.id, ChatMessageStar.account_id == actor.account_id))
    if not existing:
        db.add(ChatMessageStar(message_id=message.id, account_id=actor.account_id))
        await _emit(db, actor, conversation, "message_starred", aggregate_type="chat_message", aggregate_id=message.id, recipient_ids=[actor.account_id], extra={"message_id": message.id})
        await db.commit()
    return await _message_out(db, message, actor)


@router.delete("/conversations/{public_id}/messages/{message_id}/star")
async def unstar_message(public_id: UUID, message_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    conversation, _, message = await _message_for_actor(db, actor, public_id, message_id)
    existing = await db.scalar(select(ChatMessageStar).where(ChatMessageStar.message_id == message.id, ChatMessageStar.account_id == actor.account_id))
    if existing:
        await db.delete(existing)
        await _emit(db, actor, conversation, "message_unstarred", aggregate_type="chat_message", aggregate_id=message.id, recipient_ids=[actor.account_id], extra={"message_id": message.id})
        await db.commit()
    return await _message_out(db, message, actor)


@router.put("/conversations/{public_id}/messages/{message_id}/pin")
async def pin_message(public_id: UUID, message_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    conversation, _, message = await _message_for_actor(db, actor, public_id, message_id)
    if message.deleted_at:
        raise HTTPException(status_code=409, detail="Deleted messages cannot be pinned")
    existing = await db.scalar(select(ChatMessagePin).where(ChatMessagePin.message_id == message.id))
    if not existing:
        db.add(ChatMessagePin(conversation_id=conversation.id, message_id=message.id, pinned_by_account_id=actor.account_id))
        await _emit(db, actor, conversation, "message_pinned", aggregate_type="chat_message", aggregate_id=message.id, extra={"message_id": message.id})
        await db.commit()
    return await _message_out(db, message, actor)


@router.delete("/conversations/{public_id}/messages/{message_id}/pin")
async def unpin_message(public_id: UUID, message_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    conversation, _, message = await _message_for_actor(db, actor, public_id, message_id)
    existing = await db.scalar(select(ChatMessagePin).where(ChatMessagePin.message_id == message.id))
    if existing:
        await db.delete(existing)
        await _emit(db, actor, conversation, "message_unpinned", aggregate_type="chat_message", aggregate_id=message.id, extra={"message_id": message.id})
        await db.commit()
    return await _message_out(db, message, actor)


@router.get("/conversations/{public_id}/messages/{message_id}/thread")
async def message_thread(public_id: UUID, message_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    _, participant, message = await _message_for_actor(db, actor, public_id, message_id)
    root_id = message.thread_root_message_id or message.id
    root = await db.get(ChatMessage, root_id)
    if not root:
        raise HTTPException(status_code=404, detail="Thread not found")
    filters = [ChatMessage.thread_root_message_id == root_id]
    if participant.visible_after_message_id is not None:
        filters.append(ChatMessage.id > participant.visible_after_message_id)
    hidden_message = exists(select(ChatMessageHidden.id).where(ChatMessageHidden.message_id == ChatMessage.id, ChatMessageHidden.account_id == actor.account_id))
    replies = list((await db.execute(select(ChatMessage).where(*filters, ~hidden_message).order_by(ChatMessage.id))).scalars().all())
    return {"root": await _message_out(db, root, actor), "items": [await _message_out(db, item, actor) for item in replies]}


@router.post("/conversations/{public_id}/messages/{message_id}/forward")
async def forward_message(
    public_id: UUID,
    message_id: int,
    data: ForwardIn,
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    _, _, source = await _message_for_actor(db, actor, public_id, message_id)
    if source.deleted_at:
        raise HTTPException(status_code=409, detail="Deleted messages cannot be forwarded")
    source_sender = (await _identity_map(db, [source.sender_account_id] if source.sender_account_id else [])).get(source.sender_account_id)
    source_files = list((await db.execute(select(ChatAttachment).where(ChatAttachment.message_id == source.id).order_by(ChatAttachment.id))).scalars().all())
    created: list[tuple[ChatConversation, ChatMessage]] = []
    copied_keys: list[str] = []
    try:
        for destination in data.destinations:
            conversation, _ = await _membership(db, actor, destination.conversation_public_id)
            existing = await db.scalar(select(ChatMessage).where(ChatMessage.conversation_id == conversation.id, ChatMessage.sender_account_id == actor.account_id, ChatMessage.client_nonce == destination.client_nonce))
            if existing:
                created.append((conversation, existing))
                continue
            message = ChatMessage(
                conversation_id=conversation.id,
                sender_account_id=actor.account_id,
                client_nonce=destination.client_nonce,
                body=source.body,
                forwarded_from_message_id=source.id,
                forwarded_sender_name=source_sender["name"] if source_sender else None,
            )
            db.add(message)
            await db.flush()
            for source_file in source_files:
                content = await get_attachment(source_file.storage_key)
                storage_key = f"{actor.organization_id}/chat/{conversation.id}/{message.id}/{uuid.uuid4().hex}"
                await put_attachment(storage_key, content, source_file.content_type)
                copied_keys.append(storage_key)
                db.add(ChatAttachment(
                    organization_id=actor.organization_id,
                    conversation_id=conversation.id,
                    message_id=message.id,
                    staged_by_account_id=actor.account_id,
                    storage_key=storage_key,
                    filename=source_file.filename,
                    content_type=source_file.content_type,
                    media_kind=source_file.media_kind,
                    size=source_file.size,
                    checksum=source_file.checksum,
                    duration_seconds=source_file.duration_seconds,
                    scan_status=source_file.scan_status,
                ))
            participants = await _active_participants(db, conversation.id)
            db.add_all(ChatMessageReceipt(message_id=message.id, account_id=item.account_id) for item in participants if item.account_id != actor.account_id)
            now = _now()
            conversation.updated_at = now
            for item in participants:
                item.archived_at = None
                if item.account_id != actor.account_id and not _is_muted(item, now):
                    db.add(JobQueue(job_type="chat_push", payload={"message_id": message.id, "recipient_account_id": item.account_id}, dedup_key=f"chat-push:{message.id}:{item.account_id}"))
            await _emit(db, actor, conversation, "message_sent", aggregate_type="chat_message", aggregate_id=message.id, recipient_ids=[item.account_id for item in participants], extra={"message_id": message.id, "sender_account_id": actor.account_id, "sender_name": actor.email, "conversation_title": conversation.title if conversation.kind == "group" else None, "preview": (source.body or "Attachment")[:160], "target_url": f"/chat/{conversation.public_id}?message={message.id}"})
            created.append((conversation, message))
        await db.commit()
    except Exception:
        await db.rollback()
        for storage_key in copied_keys:
            await delete_attachment(storage_key)
        raise
    return {"items": [await _message_out(db, message, actor) for _, message in created]}


@router.get("/search")
async def search_messages(
    q: str = Query(min_length=1, max_length=200),
    conversation_public_id: UUID | None = None,
    before_id: int | None = None,
    limit: int = Query(30, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    term = q.strip()
    if not term:
        raise HTTPException(status_code=422, detail="Search text cannot be empty")
    hidden_message = exists(select(ChatMessageHidden.id).where(ChatMessageHidden.message_id == ChatMessage.id, ChatMessageHidden.account_id == actor.account_id))
    attachment_match = exists(select(ChatAttachment.id).where(ChatAttachment.message_id == ChatMessage.id, ChatAttachment.filename.ilike(f"%{term}%")))
    text_match = func.to_tsvector("simple", func.coalesce(ChatMessage.body, "")).op("@@")(func.websearch_to_tsquery("simple", term))
    statement = (
        select(ChatMessage, ChatConversation)
        .join(ChatConversation, ChatConversation.id == ChatMessage.conversation_id)
        .join(ChatParticipant, ChatParticipant.conversation_id == ChatConversation.id)
        .where(
            ChatConversation.organization_id == actor.organization_id,
            ChatParticipant.account_id == actor.account_id,
            ChatParticipant.left_at.is_(None),
            or_(ChatParticipant.visible_after_message_id.is_(None), ChatMessage.id > ChatParticipant.visible_after_message_id),
            ChatMessage.deleted_at.is_(None),
            ~hidden_message,
            or_(text_match, attachment_match),
        )
    )
    if conversation_public_id:
        statement = statement.where(ChatConversation.public_id == conversation_public_id)
    if before_id:
        statement = statement.where(ChatMessage.id < before_id)
    rows = (await db.execute(statement.order_by(ChatMessage.id.desc()).limit(limit + 1))).all()
    page = rows[:limit]
    return {
        "items": [{"conversation": {"public_id": str(conversation.public_id), "title": (await _conversation_summary(db, conversation, actor))["title"]}, "message": await _message_out(db, message, actor)} for message, conversation in page],
        "next_before_id": page[-1][0].id if len(rows) > limit and page else None,
    }


@router.post("/conversations/{public_id}/receipts")
async def acknowledge_receipts(
    public_id: UUID,
    data: ReceiptIn,
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    conversation, participant = await _membership(db, actor, public_id)
    target = await db.scalar(select(ChatMessage).where(ChatMessage.id == data.message_id, ChatMessage.conversation_id == conversation.id))
    if not target or (participant.visible_after_message_id is not None and target.id <= participant.visible_after_message_id):
        raise HTTPException(status_code=404, detail="Message not found")
    rows = (
        await db.execute(
            select(ChatMessageReceipt, ChatMessage.sender_account_id)
            .join(ChatMessage, ChatMessage.id == ChatMessageReceipt.message_id)
            .where(
                ChatMessageReceipt.account_id == actor.account_id,
                ChatMessage.conversation_id == conversation.id,
                ChatMessage.id <= data.message_id,
                *((ChatMessage.id > participant.visible_after_message_id,) if participant.visible_after_message_id is not None else ()),
            )
        )
    ).all()
    changed = False
    sender_ids: set[int] = set()
    now = _now()
    for receipt, sender_account_id in rows:
        if sender_account_id:
            sender_ids.add(sender_account_id)
        if receipt.delivered_at is None:
            receipt.delivered_at = now
            changed = True
        if data.status == "read" and receipt.read_at is None:
            receipt.read_at = now
            changed = True
    if changed:
        await _emit(db, actor, conversation, "receipts_updated", aggregate_type="chat_receipt", aggregate_id=data.message_id, recipient_ids=[actor.account_id, *sender_ids], extra={"message_id": data.message_id, "status": data.status})
        await db.commit()
    return {"acknowledged": True, "message_id": data.message_id, "status": data.status}


@router.get("/conversations/{public_id}/messages/{message_id}/receipts")
async def receipt_details(
    public_id: UUID,
    message_id: int,
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    conversation, _ = await _membership(db, actor, public_id)
    message = await db.scalar(select(ChatMessage).where(ChatMessage.id == message_id, ChatMessage.conversation_id == conversation.id))
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    if message.sender_account_id != actor.account_id:
        raise HTTPException(status_code=403, detail="Only the message author can view receipt details")
    receipts = list((await db.execute(select(ChatMessageReceipt).where(ChatMessageReceipt.message_id == message.id).order_by(ChatMessageReceipt.id))).scalars().all())
    identities = await _identity_map(db, [item.account_id for item in receipts])
    items = []
    for receipt in receipts:
        status = "read" if receipt.read_at else "delivered" if receipt.delivered_at else "sent"
        items.append({
            "account": identities.get(receipt.account_id),
            "status": status,
            "delivered_at": receipt.delivered_at,
            "read_at": receipt.read_at,
        })
    return {
        "message_id": message.id,
        "counts": {
            "total": len(items),
            "delivered": sum(1 for item in items if item["delivered_at"]),
            "read": sum(1 for item in items if item["read_at"]),
        },
        "items": items,
    }
