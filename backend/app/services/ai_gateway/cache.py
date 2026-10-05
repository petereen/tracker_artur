"""Two-tier cache. Cache failures are non-fatal and never produce an answer."""
from __future__ import annotations

import hashlib
import logging


from app.core.config import settings

log = logging.getLogger(__name__)


def exact_key(*, organization_id: int, prompt_version: str, language: str, text: str) -> str:
    """Cached answers never cross tenants: the tenant is part of the key."""
    normalized = " ".join(text.split())
    material = f"{prompt_version}|{language}|{normalized}".encode()
    return f"ai:exact:{int(organization_id)}:" + hashlib.sha256(material).hexdigest()


class ResponseCache:
    def __init__(self) -> None:
        self._redis = None

    async def _client(self):
        if not settings.AI_REDIS_URL:
            return None
        if self._redis is None:
            try:
                from redis.asyncio import Redis
                self._redis = Redis.from_url(settings.AI_REDIS_URL, decode_responses=True, socket_connect_timeout=1, socket_timeout=1)
            except Exception:
                log.warning("ai_gateway.redis_unavailable", exc_info=True)
                return None
        return self._redis

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

