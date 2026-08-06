from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enterprise_deps import ActorContext
from app.models.models import AuditLog, DomainEvent


REDACTED_KEYS = {"password", "password_hash", "token", "access_token", "refresh_token", "audio"}


def _json_safe(value: Any) -> Any:
    """Return a JSONB-safe audit payload without losing useful event data.

    Route serializers deliberately return native datetime/date/UUID/Decimal
    values.  Passing those values straight to PostgreSQL JSONB makes psycopg
    reject the entire business transaction (and caused every affected POST to
    return 500).  Keep this conversion at the event boundary so application
    responses can remain properly typed.
    """
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return value


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: ("[REDACTED]" if key.casefold() in REDACTED_KEYS else _redact(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


async def record_change(
    db: AsyncSession,
    *,
    actor: ActorContext,
    topic: str,
    aggregate_type: str,
    aggregate_id: int,
    operation: str,
    version: int = 1,
    before: dict | None = None,
    after: dict | None = None,
    channel: str = "web",
    request_id: str | None = None,
) -> DomainEvent:
    payload = _json_safe(_redact(after or {}))
    event = DomainEvent(
        organization_id=actor.organization_id,
        topic=topic,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        aggregate_version=version,
        operation=operation,
        payload=payload,
    )
    db.add(event)
    db.add(
        AuditLog(
            organization_id=actor.organization_id,
            actor_account_id=actor.account_id,
            actor_employee_id=actor.employee_id,
            channel=channel,
            action=operation,
            entity_type=aggregate_type,
            entity_id=aggregate_id,
            before_data=_json_safe(_redact(before)),
            after_data=payload,
            request_id=request_id,
        )
    )
    await db.flush()
    await db.execute(text("SELECT pg_notify('oyuns_events', :event_id)"), {"event_id": str(event.id)})
    return event
