"""Actor-filtered MCP catalog and schema conversion."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from app.core.enterprise_deps import ActorContext, permissions_for_roles
from app.core.config import settings
from app.core.security import create_mcp_access_token
from app.services.mcp import schemas


AccessMode = Literal["read", "preview"]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    title: str
    description: str
    model: type[BaseModel]
    domain: str
    access_mode: AccessMode
    required_roles: frozenset[str] = frozenset()
    required_permissions: frozenset[str] = frozenset({"assistant.read"})
    intent_tags: frozenset[str] = frozenset()
    is_mutation: bool = False

    @property
    def read_only(self) -> bool:
        return not self.is_mutation


CATALOG: tuple[ToolDefinition, ...] = (
    ToolDefinition("oyuns_knowledge_search", "Search company knowledge", "Search authorized company knowledge and file excerpts. Returns cited, bounded passages.", schemas.KnowledgeSearchInput, "knowledge", "read", intent_tags=frozenset({"knowledge"})),
    ToolDefinition("oyuns_knowledge_fetch", "Fetch knowledge excerpt", "Fetch a single authorized knowledge source by opaque reference.", schemas.KnowledgeFetchInput, "knowledge", "read", intent_tags=frozenset({"knowledge"})),
    ToolDefinition("oyuns_records_search", "Search employee directory", "Search authorized employee directory fields only.", schemas.RecordsSearchInput, "records", "read", required_permissions=frozenset({"assistant.directory"}), intent_tags=frozenset({"directory"})),
    ToolDefinition("oyuns_records_get", "Get employee record", "Get one authorized employee record by opaque reference.", schemas.RecordsGetInput, "records", "read", required_permissions=frozenset({"assistant.directory"}), intent_tags=frozenset({"directory"})),
    ToolDefinition("oyuns_records_aggregate", "Aggregate employee directory", "Return a permitted aggregate over the employee directory.", schemas.RecordsAggregateInput, "records", "read", required_permissions=frozenset({"assistant.directory"}), intent_tags=frozenset({"directory", "analytics"})),
    ToolDefinition("oyuns_tasks_search", "Search tasks", "Search tasks, blockers, and review work in the caller's permitted scope.", schemas.TasksSearchInput, "tasks", "read", intent_tags=frozenset({"tasks_read"})),
    ToolDefinition("oyuns_projects_search", "Search projects", "Search projects, plans, and milestones in the caller's permitted scope.", schemas.ProjectsSearchInput, "projects", "read", intent_tags=frozenset({"projects"})),
    ToolDefinition("oyuns_calendar_availability", "Get calendar availability", "Retrieve authorized availability; private events are reduced to free/busy when required.", schemas.CalendarAvailabilityInput, "calendar", "read", intent_tags=frozenset({"calendar"})),
    ToolDefinition("oyuns_stats_get", "Get governed statistics", "Return authorized OYUNS ERP metrics; unsupported metrics are rejected.", schemas.StatsGetInput, "analytics", "read", required_permissions=frozenset({"assistant.analytics"}), intent_tags=frozenset({"analytics"})),
    ToolDefinition("oyuns_erp_read", "Read ERP records", "Read authorized ERP dashboard totals or documents. This never creates, posts, pays, or finalizes payroll.", schemas.ERPReadInput, "erp", "read", required_permissions=frozenset({"assistant.erp"}), intent_tags=frozenset({"erp"})),
    ToolDefinition("oyuns_exchange_rate_get", "Get exchange rate", "Retrieve a current exchange rate from the configured provider.", schemas.ExchangeRateInput, "exchange", "read", intent_tags=frozenset({"exchange_rates"})),
    ToolDefinition("oyuns_tasks_prepare_create", "Prepare task creation", "Prepare a task for explicit Web or Telegram confirmation. This never creates a task directly.", schemas.TaskPrepareCreateInput, "tasks", "preview", required_permissions=frozenset({"assistant.preview"}), intent_tags=frozenset({"tasks_write"}), is_mutation=True),
    ToolDefinition("oyuns_tasks_prepare_update", "Prepare task update", "Prepare a task update for explicit Web or Telegram confirmation. This never changes a task directly.", schemas.TaskPrepareUpdateInput, "tasks", "preview", required_permissions=frozenset({"assistant.preview"}), intent_tags=frozenset({"tasks_write"}), is_mutation=True),
)


def _strict_schema(model: type[BaseModel]) -> dict:
    schema = model.model_json_schema()

    def visit(node: object) -> None:
        if isinstance(node, dict):
            if isinstance(node.get("properties"), dict):
                # OpenAI Responses strict function tools require every
                # property to be present in `required`; nullable fields carry
                # optionality in their type rather than through omission.
                node["required"] = list(node["properties"])
                node["additionalProperties"] = False
            node.pop("default", None)
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(schema)
    return schema


def allowed_tool_names(actor: ActorContext, intents: set[str] | frozenset[str] | None = None) -> list[str]:
    """Return model-visible tools; confirmation is intentionally absent."""
    intents = set(intents or ())
    permissions = actor.permissions or permissions_for_roles(actor.roles)
    return [tool.name for tool in CATALOG
            if (not tool.required_roles or actor.has_any_role(*tool.required_roles))
            and tool.required_permissions.issubset(permissions)
            and (not intents or bool(tool.intent_tags.intersection(intents)))]


def get_tool(name: str) -> ToolDefinition | None:
    return next((tool for tool in CATALOG if tool.name == name), None)


def tool_list(actor: ActorContext, intents: set[str] | frozenset[str] | None = None) -> list[dict]:
    allowed = set(allowed_tool_names(actor, intents))
    return [
        {
            "name": tool.name,
            "title": tool.title,
            "description": tool.description,
            "inputSchema": _strict_schema(tool.model),
            "annotations": {"readOnlyHint": tool.read_only, "destructiveHint": tool.is_mutation, "idempotentHint": tool.access_mode == "read"},
        }
        for tool in CATALOG
        if tool.name in allowed
    ]


def mcp_remote_tool(*, authorization: str, allowed_tools: list[str]) -> dict:
    return {
        "type": "mcp",
        "server_label": "oyuns_enterprise",
        "server_description": "Permission-scoped OYUNS company knowledge and ERP tools. Task changes are previews requiring explicit Web or Telegram confirmation.",
        "server_url": settings.AI_MCP_SERVER_URL,
        "authorization": authorization,
        "defer_loading": True,
        "allowed_tools": allowed_tools,
        # Only reads and non-executing previews are in the catalog. A trusted
        # channel callback, not the model, performs confirmation.
        "require_approval": "never",
    }


def enabled_for(actor: ActorContext) -> bool:
    if not settings.AI_MCP_ENABLED or not settings.AI_MCP_SERVER_URL.strip().startswith("https://"):
        return False
    raw = settings.AI_MCP_ORGANIZATION_ALLOWLIST.strip()
    if not raw:
        return True
    try:
        allowed = {int(value.strip()) for value in raw.split(",") if value.strip()}
    except ValueError:
        return False
    return actor.organization_id in allowed


def gateway_tool_for(actor: ActorContext, *, channel: str, conversation_id: int | None) -> dict | None:
    if not enabled_for(actor):
        return None
    allowed = allowed_tool_names(actor)
    token = create_mcp_access_token(
        account_id=actor.account_id,
        organization_id=actor.organization_id,
        channel=channel,
        conversation_id=conversation_id,
        allowed_tools=allowed,
    )
    return mcp_remote_tool(authorization=f"Bearer {token}", allowed_tools=allowed)
