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
from app.services.ai_gateway.access_policy import FULL_ACCESS
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
    transcription = config["session"]["audio"]["input"]["transcription"]
    assert transcription["model"] == voice_call.TRANSCRIPTION_MODEL and "Mongolian" in transcription["prompt"]
    assert "Language (strict)" in voice_call.VOICE_SYSTEM
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
        return SimpleNamespace(api_key="sk-test-key", realtime_enabled=True, realtime_model="gpt-realtime", realtime_voice="marin", access=FULL_ACCESS, chimege_voice_call_ready=False)

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
    # No language from the client: the account locale ("mn") opens the call.
    assert body["language"] == "mn" and "Khalkha Mongolian" in body["greeting"]
    assert "{call_language" not in captured["instructions"]


def test_session_opens_in_the_interface_language(client, monkeypatch):
    http, _ = client
    captured = {}

    async def resolve(_db, _organization_id):
        return SimpleNamespace(api_key="sk-test-key", realtime_enabled=True, realtime_model="gpt-realtime", realtime_voice="marin", access=FULL_ACCESS, chimege_voice_call_ready=False)

    async def build_context(_db, actor, *, sensitive_allowed):
        return {"reply_language": actor.detected_language}

    async def mint(runtime, instructions, tools):
        captured["instructions"] = instructions
        return {"value": "ek_secret", "expires_at": 123}

    monkeypatch.setattr(assistant_voice, "resolve_ai_runtime", resolve)
    monkeypatch.setattr(assistant_voice.gateway, "_build_context", build_context)
    monkeypatch.setattr(voice_call, "create_client_secret", mint)
    body = http.post("/v1/assistant/voice/session", json={"language": "ru"}).json()
    assert body["language"] == "ru" and "Russian" in body["greeting"] and "Здравствуйте" in body["greeting"]
    assert "The call language is Russian" in captured["instructions"] and '"reply_language": "ru"' in captured["instructions"]
    assert http.post("/v1/assistant/voice/session", json={"language": "en-US"}).json()["language"] == "en"
    assert http.post("/v1/assistant/voice/session", json={"language": "es"}).json()["language"] == "mn"


def test_call_language_falls_back_to_locale_then_mongolian():
    assert voice_call.call_language(None, "ru") == "ru"
    assert voice_call.call_language("en", "ru") == "en"
    assert voice_call.call_language("fr", "de") == "mn"


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


