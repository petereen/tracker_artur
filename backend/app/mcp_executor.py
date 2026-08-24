"""Private, signed FastAPI executor for the public OYUNS MCP edge."""
from __future__ import annotations

import hashlib
import hmac
import json
import time

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.enterprise_deps import actor_from_account_id
from app.services.mcp.catalog import allowed_tool_names, get_tool
from app.services.ai_gateway.tools.registry import dispatch_tool

router = APIRouter()


class ExecutorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token_claims: dict
    tool_name: str = Field(min_length=3, max_length=100)
    arguments: dict = Field(default_factory=dict)
    request_id: str = Field(min_length=8, max_length=128)


def _verify_signature(body: ExecutorRequest, timestamp: str | None, nonce: str | None, signature: str | None) -> None:
    secret = settings.MCP_INTERNAL_SHARED_SECRET.strip()
    if not secret or not timestamp or not nonce or not signature:
        raise HTTPException(status_code=401, detail="MCP executor authentication required")
    try:
        issued_at = int(timestamp)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid executor timestamp") from exc
    if abs(int(time.time()) - issued_at) > 60:
        raise HTTPException(status_code=401, detail="Expired executor request")
    canonical = json.dumps(body.model_dump(mode="json"), separators=(",", ":"), sort_keys=True)
    expected = hmac.new(secret.encode(), f"{timestamp}.{nonce}.{canonical}".encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=401, detail="Invalid executor signature")


@router.post("/execute")
async def execute_mcp_tool(
    body: ExecutorRequest,
    db: AsyncSession = Depends(get_db),
    x_oyuns_mcp_timestamp: str | None = Header(default=None),
    x_oyuns_mcp_nonce: str | None = Header(default=None),
    x_oyuns_mcp_signature: str | None = Header(default=None),
):
    _verify_signature(body, x_oyuns_mcp_timestamp, x_oyuns_mcp_nonce, x_oyuns_mcp_signature)
    claims = body.token_claims
    try:
        account_id = int(claims["sub"])
        organization_id = int(claims["organization_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Invalid MCP identity") from exc
    actor = await actor_from_account_id(account_id, db)
    if actor.organization_id != organization_id:
        raise HTTPException(status_code=401, detail="Invalid MCP identity")
    tool = get_tool(body.tool_name)
    if not tool or body.tool_name not in allowed_tool_names(actor) or body.tool_name not in set(claims.get("tools") or []):
        raise HTTPException(status_code=403, detail="MCP tool is not permitted")
    # PostgreSQL cancels a runaway governed read before it can consume the
    # executor's 15-second service deadline. ``SET LOCAL`` is transaction
    # scoped and is reset automatically after the request commits/rolls back.
    if tool.access_mode == "read":
        await db.execute(text("SET LOCAL statement_timeout = '5000ms'"))
    from dataclasses import replace
    actor = replace(actor, channel=str(claims.get("channel") or "web"))
    result = await dispatch_tool(
        body.tool_name,
        body.arguments,
        actor,
        db=db,
        request_id=body.request_id,
        conversation_id=claims.get("conversation_id"),
    )
    await db.commit()
    return result


@router.get("/health")
async def mcp_executor_health():
    return {"status": "ok", "service": "oyuns-mcp-executor"}
