"""Map the stable MCP catalog to existing permission-first enterprise tools."""
from __future__ import annotations

from collections import Counter
from typing import Any
import unicodedata

from sqlalchemy import select

from app.core.enterprise_deps import ActorContext
from app.models.models import CompanyKnowledge, CompanyLibraryItem, Employee, KnowledgeChunk, KnowledgeDocument, ResourcePolicy, Task
from app.services import enterprise_tools
from app.services import exchange_rate_service
from app.services.mcp import schemas
from app.services.mcp.references import action_reference, resolve_resource_reference, resource_reference
from app.services.mcp.results import envelope


def _sanitize_arguments(value: Any) -> Any:
    """Normalize text before schema validation; tools never receive SQL."""
    if isinstance(value, str):
        normalized = unicodedata.normalize("NFC", value)
        if any(unicodedata.category(char).startswith("C") for char in normalized):
            raise ValueError("INVALID_INPUT")
        # Parameterized service calls make this defense-in-depth, but rejecting
        # explicit SQL separators/comments prevents accidental generic-query
        # expansion if a future adapter is added incorrectly.
        if any(fragment in normalized.casefold() for fragment in ("--", "/*", "*/", ";")):
            raise ValueError("INVALID_INPUT")
        return normalized
    if isinstance(value, list):
        return [_sanitize_arguments(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _sanitize_arguments(item) for key, item in value.items()}
    return value


def _summary(result: dict, fallback: str) -> str:
    status = result.get("status")
    if status == "empty":
        return "No matching authorized records were found."
    if status == "denied":
        return "You do not have access to that resource."
    if status == "unavailable":
        return "The requested OYUNS capability is temporarily unavailable."
    return fallback


async def _directory(db, actor: ActorContext, *, query: str | None, include_inactive: bool, limit: int) -> dict:
    if include_inactive and not actor.has_any_role("admin", "manager"):
        return {"status": "denied", "data": {}}
    employees = await enterprise_tools._organization_employees(db, actor, include_inactive=include_inactive)
    normalized = (query or "").strip().casefold()
    if normalized:
        employees = [employee for employee in employees if normalized in employee.name.casefold() or normalized in (employee.job_title or "").casefold() or normalized in (employee.telegram_username or "").casefold()]
    items = [
        {
            "reference": resource_reference(actor, "employee", employee.id),
            "name": employee.name,
            "job_title": employee.job_title,
            "telegram_username": employee.telegram_username,
            "is_active": employee.is_active,
        }
        for employee in employees[:limit]
    ]
    return {"status": "ok" if items else "empty", "data": {"items": items}}


async def _knowledge_fetch(db, actor: ActorContext, reference: str) -> dict:
    value = resolve_resource_reference(actor, reference, kind="knowledge_source")
    if not isinstance(value, str) or ":" not in value:
        return {"status": "denied", "data": {}}
    source_type, raw_id = value.split(":", 1)
    if source_type not in {"company_file", "company_knowledge"} or not raw_id.isdigit():
        return {"status": "denied", "data": {}}
    document = await db.scalar(select(KnowledgeDocument).where(KnowledgeDocument.organization_id == actor.organization_id, KnowledgeDocument.source_type == source_type, KnowledgeDocument.source_id == int(raw_id), KnowledgeDocument.index_status == "ready"))
    if not document:
        return {"status": "empty", "data": {}}
    # Reuse the same file/knowledge policy checks as search before returning
    # anything. A fetch reference never widens the user's entitlement.
    if source_type == "company_file":
        source = await db.get(CompanyLibraryItem, int(raw_id))
        if not source or source.organization_id != actor.organization_id or source.deleted_at:
            return {"status": "empty", "data": {}}
        if not await enterprise_tools.can_read_policy(db, actor, await enterprise_tools._policy_for_file(db, source)):
            return {"status": "empty", "data": {}}
    else:
        source = await db.get(CompanyKnowledge, int(raw_id))
        if not source or source.organization_id != actor.organization_id or not source.is_active:
            return {"status": "empty", "data": {}}
        policy = await db.scalar(select(ResourcePolicy).where(ResourcePolicy.organization_id == actor.organization_id, ResourcePolicy.resource_type == "company_knowledge", ResourcePolicy.resource_id == source.id))
        if not await enterprise_tools.can_read_policy(db, actor, policy):
            return {"status": "empty", "data": {}}
    chunks = list((await db.execute(select(KnowledgeChunk).where(KnowledgeChunk.document_id == document.id).order_by(KnowledgeChunk.position).limit(2))).scalars().all())
    return {
        "status": "ok" if chunks else "empty",
        "data": {"title": document.title, "reference": reference, "passages": [{"excerpt": chunk.content[:1200], "locator": chunk.locator} for chunk in chunks]},
    }


def _safe_pending_action(actor: ActorContext, pending_action: dict, *, channel: str) -> dict:
    """Replace the legacy action token and all physical identifiers.

    The trusted Web/Telegram confirmation endpoint accepts the resulting
    opaque reference as its existing ``token`` parameter, preserving one
    confirmation path while ensuring the model never receives a usable
    database identifier or pending-action secret.
    """
    pending = dict(pending_action)
    token = pending.pop("token", None)
    for key in tuple(pending):
        if key == "id" or key.endswith("_id"):
            pending.pop(key, None)
    if token:
        pending["action_reference"] = action_reference(actor, token=token, channel=channel)
    return pending


async def execute(db, actor: ActorContext, *, tool_name: str, arguments: dict, channel: str, request_id: str, conversation_id: int | None = None) -> dict:
    """Validate, execute, redact, and wrap a single MCP tool call."""
    try:
        arguments = _sanitize_arguments(arguments)
        if tool_name == "oyuns_knowledge_search":
            data = schemas.KnowledgeSearchInput.model_validate(arguments)
            result = await enterprise_tools.execute(db, actor, "file_search_tool", {"operation": "search", "query": data.query, "search_mode": data.search_mode, "file_types": data.file_types, "limit": data.limit, "delivery": "none"}, channel=channel, prompt=data.query, conversation_id=conversation_id)
            rows = result.get("data", {}).get("results", [])
            items = [{"reference": resource_reference(actor, "knowledge_source", row["source_id"]), "title": row.get("title"), "excerpt": row.get("excerpt"), "locator": row.get("locator"), "classification": row.get("classification")} for row in rows]
            sources = [{"reference": item["reference"], "title": item["title"], "locator": item.get("locator")} for item in items]
            return envelope(result=result, request_id=request_id, summary=_summary(result, f"Found {len(items)} authorized knowledge passages."), data={"items": items}, sources=sources)

        if tool_name == "oyuns_knowledge_fetch":
            data = schemas.KnowledgeFetchInput.model_validate(arguments)
            result = await _knowledge_fetch(db, actor, data.reference)
            return envelope(result=result, request_id=request_id, summary=_summary(result, "Retrieved the authorized knowledge excerpt."))

        if tool_name == "oyuns_records_search":
            data = schemas.RecordsSearchInput.model_validate(arguments)
            result = await _directory(db, actor, query=data.query, include_inactive=data.include_inactive, limit=data.limit)
            return envelope(result=result, request_id=request_id, summary=_summary(result, f"Found {len(result.get('data', {}).get('items', []))} authorized employees."))

        if tool_name == "oyuns_records_get":
            data = schemas.RecordsGetInput.model_validate(arguments)
            value = resolve_resource_reference(actor, data.reference, kind="employee")
            employee = await db.get(Employee, int(value)) if str(value).isdigit() else None
            employees = await enterprise_tools._organization_employees(db, actor, include_inactive=actor.has_any_role("admin", "manager"))
            if not employee or employee.id not in {item.id for item in employees}:
                result = {"status": "empty", "data": {}}
            else:
                result = {"status": "ok", "data": {"reference": data.reference, "name": employee.name, "job_title": employee.job_title, "telegram_username": employee.telegram_username, "is_active": employee.is_active}}
            return envelope(result=result, request_id=request_id, summary=_summary(result, "Retrieved the authorized employee record."))

        if tool_name == "oyuns_records_aggregate":
            data = schemas.RecordsAggregateInput.model_validate(arguments)
            employees = await enterprise_tools._organization_employees(db, actor, include_inactive=actor.has_any_role("admin", "manager"))
            key = (lambda employee: "active" if employee.is_active else "inactive") if data.group_by == "active_status" else (lambda employee: employee.job_title or "Unspecified")
            result = {"status": "ok", "data": {"entity": "employees", "group_by": data.group_by, "groups": dict(sorted(Counter(key(employee) for employee in employees).items()))}}
            return envelope(result=result, request_id=request_id, summary="Returned the authorized employee aggregate.")

        if tool_name in {"oyuns_tasks_search", "oyuns_projects_search"}:
            data = (schemas.TasksSearchInput if tool_name == "oyuns_tasks_search" else schemas.ProjectsSearchInput).model_validate(arguments)
            employee_id = resolve_resource_reference(actor, data.employee_reference, kind="employee") if data.employee_reference else None
            project_id = resolve_resource_reference(actor, data.project_reference, kind="project") if data.project_reference else None
            entity = "tasks" if tool_name == "oyuns_tasks_search" else data.entity
            payload: dict[str, Any] = {"operation": "query", "entity": entity, "completion_state": data.completion_state, "active_only": data.active_only, "limit": data.limit, "employee_id": int(employee_id) if employee_id is not None else None, "project_id": int(project_id) if project_id is not None else None, "date_from": data.date_from, "date_to": data.date_to}
            if tool_name == "oyuns_tasks_search":
                payload.update({"workflow_status": data.workflow_status, "blockers_only": data.blockers_only})
            result = await enterprise_tools.execute(db, actor, "project_mgmt_tool", payload, channel=channel, prompt="MCP enterprise query", conversation_id=conversation_id)
            collection_key = {"tasks": "tasks", "projects": "projects", "plans": "plans", "milestones": "milestones"}[entity]
            rows = result.get("data", {}).get(collection_key, [])
            items = []
            for row in rows:
                item = dict(row)
                raw_id = item.pop("id", None)
                if raw_id is not None and entity in {"tasks", "projects"}:
                    item["reference"] = resource_reference(actor, "task" if entity == "tasks" else "project", raw_id)
                item.pop("project_id", None)
                items.append(item)
            return envelope(result=result, request_id=request_id, summary=_summary(result, f"Found {len(items)} authorized {entity}."), data={"items": items})

        if tool_name == "oyuns_calendar_availability":
            data = schemas.CalendarAvailabilityInput.model_validate(arguments)
            employee_id = resolve_resource_reference(actor, data.employee_reference, kind="employee") if data.employee_reference else None
            result = await enterprise_tools.execute(db, actor, "calendar_tool", {"intent": data.intent, "timeframe": data.timeframe, "date_from": data.date_from, "date_to": data.date_to, "scope": data.scope, "employee_id": int(employee_id) if employee_id is not None else None, "timezone_name": data.timezone_name}, channel=channel, prompt="MCP calendar query", conversation_id=conversation_id)
            return envelope(result=result, request_id=request_id, summary=_summary(result, "Returned authorized calendar availability."), data={"items": result.get("data", {}).get("events", []), "date_from": result.get("data", {}).get("date_from"), "date_to": result.get("data", {}).get("date_to")})

        if tool_name == "oyuns_stats_get":
            data = schemas.StatsGetInput.model_validate(arguments)
            employee_id = resolve_resource_reference(actor, data.employee_reference, kind="employee") if data.employee_reference else None
            project_id = resolve_resource_reference(actor, data.project_reference, kind="project") if data.project_reference else None
            result = await enterprise_tools.execute(db, actor, "get_stats_tool", {"metrics": data.metrics, "timeframe": data.timeframe, "date_from": data.date_from, "date_to": data.date_to, "employee_id": int(employee_id) if employee_id is not None else None, "project_id": int(project_id) if project_id is not None else None, "compare_previous": data.compare_previous, "presentation": data.presentation}, channel=channel, prompt="MCP statistics query", conversation_id=conversation_id)
            return envelope(result=result, request_id=request_id, summary=_summary(result, "Returned authorized OYUNS metrics."))

        if tool_name == "oyuns_erp_read":
            data = schemas.ERPReadInput.model_validate(arguments)
            result = await enterprise_tools.execute(db, actor, "erp_query_tool", data.model_dump(mode="json"), channel=channel, prompt="MCP ERP read", conversation_id=conversation_id)
            # ERP document numbers and totals are business identifiers, not
            # database references. The adapter intentionally strips all IDs.
            safe = result.get("data", {})
            if "stock_balances" in safe:
                safe = {"stock_balances": [{"quantity": row.get("quantity"), "value": row.get("value")} for row in safe["stock_balances"]]}
            return envelope(result=result, request_id=request_id, summary=_summary(result, "Returned authorized ERP data."), data=safe)

        if tool_name == "oyuns_exchange_rate_get":
            data = schemas.ExchangeRateInput.model_validate(arguments)
            result = await exchange_rate_service.get_exchange_rate(
                provider=data.provider,
                pair=data.pair,
                force_refresh=data.force_refresh,
                request_type=data.request_type,
            )
            status = "ok" if result.get("ok", True) else "unavailable"
            return envelope(result={"status": status, "data": result}, request_id=request_id,
                            summary="Returned the requested exchange rate." if status == "ok" else "The exchange-rate service is unavailable.",
                            data=result)

        if tool_name == "oyuns_tasks_prepare_create":
            data = schemas.TaskPrepareCreateInput.model_validate(arguments)
            action_type = "delegate_task" if data.assignee and data.assignee.casefold() not in {"self", "me", "myself", "би", "өөрөө", "надад", "өөртөө"} else "create_task"
            result = await enterprise_tools.execute(db, actor, action_type, data.model_dump(mode="json"), channel=channel, prompt=data.title, conversation_id=conversation_id)
            pending = _safe_pending_action(actor, result.get("data", {}).get("pending_action") or {}, channel=channel)
            safe = {"pending_action": pending} if pending else {}
            return envelope(result=result, request_id=request_id, summary=_summary(result, "Task preview created. Ask the user to confirm it in the current channel."), data=safe)

        if tool_name == "oyuns_tasks_prepare_update":
            data = schemas.TaskPrepareUpdateInput.model_validate(arguments)
            value = resolve_resource_reference(actor, data.task_reference, kind="task")
            task = await db.scalar(select(Task).where(Task.organization_id == actor.organization_id, Task.public_id == str(value)))
            if not task:
                result = {"status": "empty", "data": {}}
            else:
                changes = {key: value for key, value in data.model_dump(exclude={"task_reference"}, exclude_none=True, mode="json").items()}
                result = await enterprise_tools.execute(db, actor, "project_mgmt_update_tool", {"operation": "update_task", "task_id": task.id, "changes": changes}, channel=channel, prompt="MCP task update", conversation_id=conversation_id)
            pending = _safe_pending_action(actor, result.get("data", {}).get("pending_action") or {}, channel=channel)
            return envelope(result=result, request_id=request_id, summary=_summary(result, "Task update preview created. Ask the user to confirm it in the current channel."), data={"pending_action": pending} if pending else {})

        return envelope(result={"status": "denied", "data": {}, "warnings": ["INVALID_INPUT"]}, request_id=request_id, summary="Unknown MCP tool.")
    except ValueError as exc:
        return envelope(result={"status": "denied", "data": {}, "warnings": ["INVALID_INPUT"]}, request_id=request_id, summary=str(exc))
    except Exception:
        return envelope(result={"status": "unavailable", "data": {}}, request_id=request_id, summary="The requested OYUNS capability is temporarily unavailable.")
