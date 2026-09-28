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
    for field in ("primary_model", "fallback_model", "reasoning_effort", "max_output_tokens", "web_search_enabled", "realtime_model", "realtime_voice", "realtime_enabled"):
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
