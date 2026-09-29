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


STT_TOKEN = "chimege-stt-token-0123456789"
TTS_TOKEN = "chimege-tts-token-9876543210"


def test_chimege_tokens_are_encrypted_switchable_and_fall_back_to_env(monkeypatch):
    monkeypatch.setenv("CHIMEGE_API_TOKEN", "env-stt-token-123")
    monkeypatch.delenv("CHIMEGE_TTS_API_TOKEN", raising=False)
    organization = SimpleNamespace(id=5, settings={})
    http, _ = client("admin", organization)
    before = http.get("/v1/settings/ai-agent").json()["chimege"]
    assert before["stt"]["source"] == "environment" and before["tts"]["source"] == "none" and not before["voice_call_ready"]

    body = http.put("/v1/settings/ai-agent", json={"chimege_stt_token": STT_TOKEN, "chimege_tts_token": TTS_TOKEN}).json()
    assert STT_TOKEN not in json.dumps(body) and TTS_TOKEN not in json.dumps(body)
    assert STT_TOKEN not in json.dumps(organization.settings) and TTS_TOKEN not in json.dumps(organization.settings)
    chimege = body["chimege"]
    assert chimege["stt"] == {"has_token": True, "token_last4": STT_TOKEN[-4:], "source": "organization", "enabled": True}
    assert chimege["voice_call_enabled"] and chimege["voice_call_ready"]
    runtime = ai_runtime.build_runtime(organization.settings)
    assert runtime.stt_token == STT_TOKEN and runtime.tts_token == TTS_TOKEN

    body = http.put("/v1/settings/ai-agent", json={"chimege_tts_enabled": False}).json()
    runtime = ai_runtime.build_runtime(organization.settings)
    assert runtime.tts_token == "" and runtime.chimege_tts_token == TTS_TOKEN
    assert not body["chimege"]["voice_call_ready"]

    http.put("/v1/settings/ai-agent", json={"clear_chimege_stt_token": True})
    assert ai_runtime.build_runtime(organization.settings).stt_token == "env-stt-token-123"
    assert http.put("/v1/settings/ai-agent", json={"chimege_stt_token": "bad token"}).status_code == 422


def test_chimege_test_synthesizes_then_recognizes(monkeypatch):
    calls = []

    async def synthesize(text, *, token=None, **_kwargs):
        calls.append(("tts", token))
        return b"RIFFwav", None

    async def recognize(audio, token):
        calls.append(("stt", token, audio))
        return "сайн байна уу", None

    monkeypatch.setattr(ai_settings.voice_service, "synthesize", synthesize)
    monkeypatch.setattr(ai_settings.voice_service, "transcribe_chimege", recognize)
    monkeypatch.delenv("CHIMEGE_API_TOKEN", raising=False)
    monkeypatch.delenv("CHIMEGE_TTS_API_TOKEN", raising=False)
    http, _ = client("admin", SimpleNamespace(id=5, settings={}))
    assert http.post("/v1/settings/ai-agent/chimege/test", json={}).json() == {"tts": {"ok": False, "error": "not_configured"}, "stt": {"ok": False, "error": "not_configured"}}
    body = http.post("/v1/settings/ai-agent/chimege/test", json={"stt_token": STT_TOKEN, "tts_token": TTS_TOKEN}).json()
    assert body["tts"]["ok"] and body["stt"]["ok"] and body["stt"]["transcript"] == "сайн байна уу"
    assert calls == [("tts", TTS_TOKEN), ("stt", STT_TOKEN, b"RIFFwav")]


ELEVEN_KEY = "sk_elevenlabs0123456789abcdef"


def test_elevenlabs_key_and_voice_call_engine_are_stored_and_switchable(monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    organization = SimpleNamespace(id=5, settings={})
    http, _ = client("admin", organization)
    before = http.get("/v1/settings/ai-agent").json()
    assert before["voice_call_provider"] == "auto" and before["elevenlabs"]["source"] == "none" and not before["elevenlabs"]["ready"]

    body = http.put("/v1/settings/ai-agent", json={"elevenlabs_api_key": ELEVEN_KEY, "voice_call_provider": "elevenlabs", "elevenlabs_voice_id": "JBFqnCBsd6RMkjVDRZzb", "elevenlabs_model": "eleven_turbo_v2_5"}).json()
    assert ELEVEN_KEY not in json.dumps(body) and ELEVEN_KEY not in json.dumps(organization.settings)
    assert body["voice_call_provider"] == "elevenlabs"
    assert body["elevenlabs"]["source"] == "organization" and body["elevenlabs"]["key_last4"] == ELEVEN_KEY[-4:] and body["elevenlabs"]["ready"]
    runtime = ai_runtime.build_runtime(organization.settings)
    assert runtime.elevenlabs_api_key == ELEVEN_KEY and runtime.elevenlabs_voice_id == "JBFqnCBsd6RMkjVDRZzb" and runtime.elevenlabs_model == "eleven_turbo_v2_5"

    assert not http.put("/v1/settings/ai-agent", json={"elevenlabs_enabled": False}).json()["elevenlabs"]["ready"]
    monkeypatch.setenv("ELEVENLABS_API_KEY", "env-eleven-key-123456")
    http.put("/v1/settings/ai-agent", json={"clear_elevenlabs_api_key": True})
    assert ai_runtime.build_runtime(organization.settings).elevenlabs_api_key == "env-eleven-key-123456"
    for bad in ({"voice_call_provider": "siri"}, {"elevenlabs_model": "eleven_v3"}, {"elevenlabs_voice_id": "../x"}, {"elevenlabs_api_key": "short"}):
        assert http.put("/v1/settings/ai-agent", json=bad).status_code == 422


def test_elevenlabs_test_checks_voices_and_streaming_token(monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    calls = []

    async def voices(key):
        calls.append(("voices", key))
        return [{"voice_id": "a", "name": "Sarah"}]

    async def token(key):
        calls.append(("token", key))
        return "sutkn_1"

    monkeypatch.setattr(ai_settings.elevenlabs_service, "list_voices", voices)
    monkeypatch.setattr(ai_settings.elevenlabs_service, "create_tts_token", token)
    http, _ = client("admin", SimpleNamespace(id=5, settings={}))
    assert http.post("/v1/settings/ai-agent/elevenlabs/test", json={}).json()["error"] == "not_configured"
    body = http.post("/v1/settings/ai-agent/elevenlabs/test", json={"api_key": ELEVEN_KEY}).json()
    assert body["ok"] and body["voices"] == 1 and calls == [("voices", ELEVEN_KEY), ("token", ELEVEN_KEY)]
    assert http.get("/v1/settings/ai-agent/elevenlabs/voices").json() == {"voices": [], "error": "not_configured"}
