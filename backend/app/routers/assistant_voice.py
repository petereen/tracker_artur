"""OYUNS live voice call: realtime session minting and governed tool calls."""
from __future__ import annotations

import logging
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.enterprise_deps import ActorContext, get_actor
from app.services.ai_gateway import AIGateway
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


def _require_assistant(actor: ActorContext) -> None:
    if not actor.can("assistant.read"):
        raise HTTPException(status_code=403, detail="Insufficient permission")


@router.post("/session")
async def create_voice_session(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    """Mint a short-lived Realtime client secret bound to OYUNS' configuration."""
    _require_assistant(actor)
    runtime = await resolve_ai_runtime(db, actor.organization_id)
    if not runtime.realtime_enabled:
        raise HTTPException(status_code=403, detail="voice_disabled")
    if not runtime.api_key:
        raise HTTPException(status_code=503, detail="not_configured")
    if not voice_call.allow_session_start(actor.account_id):
        raise HTTPException(status_code=429, detail="rate_limited")
    context = await gateway._build_context(db, actor, sensitive_allowed=True)
    context["input_mode"] = "live_voice_call"
    definitions = voice_call.visible_voice_tools(gateway.tool_registry, actor)
    tools = voice_call.realtime_tools(definitions)
    try:
        secret = await voice_call.create_client_secret(runtime, voice_call.build_instructions(context), tools)
    except voice_call.VoiceCallError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    session_id = uuid4().hex
    await record_change(
        db, actor=actor, topic="assistant", aggregate_type="assistant_voice_call", aggregate_id=actor.account_id,
        operation="started", after={"session_id": session_id, "model": runtime.realtime_model, "tools": len(tools)},
    )
    await db.commit()
    return {
        "session_id": session_id,
        "client_secret": secret["value"],
        "expires_at": secret["expires_at"],
        "model": runtime.realtime_model,
        "voice": runtime.realtime_voice,
        "calls_url": voice_call.REALTIME_CALLS_URL,
        "tools": [definition.name for definition in definitions],
    }


@router.post("/tool")
async def run_voice_tool(data: VoiceToolCall, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    """Run one model tool call for the caller, re-checking permission."""
    _require_assistant(actor)
    allowed = {definition.name for definition in voice_call.visible_voice_tools(gateway.tool_registry, actor)}
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
