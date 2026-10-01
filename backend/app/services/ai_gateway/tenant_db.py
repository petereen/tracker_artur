"""Tenant-isolated database access for the OYUNS AI agent.

Every agent turn runs for exactly one tenant, and all of its data access is
confined to that tenant by four independent layers:

1. ``tenant_ai_session(organization_id)`` refuses to open without a tenant
   and refuses a tenant other than the one already bound to the request.
2. The session runs inside ``tenant_scope``: the ORM guard rejects loading or
   writing another tenant's rows (``TenantBoundaryViolation``) and new rows
   are stamped with the tenant.
3. Every transaction sets ``app.tenant_id`` and ``app.rls_strict = on``, so
   PostgreSQL row-level security (``tenant_row_visible``) hides every other
   tenant's rows, and nothing at all is visible if the tenant were missing.
4. Each tenant gets its own connection pool on a dedicated engine
   (``AI_DATABASE_URL``, a least-privilege role without BYPASSRLS): agent
   connections are never shared between tenants, and RLS applies to them
   even where the main API still connects as the schema owner.
"""
from __future__ import annotations

import logging
from collections import OrderedDict
from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from app.core.config import settings
from app.core.tenancy import TenantBoundaryViolation, current_tenant_id, tenant_scope

log = logging.getLogger(__name__)

# Idle tenants' pools are closed once this many tenants have pools; with one
# kept-open connection per pool this bounds idle agent connections to 16.
MAX_TENANT_POOLS = 16
_engines: "OrderedDict[int, AsyncEngine]" = OrderedDict()
_role_checked: dict[str, bool] = {}


class TenantIsolationError(TenantBoundaryViolation):
    """The agent was asked to touch data without (or outside) its tenant."""


def ai_database_url() -> str:
    return settings.AI_DATABASE_URL or settings.DATABASE_URL


def require_tenant(organization_id: int | None) -> int:
    """The turn's tenant; fails closed when it is missing or conflicts."""
    if not isinstance(organization_id, int) or isinstance(organization_id, bool) or organization_id <= 0:
        raise TenantIsolationError("OYUNS agent turn without a tenant")
    bound = current_tenant_id()
    if bound is not None and bound != organization_id:
        log.error("ai_tenant.mismatch bound=%s requested=%s", bound, organization_id)
        raise TenantIsolationError(f"agent bound to tenant {bound}, not {organization_id}")
    return organization_id


def _strict_rls(_session, _transaction, connection) -> None:
    if connection.dialect.name == "postgresql":
        # ``after_begin`` of the tenancy module already set app.tenant_id;
        # strict mode makes a missing tenant see nothing instead of all.
        connection.execute(text("SELECT set_config('app.rls_strict', 'on', true)"))


def _engine_for(organization_id: int) -> AsyncEngine:
    engine = _engines.get(organization_id)
    if engine is not None:
        _engines.move_to_end(organization_id)
        return engine
    url = ai_database_url()
    options = {"pool_pre_ping": True}
    if url.startswith("postgresql"):
        options.update(pool_size=1, max_overflow=3, pool_recycle=1800)
    engine = create_async_engine(url, **options)
    _engines[organization_id] = engine
    while len(_engines) > MAX_TENANT_POOLS:
        _, stale = _engines.popitem(last=False)
        # Connections return to a disposed pool and are closed on check-in.
        stale.sync_engine.dispose(close=False)
    return engine


async def _check_role(session: AsyncSession) -> None:
    """Warn (or refuse) once per URL when the agent's role bypasses RLS."""
    url = ai_database_url()
    if url in _role_checked:
        if not _role_checked[url] and settings.AI_DATABASE_REQUIRE_RLS:
            raise TenantIsolationError("AI database role bypasses row-level security")
        return
    bind = session.bind
    if bind is None or bind.dialect.name != "postgresql":
        _role_checked[url] = True
        return
    row = (await session.execute(text(
        "SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user"
    ))).first()
    enforced = not bool(row and row[0])
    _role_checked[url] = enforced
    if not enforced:
        log.warning("ai_tenant.rls_bypassed: set AI_DATABASE_URL to a NOBYPASSRLS role (ops/sql/oyuns_ai_role.sql)")
        if settings.AI_DATABASE_REQUIRE_RLS:
            raise TenantIsolationError("AI database role bypasses row-level security")


@asynccontextmanager
async def tenant_ai_session(organization_id: int | None) -> AsyncIterator[AsyncSession]:
    """A short-lived session that can only ever see ``organization_id``."""
    tenant_id = require_tenant(organization_id)
    with tenant_scope(tenant_id):
        async with AsyncSession(_engine_for(tenant_id), expire_on_commit=False) as session:
            event.listen(session.sync_session, "after_begin", _strict_rls)
            await _check_role(session)
            yield session


async def bind_session_tenant(db, organization_id: int) -> None:
    """Pin a caller-provided session (API request, bot turn) to the tenant.

    The request session's transaction may have begun before the tenant was
    known; the RLS setting is (re)applied to it so the agent's context and
    preview writes on that session are confined as well.
    """
    if not isinstance(db, AsyncSession):
        return
    owner = db.info.get("ai_tenant_id")
    if owner is not None and owner != organization_id:
        raise TenantIsolationError(f"session pinned to tenant {owner}, not {organization_id}")
    db.info["ai_tenant_id"] = organization_id
    bind = db.bind
    if bind is not None and bind.dialect.name == "postgresql" and db.in_transaction():
        await db.execute(text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": str(organization_id)})


async def dispose_all() -> None:
    while _engines:
        _, engine = _engines.popitem()
        await engine.dispose()
