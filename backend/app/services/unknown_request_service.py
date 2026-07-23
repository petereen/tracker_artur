"""Safe review queue for requests that OYUNS cannot classify."""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.bot.db import get_session
from app.models.models import AssistantContextExample, UnknownAssistantRequest
from app.services.knowledge_service import tokenize_search_terms

log = logging.getLogger(__name__)


def _normalized_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())[:6_000]


def _learning_terms(text: str) -> list[str]:
    """Keep a compact, useful dictionary view alongside the original phrase."""
    return tokenize_search_terms([text])[:24]


def record_unknown_request(
    *,
    text: str,
    language: str,
    channel: str,
    reason: str = "unclassified",
) -> None:
    """Store a de-duplicated request and its useful terms for administrator review."""
    normalized = _normalized_text(text)
    if not normalized:
        return
    fingerprint = hashlib.sha256(normalized.casefold().encode("utf-8")).hexdigest()
    terms = _learning_terms(normalized)
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
                existing.terms = terms
                existing.reason = reason[:80] or "unclassified"
            else:
                session.add(
                    UnknownAssistantRequest(
                        text=normalized,
                        text_hash=fingerprint,
                        language=language[:8],
                        channel=channel[:16],
                        terms=terms,
                        reason=reason[:80] or "unclassified",
                    )
                )
            session.commit()
    except SQLAlchemyError:
        log.exception("assistant.unknown_request_store_failed")


def active_context_examples(*, limit: int = 40) -> list[dict]:
    """Return only administrator-approved wording for the router's context window."""
    try:
        with get_session() as session:
            rows = session.execute(
                select(AssistantContextExample)
                .where(AssistantContextExample.is_active.is_(True))
                .order_by(AssistantContextExample.updated_at.desc(), AssistantContextExample.id.desc())
                .limit(limit)
            ).scalars().all()
            return [
                {"phrase": row.phrase, "intent": row.intent, "meaning": row.meaning}
                for row in rows
            ]
    except SQLAlchemyError:
        log.exception("assistant.context_examples_load_failed")
        return []
