"""Admin settings for the OYUNS AI agent: OpenAI key and model selection.

The key is stored encrypted in ``organization.settings["ai_agent"]`` and is
never returned; responses expose only whether a key exists, its last four
characters, and where the active key comes from (organization or env).
"""
from __future__ import annotations

import hashlib
import re
import time
from datetime import datetime, timezone
from typing import Literal

import aiohttp
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.enterprise_deps import ActorContext, require_roles
from app.models.models import Organization
from app.services import elevenlabs_service, voice_service
from app.services.ai_gateway import access_policy
from app.services.ai_gateway import runtime as ai_runtime
from app.services.enterprise_events import record_change
from app.services.secret_box import encrypt_secret

router = APIRouter()
require_admin = require_roles("admin")

MODELS_URL = "https://api.openai.com/v1/models"
RESPONSES_URL = "https://api.openai.com/v1/responses"
MODEL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,99}$")
CHAT_MODEL_RE = re.compile(r"^(?:gpt-|o\d|chatgpt-)")
REALTIME_MODEL_RE = re.compile(r"^gpt-(?:[\w.-]*-)?realtime")
EXCLUDED_MODEL_RE = re.compile(r"(?:audio|realtime|transcribe|tts|image|embedding|moderation|search|whisper|dall-e)", re.I)
ELEVENLABS_VOICE_ID_RE = re.compile(r"^[A-Za-z0-9]{8,64}$")
MODELS_CACHE_SECONDS = 600
_models_cache: dict[str, tuple[float, list[str]]] = {}


