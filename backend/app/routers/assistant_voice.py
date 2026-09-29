"""OYUNS live voice call: realtime session minting and governed tool calls,
plus the turn-based Chimege and ElevenLabs pipelines."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.enterprise_deps import ActorContext, get_actor
from app.services import elevenlabs_service, voice_service
from app.services.ai_gateway import AIGateway, GatewayError
from app.services.ai_gateway.runtime import resolve_ai_runtime
from app.services.ai_gateway import voice_call
from app.services.enterprise_events import record_change

log = logging.getLogger(__name__)
router = APIRouter()
gateway = AIGateway()


class VoiceToolCall(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    # The Realtime API delivers arguments as a JSON string.
    arguments: str | dict | None = None
    call_id: str | None = Field(default=None, max_length=200)
    session_id: str | None = Field(default=None, max_length=64)


class VoiceSessionInput(BaseModel):
    # The interface language the call opens in; defaults to the account locale.
    language: str | None = Field(default=None, max_length=16)
    # The caller's engine pick in the call window; None uses the admin setting.
    provider: Literal["openai", "chimege", "elevenlabs"] | None = None


class SpeechStreamInput(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)


class ChimegeSpeechInput(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1, max_length=voice_call.CHIMEGE_MAX_SPEECH_CHARS)


def _require_assistant(actor: ActorContext) -> None:
    if not actor.can("assistant.read"):
        raise HTTPException(status_code=403, detail="Insufficient permission")


@router.post("/session")
async def create_voice_session(data: VoiceSessionInput | None = None, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    """Mint a short-lived Realtime client secret bound to OYUNS' configuration."""
    _require_assistant(actor)
    runtime = await resolve_ai_runtime(db, actor.organization_id)
    if not runtime.realtime_enabled:
        raise HTTPException(status_code=403, detail="voice_disabled")
    if not runtime.api_key:
        raise HTTPException(status_code=503, detail="not_configured")
    if not voice_call.allow_session_start(actor.account_id):
        raise HTTPException(status_code=429, detail="rate_limited")
    language = voice_call.call_language(data.language if data else None, actor.locale)
    providers = voice_call.available_providers(runtime)
    provider = voice_call.resolve_provider(runtime, language, data.provider if data else None)
    speech_url: str | None = None
    notice: str | None = None
    if provider == "elevenlabs":
        try:
            token = await elevenlabs_service.create_tts_token(runtime.elevenlabs_api_key)
            speech_url = elevenlabs_service.stream_url(runtime.elevenlabs_voice_id, runtime.elevenlabs_model, token)
        except elevenlabs_service.ElevenLabsError as exc:
            # A rejected key or quota must not make the call unusable: fall
            # back to the automatic engine and tell the caller why.
            log.warning("voice_call.elevenlabs_unavailable kind=%s", exc.kind)
            notice = f"elevenlabs_{exc.kind}"
            provider = "chimege" if language == "mn" and "chimege" in providers else "openai"
    if provider == "chimege":
        # Chimege only speaks Mongolian.
        language = "mn"
    actor = replace(actor, channel="web", detected_language=language)
    if provider in ("chimege", "elevenlabs"):
        session_id = voice_call.open_turn_call(actor.account_id, provider=provider, language=language)
        body = {
            "mode": provider, "provider": provider, "providers": providers, "session_id": session_id,
            "language": language, "greeting_text": voice_call.TURN_GREETINGS[language], "notice": notice,
        }
        if provider == "elevenlabs":
            voice_call.turn_call(session_id, actor.account_id).speech_tokens = 1
            body["speech_url"] = speech_url
            body["sample_rate"] = elevenlabs_service.OUTPUT_SAMPLE_RATE
        await record_change(
            db, actor=actor, topic="assistant", aggregate_type="assistant_voice_call", aggregate_id=actor.account_id,
            operation="started", after={"session_id": session_id, "mode": provider, "language": language},
        )
        await db.commit()
        return body
    context = await gateway._build_context(db, actor, sensitive_allowed=True)
    context["input_mode"] = "live_voice_call"
    definitions = voice_call.visible_voice_tools(gateway.tool_registry, actor, access=runtime.access)
    tools = voice_call.realtime_tools(definitions)
    try:
        secret = await voice_call.create_client_secret(runtime, voice_call.build_instructions(context, language), tools)
    except voice_call.VoiceCallError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    session_id = uuid4().hex
    await record_change(
        db, actor=actor, topic="assistant", aggregate_type="assistant_voice_call", aggregate_id=actor.account_id,
        operation="started", after={"session_id": session_id, "model": runtime.realtime_model, "language": language, "tools": len(tools)},
    )
    await db.commit()
    return {
        "mode": "realtime",
        "provider": "openai",
        "providers": providers,
        "notice": notice,
        "session_id": session_id,
        "client_secret": secret["value"],
        "expires_at": secret["expires_at"],
        "model": runtime.realtime_model,
        "voice": runtime.realtime_voice,
        "language": language,
        "greeting": voice_call.greeting_instruction(language),
        "calls_url": voice_call.REALTIME_CALLS_URL,
        "tools": [definition.name for definition in definitions],
    }


