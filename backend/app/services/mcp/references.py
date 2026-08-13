"""Encrypted, actor-bound references used at the MCP boundary."""
from __future__ import annotations

import json
from typing import Any

from app.core.enterprise_deps import ActorContext
from app.services.secret_box import decrypt_secret, encrypt_secret


def _pack(prefix: str, actor: ActorContext, kind: str, value: Any) -> str:
    payload = {
        "organization_id": actor.organization_id,
        "account_id": actor.account_id,
        "kind": kind,
        "value": value,
    }
    return prefix + encrypt_secret(json.dumps(payload, separators=(",", ":"), default=str))


def _unpack(prefix: str, actor: ActorContext, reference: str, *, expected_kind: str | None = None) -> Any:
    if not isinstance(reference, str) or not reference.startswith(prefix):
        raise ValueError("Invalid resource reference")
    try:
        payload = json.loads(decrypt_secret(reference[len(prefix):]))
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid resource reference") from exc
    if payload.get("organization_id") != actor.organization_id or payload.get("account_id") != actor.account_id:
        raise ValueError("Resource reference is not available to this account")
    if expected_kind and payload.get("kind") != expected_kind:
        raise ValueError("Resource reference has the wrong type")
    return payload.get("value")


def resource_reference(actor: ActorContext, kind: str, resource_id: int | str) -> str:
    return _pack("mcpref_", actor, kind, resource_id)


def resolve_resource_reference(actor: ActorContext, reference: str, *, kind: str) -> int | str:
    return _unpack("mcpref_", actor, reference, expected_kind=kind)


def action_reference(actor: ActorContext, *, token: str, channel: str) -> str:
    return _pack("mcpact_", actor, "pending_action", {"token": token, "channel": channel})


def resolve_action_reference(actor: ActorContext, reference: str, *, channel: str) -> str:
    value = _unpack("mcpact_", actor, reference, expected_kind="pending_action")
    if not isinstance(value, dict) or value.get("channel") != channel or not isinstance(value.get("token"), str):
        raise ValueError("Action reference is unavailable")
    return value["token"]