def _model_id(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return ""
    if not MODEL_ID_RE.match(value):
        raise ValueError("Invalid model ID")
    return value


class AiAgentSettingsInput(BaseModel):
    api_key: str | None = Field(default=None, max_length=400, description="A new OpenAI key; null keeps the stored key.")
    clear_api_key: bool = False
    primary_model: str | None = Field(default=None, max_length=100)
    fallback_model: str | None = Field(default=None, max_length=100, description="Empty string disables the fallback model.")
    reasoning_effort: Literal["none", "low", "medium", "high"] | None = None
    max_output_tokens: int | None = Field(default=None, ge=ai_runtime.MIN_OUTPUT_TOKENS, le=ai_runtime.MAX_OUTPUT_TOKENS)
    web_search_enabled: bool | None = None
    realtime_model: str | None = Field(default=None, max_length=100, description="Realtime model for OYUNS voice calls; empty resets to the default.")
    realtime_voice: Literal[ai_runtime.REALTIME_VOICES] | None = None  # type: ignore[valid-type]
    realtime_enabled: bool | None = None
    chimege_stt_token: str | None = Field(default=None, max_length=400, description="A new Chimege STT token; null keeps the stored one.")
    chimege_tts_token: str | None = Field(default=None, max_length=400, description="A new Chimege TTS token; null keeps the stored one.")
    clear_chimege_stt_token: bool = False
    clear_chimege_tts_token: bool = False
    chimege_stt_enabled: bool | None = None
    chimege_tts_enabled: bool | None = None
    chimege_voice_call_enabled: bool | None = None
    voice_call_provider: Literal[ai_runtime.VOICE_CALL_PROVIDERS] | None = None  # type: ignore[valid-type]
    elevenlabs_api_key: str | None = Field(default=None, max_length=400, description="A new ElevenLabs key; null keeps the stored one.")
    clear_elevenlabs_api_key: bool = False
    elevenlabs_enabled: bool | None = None
    elevenlabs_voice_id: str | None = Field(default=None, max_length=64)
    elevenlabs_model: Literal[ai_runtime.ELEVENLABS_MODELS] | None = None  # type: ignore[valid-type]

    @field_validator("elevenlabs_api_key")
    @classmethod
    def validate_elevenlabs_key(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        value = value.strip()
        if len(value) < 16 or any(char.isspace() for char in value):
            raise ValueError("The ElevenLabs API key looks invalid")
        return value

    @field_validator("elevenlabs_voice_id")
    @classmethod
    def validate_voice_id(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        value = value.strip()
        if not ELEVENLABS_VOICE_ID_RE.match(value):
            raise ValueError("Invalid ElevenLabs voice ID")
        return value

    @field_validator("chimege_stt_token", "chimege_tts_token")
    @classmethod
    def validate_chimege_token(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        value = value.strip()
        if len(value) < 8 or any(char.isspace() for char in value):
            raise ValueError("The Chimege token looks invalid")
        return value

    @field_validator("realtime_model")
    @classmethod
    def validate_realtime_model(cls, value: str | None) -> str | None:
        value = _model_id(value)
        if value and "realtime" not in value:
            raise ValueError("Choose a realtime model (for example gpt-realtime)")
        return value

    @field_validator("api_key")
    @classmethod
    def validate_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        if len(value) < 20 or any(char.isspace() for char in value):
            raise ValueError("The API key looks invalid")
        return value

    @field_validator("primary_model", "fallback_model")
    @classmethod
    def validate_model(cls, value: str | None) -> str | None:
        return _model_id(value)


class AccessEntry(BaseModel):
    read: bool
    write: bool = False


class AiAccessInput(BaseModel):
    sections: dict[str, AccessEntry]

    @field_validator("sections")
    @classmethod
    def validate_sections(cls, value: dict[str, AccessEntry]) -> dict[str, AccessEntry]:
        known = {section.key for section in access_policy.SECTIONS}
        unknown = sorted(set(value) - known)
        if unknown:
            raise ValueError(f"Unknown sections: {', '.join(unknown)}")
        return value


class ChimegeTestInput(BaseModel):
    stt_token: str | None = Field(default=None, max_length=400)
    tts_token: str | None = Field(default=None, max_length=400)


class ElevenLabsTestInput(BaseModel):
    api_key: str | None = Field(default=None, max_length=400)


class AiAgentTestInput(BaseModel):
    api_key: str | None = Field(default=None, max_length=400)
    model: str | None = Field(default=None, max_length=100)

    @field_validator("model")
    @classmethod
    def validate_model(cls, value: str | None) -> str | None:
        return _model_id(value) or None


def _settings_out(organization: Organization) -> dict:
    stored = ai_runtime.stored_config(organization.settings)
    active = ai_runtime.build_runtime(organization.settings)
    primary, fallback = ai_runtime.default_models()
    return {
        "has_key": bool(stored.get("api_key_enc")),
        "key_last4": stored.get("api_key_last4"),
        "key_source": active.source,
        "env_key_available": bool(settings.OPENAI_API_KEY.strip()),
        "primary_model": active.primary_model,
        "fallback_model": active.fallback_model,
        "reasoning_effort": active.reasoning_effort,
        "max_output_tokens": active.max_output_tokens,
        "web_search_enabled": active.web_search_enabled,
        "realtime_model": active.realtime_model,
        "realtime_voice": active.realtime_voice,
        "realtime_enabled": active.realtime_enabled,
        "realtime_voices": list(ai_runtime.REALTIME_VOICES),
        "chimege": {
            "stt": {"has_token": bool(stored.get("chimege_stt_token_enc")), "token_last4": stored.get("chimege_stt_token_last4"), "source": active.chimege_stt_source, "enabled": active.chimege_stt_enabled},
            "tts": {"has_token": bool(stored.get("chimege_tts_token_enc")), "token_last4": stored.get("chimege_tts_token_last4"), "source": active.chimege_tts_source, "enabled": active.chimege_tts_enabled},
            "voice_call_enabled": active.chimege_voice_call_enabled,
            "voice_call_ready": active.chimege_voice_call_ready,
        },
        "voice_call_provider": active.voice_call_provider,
        "voice_call_providers": list(ai_runtime.VOICE_CALL_PROVIDERS),
        "elevenlabs": {
            "has_key": bool(stored.get(ai_runtime.ELEVENLABS_KEY_FIELD)),
            "key_last4": stored.get("elevenlabs_api_key_last4"),
            "source": active.elevenlabs_source,
            "enabled": active.elevenlabs_enabled,
            "ready": active.elevenlabs_ready,
            "voice_id": active.elevenlabs_voice_id,
            "model": active.elevenlabs_model,
            "models": list(ai_runtime.ELEVENLABS_MODELS),
            "default_voice_id": ai_runtime.DEFAULT_ELEVENLABS_VOICE,
        },
        "defaults": {"primary_model": primary, "fallback_model": fallback, "reasoning_effort": "low", "max_output_tokens": ai_runtime.DEFAULT_OUTPUT_TOKENS, "realtime_model": ai_runtime.DEFAULT_REALTIME_MODEL, "realtime_voice": ai_runtime.DEFAULT_REALTIME_VOICE},
        "limits": {"min_output_tokens": ai_runtime.MIN_OUTPUT_TOKENS, "max_output_tokens": ai_runtime.MAX_OUTPUT_TOKENS},
        "updated_at": stored.get("updated_at"),
    }


@router.get("")
async def get_ai_agent_settings(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_admin)):
    organization = await db.get(Organization, actor.organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return _settings_out(organization)


@router.put("")
async def update_ai_agent_settings(data: AiAgentSettingsInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_admin)):
    organization = await db.get(Organization, actor.organization_id, with_for_update=True)
    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    stored = ai_runtime.stored_config(organization.settings)
    changes: dict = {}
    if data.clear_api_key:
        for key in ("api_key_enc", "api_key_last4"):
            stored.pop(key, None)
        changes["api_key"] = "cleared"
    elif data.api_key:
        stored["api_key_enc"] = encrypt_secret(data.api_key)
        stored["api_key_last4"] = data.api_key[-4:]
        changes["api_key"] = f"replaced (…{data.api_key[-4:]})"
    for kind in ("stt", "tts"):
        field = ai_runtime.CHIMEGE_TOKENS[kind][0]
        last4 = f"chimege_{kind}_token_last4"
        token = getattr(data, f"chimege_{kind}_token")
        if getattr(data, f"clear_chimege_{kind}_token"):
            stored.pop(field, None)
            stored.pop(last4, None)
            changes[f"chimege_{kind}_token"] = "cleared"
        elif token:
            stored[field] = encrypt_secret(token)
            stored[last4] = token[-4:]
            changes[f"chimege_{kind}_token"] = f"replaced (…{token[-4:]})"
    if data.clear_elevenlabs_api_key:
        stored.pop(ai_runtime.ELEVENLABS_KEY_FIELD, None)
        stored.pop("elevenlabs_api_key_last4", None)
        changes["elevenlabs_api_key"] = "cleared"
    elif data.elevenlabs_api_key:
        stored[ai_runtime.ELEVENLABS_KEY_FIELD] = encrypt_secret(data.elevenlabs_api_key)
        stored["elevenlabs_api_key_last4"] = data.elevenlabs_api_key[-4:]
        changes["elevenlabs_api_key"] = f"replaced (…{data.elevenlabs_api_key[-4:]})"
    for field in (
        "primary_model", "fallback_model", "reasoning_effort", "max_output_tokens", "web_search_enabled", "realtime_model", "realtime_voice",
        "realtime_enabled", "chimege_stt_enabled", "chimege_tts_enabled", "chimege_voice_call_enabled", "voice_call_provider",
        "elevenlabs_enabled", "elevenlabs_voice_id", "elevenlabs_model",
    ):
        value = getattr(data, field)
        if value is None or (field == "primary_model" and value == ""):
            continue
        if stored.get(field) != value:
            changes[field] = value
        stored[field] = value
    stored["updated_at"] = datetime.now(timezone.utc).isoformat()
    stored["updated_by_account_id"] = actor.account_id
    organization.settings = {**(organization.settings or {}), ai_runtime.AI_AGENT_SETTINGS_KEY: stored}
    await record_change(db, actor=actor, topic="settings", aggregate_type="ai_agent_settings", aggregate_id=organization.id, operation="updated", after=changes)
    await db.commit()
    ai_runtime.invalidate(organization.id)
    _models_cache.clear()
    return _settings_out(organization)


def _access_out(organization: Organization) -> dict:
    stored = ai_runtime.stored_config(organization.settings)
    return {
        "groups": access_policy.catalog(),
        "sections": access_policy.normalize(stored.get(access_policy.ACCESS_KEY)),
        "configured": isinstance(stored.get(access_policy.ACCESS_KEY), dict),
        "updated_at": stored.get("access_updated_at"),
    }


@router.get("/access")
async def get_ai_access(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_admin)):
    organization = await db.get(Organization, actor.organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return _access_out(organization)


@router.put("/access")
async def update_ai_access(data: AiAccessInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_admin)):
    """Replace which data sections the AI assistant may read or prepare changes in."""
    organization = await db.get(Organization, actor.organization_id, with_for_update=True)
    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    stored = ai_runtime.stored_config(organization.settings)
    before = access_policy.normalize(stored.get(access_policy.ACCESS_KEY))
    after = access_policy.normalize({key: entry.model_dump() for key, entry in data.sections.items()})
    stored[access_policy.ACCESS_KEY] = after
    stored["access_updated_at"] = datetime.now(timezone.utc).isoformat()
    stored["access_updated_by_account_id"] = actor.account_id
    organization.settings = {**(organization.settings or {}), ai_runtime.AI_AGENT_SETTINGS_KEY: stored}
    changes = {key: value for key, value in after.items() if before.get(key) != value}
    await record_change(db, actor=actor, topic="settings", aggregate_type="ai_agent_access", aggregate_id=organization.id, operation="updated", before={key: before[key] for key in changes}, after=changes)
    await db.commit()
    ai_runtime.invalidate(organization.id)
    return _access_out(organization)


async def _active_key(db: AsyncSession, actor: ActorContext, explicit: str | None) -> str:
    if explicit and explicit.strip():
        return explicit.strip()
    ai_runtime.invalidate(actor.organization_id)
    return (await ai_runtime.resolve_ai_runtime(db, actor.organization_id)).api_key


def _error_kind(status: int) -> str:
    return {401: "invalid_key", 403: "forbidden", 404: "model_not_found", 429: "rate_limited"}.get(status, "provider_error" if status >= 500 else "rejected")


async def _fetch_model_ids(key: str) -> tuple[list[str] | None, int, str]:
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
        async with session.get(MODELS_URL, headers={"Authorization": f"Bearer {key}"}) as response:
            if response.status != 200:
                return None, response.status, (await response.text())[:300]
            body = await response.json()
    return sorted(
        {str(item.get("id")) for item in body.get("data", []) if isinstance(item, dict) and item.get("id")},
    ), 200, ""


def _realtime_models(ids: list[str]) -> list[str]:
    return [item for item in ids if REALTIME_MODEL_RE.match(item) and not re.search(r"(?:transcribe|tts)", item)]


async def _list_models(key: str) -> tuple[list[str] | None, int, str]:
    ids, status, detail = await _fetch_model_ids(key)
    if ids is None:
        return None, status, detail
    return [item for item in ids if CHAT_MODEL_RE.match(item) and not EXCLUDED_MODEL_RE.search(item)], 200, ""


@router.get("/models")
async def list_ai_models(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_admin)):
    key = await _active_key(db, actor, None)
    if not key:
        return {"models": [], "error": "not_configured"}
    cache_key = hashlib.sha256(key.encode()).hexdigest()
    cached = _models_cache.get(cache_key)
    if cached and cached[0] > time.monotonic():
        return {"models": [item for item in cached[1] if CHAT_MODEL_RE.match(item) and not EXCLUDED_MODEL_RE.search(item)], "realtime_models": _realtime_models(cached[1]), "error": None}
    try:
        ids, status, _ = await _fetch_model_ids(key)
    except (aiohttp.ClientError, TimeoutError):
        return {"models": [], "realtime_models": [], "error": "network"}
    if ids is None:
        return {"models": [], "realtime_models": [], "error": _error_kind(status)}
    _models_cache[cache_key] = (time.monotonic() + MODELS_CACHE_SECONDS, ids)
    return {"models": [item for item in ids if CHAT_MODEL_RE.match(item) and not EXCLUDED_MODEL_RE.search(item)], "realtime_models": _realtime_models(ids), "error": None}


@router.post("/test")
async def test_ai_agent_settings(data: AiAgentTestInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_admin)):
    """Check a key (new or stored) and that the chosen model answers."""
    key = await _active_key(db, actor, data.api_key)
    if not key:
        return {"ok": False, "error": "not_configured", "latency_ms": None, "model": data.model}
    runtime = await ai_runtime.resolve_ai_runtime(db, actor.organization_id)
    model = data.model or runtime.primary_model
    started = time.monotonic()
    try:
        models, status, _ = await _list_models(key)
        if models is None:
            return {"ok": False, "error": _error_kind(status), "latency_ms": int((time.monotonic() - started) * 1000), "model": model}
        payload: dict = {"model": model, "input": "Reply with the single word OK.", "max_output_tokens": 64, "store": False}
        if re.match(r"^(?:gpt-5|o\d)", model):
            payload["reasoning"] = {"effort": "low"}
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
            async with session.post(RESPONSES_URL, json=payload, headers={"Authorization": f"Bearer {key}"}) as response:
                latency = int((time.monotonic() - started) * 1000)
                if response.status != 200:
                    detail = (await response.text())[:300]
                    return {"ok": False, "error": _error_kind(response.status), "detail": detail, "latency_ms": latency, "model": model}
    except (aiohttp.ClientError, TimeoutError):
        return {"ok": False, "error": "network", "latency_ms": int((time.monotonic() - started) * 1000), "model": model}
    await record_change(db, actor=actor, topic="settings", aggregate_type="ai_agent_settings", aggregate_id=actor.organization_id, operation="tested", after={"model": model, "ok": True})
    await db.commit()
    return {"ok": True, "error": None, "latency_ms": latency, "model": model, "model_listed": model in models}


