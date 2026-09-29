"""Per-request tenant resolution and boundary enforcement (pure ASGI).

For every HTTP/WebSocket request outside the operator console it:

* resolves a tenant from the host (``<slug>.<TENANT_BASE_DOMAIN>`` or a
  verified custom domain) and from the signed access token;
* rejects a token of one tenant presented on another tenant's host;
* blocks suspended/terminated tenants, missing/expired licenses and routes of
  feature modules the license does not include;
* publishes the tenant in ``app.core.tenancy``'s context variable, so every
  database transaction of the request runs under PostgreSQL RLS for it.

``/v1/platform/*`` is the operator console: tenant tokens are refused there
and the console can be pinned to specific hosts and client networks.
"""

from __future__ import annotations

import logging
from urllib.parse import parse_qs

from starlette.datastructures import Headers
from starlette.responses import JSONResponse

from app.core.config import settings
from app.core.security import decode_token
from app.core.tenancy import (
    TenantNotFound,
    _csv,
    classify_host,
    client_ip_allowed,
    evaluate_tenant_access,
    reset_current_tenant,
    set_current_tenant,
    system_scope,
    tenant_directory,
)

log = logging.getLogger(__name__)

PLATFORM_PREFIX = "/v1/platform"
PUBLIC_PATHS = frozenset({"/health", "/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"})
# Internal service-to-service surfaces authenticate on their own.
INTERNAL_PREFIXES = ("/v1/mcp-executor",)
SCOPE_KEY = "oyuns.tenant"


def _bearer(headers: Headers, scope) -> str | None:
    authorization = headers.get("authorization") or ""
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip() or None
    if scope["type"] == "websocket":
        values = parse_qs(scope.get("query_string", b"").decode("latin-1")).get("token")
        return values[0] if values else None
    return None


def _client_ip(headers: Headers, scope) -> str | None:
    forwarded = headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    client = scope.get("client")
    return client[0] if client else None


class TenantContextMiddleware:
    def __init__(self, app, directory=None) -> None:
        self.app = app
        self.directory = directory or tenant_directory

    async def __call__(self, scope, receive, send):
        if scope["type"] not in {"http", "websocket"}:
            return await self.app(scope, receive, send)
        path = scope.get("path") or "/"
        if path in PUBLIC_PATHS or any(path.startswith(prefix) for prefix in INTERNAL_PREFIXES):
            return await self.app(scope, receive, send)
        headers = Headers(scope=scope)
        if path == PLATFORM_PREFIX or path.startswith(PLATFORM_PREFIX + "/"):
            return await self._platform(scope, receive, send, headers)
        return await self._tenant(scope, receive, send, headers, path)

    async def _platform(self, scope, receive, send, headers: Headers):
        console_hosts = _csv(settings.PLATFORM_CONSOLE_HOSTS)
        host = (headers.get("host") or "").split(":")[0].lower().strip(".")
        # Pinned console hosts win; otherwise any non-tenant host may serve it.
        # A tenant's own domain never exposes the operator console.
        allowed = host in console_hosts if console_hosts else classify_host(host)[0] == "root"
        if not allowed:
            return await self._deny(scope, receive, send, 404, "not_found", "Not Found")
        if not client_ip_allowed(_client_ip(headers, scope)):
            return await self._deny(scope, receive, send, 403, "platform_network_denied", "Operator console is not reachable from this network")
        # The console always runs in the (declared) system context.
        with system_scope():
            return await self.app(scope, receive, send)

    async def _tenant(self, scope, receive, send, headers: Headers, path: str):
        try:
            host_tenant = await self.directory.resolve_host(headers.get("host"))
        except TenantNotFound:
            return await self._deny(scope, receive, send, 404, "tenant_not_found", "Workspace not found")

        bearer = _bearer(headers, scope)
        claims = decode_token(bearer) if bearer else None
        token_tenant: int | None = None
        if claims:
            kind = claims.get("kind")
            if kind == "platform":
                return await self._deny(scope, receive, send, 403, "platform_token_not_allowed", "Operator tokens cannot access tenant workspaces")
            if kind == "enterprise" and claims.get("organization_id") is not None:
                token_tenant = int(claims["organization_id"])
            elif kind is None and claims.get("sub"):
                # Legacy admin-panel tokens belong to the primary tenant.
                token_tenant = await self.directory.primary_id()

        if host_tenant is not None and token_tenant is not None and host_tenant != token_tenant:
            return await self._deny(scope, receive, send, 403, "tenant_mismatch", "This session belongs to another workspace")

        tenant_id = token_tenant if token_tenant is not None else host_tenant
        if tenant_id is None:
            # Shared host, not signed in (login, public pages): system context.
            return await self.app(scope, receive, send)

        state = await self.directory.state(tenant_id)
        if state is None:
            return await self._deny(scope, receive, send, 401, "tenant_not_found", "Workspace not found")
        denial = evaluate_tenant_access(state, path)
        if denial:
            return await self._deny(scope, receive, send, denial.status_code, denial.code, denial.message)

        scope[SCOPE_KEY] = state
        context_token = set_current_tenant(tenant_id)
        try:
            return await self.app(scope, receive, send)
        finally:
            reset_current_tenant(context_token)

    @staticmethod
    async def _deny(scope, receive, send, status_code: int, code: str, message: str):
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 4000 + min(status_code, 999), "reason": code})
            return
        response = JSONResponse(status_code=status_code, content={"detail": {"code": code, "message": message}})
        await response(scope, receive, send)


def request_tenant(request) -> object | None:
    """The ``TenantState`` resolved for this request, if any."""
    return request.scope.get(SCOPE_KEY)
