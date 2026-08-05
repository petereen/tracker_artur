import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.enterprise_deps import actor_from_token
from app.models.models import DomainEvent


router = APIRouter()


@router.websocket("/realtime")
async def realtime(websocket: WebSocket, token: str, cursor: int = 0):
    await websocket.accept()
    try:
        async with AsyncSessionLocal() as db:
            actor = await actor_from_token(token, db)
        last_id = max(cursor, 0)
        while True:
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
                await websocket.send_json(
                    {
                        "id": event.id,
                        "topic": event.topic,
                        "entityType": event.aggregate_type,
                        "entityId": event.aggregate_id,
                        "version": event.aggregate_version,
                        "operation": event.operation,
                        "payload": event.payload,
                        "occurredAt": event.created_at.isoformat(),
                    }
                )
                last_id = event.id
            await asyncio.sleep(0.75)
    except (WebSocketDisconnect, asyncio.CancelledError):
        return
    except Exception:
        await websocket.close(code=4401)
