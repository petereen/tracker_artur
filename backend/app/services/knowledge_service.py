"""Small-library retrieval for admin-curated company knowledge."""

from __future__ import annotations

import logging
import re
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.bot.db import get_session
from app.models.models import CompanyKnowledge

log = logging.getLogger(__name__)

_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)
_STOP_WORDS = {
    # English
    "a", "an", "and", "are", "can", "do", "for", "how", "i", "in", "is", "me",
    "my", "of", "on", "the", "to", "what", "with",
    # Russian
    "в", "для", "и", "как", "мне", "мой", "моя", "о", "по", "что", "это",
    # Mongolian
    "ба", "би", "бол", "миний", "надад", "нь", "тухай", "юу", "ямар", "яаж",
}


def tokenize_search_terms(values: Iterable[str]) -> list[str]:
    tokens: list[str] = []
    seen: set[str] = set()
    for value in values:
        for token in _WORD_RE.findall((value or "").casefold()):
            if len(token) < 2 or token in _STOP_WORDS or token in seen:
                continue
            seen.add(token)
            tokens.append(token)
    return tokens[:24]


def _match_count(token: str, value: str) -> int:
    """Count exact matches, then safely handle common word inflections.

    The curated library is multilingual. Russian and Mongolian suffixes often
    make an otherwise relevant article invisible to a plain substring search.
    A five-character prefix is deliberately only a low-weight fallback.
    """
    lowered = (value or "").casefold()
    exact = lowered.count(token)
    if exact or len(token) < 5:
        return exact
    stem = token[:5]
    return sum(1 for word in _WORD_RE.findall(lowered) if word.startswith(stem))


def rank_knowledge(
    entries: list[dict],
    terms: Iterable[str],
    *,
    limit: int = 5,
    max_chars: int = 12_000,
) -> list[dict]:
    """Rank active entries with title/category weighted above body matches."""
    tokens = tokenize_search_terms(terms)
    if not tokens:
        return []

    ranked: list[tuple[int, int, dict]] = []
    for entry in entries:
        if not entry.get("is_active", False):
            continue
        title = (entry.get("title") or "").casefold()
        category = (entry.get("category") or "").casefold()
        content = (entry.get("content") or "").casefold()
        score = 0
        for token in tokens:
            title_matches = _match_count(token, title)
            category_matches = _match_count(token, category)
            content_matches = _match_count(token, content)
            score += (8 if token in title else 5 if title_matches else 0)
            score += (4 if token in category else 2 if category_matches else 0)
            score += min(content_matches, 3)
        if score:
            ranked.append((score, int(entry.get("id") or 0), entry))

    ranked.sort(key=lambda item: (-item[0], -item[1]))
    selected: list[dict] = []
    used_chars = 0
    for _, _, entry in ranked[:limit]:
        remaining = max_chars - used_chars
        if remaining <= 0:
            break
        copy = dict(entry)
        copy["content"] = (copy.get("content") or "")[:remaining]
        used_chars += len(copy["content"])
        selected.append(copy)
    return selected


def list_active_knowledge() -> list[dict]:
    try:
        with get_session() as session:
            rows = session.execute(
                select(CompanyKnowledge)
                .where(CompanyKnowledge.is_active.is_(True))
                .order_by(CompanyKnowledge.updated_at.desc(), CompanyKnowledge.id.desc())
            ).scalars().all()
            return [
                {
                    "id": row.id,
                    "title": row.title,
                    "category": row.category,
                    "content": row.content,
                    "is_active": row.is_active,
                }
                for row in rows
            ]
    except SQLAlchemyError:
        log.exception("knowledge.list_failed")
        return []


def search_knowledge(terms: Iterable[str], *, limit: int = 5) -> list[dict]:
    return rank_knowledge(list_active_knowledge(), terms, limit=limit)


def active_knowledge_count() -> int:
    try:
        with get_session() as session:
            return int(
                session.execute(
                    select(func.count()).where(CompanyKnowledge.is_active.is_(True))
                ).scalar_one()
            )
    except SQLAlchemyError:
        log.exception("knowledge.count_failed")
        return 0