CHIMEGE_TEST_PHRASE = "Сайн байна уу. Энэ бол OYUNS туслахын дуу хоолойны шалгалт."


@router.post("/chimege/test")
async def test_chimege_settings(data: ChimegeTestInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_admin)):
    """Check the Chimege tokens: synthesize a phrase, then recognize it back.

    Tokens typed but not yet saved are tested in place of the stored ones.
    Switches are ignored so a token can be verified before enabling it.
    """
    ai_runtime.invalidate(actor.organization_id)
    runtime = await ai_runtime.resolve_ai_runtime(db, actor.organization_id)
    tts_token = (data.tts_token or "").strip() or runtime.chimege_tts_token
    stt_token = (data.stt_token or "").strip() or runtime.chimege_stt_token
    result: dict = {"tts": {"ok": False, "error": "not_configured"}, "stt": {"ok": False, "error": "not_configured"}}
    audio: bytes | None = None
    if tts_token:
        started = time.monotonic()
        audio, error = await voice_service.synthesize(CHIMEGE_TEST_PHRASE, token=tts_token)
        result["tts"] = {"ok": bool(audio), "error": None if audio else error, "latency_ms": int((time.monotonic() - started) * 1000)}
    if stt_token:
        if audio:
            started = time.monotonic()
            transcript, error = await voice_service.transcribe_chimege(audio, stt_token)
            result["stt"] = {"ok": bool(transcript), "error": None if transcript else error, "transcript": transcript, "latency_ms": int((time.monotonic() - started) * 1000)}
        else:
            # Recognition is checked on the synthesized phrase; without it the token stays unverified.
            result["stt"] = {"ok": None, "error": "needs_tts"}
    await record_change(db, actor=actor, topic="settings", aggregate_type="ai_agent_settings", aggregate_id=actor.organization_id, operation="tested", after={"chimege_tts": result["tts"]["ok"], "chimege_stt": result["stt"]["ok"]})
    await db.commit()
    return result


