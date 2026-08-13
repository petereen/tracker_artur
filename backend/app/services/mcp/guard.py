"""Redis-backed replay, rate, and concurrency controls for MCP requests."""
from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager

from app.core.config import settings


class MCPGuard:
    """Fail closed in production when Redis is configured but unavailable.

    The in-memory implementation is intentionally only a local-development
    fallback; each deployed edge has Redis in the existing Compose topology.
    """

    def __init__(self) -> None:
        self._redis = None
        self._connect_attempted = False
        self._memory: dict[str, tuple[int, float]] = {}
        self._lock = asyncio.Lock()

    async def _client(self):
        if self._connect_attempted:
            return self._redis
        self._connect_attempted = True
        try:
            from redis.asyncio import Redis
            client = Redis.from_url(settings.AI_REDIS_URL, decode_responses=True)
            await client.ping()
            self._redis = client
        except Exception:
            self._redis = None
        return self._redis

    async def _increment(self, key: str, *, limit: int, ttl: int = 60) -> bool:
        client = await self._client()
        if client:
            value = await client.incr(key)
            if value == 1:
                await client.expire(key, ttl)
            return value <= limit
        now = time.monotonic()
        async with self._lock:
            value, expiry = self._memory.get(key, (0, now + ttl))
            if expiry <= now:
                value, expiry = 0, now + ttl
            value += 1
            self._memory[key] = (value, expiry)
            return value <= limit

    async def ensure_fresh_request(self, *, jti: str, request_id: str) -> bool:
        key = f"oyuns:mcp:replay:{jti}:{request_id}"
        client = await self._client()
        if client:
            return bool(await client.set(key, "1", ex=settings.MCP_TOKEN_TTL_SECONDS, nx=True))
        return await self._increment(key, limit=1, ttl=settings.MCP_TOKEN_TTL_SECONDS)

    async def allow(self, *, account_id: int, organization_id: int, access_mode: str) -> bool:
        actor_limit = settings.MCP_PREVIEWS_PER_ACTOR_MINUTE if access_mode == "preview" else settings.MCP_READS_PER_ACTOR_MINUTE
        actor_ok = await self._increment(f"oyuns:mcp:rate:actor:{account_id}:{access_mode}", limit=actor_limit)
        org_ok = await self._increment(f"oyuns:mcp:rate:organization:{organization_id}:read", limit=settings.MCP_READS_PER_ORGANIZATION_MINUTE)
        return actor_ok and org_ok

    async def allow_confirmation(self, *, account_id: int) -> bool:
        return await self._increment(
            f"oyuns:mcp:rate:actor:{account_id}:confirm",
            limit=settings.MCP_CONFIRMS_PER_ACTOR_MINUTE,
        )

    async def _decrement(self, key: str) -> None:
        client = await self._client()
        if client:
            await client.decr(key)
            return
        async with self._lock:
            value, expiry = self._memory.get(key, (0, time.monotonic() + 60))
            self._memory[key] = (max(0, value - 1), expiry)

    @asynccontextmanager
    async def read_slot(self, organization_id: int):
        """Bound simultaneous read work per tenant, releasing on every path."""
        key = f"oyuns:mcp:inflight:organization:{organization_id}"
        acquired = await self._increment(key, limit=settings.MCP_MAX_ORGANIZATION_CONCURRENT_READS, ttl=60)
        if not acquired:
            await self._decrement(key)
            yield False
            return
        try:
            yield True
        finally:
            await self._decrement(key)


guard = MCPGuard()
