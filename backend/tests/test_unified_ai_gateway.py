"""Contracts for the in-process gateway boundary."""
from __future__ import annotations

from app.core.enterprise_deps import ActorContext, permissions_for_roles
from app.core.security import create_action_preview_token, decode_action_preview_token, verify_action_preview_token
from app.services.ai_gateway.tools.registry import ToolRegistry
from app.services.mcp.catalog import get_tool


def actor(role: str = "member") -> ActorContext:
    roles = frozenset({role})
    return ActorContext(7, 3, 9, "person@example.test", "mn", roles, permissions_for_roles(roles), "mn", "web")


def test_unassigned_authenticated_accounts_can_search_company_knowledge():
    permissions = permissions_for_roles(frozenset())
    unassigned = ActorContext(7, 3, 9, "person@example.test", "mn", frozenset(), permissions, "mn", "web")
    names = {item["name"] for item in ToolRegistry().visible_tools(unassigned, {"knowledge"})}

    assert permissions == frozenset({"assistant.read"})
    assert "oyuns_knowledge_search" in names
    assert "oyuns_knowledge_fetch" in names
    assert "oyuns_tasks_prepare_create" not in names


def test_registry_gates_previews_and_sensitive_domains_by_role():
    contractor = {item["name"] for item in ToolRegistry().visible_tools(actor("contractor"))}
    assert "oyuns_knowledge_search" in contractor
    member = {item["name"] for item in ToolRegistry().visible_tools(actor())}
    # Previews never mutate, so they are visible to every role with
    # assistant.preview without intent keywords.
    assert "oyuns_tasks_prepare_create" in member
    assert "oyuns_payroll_summary" not in member
    admin = {item["name"] for item in ToolRegistry().visible_tools(actor("admin"))}
    assert {"oyuns_erp_read", "oyuns_payroll_summary", "oyuns_tasks_prepare_create"} <= admin


def test_strict_tool_schemas_require_all_properties_for_responses():
    for tool in ToolRegistry().visible_tools(actor(), {"tasks_write"}):
        schema = tool["inputSchema"]
        assert schema.get("additionalProperties") is False
        assert set(schema.get("required", [])) == set(schema.get("properties", {}))


def test_preview_is_explicitly_mutating_and_compactly_signed():
    tool = get_tool("oyuns_tasks_prepare_create")
    assert tool is not None and tool.is_mutation and not tool.read_only
    token = create_action_preview_token(action_id=123, payload_digest="a" * 64, account_id=7, organization_id=3, channel="telegram")
    assert len(token) <= 64
    claims = decode_action_preview_token(token)
    assert claims and claims["action_id"] == "123"
    assert verify_action_preview_token(token, payload_digest="a" * 64, account_id=7, organization_id=3, channel="telegram")
    assert not verify_action_preview_token(token, payload_digest="b" * 64, account_id=7, organization_id=3, channel="telegram")
