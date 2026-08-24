"""Permission-first, zero-hop dispatcher for the governed MCP catalog."""
from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.core.enterprise_deps import ActorContext, permissions_for_roles
from app.services.mcp import adapters
from app.services.mcp.catalog import CATALOG, ToolDefinition, get_tool, tool_list

ToolResult = dict[str, Any]


class ToolRegistry:
    """A process-local view of the MCP catalog.

    The registry does not trust the model-visible schema. Every dispatch
    repeats lookup and authorization immediately before calling an adapter.
    """

    def __init__(self, definitions: tuple[ToolDefinition, ...] = CATALOG) -> None:
        self._definitions = {definition.name: definition for definition in definitions}

    def get(self, name: str) -> ToolDefinition | None:
        return self._definitions.get(name)

    def visible_tools(self, actor: ActorContext, intents: set[str] | frozenset[str] | None = None) -> list[dict]:
        # Use the catalog serializer so external MCP and internal Responses
        # tool schemas cannot drift apart.
        return tool_list(actor, intents)

    def visible_definitions(self, actor: ActorContext, intents: set[str] | frozenset[str] | None = None) -> list[ToolDefinition]:
        names = {item["name"] for item in self.visible_tools(actor, intents)}
        return [definition for definition in self._definitions.values() if definition.name in names]

    @staticmethod
    def _denied(request_id: str, summary: str = "The requested tool is unavailable.") -> ToolResult:
        return {"status": "denied", "summary": summary, "data": {}, "sources": [], "page": {"returned": 0}, "warnings": ["ACCESS_DENIED"], "request_id": request_id}

    async def dispatch_tool(self, tool_name: str, arguments: dict, actor_context: ActorContext,
                            *, db: Any, request_id: str | None = None, conversation_id: int | None = None) -> ToolResult:
        request_id = request_id or f"tool-{uuid4().hex}"
        definition = self.get(tool_name)
        if definition is None:
            return self._denied(request_id)
        permissions = actor_context.permissions or permissions_for_roles(actor_context.roles)
        if definition.required_roles and not actor_context.has_any_role(*definition.required_roles):
            return self._denied(request_id)
        if not definition.required_permissions.issubset(permissions):
            return self._denied(request_id)
        # Adapters validate the strict schema again and apply resource-level
        # ACLs. No HTTP edge, JWT, or internal shared-secret hop is involved.
        return await adapters.execute(
            db,
            actor_context,
            tool_name=tool_name,
            arguments=arguments,
            channel=actor_context.channel,
            request_id=request_id,
            conversation_id=conversation_id,
        )


default_registry = ToolRegistry()


async def dispatch_tool(tool_name: str, arguments: dict, actor_context: ActorContext, *, db: Any,
                        request_id: str | None = None, conversation_id: int | None = None) -> ToolResult:
    return await default_registry.dispatch_tool(tool_name, arguments, actor_context, db=db, request_id=request_id, conversation_id=conversation_id)
