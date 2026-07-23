"""Safe review queue for requests that OYUNS cannot classify."""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.bot.db import get_session
from app.models.models import UnknownAssistantRequest

log = logging.getLogger(__name__)


def _normalized_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())[:6_000]


def record_unknown_request(*, text: str, language: str, channel: str) -> None:
    """Store a de-duplicated request for an administrator to review later."""
    normalized = _normalized_text(text)
    if not normalized:
        return
    fingerprint = hashlib.sha256(normalized.casefold().encode("utf-8")).hexdigest()
    try:
        with get_session() as session:
            existing = session.execute(
                select(UnknownAssistantRequest).where(
                    UnknownAssistantRequest.text_hash == fingerprint
                )
            ).scalar_one_or_none()
            if existing:
                existing.occurrence_count += 1
                existing.last_seen_at = datetime.now(timezone.utc)
            else:
                session.add(
                    UnknownAssistantRequest(
                        text=normalized,
                        text_hash=fingerprint,
                        language=language[:8],
                        channel=channel[:16],
                    )
                )
            session.commit()
    except SQLAlchemyError:
        log.exception("assistant.unknown_request_store_failed")
