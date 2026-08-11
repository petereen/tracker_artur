"""Two-tier cache. Cache failures are non-fatal and never produce an answer."""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.models import AssistantSemanticCache

log = logging.getLogger(__name__)


def exact_key(*, prompt_version: str, language: str, text: str) -> str:
    normalized = " ".join(text.split())
    material = f"{prompt_version}|{language}|{normalized}".encode()
    return "ai:exact:" + hashlib.sha256(material).hexdigest()


class ResponseCache:
    def __init__(self) -> None:
        self._redis = None

    async def _client(self):
        if not settings.AI_REDIS_URL:
            return None
        if self._redis is None:
            try:
                from redis.asyncio import Redis
                self._redis = Redis.from_url(settings.AI_REDIS_URL, decode_responses=True)
            except Exception:
                log.warning("ai_gateway.redis_unavailable", exc_info=True)
                return None
        return self._redis

    async def get_exact(self, key: str) -> dict | None:
        try:
            client = await self._client()
            value = await client.get(key) if client else None
            return json.loads(value) if value else None
        except Exception:
            log.warning("ai_gateway.redis_get_failed", exc_info=True)
            return None

    async def put_exact(self, key: str, value: dict) -> None:
        try:
            client = await self._client()
            if client:
                await client.set(key, json.dumps(value, ensure_ascii=False), ex=settings.AI_EXACT_CACHE_TTL_SECONDS)
        except Exception:
            log.warning("ai_gateway.redis_set_failed", exc_info=True)

    async def circuit_open(self, model_key: str) -> bool:
        try:
            client = await self._client()
            return bool(client and await client.exists(f"ai:circuit:{model_key}:open"))
        except Exception:
            return False

    async def record_model_success(self, model_key: str) -> None:
        try:
            client = await self._client()
            if client:
                await client.delete(f"ai:circuit:{model_key}:failures")
        except Exception:
            log.warning("ai_gateway.circuit_success_failed", exc_info=True)

    async def record_model_failure(self, model_key: str) -> None:
        try:
            client = await self._client()
            if not client:
                return
            failures = await client.incr(f"ai:circuit:{model_key}:failures")
            await client.expire(f"ai:circuit:{model_key}:failures", 60)
            if failures >= settings.AI_CIRCUIT_FAILURE_THRESHOLD:
                await client.set(f"ai:circuit:{model_key}:open", "1", ex=settings.AI_CIRCUIT_OPEN_SECONDS)
        except Exception:
            log.warning("ai_gateway.circuit_failure_failed", exc_info=True)

    async def get_semantic(self, db: AsyncSession, embedding: list[float], *, prompt_version: str, language: str) -> AssistantSemanticCache | None:
        # pgvector's cosine distance operator avoids pulling all vectors into
        # application memory. A missing extension simply yields no cache hit.
        try:
            rows = (await db.execute(
                select(AssistantSemanticCache)
                .where(AssistantSemanticCache.expires_at > datetime.now(timezone.utc), AssistantSemanticCache.prompt_version == prompt_version, AssistantSemanticCache.language == language)
                .order_by(AssistantSemanticCache.embedding.cosine_distance(embedding))
                .limit(1)
            )).scalars().all()
            if not rows:
                return None
            candidate = rows[0]
            distance = await db.scalar(select(AssistantSemanticCache.embedding.cosine_distance(embedding)).where(AssistantSemanticCache.id == candidate.id))
            return candidate if distance is not None and 1 - float(distance) >= settings.AI_SEMANTIC_CACHE_THRESHOLD else None
        except Exception:
            log.warning("ai_gateway.semantic_get_failed", exc_info=True)
            return None

    async def put_semantic(self, db: AsyncSession, *, text: str, answer: str, embedding: list[float], language: str, prompt_version: str, model: str, usage: dict) -> None:
        db.add(AssistantSemanticCache(
            prompt_version=prompt_version, language=language, query_text=text, answer=answer,
            embedding=embedding, source_model=model, usage=usage,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=settings.AI_SEMANTIC_CACHE_TTL_SECONDS),
        ))
