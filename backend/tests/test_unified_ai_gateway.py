"""Contracts for the in-process gateway boundary."""
from __future__ import annotations

from app.core.enterprise_deps import ActorContext, permissions_for_roles
from app.core.security import create_action_preview_token, decode_action_preview_token, verify_action_preview_token
from app.services.ai_gateway.tools.registry import ToolRegistry
from app.services.mcp.catalog import get_tool


def actor(role: str = "member") -> ActorContext:
    roles = frozenset({role})
    return ActorContext(7, 3, 9, "person@example.test", "mn", roles, permissions_for_roles(roles), "mn", "web")


def test_registry_prunes_mutations_and_privileged_reads_by_permission():
    member = {item["name"] for item in ToolRegistry().visible_tools(actor(), {"tasks_write", "erp"})}
    assert "oyuns_tasks_prepare_create" in member
    assert "oyuns_erp_read" not in member
    admin = {item["name"] for item in ToolRegistry().visible_tools(actor("admin"), {"erp"})}
    assert admin == {"oyuns_erp_read"}


def test_preview_is_explicitly_mutating_and_compactly_signed():
    tool = get_tool("oyuns_tasks_prepare_create")
    assert tool is not None and tool.is_mutation and not tool.read_only
    token = create_action_preview_token(action_id=123, payload_digest="a" * 64, account_id=7, organization_id=3, channel="telegram")
    assert len(token) <= 64
    claims = decode_action_preview_token(token)
    assert claims and claims["action_id"] == "123"
    assert verify_action_preview_token(token, payload_digest="a" * 64, account_id=7, organization_id=3, channel="telegram")
    assert not verify_action_preview_token(token, payload_digest="b" * 64, account_id=7, organization_id=3, channel="telegram")
