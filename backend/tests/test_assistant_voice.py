"""OYUNS live voice calls: session minting and governed tool dispatch."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.enterprise_deps import build_actor_context, get_actor
from app.routers import assistant_voice
from app.services.ai_gateway import voice_call
from app.services.ai_gateway.runtime import build_runtime


class FakeDb:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


def member():
    return build_actor_context(account_id=11, organization_id=1, employee_id=3, email="w@example.test", locale="mn", roles=frozenset({"member"}))


@pytest.fixture
def client(monkeypatch):
    db = FakeDb()
    app = FastAPI()
    app.include_router(assistant_voice.router, prefix="/v1/assistant/voice")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_actor] = member

    async def record_change(*_args, **_kwargs):
        return SimpleNamespace(id=1)

    async def build_context(_db, _actor, *, sensitive_allowed):
        return {"reply_language": "mn", "current_employee": {"name": "Сараа"}}

    monkeypatch.setattr(assistant_voice, "record_change", record_change)
    monkeypatch.setattr(assistant_voice.gateway, "_build_context", build_context)
    voice_call._session_starts.clear()
    return TestClient(app), db


def runtime_with(**stored):
    return build_runtime({"ai_agent": stored})


def test_session_config_uses_latest_realtime_model_and_read_only_tools():
    definitions = voice_call.visible_voice_tools(assistant_voice.gateway.tool_registry, member())
    assert definitions and all(item.read_only for item in definitions)
    assert "oyuns_tasks_prepare_create" not in {item.name for item in definitions}
    tools = voice_call.realtime_tools(definitions)
    assert all(tool["type"] == "function" and tool["parameters"]["type"] == "object" for tool in tools)
    config = voice_call.session_config(build_runtime(None), "instructions", tools)
    assert config["session"]["model"] == "gpt-realtime"
    assert config["session"]["audio"]["output"]["voice"] == "marin"
    assert config["expires_after"]["seconds"] <= 600
    minimal = voice_call.session_config(runtime_with(realtime_model="gpt-realtime-mini", realtime_voice="cedar"), "x", [], minimal=True)
    assert minimal["session"]["model"] == "gpt-realtime-mini" and "input" not in minimal["session"]["audio"]


def test_session_requires_a_configured_key(client, monkeypatch):
    http, _ = client

    async def resolve(_db, _organization_id):
        return runtime_with()

    monkeypatch.setattr(assistant_voice, "resolve_ai_runtime", resolve)
    monkeypatch.setattr("app.services.ai_gateway.runtime._env_key", lambda: "")
    response = http.post("/v1/assistant/voice/session")
    assert response.status_code == 503 and response.json()["detail"] == "not_configured"


def test_session_can_be_disabled_by_admin(client, monkeypatch):
    http, _ = client

    async def resolve(_db, _organization_id):
        return runtime_with(realtime_enabled=False)

    monkeypatch.setattr(assistant_voice, "resolve_ai_runtime", resolve)
    assert http.post("/v1/assistant/voice/session").json()["detail"] == "voice_disabled"


def test_session_mints_a_client_secret_with_grounded_instructions(client, monkeypatch):
    http, db = client
    captured = {}

    async def resolve(_db, _organization_id):
        return SimpleNamespace(api_key="sk-test-key", realtime_enabled=True, realtime_model="gpt-realtime", realtime_voice="marin")

    async def mint(runtime, instructions, tools):
        captured.update(instructions=instructions, tools=tools)
        return {"value": "ek_secret", "expires_at": 123}

    monkeypatch.setattr(assistant_voice, "resolve_ai_runtime", resolve)
    monkeypatch.setattr(voice_call, "create_client_secret", mint)
    body = http.post("/v1/assistant/voice/session").json()
    assert body["client_secret"] == "ek_secret" and body["calls_url"] == voice_call.REALTIME_CALLS_URL
    assert "sk-test-key" not in json.dumps(body)
    assert "Сараа" in captured["instructions"] and "live_voice_call" in captured["instructions"]
    assert {tool["name"] for tool in captured["tools"]} == set(body["tools"])
    assert db.commits == 1


def test_session_starts_are_rate_limited_per_account():
    voice_call._session_starts.clear()
    assert all(voice_call.allow_session_start(5, now=float(index)) for index in range(voice_call.SESSION_RATE_LIMIT))
    assert not voice_call.allow_session_start(5, now=20.0)
    assert voice_call.allow_session_start(5, now=20.0 + voice_call.SESSION_RATE_WINDOW_SECONDS)


def test_tool_calls_are_rechecked_against_the_caller(client, monkeypatch):
    http, db = client
    calls = []

    async def dispatch(name, arguments, actor, *, db, **_kwargs):
        calls.append((name, arguments, actor.account_id))
        return {"status": "ok", "summary": "1 task", "data": {"items": [{"title": "Тайлан"}]}}

    monkeypatch.setattr(assistant_voice.gateway.tool_registry, "dispatch_tool", dispatch)
    denied = http.post("/v1/assistant/voice/tool", json={"name": "oyuns_tasks_prepare_create", "arguments": "{}", "call_id": "c1"}).json()
    assert json.loads(denied["output"])["status"] == "denied" and not calls
    invalid = http.post("/v1/assistant/voice/tool", json={"name": "oyuns_tasks_search", "arguments": "{not json", "call_id": "c2"}).json()
    assert json.loads(invalid["output"])["status"] == "invalid_input"
    ok = http.post("/v1/assistant/voice/tool", json={"name": "oyuns_tasks_search", "arguments": json.dumps({"query": "тайлан"}), "call_id": "c3"}).json()
    assert ok["call_id"] == "c3" and json.loads(ok["output"])["status"] == "ok"
    assert calls == [("oyuns_tasks_search", {"query": "тайлан"}, 11)] and db.commits == 1


def test_large_tool_output_is_bounded():
    output = voice_call.tool_output({"status": "ok", "summary": "big", "data": {"text": "x" * 50_000}})
    assert len(output) <= voice_call.MAX_TOOL_OUTPUT_CHARS + 200
    assert json.loads(output)["status"] == "ok"
