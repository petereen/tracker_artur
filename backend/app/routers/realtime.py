import asyncio
from datetime import datetime, timedelta, timezone
from time import monotonic

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.database import AsyncSessionLocal
from app.core.enterprise_deps import actor_from_token
from app.models.models import DomainEvent, WorkspacePresence


router = APIRouter()


async def _touch_presence(actor) -> None:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=60)
    async with AsyncSessionLocal() as db:
        presence = await db.scalar(select(WorkspacePresence).where(WorkspacePresence.account_id == actor.account_id))
        became_online = not presence or presence.last_seen_at < cutoff
        await db.execute(
            pg_insert(WorkspacePresence)
            .values(organization_id=actor.organization_id, account_id=actor.account_id, last_seen_at=now)
            .on_conflict_do_update(index_elements=[WorkspacePresence.account_id], set_={"organization_id": actor.organization_id, "last_seen_at": now})
        )
        if became_online:
            db.add(DomainEvent(
                organization_id=actor.organization_id,
                topic="chat_presence",
                aggregate_type="workspace_presence",
                aggregate_id=actor.account_id,
                operation="online",
                payload={"account_id": actor.account_id, "last_seen_at": now.isoformat()},
            ))
        await db.commit()


@router.websocket("/realtime")
async def realtime(websocket: WebSocket, token: str, cursor: int = 0):
    await websocket.accept()
    try:
        async with AsyncSessionLocal() as db:
            actor = await actor_from_token(token, db)
        await _touch_presence(actor)
        last_presence_touch = monotonic()
        last_id = max(cursor, 0)
        while True:
            try:
                incoming = await asyncio.wait_for(websocket.receive_json(), timeout=0.75)
                if incoming.get("type") == "presence.heartbeat" and monotonic() - last_presence_touch >= 20:
                    await _touch_presence(actor)
                    last_presence_touch = monotonic()
            except asyncio.TimeoutError:
                pass
            async with AsyncSessionLocal() as db:
                events = (
                    await db.execute(
                        select(DomainEvent)
                        .where(DomainEvent.organization_id == actor.organization_id, DomainEvent.id > last_id)
                        .order_by(DomainEvent.id)
                        .limit(200)
                    )
                ).scalars().all()
            for event in events:
                if event.topic == "notifications" and event.payload.get("recipient_account_id") != actor.account_id:
                    last_id = event.id
                    continue
                if event.topic == "chat" and actor.account_id not in event.payload.get("recipient_account_ids", []):
                    last_id = event.id
                    continue
                payload = dict(event.payload or {})
                payload.pop("recipient_account_ids", None)
                await websocket.send_json(
                    {
                        "id": event.id,
                        "topic": event.topic,
                        "entityType": event.aggregate_type,
                        "entityId": event.aggregate_id,
                        "version": event.aggregate_version,
                        "operation": event.operation,
                        "payload": payload,
                        "occurredAt": event.created_at.isoformat(),
                    }
                )
                last_id = event.id
    except (WebSocketDisconnect, asyncio.CancelledError):
        return
    except Exception:
        await websocket.close(code=4401)