def chimege_runtime(**overrides):
    values = dict(
        api_key="sk-test-key", realtime_enabled=True, realtime_model="gpt-realtime", realtime_voice="marin", access=FULL_ACCESS,
        chimege_voice_call_ready=True, tts_token="tts-token", voice_call_provider="auto", elevenlabs_ready=False,
        elevenlabs_api_key="", elevenlabs_voice_id="voice123abc", elevenlabs_model="eleven_flash_v2_5",
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def test_mongolian_calls_use_chimege_and_other_languages_realtime(client, monkeypatch):
    http, db = client
    minted = []

    async def resolve(_db, _organization_id):
        return chimege_runtime()

    async def mint(runtime, instructions, tools):
        minted.append(instructions)
        return {"value": "ek_secret", "expires_at": 123}

    monkeypatch.setattr(assistant_voice, "resolve_ai_runtime", resolve)
    monkeypatch.setattr(voice_call, "create_client_secret", mint)
    body = http.post("/v1/assistant/voice/session", json={"language": "mn"}).json()
    assert body["mode"] == "chimege" and body["provider"] == "chimege" and body["greeting_text"] == voice_call.CHIMEGE_GREETING
    assert "client_secret" not in body and not minted
    assert voice_call.chimege_call(body["session_id"], 11) is not None
    assert voice_call.chimege_call(body["session_id"], 99) is None
    assert http.post("/v1/assistant/voice/session", json={"language": "ru"}).json()["mode"] == "realtime" and minted


def test_mongolian_call_falls_back_to_realtime_when_chimege_is_not_ready(client, monkeypatch):
    http, _ = client

    async def resolve(_db, _organization_id):
        return chimege_runtime(chimege_voice_call_ready=False)

    async def mint(runtime, instructions, tools):
        return {"value": "ek_secret", "expires_at": 123}

    monkeypatch.setattr(assistant_voice, "resolve_ai_runtime", resolve)
    monkeypatch.setattr(voice_call, "create_client_secret", mint)
    assert http.post("/v1/assistant/voice/session", json={"language": "mn"}).json()["mode"] == "realtime"


def test_chimege_turn_runs_a_read_only_agent_turn_and_keeps_history(client, monkeypatch):
    http, db = client
    turns = []

    async def transcribe(audio, filename="voice.ogg", *, organization_id=None, content_type="audio/ogg"):
        assert content_type == "audio/wav" and organization_id == 1
        return ("Миний даалгавар юу байна?" if audio == b"speech" else None), None

    async def execute_turn(_db, actor, history, *, memory=None, input_mode="text", **_kwargs):
        turns.append((actor.detected_language, list(history), list(memory or []), input_mode))
        return SimpleNamespace(answer="Танд хоёр даалгавар байна.", memory=[{"tool": "oyuns_tasks_search", "items": [{"title": "Тайлан"}]}])

    async def resolve(_db, _organization_id):
        return chimege_runtime()

    async def synthesize(text, *, token=None, **_kwargs):
        return (b"RIFF" + text.encode(), None) if token == "tts-token" else (None, "no token")

    monkeypatch.setattr(assistant_voice.voice_service, "transcribe", transcribe)
    monkeypatch.setattr(assistant_voice.voice_service, "synthesize", synthesize)
    monkeypatch.setattr(assistant_voice.gateway, "execute_turn", execute_turn)
    monkeypatch.setattr(assistant_voice, "resolve_ai_runtime", resolve)
    session_id = voice_call.open_chimege_call(11)

    first = http.post("/v1/assistant/voice/chimege/turn", data={"session_id": session_id}, files={"file": ("speech.wav", b"speech", "audio/wav")}).json()
    assert first == {"transcript": "Миний даалгавар юу байна?", "answer": "Танд хоёр даалгавар байна.", "error": None, "language": "mn"}
    http.post("/v1/assistant/voice/chimege/turn", data={"session_id": session_id}, files={"file": ("speech.wav", b"speech", "audio/wav")})
    assert turns[0] == ("mn", [{"role": "user", "content": "Миний даалгавар юу байна?"}], [], "voice_call")
    assert len(turns[1][1]) == 3 and turns[1][2][0]["tool"] == "oyuns_tasks_search"

    silent = http.post("/v1/assistant/voice/chimege/turn", data={"session_id": session_id}, files={"file": ("speech.wav", b"noise", "audio/wav")}).json()
    assert silent["transcript"] == "" and silent["error"] == "not_understood" and len(turns) == 2

    speech = http.post("/v1/assistant/voice/chimege/speech", json={"session_id": session_id, "text": "Сайн байна уу"})
    assert speech.status_code == 200 and speech.headers["content-type"] == "audio/wav"
    assert http.post("/v1/assistant/voice/chimege/speech", json={"session_id": "unknown", "text": "x"}).status_code == 404
    assert http.post("/v1/assistant/voice/chimege/turn", data={"session_id": "unknown"}, files={"file": ("speech.wav", b"speech", "audio/wav")}).status_code == 404


def test_chimege_calls_expire_when_idle():
    session_id = voice_call.open_chimege_call(7, now=0.0)
    assert voice_call.chimege_call(session_id, 7, now=10.0) is not None
    assert voice_call.chimege_call(session_id, 7, now=10.0 + voice_call.CHIMEGE_CALL_IDLE_SECONDS) is None


def test_voice_call_turns_offer_only_read_only_tools():
    from app.services.ai_gateway import GatewayRequest

    def names(read_only):
        request = GatewayRequest(text="x", history=[], channel="web", actor_context=member(), runtime=build_runtime(None), read_only=read_only)
        return assistant_voice.gateway._tool_catalog(request)[1]

    assert "oyuns_tasks_prepare_create" in names(False)
    assert "oyuns_tasks_prepare_create" not in names(True) and "oyuns_tasks_search" in names(True)


def test_provider_resolution_honours_caller_then_admin_then_language():
    both = chimege_runtime(elevenlabs_ready=True, elevenlabs_api_key="xi-key")
    assert voice_call.available_providers(both) == ["openai", "chimege", "elevenlabs"]
    assert voice_call.resolve_provider(both, "mn") == "chimege"
    assert voice_call.resolve_provider(both, "ru") == "openai"
    assert voice_call.resolve_provider(both, "ru", "elevenlabs") == "elevenlabs"
    admin_pick = chimege_runtime(elevenlabs_ready=True, elevenlabs_api_key="xi-key", voice_call_provider="elevenlabs")
    assert voice_call.resolve_provider(admin_pick, "mn") == "elevenlabs"
    assert voice_call.resolve_provider(admin_pick, "mn", "openai") == "openai"
    # A pick that is not ready falls back to the automatic choice.
    assert voice_call.resolve_provider(chimege_runtime(voice_call_provider="elevenlabs"), "mn", "elevenlabs") == "chimege"
    assert voice_call.resolve_provider(chimege_runtime(chimege_voice_call_ready=False), "mn", "chimege") == "openai"


def elevenlabs_client(monkeypatch, http):
    minted = []

    async def resolve(_db, _organization_id):
        return chimege_runtime(elevenlabs_ready=True, elevenlabs_api_key="xi-key", voice_call_provider="elevenlabs")

    async def create_token(key):
        minted.append(key)
        return f"sutkn_{len(minted)}"

    monkeypatch.setattr(assistant_voice, "resolve_ai_runtime", resolve)
    monkeypatch.setattr(assistant_voice.elevenlabs_service, "create_tts_token", create_token)
    return minted


def test_elevenlabs_session_returns_a_single_use_stream_url_without_the_key(client, monkeypatch):
    http, db = client
    minted = elevenlabs_client(monkeypatch, http)
    body = http.post("/v1/assistant/voice/session", json={"language": "ru"}).json()
    assert body["mode"] == "elevenlabs" and body["language"] == "ru" and body["providers"] == ["openai", "chimege", "elevenlabs"]
    assert body["greeting_text"] == voice_call.TURN_GREETINGS["ru"] and body["sample_rate"] == 24_000
    url = body["speech_url"]
    assert url.startswith("wss://api.elevenlabs.io/v1/text-to-speech/voice123abc/stream-input?")
    assert "single_use_token=sutkn_1" in url and "model_id=eleven_flash_v2_5" in url and "output_format=pcm_24000" in url
    assert "xi-key" not in json.dumps(body) and minted == ["xi-key"] and db.commits == 1
    # The caller can still pick another engine for this call.
    assert http.post("/v1/assistant/voice/session", json={"language": "ru", "provider": "chimege"}).json()["language"] == "mn"

    stream = http.post("/v1/assistant/voice/elevenlabs/stream", json={"session_id": body["session_id"]}).json()
    assert "single_use_token=sutkn_2" in stream["speech_url"]
    assert http.post("/v1/assistant/voice/elevenlabs/stream", json={"session_id": "unknown"}).status_code == 404


def test_elevenlabs_session_falls_back_when_the_key_is_rejected(client, monkeypatch):
    http, _ = client
    elevenlabs_client(monkeypatch, http)

    async def create_token(_key):
        raise assistant_voice.elevenlabs_service.ElevenLabsError("invalid_key")

    async def mint(runtime, instructions, tools):
        return {"value": "ek_secret", "expires_at": 123}

    monkeypatch.setattr(assistant_voice.elevenlabs_service, "create_tts_token", create_token)
    monkeypatch.setattr(voice_call, "create_client_secret", mint)
    body = http.post("/v1/assistant/voice/session", json={"language": "en"}).json()
    assert body["mode"] == "realtime" and body["provider"] == "openai" and body["notice"] == "elevenlabs_invalid_key"
    mongolian = http.post("/v1/assistant/voice/session", json={"language": "mn"}).json()
    assert mongolian["mode"] == "chimege" and mongolian["notice"] == "elevenlabs_invalid_key"


def test_elevenlabs_turn_uses_scribe_language_and_returns_a_stream(client, monkeypatch):
    http, _ = client
    elevenlabs_client(monkeypatch, http)
    turns = []

    async def scribe(audio, key, *, fallback_language, content_type="audio/wav"):
        assert key == "xi-key" and fallback_language == "mn"
        return ("Сколько у меня задач?", "ru", None) if audio == b"speech" else (None, None, "network")

    async def fallback(audio, filename="voice.ogg", *, organization_id=None, content_type="audio/ogg"):
        return "Миний даалгавар", None

    async def execute_turn(_db, actor, history, *, memory=None, input_mode="text", **_kwargs):
        turns.append((actor.detected_language, history[-1]["content"], input_mode))
        return SimpleNamespace(answer="У вас две задачи.", memory=[])

    monkeypatch.setattr(assistant_voice.elevenlabs_service, "transcribe", scribe)
    monkeypatch.setattr(assistant_voice.voice_service, "transcribe", fallback)
    monkeypatch.setattr(assistant_voice.gateway, "execute_turn", execute_turn)
    session_id = voice_call.open_turn_call(11, provider="elevenlabs", language="mn")

    body = http.post("/v1/assistant/voice/turn", data={"session_id": session_id}, files={"file": ("speech.wav", b"speech", "audio/wav")}).json()
    assert body["answer"] == "У вас две задачи." and body["language"] == "ru" and "single_use_token=" in body["speech_url"]
    assert turns[-1] == ("ru", "Сколько у меня задач?", "voice_call")
    # Scribe failing falls back to the Chimege/OpenAI transcription in the call language.
    body = http.post("/v1/assistant/voice/turn", data={"session_id": session_id}, files={"file": ("speech.wav", b"other", "audio/wav")}).json()
    assert body["transcript"] == "Миний даалгавар" and turns[-1][0] == "mn"
    # Chimege calls keep the old path and never mint ElevenLabs tokens.
    chimege_id = voice_call.open_chimege_call(11)
    body = http.post("/v1/assistant/voice/chimege/turn", data={"session_id": chimege_id}, files={"file": ("speech.wav", b"speech", "audio/wav")}).json()
    assert "speech_url" not in body
    assert http.post("/v1/assistant/voice/elevenlabs/stream", json={"session_id": chimege_id}).status_code == 404


def test_elevenlabs_speech_tokens_are_capped_per_call(client, monkeypatch):
    http, _ = client
    elevenlabs_client(monkeypatch, http)
    session_id = voice_call.open_turn_call(11, provider="elevenlabs", language="en")
    voice_call.turn_call(session_id, 11).speech_tokens = voice_call.MAX_SPEECH_TOKENS_PER_CALL
    response = http.post("/v1/assistant/voice/elevenlabs/stream", json={"session_id": session_id})
    assert response.status_code == 429 and response.json()["detail"] == "elevenlabs_rate_limited"


def test_scribe_retries_pinned_to_the_call_language_on_a_foreign_detection(monkeypatch):
    import asyncio

    from app.services import elevenlabs_service

    calls = []

    async def post(audio, key, language_code, content_type):
        calls.append(language_code)
        return 200, ({"text": "Сайн байна уу", "language_code": "kaz"} if language_code is None else {"text": "Сайн байна уу", "language_code": "mon"})

    monkeypatch.setattr(elevenlabs_service, "_post_stt", post)
    assert asyncio.run(elevenlabs_service.transcribe(b"x", "k", fallback_language="mn")) == ("Сайн байна уу", "mn", None)
    assert calls == [None, "mn"]

    async def rejected(*_args):
        return 401, "bad key"

    monkeypatch.setattr(elevenlabs_service, "_post_stt", rejected)
    assert asyncio.run(elevenlabs_service.transcribe(b"x", "k", fallback_language="en")) == (None, None, "invalid_key")
