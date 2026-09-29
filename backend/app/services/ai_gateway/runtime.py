"""Per-organization OpenAI key and model selection for OYUNS.

Admins configure the key and models in platform settings; the environment
(`OPENAI_API_KEY`, the model registry) remains the fallback. The key is stored
encrypted in ``organization.settings["ai_agent"]`` and never leaves the server.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import select

from app.core.config import settings
from app.models.models import Organization
from app.services.ai_gateway.access_policy import FULL_ACCESS, AccessPolicy, policy_from_config
from app.services.ai_gateway.config import registry
from app.services.secret_box import decrypt_secret

log = logging.getLogger(__name__)

AI_AGENT_SETTINGS_KEY = "ai_agent"
REASONING_EFFORTS = ("none", "low", "medium", "high")
MIN_OUTPUT_TOKENS = 500
MAX_OUTPUT_TOKENS = 8_000
DEFAULT_OUTPUT_TOKENS = 2_000
CACHE_TTL_SECONDS = 60.0

KeySource = Literal["organization", "environment", "none"]
# Live voice calls with OYUNS use the OpenAI Realtime API. "gpt-realtime" is
# OpenAI's alias for its latest generally available realtime model; admins
# can pin another realtime model in platform settings.
DEFAULT_REALTIME_MODEL = "gpt-realtime"
DEFAULT_REALTIME_VOICE = "marin"
REALTIME_VOICES = ("marin", "cedar", "alloy", "ash", "ballad", "coral", "echo", "sage", "shimmer", "verse")
# Chimege (Mongolian STT/TTS) tokens: stored encrypted like the OpenAI key,
# with the historical environment variables as the fallback.
CHIMEGE_TOKENS = {"stt": ("chimege_stt_token_enc", "CHIMEGE_API_TOKEN"), "tts": ("chimege_tts_token_enc", "CHIMEGE_TTS_API_TOKEN")}
# ElevenLabs (streaming TTS + Scribe STT) for voice calls: the key is stored
# encrypted like the others, `ELEVENLABS_API_KEY` is the fallback.
ELEVENLABS_KEY_FIELD = "elevenlabs_api_key_enc"
ELEVENLABS_ENV = "ELEVENLABS_API_KEY"
# Only these models stream over the `stream-input` WebSocket (v3 does not).
ELEVENLABS_MODELS = ("eleven_flash_v2_5", "eleven_turbo_v2_5", "eleven_multilingual_v2")
DEFAULT_ELEVENLABS_MODEL = "eleven_flash_v2_5"
# "Sarah", a premade multilingual voice every ElevenLabs account has.
DEFAULT_ELEVENLABS_VOICE = "EXAVITQu4vr4xnSDxMaL"
# Voice call engine: `auto` keeps Chimege for Mongolian and OpenAI Realtime
# for other languages; the others pin one engine (falling back when not ready).
VOICE_CALL_PROVIDERS = ("auto", "openai", "chimege", "elevenlabs")


@dataclass(frozen=True, slots=True)
class AIRuntime:
    api_key: str
    primary_model: str
    fallback_model: str | None
    reasoning_effort: str
    max_output_tokens: int
    web_search_enabled: bool
    source: KeySource
    realtime_model: str = DEFAULT_REALTIME_MODEL
    realtime_voice: str = DEFAULT_REALTIME_VOICE
    realtime_enabled: bool = True
    access: AccessPolicy = FULL_ACCESS
    chimege_stt_token: str = ""
    chimege_tts_token: str = ""
    chimege_stt_source: KeySource = "none"
    chimege_tts_source: KeySource = "none"
    chimege_stt_enabled: bool = True
    chimege_tts_enabled: bool = True
    # Mongolian voice calls: Chimege STT → OYUNS agent → Chimege TTS instead
    # of the OpenAI Realtime model, which handles Mongolian poorly.
    chimege_voice_call_enabled: bool = True
    voice_call_provider: str = "auto"
    elevenlabs_api_key: str = ""
    elevenlabs_source: KeySource = "none"
    elevenlabs_enabled: bool = True
    elevenlabs_voice_id: str = DEFAULT_ELEVENLABS_VOICE
    elevenlabs_model: str = DEFAULT_ELEVENLABS_MODEL

    @property
    def elevenlabs_ready(self) -> bool:
        return bool(self.elevenlabs_enabled and self.elevenlabs_api_key)

    @property
    def stt_token(self) -> str:
        """The Chimege STT token when Chimege recognition is switched on."""
        return self.chimege_stt_token if self.chimege_stt_enabled else ""

    @property
    def tts_token(self) -> str:
        """The Chimege TTS token when Chimege speech is switched on."""
        return self.chimege_tts_token if self.chimege_tts_enabled else ""

    @property
    def chimege_voice_call_ready(self) -> bool:
        return bool(self.chimege_voice_call_enabled and self.stt_token and self.tts_token)

    @property
    def models(self) -> list[str]:
        """Primary first, then a distinct fallback."""
        return [self.primary_model] + ([self.fallback_model] if self.fallback_model and self.fallback_model != self.primary_model else [])


def default_models() -> tuple[str, str | None]:
    config = registry()
    ids = [model.id for model in config.models.values()]
    primary = config.models["luna"].id if "luna" in config.models else ids[0]
    fallback = config.models["terra"].id if "terra" in config.models else next((item for item in ids if item != primary), None)
    return primary, fallback


def _env_key() -> str:
    return (settings.OPENAI_API_KEY or os.getenv("OPENAI_API_KEY", "")).strip()


def _clamp_tokens(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return DEFAULT_OUTPUT_TOKENS
    return max(MIN_OUTPUT_TOKENS, min(MAX_OUTPUT_TOKENS, number))


def stored_config(organization_settings: dict | None) -> dict:
    raw = (organization_settings or {}).get(AI_AGENT_SETTINGS_KEY)
    return dict(raw) if isinstance(raw, dict) else {}


def _chimege_token(stored: dict, kind: str) -> tuple[str, KeySource]:
    field, env_name = CHIMEGE_TOKENS[kind]
    if stored.get(field):
        try:
            token = decrypt_secret(str(stored[field])).strip()
            if token:
                return token, "organization"
        except ValueError:
            log.warning("ai_runtime.chimege_%s_token_undecryptable", kind)
    token = os.getenv(env_name, "").strip()
    return token, "environment" if token else "none"


def _elevenlabs_key(stored: dict) -> tuple[str, KeySource]:
    if stored.get(ELEVENLABS_KEY_FIELD):
        try:
            key = decrypt_secret(str(stored[ELEVENLABS_KEY_FIELD])).strip()
            if key:
                return key, "organization"
        except ValueError:
            log.warning("ai_runtime.elevenlabs_key_undecryptable")
    key = os.getenv(ELEVENLABS_ENV, "").strip()
    return key, "environment" if key else "none"


def build_runtime(organization_settings: dict | None) -> AIRuntime:
    """Merge organization settings over environment defaults."""
    stored = stored_config(organization_settings)
    api_key = ""
    source: KeySource = "none"
    if stored.get("api_key_enc"):
        try:
            api_key = decrypt_secret(str(stored["api_key_enc"])).strip()
            source = "organization" if api_key else "none"
        except ValueError:
            log.warning("ai_runtime.organization_key_undecryptable")
    if not api_key:
        api_key = _env_key()
        source = "environment" if api_key else "none"
    primary, fallback = default_models()
    effort = str(stored.get("reasoning_effort") or "low")
    voice = str(stored.get("realtime_voice") or DEFAULT_REALTIME_VOICE)
    stt_token, stt_source = _chimege_token(stored, "stt")
    tts_token, tts_source = _chimege_token(stored, "tts")
    elevenlabs_key, elevenlabs_source = _elevenlabs_key(stored)
    provider = str(stored.get("voice_call_provider") or "auto")
    elevenlabs_model = str(stored.get("elevenlabs_model") or "")
    return AIRuntime(
        voice_call_provider=provider if provider in VOICE_CALL_PROVIDERS else "auto",
        elevenlabs_api_key=elevenlabs_key,
        elevenlabs_source=elevenlabs_source,
        elevenlabs_enabled=bool(stored.get("elevenlabs_enabled", True)),
        elevenlabs_voice_id=str(stored.get("elevenlabs_voice_id") or "").strip() or DEFAULT_ELEVENLABS_VOICE,
        elevenlabs_model=elevenlabs_model if elevenlabs_model in ELEVENLABS_MODELS else DEFAULT_ELEVENLABS_MODEL,
        chimege_stt_token=stt_token,
        chimege_tts_token=tts_token,
        chimege_stt_source=stt_source,
        chimege_tts_source=tts_source,
        chimege_stt_enabled=bool(stored.get("chimege_stt_enabled", True)),
        chimege_tts_enabled=bool(stored.get("chimege_tts_enabled", True)),
        chimege_voice_call_enabled=bool(stored.get("chimege_voice_call_enabled", True)),
        realtime_model=str(stored.get("realtime_model") or "").strip() or DEFAULT_REALTIME_MODEL,
        realtime_voice=voice if voice in REALTIME_VOICES else DEFAULT_REALTIME_VOICE,
        realtime_enabled=bool(stored.get("realtime_enabled", True)),
        api_key=api_key,
        primary_model=str(stored.get("primary_model") or "").strip() or primary,
        # An explicitly saved empty fallback disables the second model.
        fallback_model=(str(stored.get("fallback_model") or "").strip() or None) if "fallback_model" in stored else fallback,
        reasoning_effort=effort if effort in REASONING_EFFORTS else "low",
        max_output_tokens=_clamp_tokens(stored.get("max_output_tokens", DEFAULT_OUTPUT_TOKENS)),
        web_search_enabled=bool(stored.get("web_search_enabled", True)),
        source=source,
        access=policy_from_config(stored),
    )


_cache: dict[int | None, tuple[float, AIRuntime]] = {}


def invalidate(organization_id: int | None = None) -> None:
    _cache.pop(organization_id, None)
    # The org-less default follows whichever organization configured a key.
    _cache.pop(None, None)


async def resolve_ai_runtime(db: Any, organization_id: int | None) -> AIRuntime:
    """Return the runtime for an organization, cached briefly per process.

    ``organization_id=None`` serves org-less bot paths in this single-company
    deployment: the lowest-id organization that configured a key, else env.
    """
    cached = _cache.get(organization_id)
    if cached and cached[0] > time.monotonic():
        return cached[1]
    organization_settings: dict | None = None

    async def lookup() -> dict | None:
        if organization_id is not None:
            organization = await db.get(Organization, organization_id)
            return getattr(organization, "settings", None) if organization else None
        rows = (await db.execute(select(Organization.settings).order_by(Organization.id))).scalars().all()
        configured = ("api_key_enc", ELEVENLABS_KEY_FIELD, *(field for field, _ in CHIMEGE_TOKENS.values()))
        return next((row for row in rows if any(stored_config(row).get(key) for key in configured)), rows[0] if rows else None)

    try:
        # A savepoint keeps a failed lookup from aborting the caller's
        # PostgreSQL transaction (the error is handled here, not re-raised).
        if hasattr(db, "begin_nested"):
            async with db.begin_nested():
                organization_settings = await lookup()
        else:
            organization_settings = await lookup()
    except Exception:
        log.warning("ai_runtime.settings_lookup_failed organization_id=%s", organization_id, exc_info=True)
    runtime = build_runtime(organization_settings)
    _cache[organization_id] = (time.monotonic() + CACHE_TTL_SECONDS, runtime)
    return runtime


async def openai_api_key(organization_id: int | None = None) -> str:
    """Key for service code without a request session (bot, workers)."""
    cached = _cache.get(organization_id)
    if cached and cached[0] > time.monotonic():
        return cached[1].api_key
    try:
        from app.core.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            return (await resolve_ai_runtime(db, organization_id)).api_key
    except Exception:
        log.warning("ai_runtime.key_lookup_failed", exc_info=True)
        return _env_key()


async def chimege_tokens(organization_id: int | None = None) -> tuple[str, str]:
    """Active (switched-on) Chimege STT and TTS tokens for service code."""
    cached = _cache.get(organization_id)
    if cached and cached[0] > time.monotonic():
        return cached[1].stt_token, cached[1].tts_token
    try:
        from app.core.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            runtime = await resolve_ai_runtime(db, organization_id)
            return runtime.stt_token, runtime.tts_token
    except Exception:
        log.warning("ai_runtime.chimege_lookup_failed", exc_info=True)
        return os.getenv("CHIMEGE_API_TOKEN", "").strip(), os.getenv("CHIMEGE_TTS_API_TOKEN", "").strip()


def has_api_key_hint() -> bool:
    """Synchronous availability check: env key or any recently resolved key."""
    return bool(_env_key()) or any(runtime.api_key for _, runtime in _cache.values())