async def _elevenlabs_key(db: AsyncSession, actor: ActorContext, explicit: str | None) -> str:
    if explicit and explicit.strip():
        return explicit.strip()
    ai_runtime.invalidate(actor.organization_id)
    return (await ai_runtime.resolve_ai_runtime(db, actor.organization_id)).elevenlabs_api_key


@router.get("/elevenlabs/voices")
async def list_elevenlabs_voices(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_admin)):
    """The voices the ElevenLabs key can use (premade, cloned and library)."""
    key = await _elevenlabs_key(db, actor, None)
    if not key:
        return {"voices": [], "error": "not_configured"}
    try:
        return {"voices": await elevenlabs_service.list_voices(key), "error": None}
    except elevenlabs_service.ElevenLabsError as exc:
        return {"voices": [], "error": exc.kind}


@router.post("/elevenlabs/test")
async def test_elevenlabs_settings(data: ElevenLabsTestInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_admin)):
    """Check an ElevenLabs key (new or stored): list voices and mint a
    streaming TTS token, which is what a call needs."""
    key = await _elevenlabs_key(db, actor, data.api_key)
    if not key:
        return {"ok": False, "error": "not_configured", "latency_ms": None, "voices": 0}
    started = time.monotonic()
    try:
        voices = await elevenlabs_service.list_voices(key)
        await elevenlabs_service.create_tts_token(key)
    except elevenlabs_service.ElevenLabsError as exc:
        return {"ok": False, "error": exc.kind, "latency_ms": int((time.monotonic() - started) * 1000), "voices": 0}
    latency = int((time.monotonic() - started) * 1000)
    await record_change(db, actor=actor, topic="settings", aggregate_type="ai_agent_settings", aggregate_id=actor.organization_id, operation="tested", after={"elevenlabs": True})
    await db.commit()
    return {"ok": True, "error": None, "latency_ms": latency, "voices": len(voices)}