@router.post("/tool")
async def run_voice_tool(data: VoiceToolCall, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    """Run one model tool call for the caller, re-checking permission."""
    _require_assistant(actor)
    runtime = await resolve_ai_runtime(db, actor.organization_id)
    allowed = {definition.name for definition in voice_call.visible_voice_tools(gateway.tool_registry, actor, access=runtime.access)}
    if data.name not in allowed:
        result = {"status": "denied", "summary": "The requested tool is unavailable in a voice call.", "data": {}, "sources": [], "warnings": ["ACCESS_DENIED"]}
        return {"call_id": data.call_id, "output": voice_call.tool_output(result)}
    try:
        arguments = voice_call.parse_arguments(data.arguments)
    except voice_call.VoiceCallError:
        result = {"status": "invalid_input", "summary": "Tool arguments were not valid JSON.", "data": {"reason": "invalid_arguments"}, "sources": [], "warnings": []}
        return {"call_id": data.call_id, "output": voice_call.tool_output(result)}
    try:
        result = await gateway.tool_registry.dispatch_tool(data.name, arguments, actor, db=db)
        # Reads only add tool-audit rows; persist them.
        await db.commit()
    except Exception:  # noqa: BLE001 - the model gets a recoverable status instead of a 500
        log.warning("voice_call.tool_failed tool=%s", data.name, exc_info=True)
        await db.rollback()
        result = {"status": "unavailable", "summary": "The lookup failed.", "data": {}, "sources": [], "warnings": ["TOOL_FAILED"]}
    return {"call_id": data.call_id, "status": result.get("status"), "output": voice_call.tool_output(result)}


def _live_turn_call(session_id: str, actor: ActorContext) -> voice_call.TurnCall:
    call = voice_call.turn_call(session_id, actor.account_id)
    if call is None:
        raise HTTPException(status_code=404, detail="call_ended")
    return call


async def _speech_url(runtime, call: voice_call.TurnCall) -> str:
    """A fresh single-use ElevenLabs stream URL for one spoken answer."""
    if not runtime.elevenlabs_ready:
        raise elevenlabs_service.ElevenLabsError("not_configured")
    if call.speech_tokens >= voice_call.MAX_SPEECH_TOKENS_PER_CALL:
        raise elevenlabs_service.ElevenLabsError("rate_limited")
    call.speech_tokens += 1
    token = await elevenlabs_service.create_tts_token(runtime.elevenlabs_api_key)
    return elevenlabs_service.stream_url(runtime.elevenlabs_voice_id, runtime.elevenlabs_model, token)


async def _optional_speech_url(runtime, call: voice_call.TurnCall) -> str | None:
    try:
        return await _speech_url(runtime, call)
    except elevenlabs_service.ElevenLabsError as exc:
        log.warning("voice_call.elevenlabs_token_failed kind=%s", exc.kind)
        return None


async def _transcribe_turn(audio: bytes, call: voice_call.TurnCall, runtime, actor: ActorContext) -> tuple[str, str, str | None]:
    """(transcript, language, error): Scribe for ElevenLabs calls, with the
    Chimege → OpenAI transcription as the fallback and the Chimege default."""
    if call.provider == "elevenlabs" and runtime is not None and runtime.elevenlabs_api_key:
        text, language, error = await elevenlabs_service.transcribe(audio, runtime.elevenlabs_api_key, fallback_language=call.language)
        if text or error is None:
            return (text or "").strip(), language or call.language, None
        log.info("voice_call.scribe_failed kind=%s; falling back", error)
    text, error = await voice_service.transcribe(audio, filename="speech.wav", organization_id=actor.organization_id, content_type="audio/wav")
    return (text or "").strip(), call.language, error


@router.post("/turn")
@router.post("/chimege/turn")
async def voice_turn(
    session_id: str = Form(..., max_length=64),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    """One spoken turn of a turn-based call: STT → OYUNS agent (read-only).

    ElevenLabs calls also get a fresh stream URL for speaking the answer,
    minted while the agent works.
    """
    _require_assistant(actor)
    call = _live_turn_call(session_id, actor)
    audio = await file.read(voice_call.TURN_MAX_AUDIO_BYTES + 1)
    if len(audio) > voice_call.TURN_MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="audio_too_long")
    runtime = await resolve_ai_runtime(db, actor.organization_id) if call.provider == "elevenlabs" else None
    transcript, language, error = await _transcribe_turn(audio, call, runtime, actor)
    speech = asyncio.create_task(_optional_speech_url(runtime, call)) if runtime is not None else None
    extra = {"language": language}

    async def speech_url() -> dict:
        return {"speech_url": await speech} if speech is not None else {}

    if not transcript:
        return {"transcript": "", "answer": "", "error": "not_understood" if not error else "stt_failed", **extra, **await speech_url()}
    actor = replace(actor, channel="web", detected_language=language)
    try:
        routed = await gateway.execute_turn(
            db, actor, [*call.history, {"role": "user", "content": transcript}],
            memory=call.memory, input_mode="voice_call",
        )
        # Reads only add tool-audit rows; persist them.
        await db.commit()
    except GatewayError as exc:
        await db.rollback()
        log.warning("voice_call.turn_failed provider=%s status=%s", call.provider, exc.status_code)
        return {"transcript": transcript, "answer": "", "error": "agent_unavailable", **extra, **await speech_url()}
    answer = (routed.answer or "").strip()
    call.remember(transcript, answer, routed.memory)
    return {"transcript": transcript, "answer": answer, "error": None, **extra, **await speech_url()}


@router.post("/elevenlabs/stream")
async def elevenlabs_stream(data: SpeechStreamInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    """A single-use ElevenLabs stream URL for a live ElevenLabs call."""
    _require_assistant(actor)
    call = _live_turn_call(data.session_id, actor)
    if call.provider != "elevenlabs":
        raise HTTPException(status_code=404, detail="call_ended")
    runtime = await resolve_ai_runtime(db, actor.organization_id)
    try:
        return {"speech_url": await _speech_url(runtime, call), "sample_rate": elevenlabs_service.OUTPUT_SAMPLE_RATE}
    except elevenlabs_service.ElevenLabsError as exc:
        status = {"not_configured": 503, "rate_limited": 429}.get(exc.kind, 502)
        raise HTTPException(status_code=status, detail=f"elevenlabs_{exc.kind}") from exc


@router.post("/chimege/speech")
async def chimege_speech(data: ChimegeSpeechInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    """Chimege WAV for one part of an answer in a live Mongolian call."""
    _require_assistant(actor)
    _live_turn_call(data.session_id, actor)
    runtime = await resolve_ai_runtime(db, actor.organization_id)
    if not runtime.tts_token:
        raise HTTPException(status_code=503, detail="tts_not_configured")
    audio, error = await voice_service.synthesize(data.text, token=runtime.tts_token)
    if not audio:
        log.warning("voice_call.chimege_tts_failed detail=%s", error)
        raise HTTPException(status_code=502, detail="tts_failed")
    return Response(content=audio, media_type="audio/wav")
