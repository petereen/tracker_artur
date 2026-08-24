from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.enterprise_deps import ActorContext, get_actor
from app.models.models import (
    ChatConversation,
    ChatMessage,
    ChatMessageReceipt,
    ChatParticipant,
    Employee,
    UserAccount,
    WorkspacePresence,
)
from app.services.enterprise_events import record_change


router = APIRouter()
ONLINE_WINDOW = timedelta(seconds=60)
MAX_GROUP_MEMBERS = 100


class DirectConversationIn(BaseModel):
    account_id: int | None = None
    employee_id: int | None = None


class GroupConversationIn(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    member_account_ids: list[int]


class GroupTitleIn(BaseModel):
    title: str = Field(min_length=1, max_length=80)


class GroupMembersIn(BaseModel):
    account_ids: list[int]


class MessageIn(BaseModel):
    body: str = Field(min_length=1, max_length=4000)
    client_nonce: UUID


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
            "name": employee.name if employee else account.email,
            "email": account.email,
            "avatar_url": (employee.metadata_json or {}).get("avatar_url") if employee else None,
            "is_online": bool(presence and presence.last_seen_at >= cutoff),
            "last_seen_at": presence.last_seen_at if presence else None,
        }
        for account, employee, presence in rows
    }


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
    return {
        "id": message.id,
        "conversation_id": message.conversation_id,
        "sender": identities.get(message.sender_account_id),
        "sender_account_id": message.sender_account_id,
        "client_nonce": str(message.client_nonce),
        "body": message.body,
        "created_at": message.created_at,
        "is_mine": message.sender_account_id == actor.account_id,
        "status": status,
        "receipts": receipts,
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
    last_message = await db.scalar(select(ChatMessage).where(*message_filters).order_by(ChatMessage.id.desc()).limit(1))
    unread = await db.scalar(
        select(func.count(ChatMessageReceipt.id))
        .join(ChatMessage, ChatMessage.id == ChatMessageReceipt.message_id)
        .where(
            ChatMessage.conversation_id == conversation.id,
            ChatMessageReceipt.account_id == actor.account_id,
            ChatMessageReceipt.read_at.is_(None),
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
            "body": last_message.body,
            "sender_account_id": last_message.sender_account_id,
            "sender_name": sender_identity["name"] if sender_identity else None,
            "created_at": last_message.created_at,
        } if last_message else None),
        "unread_count": int(unread),
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
    statement = (
        select(UserAccount.id)
        .outerjoin(Employee, Employee.id == UserAccount.employee_id)
        .where(
            UserAccount.organization_id == actor.organization_id,
            UserAccount.status == "active",
            UserAccount.id != actor.account_id,
        )
        .order_by(func.coalesce(Employee.name, UserAccount.email))
        .limit(limit)
    )
    if q.strip():
        term = f"%{q.strip()}%"
        statement = statement.where(func.coalesce(Employee.name, UserAccount.email).ilike(term))
    ids = list((await db.execute(statement)).scalars().all())
    identities = await _identity_map(db, ids)
    return [identities[account_id] for account_id in ids if account_id in identities]


@router.get("/conversations")
async def conversations(
    q: str = "",
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
    if q.strip():
        term = q.strip().casefold()
        summaries = [
            item for item in summaries
            if term in item["title"].casefold()
            or any(term in member["name"].casefold() for member in item["members"])
        ]
    page = summaries[cursor:cursor + limit]
    next_cursor = cursor + limit if cursor + limit < len(summaries) else None
    return {"items": page, "next_cursor": next_cursor}


@router.get("/unread-count")
async def unread_count(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    total = await db.scalar(
        select(func.count(ChatMessageReceipt.id))
        .join(ChatMessage, ChatMessage.id == ChatMessageReceipt.message_id)
        .join(ChatParticipant, ChatParticipant.conversation_id == ChatMessage.conversation_id)
        .where(
            ChatMessageReceipt.account_id == actor.account_id,
            ChatMessageReceipt.read_at.is_(None),
            ChatParticipant.account_id == actor.account_id,
            ChatParticipant.left_at.is_(None),
        )
    ) or 0
    return {"unread_count": int(total)}


@router.post("/conversations/direct")
async def open_direct(
    data: DirectConversationIn,
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    if bool(data.account_id) == bool(data.employee_id):
        raise HTTPException(status_code=422, detail="Provide exactly one account_id or employee_id")
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


@router.get("/conversations/{public_id}/messages")
async def messages(
    public_id: UUID,
    before_id: int | None = None,
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    conversation, participant = await _membership(db, actor, public_id)
    filters = [ChatMessage.conversation_id == conversation.id]
    if participant.visible_after_message_id is not None:
        filters.append(ChatMessage.id > participant.visible_after_message_id)
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
    body = data.body.strip()
    if not body:
        raise HTTPException(status_code=422, detail="Message cannot be empty")
    existing = await db.scalar(select(ChatMessage).where(ChatMessage.conversation_id == conversation.id, ChatMessage.sender_account_id == actor.account_id, ChatMessage.client_nonce == data.client_nonce))
    if existing:
        return await _message_out(db, existing, actor)
    message = ChatMessage(conversation_id=conversation.id, sender_account_id=actor.account_id, client_nonce=data.client_nonce, body=body)
    db.add(message)
    await db.flush()
    participant_ids = [item.account_id for item in await _active_participants(db, conversation.id)]
    db.add_all(ChatMessageReceipt(message_id=message.id, account_id=account_id) for account_id in participant_ids if account_id != actor.account_id)
    conversation.updated_at = _now()
    await db.flush()
    await _emit(db, actor, conversation, "message_sent", aggregate_type="chat_message", aggregate_id=message.id, recipient_ids=participant_ids, extra={"message_id": message.id, "sender_account_id": actor.account_id})
    await db.commit()
    await db.refresh(message)
    return await _message_out(db, message, actor)


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
