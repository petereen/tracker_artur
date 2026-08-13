import asyncio

import pytest

from app.core.enterprise_deps import ActorContext
from app.core.security import create_mcp_access_token, decode_mcp_access_token
from app.services.ai_gateway.gateway import AIGateway, Classification, GatewayRequest
from app.services.mcp.catalog import allowed_tool_names, tool_list
from app.services.mcp.references import resolve_resource_reference, resource_reference
from app.services.mcp.results import MAX_RESULT_BYTES, envelope


def _actor(*, account_id: int = 7, organization_id: int = 3) -> ActorContext:
    return ActorContext(
        account_id=account_id,
        organization_id=organization_id,
        employee_id=9,
        email="person@example.test",
        locale="mn",
        roles=frozenset({"member"}),
    )


def test_mcp_catalog_uses_strict_versioned_tool_contracts():
    tools = tool_list(_actor())
    names = {tool["name"] for tool in tools}
    assert "oyuns_knowledge_search" in names
    assert "oyuns_tasks_prepare_create" in names
    assert all(name.startswith("oyuns_") for name in names)
    assert all(tool["inputSchema"].get("additionalProperties") is False for tool in tools)
    assert set(allowed_tool_names(_actor())) == names


def test_mcp_token_is_actor_scoped_and_audience_bound():
    token = create_mcp_access_token(
        account_id=7,
        organization_id=3,
        channel="web",
        conversation_id=11,
        allowed_tools=["oyuns_knowledge_search"],
    )
    claims = decode_mcp_access_token(token)
    assert claims and claims["sub"] == "7"
    assert claims["organization_id"] == 3
    assert claims["aud"] == "oyuns-mcp"
    assert claims["tools"] == ["oyuns_knowledge_search"]
    assert claims["jti"]


def test_opaque_resource_reference_cannot_cross_actor_or_organization():
    reference = resource_reference(_actor(), "employee", 41)
    assert resolve_resource_reference(_actor(), reference, kind="employee") == 41
    with pytest.raises(ValueError):
        resolve_resource_reference(_actor(account_id=8), reference, kind="employee")
    with pytest.raises(ValueError):
        resolve_resource_reference(_actor(organization_id=4), reference, kind="employee")


def test_mcp_envelope_redacts_internal_secrets_and_marks_oversized_results_partial():
    output = envelope(
        result={"status": "ok", "data": {}},
        request_id="mcp-request-1",
        summary="safe",
        data={"token": "secret", "storage_key": "private/file", "id": 42, "items": [{"excerpt": "x" * (MAX_RESULT_BYTES + 100)}]},
    )
    assert "token" not in output["data"]
    assert "storage_key" not in output["data"]
    assert "id" not in output["data"]
    assert output["status"] == "partial"
    assert "OUTPUT_TRUNCATED" in output["warnings"]


def test_gateway_uses_remote_mcp_and_preserves_deferred_list_context(monkeypatch):
    gateway = AIGateway()

    class Cache:
        async def circuit_open(self, _key): return False
        async def record_model_success(self, _key): return None
        async def record_model_failure(self, _key): return None

    async def classify(_text):
        return Classification(
            category="simple_qa", language="mn", requires_freshness=False,
            requires_enterprise_tools=True, requested_modalities=["text"], cache_eligible=False,
        )

    async def post(payload, *, model_key, retries=2):
        del model_key, retries
        assert payload["tools"][0]["type"] == "mcp"
        assert payload["tools"][0]["defer_loading"] is True
        return {
            "output": [
                {"type": "mcp_list_tools", "server_label": "oyuns_enterprise", "tools": []},
                {"type": "mcp_call", "output": '{"structuredContent":{"status":"ok","data":{"items":[]},"sources":[]}}'},
                {"type": "message", "content": [{"type": "output_text", "text": "Done."}]},
            ],
            "usage": {},
        }

    gateway.cache = Cache()
    monkeypatch.setattr(gateway, "_classify", classify)
    monkeypatch.setattr(gateway, "_post", post)
    response = asyncio.run(gateway.respond(None, GatewayRequest(
        text="find company policy", history=[], channel="web",
        mcp_tool={"type": "mcp", "server_url": "https://mcp.example.test/mcp", "defer_loading": True},
    )))
    assert response.answer == "Done."
    assert response.tool_results[0]["status"] == "ok"
    assert response.mcp_context[0]["type"] == "mcp_list_tools"

