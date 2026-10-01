"""The OYUNS agent never reads or writes outside the asking tenant."""
import asyncio

import pytest

from app.core.enterprise_deps import ActorContext
from app.core.tenancy import current_tenant_id, tenant_scope
from app.services.ai_gateway import tenant_db
from app.services.ai_gateway.gateway import AIGateway
from app.services.ai_gateway.tenant_db import TenantIsolationError, require_tenant, tenant_ai_session
from app.services.ai_gateway.tools.registry import ToolRegistry


def actor(organization_id):
    return ActorContext(account_id=7, organization_id=organization_id, employee_id=None, email="a@test", locale="mn", roles=frozenset({"member"}))


@pytest.mark.parametrize("value", [None, 0, -1, "1", True])
def test_turn_without_a_tenant_fails_closed(value):
    with pytest.raises(TenantIsolationError):
        require_tenant(value)


def test_turn_for_another_tenant_than_the_bound_one_fails():
    with tenant_scope(1):
        assert require_tenant(1) == 1
        with pytest.raises(TenantIsolationError):
            require_tenant(2)


def test_execute_turn_refuses_a_cross_tenant_actor_before_reading_data():
    gateway = AIGateway()

    async def run():
        with tenant_scope(1):
            await gateway.execute_turn(object(), actor(2), [{"role": "user", "content": "hello"}])

    with pytest.raises(TenantIsolationError):
        asyncio.run(run())


def test_direct_tool_dispatch_is_denied_across_tenants():
    async def run():
        with tenant_scope(1):
            return await ToolRegistry().dispatch_tool("oyuns_hr_get", {}, actor(2), db=object())

    assert ToolRegistry().get("oyuns_hr_get") is not None
    result = asyncio.run(run())
    assert result["status"] == "denied"


def test_agent_sessions_are_pinned_to_their_tenant_with_own_pools(monkeypatch):
    monkeypatch.setattr(tenant_db.settings, "AI_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setattr(tenant_db, "_engines", type(tenant_db._engines)())
    monkeypatch.setattr(tenant_db, "_role_checked", {})

    async def run():
        seen = []
        async with tenant_ai_session(5) as first:
            seen.append(current_tenant_id())
        async with tenant_ai_session(6) as second:
            seen.append(current_tenant_id())
        assert first.bind is not second.bind  # one pool per tenant
        assert current_tenant_id() is None
        with tenant_scope(5):
            with pytest.raises(TenantIsolationError):
                async with tenant_ai_session(6):
                    pass
        await tenant_db.dispose_all()
        return seen

    assert asyncio.run(run()) == [5, 6]


def test_session_already_pinned_to_one_tenant_cannot_serve_another():
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    async def run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with AsyncSession(engine) as session:
            await tenant_db.bind_session_tenant(session, 3)
            with pytest.raises(TenantIsolationError):
                await tenant_db.bind_session_tenant(session, 4)
        await engine.dispose()

    asyncio.run(run())
