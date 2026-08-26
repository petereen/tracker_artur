from __future__ import annotations

import hmac
import uuid
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.enterprise_deps import ActorContext, actor_from_account_id, get_actor
from app.models.models import ChatCall, ChatConversation, ChatMessage, Employee, UserAccount
from app.routers.chat import OYUNS_AGENT_EMAIL_PREFIX, _active_participants, _emit


router = APIRouter()


class AuthorizeCallIn(BaseModel):
    conversation_id: UUID = Field(alias="conversationId")
    recipient_id: int = Field(alias="recipientId")


class InternalCallCreateIn(BaseModel):
    call_id: UUID = Field(alias="callId")
    conversation_id: UUID = Field(alias="conversationId")
    caller_id: int = Field(alias="callerId")
    callee_id: int = Field(alias="calleeId")
    call_type: Literal["audio", "video"] = Field(alias="callType")


class InternalCallLifecycleIn(BaseModel):
    state: Literal["accepted", "connected", "ended"]
    outcome: Literal["completed", "missed", "declined", "canceled", "failed"] | None = None
    reason: str | None = Field(default=None, max_length=120)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _require_internal_secret(value: str | None) -> None:
    expected = settings.CALL_SIGNALING_SECRET
    if not expected or not value or not hmac.compare_digest(value, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signaling service credential")


async def _identity(db: AsyncSession, account_id: int) -> dict:
    row = (
        await db.execute(
            select(UserAccount, Employee)
            .outerjoin(Employee, Employee.id == UserAccount.employee_id)
            .where(UserAccount.id == account_id, UserAccount.status == "active")
        )
    ).one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Call participant not found")
    account, employee = row
    return {
        "userId": str(account.id),
        "name": employee.name if employee else account.email,
        "avatar": (employee.metadata_json or {}).get("avatar_url") if employee else None,
        "isAgent": account.email.startswith(OYUNS_AGENT_EMAIL_PREFIX),
    }


@router.get("/session")
async def signaling_session(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    identity = await _identity(db, actor.account_id)
    return {**identity, "organizationId": str(actor.organization_id)}


@router.post("/authorize")
async def authorize_call(data: AuthorizeCallIn, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    conversation = await db.scalar(
        select(ChatConversation).where(
            ChatConversation.public_id == data.conversation_id,
            ChatConversation.organization_id == actor.organization_id,
            ChatConversation.kind == "direct",
            ChatConversation.archived_at.is_(None),
        )
    )
    if not conversation:
        raise HTTPException(status_code=404, detail="Direct conversation not found")
    participants = await _active_participants(db, conversation.id)
    participant_ids = {item.account_id for item in participants}
    if len(participant_ids) != 2 or actor.account_id not in participant_ids or data.recipient_id not in participant_ids or data.recipient_id == actor.account_id:
        raise HTTPException(status_code=403, detail="Recipient is not the direct-chat counterpart")
    caller = await _identity(db, actor.account_id)
    callee = await _identity(db, data.recipient_id)
    if callee["isAgent"]:
        raise HTTPException(status_code=422, detail="The OYUNS agent cannot receive calls")
    return {"conversationId": str(conversation.public_id), "caller": caller, "callee": callee}


@router.post("/internal/initiate", status_code=201)
async def internal_initiate_call(
    data: InternalCallCreateIn,
    x_call_service_secret: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    _require_internal_secret(x_call_service_secret)
    existing = await db.get(ChatCall, data.call_id)
    if existing:
        return {"callId": str(existing.id), "status": existing.status}
    conversation = await db.scalar(select(ChatConversation).where(ChatConversation.public_id == data.conversation_id, ChatConversation.kind == "direct"))
    if not conversation:
        raise HTTPException(status_code=404, detail="Direct conversation not found")
    participants = await _active_participants(db, conversation.id)
    if {item.account_id for item in participants} != {data.caller_id, data.callee_id}:
        raise HTTPException(status_code=403, detail="Call participants do not match the direct conversation")
    call = ChatCall(
        id=data.call_id,
        organization_id=conversation.organization_id,
        conversation_id=conversation.id,
        caller_account_id=data.caller_id,
        callee_account_id=data.callee_id,
        call_type=data.call_type,
    )
    db.add(call)
    await db.commit()
    return {"callId": str(call.id), "status": call.status}


@router.patch("/internal/{call_id}")
async def internal_update_call(
    call_id: UUID,
    data: InternalCallLifecycleIn,
    x_call_service_secret: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    _require_internal_secret(x_call_service_secret)
    call = await db.scalar(select(ChatCall).where(ChatCall.id == call_id).with_for_update())
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")
    if call.status == "ended":
        return {"callId": str(call.id), "status": call.status, "durationSeconds": call.duration_seconds}
    now = _now()
    if data.state == "accepted":
        call.status = "accepted"
        call.accepted_at = call.accepted_at or now
    elif data.state == "connected":
        call.status = "connected"
        call.accepted_at = call.accepted_at or now
        call.connected_at = call.connected_at or now
    else:
        call.status = "ended"
        call.ended_at = now
        call.outcome = data.outcome or ("completed" if call.connected_at else "failed")
        call.end_reason = data.reason
        call.duration_seconds = max(0, int((now - call.connected_at).total_seconds())) if call.connected_at else 0
        message = await db.scalar(select(ChatMessage).where(ChatMessage.call_id == call.id))
        if not message:
            message = ChatMessage(
                conversation_id=call.conversation_id,
                sender_account_id=None,
                client_nonce=uuid.uuid4(),
                kind="call",
                call_id=call.id,
            )
            db.add(message)
            await db.flush()
            conversation = await db.get(ChatConversation, call.conversation_id)
            conversation.updated_at = now
            participants = await _active_participants(db, call.conversation_id)
            actor = await actor_from_account_id(call.caller_account_id, db)
            await _emit(
                db,
                actor,
                conversation,
                "message_sent",
                aggregate_type="chat_message",
                aggregate_id=message.id,
                recipient_ids=[item.account_id for item in participants],
                extra={
                    "message_id": message.id,
                    "sender_account_id": None,
                    "preview": "Call ended",
                    "target_url": f"/chat/{conversation.public_id}?message={message.id}",
                },
            )
    await db.commit()
    return {"callId": str(call.id), "status": call.status, "durationSeconds": call.duration_seconds}
