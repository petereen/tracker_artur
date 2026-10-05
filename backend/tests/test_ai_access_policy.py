"""Organization-wide OYUNS AI assistant access rights."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.enterprise_deps import build_actor_context, get_actor
from app.routers import ai_settings
from app.services.ai_gateway import AIGateway, GatewayRequest
from app.services.ai_gateway import access_policy
from app.services.ai_gateway.runtime import build_runtime
from app.services.ai_gateway.tools import registry as registry_module
from app.services.mcp.catalog import CATALOG


def admin():
    return build_actor_context(account_id=1, organization_id=1, employee_id=1, email="a@example.test", locale="mn", roles=frozenset({"admin"}))


def runtime_with_access(sections: dict) -> object:
    return build_runtime({"ai_agent": {"access": sections}})


def test_every_catalog_tool_belongs_to_exactly_one_section():
    mapped = [tool for section in access_policy.SECTIONS for tool in (*section.read_tools, *section.write_tools)]
    assert sorted(mapped) == sorted(tool.name for tool in CATALOG)


def test_write_tools_are_exactly_the_mutating_previews():
    writes = {tool for section in access_policy.SECTIONS for tool in section.write_tools}
    assert writes == {tool.name for tool in CATALOG if tool.is_mutation}


def test_unconfigured_organization_keeps_full_access():
    runtime = build_runtime(None)
    assert runtime.access.denied_tools == frozenset()
    matrix = access_policy.normalize(None)
    assert all(entry["read"] for entry in matrix.values())
    assert matrix["tasks"]["write"] is True
    assert matrix["payroll"]["write"] is False


def test_write_requires_read():
    matrix = access_policy.normalize({"tasks": {"read": False, "write": True}})
    assert matrix["tasks"] == {"read": False, "write": False}


def test_disabled_sections_deny_their_tools():
    runtime = runtime_with_access({"payroll": {"read": False}, "tasks": {"read": True, "write": False}})
    assert not runtime.access.allows("oyuns_payroll_summary")
    assert not runtime.access.allows("oyuns_tasks_prepare_create")
    assert not runtime.access.allows("oyuns_tasks_prepare_update")
    assert runtime.access.allows("oyuns_tasks_search")
    assert runtime.access.can_read("tasks") and not runtime.access.can_read("payroll")


def test_visible_definitions_and_model_catalog_exclude_disabled_sections():
    runtime = runtime_with_access({"crm": {"read": False}, "tasks": {"read": True, "write": False}})
    gateway = AIGateway()
    names = {item.name for item in gateway.tool_registry.visible_definitions(admin(), access=runtime.access)}
    assert "oyuns_crm_search" not in names and "oyuns_tasks_prepare_create" not in names
    assert "oyuns_tasks_search" in names
    request = GatewayRequest(text="hi", history=[], channel="web", actor_context=admin(), runtime=runtime)
    tools, allowed = gateway._tool_catalog(request)
    assert "oyuns_crm_search" not in allowed
    assert all(tool["name"] != "oyuns_crm_search" for tool in tools)
    assert "CRM clients/partners and activities" not in gateway._available_data(admin(), sensitive_allowed=True, access=runtime.access)


def test_dispatch_rechecks_the_organization_policy(monkeypatch):
    runtime = runtime_with_access({"hr": {"read": False}})

    async def resolve(_db, _organization_id):
        return runtime

    async def execute(*_args, **_kwargs):
        raise AssertionError("a disabled tool must not reach the adapter")

    monkeypatch.setattr(registry_module, "resolve_ai_runtime", resolve)
    monkeypatch.setattr(registry_module.adapters, "execute", execute)
    result = asyncio.run(registry_module.default_registry.dispatch_tool("oyuns_hr_get", {}, admin(), db=None))
    assert result["status"] == "denied"
    assert "access settings" in result["summary"]


class FakeDb:
    def __init__(self, organization):
        self.organization = organization
        self.commits = 0

    async def get(self, _model, _id, **_kwargs):
        return self.organization

    async def commit(self):
        self.commits += 1


@pytest.fixture
def client(monkeypatch):
    organization = SimpleNamespace(id=1, settings={"ai_agent": {"primary_model": "gpt-5-mini"}})
    db = FakeDb(organization)
    app = FastAPI()
    app.include_router(ai_settings.router, prefix="/v1/settings/ai-agent")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[ai_settings.require_admin] = admin
    changes: list[dict] = []

    async def record_change(*_args, **kwargs):
        changes.append(kwargs)
        return SimpleNamespace(id=1)

    monkeypatch.setattr(ai_settings, "record_change", record_change)
    return TestClient(app), organization, changes


def test_access_endpoints_round_trip(client):
    http, organization, changes = client
    initial = http.get("/v1/settings/ai-agent/access").json()
    assert initial["configured"] is False
    assert [group["key"] for group in initial["groups"]] == [key for key, _ in access_policy.GROUPS]
    assert all(entry["read"] for entry in initial["sections"].values())

    sections = {key: dict(entry) for key, entry in initial["sections"].items()}
    sections["payroll"] = {"read": False, "write": False}
    sections["tasks"] = {"read": True, "write": False}
    saved = http.put("/v1/settings/ai-agent/access", json={"sections": sections}).json()
    assert saved["configured"] is True
    assert saved["sections"]["payroll"] == {"read": False, "write": False}
    # Other AI settings are preserved next to the access matrix.
    assert organization.settings["ai_agent"]["primary_model"] == "gpt-5-mini"
    assert set(changes[-1]["after"]) == {"payroll", "tasks"}
    assert not build_runtime(organization.settings).access.allows("oyuns_payroll_summary")


def test_access_endpoint_rejects_unknown_sections(client):
    http, _, _ = client
    response = http.put("/v1/settings/ai-agent/access", json={"sections": {"nope": {"read": True}}})
    assert response.status_code == 422


def test_access_endpoints_require_admin():
    app = FastAPI()
    app.include_router(ai_settings.router, prefix="/v1/settings/ai-agent")
    app.dependency_overrides[get_actor] = lambda: build_actor_context(account_id=2, organization_id=1, employee_id=2, email="m@example.test", locale="mn", roles=frozenset({"member"}))
    app.dependency_overrides[get_db] = lambda: None
    assert TestClient(app).get("/v1/settings/ai-agent/access").status_code == 403
