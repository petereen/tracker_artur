"""Admin AI settings: key storage, precedence, and the connection test."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.database import get_db
from app.core.enterprise_deps import build_actor_context, get_actor
from app.routers import ai_settings
from app.services.ai_gateway import runtime as ai_runtime

KEY = "sk-proj-organizationkey0123456789abcd"


class FakeDb:
    def __init__(self, organization):
        self.organization = organization
        self.commits = 0

    async def get(self, _model, _key, **_kwargs):
        return self.organization

    async def commit(self):
        self.commits += 1


def client(role: str, organization) -> tuple[TestClient, FakeDb]:
    db = FakeDb(organization)
    app = FastAPI()
    app.include_router(ai_settings.router, prefix="/v1/settings/ai-agent")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_actor] = lambda: build_actor_context(account_id=1, organization_id=5, employee_id=None, email="a@example.test", locale="mn", roles=frozenset({role}))
    return TestClient(app), db


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    async def record_change(*_args, **_kwargs):
        return SimpleNamespace(id=1)

    monkeypatch.setattr(ai_settings, "record_change", record_change)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-env-fallbackkey0123456789abcdef")
    ai_runtime._cache.clear()
    yield
    ai_runtime._cache.clear()


def test_non_admin_cannot_read_or_change_ai_settings():
    http, _ = client("manager", SimpleNamespace(id=5, settings={}))
    assert http.get("/v1/settings/ai-agent").status_code == 403
    assert http.put("/v1/settings/ai-agent", json={"primary_model": "gpt-5-mini"}).status_code == 403


def test_key_is_stored_encrypted_and_never_returned():
    organization = SimpleNamespace(id=5, settings={})
    http, db = client("admin", organization)
    response = http.put("/v1/settings/ai-agent", json={"api_key": KEY, "primary_model": "gpt-5-mini", "fallback_model": "", "max_output_tokens": 3000})
    assert response.status_code == 200
    body = response.json()
    assert KEY not in json.dumps(body)
    assert body["has_key"] and body["key_last4"] == KEY[-4:] and body["key_source"] == "organization"
    assert body["primary_model"] == "gpt-5-mini" and body["fallback_model"] is None
    stored = organization.settings["ai_agent"]
    assert stored["api_key_enc"] != KEY and KEY not in json.dumps(stored)
    assert db.commits == 1
    assert KEY not in json.dumps(http.get("/v1/settings/ai-agent").json())


def test_organization_key_wins_over_env_and_clearing_falls_back():
    organization = SimpleNamespace(id=5, settings={})
    http, _ = client("admin", organization)
    http.put("/v1/settings/ai-agent", json={"api_key": KEY})
    assert ai_runtime.build_runtime(organization.settings).api_key == KEY
    http.put("/v1/settings/ai-agent", json={"clear_api_key": True})
    runtime = ai_runtime.build_runtime(organization.settings)
    assert runtime.api_key == settings.OPENAI_API_KEY and runtime.source == "environment"


def test_saving_invalidates_the_runtime_cache():
    organization = SimpleNamespace(id=5, settings={})
    http, db = client("admin", organization)
    asyncio.run(ai_runtime.resolve_ai_runtime(db, 5))
    assert 5 in ai_runtime._cache
    http.put("/v1/settings/ai-agent", json={"reasoning_effort": "medium"})
    assert 5 not in ai_runtime._cache


def test_invalid_model_ids_and_keys_are_rejected():
    http, _ = client("admin", SimpleNamespace(id=5, settings={}))
    assert http.put("/v1/settings/ai-agent", json={"primary_model": "gpt 5; drop"}).status_code == 422
    assert http.put("/v1/settings/ai-agent", json={"api_key": "short"}).status_code == 422


def test_connection_test_maps_a_rejected_key(monkeypatch):
    async def list_models(_key):
        return None, 401, "invalid"

    monkeypatch.setattr(ai_settings, "_list_models", list_models)
    http, _ = client("admin", SimpleNamespace(id=5, settings={}))
    body = http.post("/v1/settings/ai-agent/test", json={"api_key": KEY, "model": "gpt-5-mini"}).json()
    assert body == {"ok": False, "error": "invalid_key", "latency_ms": body["latency_ms"], "model": "gpt-5-mini"}


def test_model_list_is_filtered_to_chat_models(monkeypatch):
    class Response:
        status = 200

        async def json(self):
            return {"data": [{"id": "gpt-5-mini"}, {"id": "text-embedding-3-small"}, {"id": "gpt-4o-mini-transcribe"}, {"id": "o4-mini"}, {"id": "dall-e-3"}]}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

    class Session:
        def __init__(self, **_):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        def get(self, *_args, **_kwargs):
            return Response()

    monkeypatch.setattr(ai_settings.aiohttp, "ClientSession", Session)
    models, status, _ = asyncio.run(ai_settings._list_models(KEY))
    assert status == 200 and models == ["gpt-5-mini", "o4-mini"]
