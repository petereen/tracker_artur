"""Private Jev evaluator client and deterministic local-read helpers."""
from __future__ import annotations

import asyncio
import calendar as calendar_module
import logging
import math
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import aiohttp
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.enterprise_deps import ActorContext
from app.services import enterprise_tools
from app.services.ai_gateway.tools.registry import ToolRegistry
from app.services.exchange_rate_service import normalize_mongolbank_pair
from app.services.mcp import schemas

log = logging.getLogger(__name__)

LOCAL_TO_TOOL = {
    "knowledge_search": "oyuns_knowledge_search",
    "employee_lookup": "oyuns_records_search",
    "employee_count": "oyuns_records_aggregate",
    "tasks_lookup": "oyuns_tasks_search",
    "projects_lookup": "oyuns_projects_search",
    "calendar_lookup": "oyuns_calendar_availability",
    "stats_lookup": "oyuns_stats_get",
    "erp_lookup": "oyuns_erp_read",
    "exchange_rate_lookup": "oyuns_exchange_rate_get",
}

_CURRENCY_NAMES = {
    "usd": "USD", "доллар": "USD", "амдоллар": "USD", "dollar": "USD",
    "eur": "EUR", "евро": "EUR", "euro": "EUR",
    "cny": "CNY", "юань": "CNY", "yuan": "CNY",
    "jpy": "JPY", "иен": "JPY", "yen": "JPY",
    "rub": "RUB", "рубль": "RUB", "ruble": "RUB",
    "krw": "KRW", "вон": "KRW", "won": "KRW",
}


@dataclass(slots=True)
class JevEvaluation:
    route: str
    confidence: float
    probabilities: dict[str, float]
    arguments: dict[str, Any]
    model: str
    usage: dict[str, Any]


class JevUnavailable(RuntimeError):
    pass


def _date_window(name: str, now: date) -> tuple[str | None, str | None]:
    if name == "today":
        value = now.isoformat()
        return value, value
    if name == "this_week":
        start = now - timedelta(days=now.weekday())
        return start.isoformat(), (start + timedelta(days=6)).isoformat()
    if name == "this_month":
        start = now.replace(day=1)
        end = now.replace(day=calendar_module.monthrange(now.year, now.month)[1])
        return start.isoformat(), end.isoformat()
    return None, None


def _mentions_write(text: str) -> bool:
    lowered = text.casefold()
    return any(term in lowered for term in (
        "create", "assign", "delegate", "update", "change", "delete", "cancel", "создай", "назнач", "обнов", "устга", "үүсгэ", "өг", "оноо",
    ))


def _currency_pair(text: str) -> str | None:
    lowered = text.casefold()
    match = re.search(r"\b([a-z]{3})\s*(?:/|to|->)\s*([a-z]{3})\b", lowered)
    if match:
        return f"{match.group(1).upper()}/{match.group(2).upper()}"
    for key, code in _CURRENCY_NAMES.items():
        if key in lowered:
            return normalize_mongolbank_pair(code)
    return None


def _route_args(route: str, request_text: str, arguments: dict[str, Any], actor: ActorContext, now: date) -> tuple[str, dict[str, Any]] | None:
    if _mentions_write(request_text):
        return None
    timeframe = str(arguments.get("timeframe") or "unspecified")
    date_from, date_to = _date_window(timeframe, now)
    if timeframe == "custom":
        return None
    scope = str(arguments.get("scope") or "unspecified")
    employee_reference = None
    if scope == "self" or (scope == "unspecified" and any(term in request_text.casefold() for term in ("my", "mine", "миний", "надад", "би", "мои", "моих"))):
        if actor.employee_id is None:
            return None
        from app.services.mcp.references import resource_reference
        employee_reference = resource_reference(actor, "employee", actor.employee_id)

    if route == "knowledge_search":
        if enterprise_tools.wants_file_attachment(request_text):
            return None
        return LOCAL_TO_TOOL[route], schemas.KnowledgeSearchInput(query=request_text[:500], search_mode="hybrid", file_types=[], limit=5, delivery="none").model_dump(mode="json")
    if route == "employee_lookup":
        return LOCAL_TO_TOOL[route], schemas.RecordsSearchInput(query=None, include_inactive=False, limit=10).model_dump(mode="json")
    if route == "employee_count":
        group_by = "job_title" if any(term in request_text.casefold() for term in ("job", "title", "албан тушаал", "должност")) else "active_status"
        return LOCAL_TO_TOOL[route], schemas.RecordsAggregateInput(group_by=group_by).model_dump(mode="json")
    if route == "tasks_lookup":
        completion = str(arguments.get("completion_state") or "open")
        completion = completion if completion in {"open", "completed", "all"} else "open"
        return LOCAL_TO_TOOL[route], schemas.TasksSearchInput(completion_state=completion, workflow_status=None, blockers_only=False, active_only=False, limit=10, employee_reference=employee_reference, project_reference=None, date_from=date_from, date_to=date_to).model_dump(mode="json")
    if route == "projects_lookup":
        completion = str(arguments.get("completion_state") or "open")
        completion = completion if completion in {"open", "completed", "all"} else "open"
        entity = str(arguments.get("project_entity") or "projects")
        entity = entity if entity in {"projects", "plans", "milestones"} else "projects"
        return LOCAL_TO_TOOL[route], schemas.ProjectsSearchInput(entity=entity, completion_state=completion, active_only=False, limit=10, employee_reference=employee_reference, project_reference=None, date_from=date_from, date_to=date_to).model_dump(mode="json")
    if route == "calendar_lookup":
        intent = str(arguments.get("calendar_intent") or "availability")
        intent = intent if intent in {"events", "schedule", "availability"} else "availability"
        calendar_timeframe = timeframe if timeframe in {"today", "this_week", "custom"} else "today"
        return LOCAL_TO_TOOL[route], schemas.CalendarAvailabilityInput(intent=intent, timeframe=calendar_timeframe, date_from=date_from, date_to=date_to, scope=scope if scope in {"self", "team", "organization"} else "self", employee_reference=employee_reference, timezone_name=None).model_dump(mode="json")
    if route == "stats_lookup":
        metric = str(arguments.get("stats_metric") or "task_completion")
        if metric not in {"task_completion", "deadline_health", "work_hours", "utilization", "billable_ratio", "report_compliance", "active_projects", "budget_burn"}:
            return None
        stats_timeframe = timeframe if timeframe in {"today", "this_week", "this_month", "custom"} else "this_week"
        return LOCAL_TO_TOOL[route], schemas.StatsGetInput(metrics=[metric], timeframe=stats_timeframe, date_from=date_from, date_to=date_to, employee_reference=employee_reference, project_reference=None, compare_previous=False, presentation="summary").model_dump(mode="json")
    if route == "erp_lookup":
        resource = str(arguments.get("erp_resource") or "dashboard")
        if resource not in {"dashboard", "documents"}:
            return None
        return LOCAL_TO_TOOL[route], schemas.ERPReadInput(resource=resource, document_type=None, limit=10).model_dump(mode="json")
    if route == "exchange_rate_lookup":
        request_type = str(arguments.get("exchange_request_type") or "single")
        request_type = request_type if request_type in {"single", "all", "calculated"} else "single"
        pair = "all" if request_type == "all" else (str(arguments.get("currency_pair")) if arguments.get("currency_pair") not in {None, "", "unspecified"} else _currency_pair(request_text))
        if not pair:
            return None
        return LOCAL_TO_TOOL[route], schemas.ExchangeRateInput(provider="MongolBank", pair=pair, force_refresh=False, request_type=request_type).model_dump(mode="json")
    return None


async def resolve_local_route(db: Any, actor: ActorContext, evaluation: JevEvaluation, text: str, *, now: date) -> tuple[str, dict[str, Any]] | None:
    if evaluation.route not in LOCAL_TO_TOOL or evaluation.confidence <= float(settings.JEV_ROUTER_CONFIDENCE_THRESHOLD):
        return None
    if evaluation.route == "employee_lookup" and isinstance(db, AsyncSession):
        # A directory lookup is local only when the prompt names an authorized
        # employee. Broad directory listings remain safe but are classified as
        # employee_count by the evaluator.
        employees = await enterprise_tools._organization_employees(db, actor, include_inactive=False)
        lowered = text.casefold()
        matched = next((employee.name or employee.telegram_username for employee in employees if (employee.name and employee.name.casefold() in lowered) or (employee.telegram_username and employee.telegram_username.casefold() in lowered)), None)
        if not matched:
            if not any(term in lowered for term in ("list", "directory", "employees", "ажилтан", "ажилч", "сотрудник", "персонал")):
                return None
        resolved = _route_args(evaluation.route, text, evaluation.arguments, actor, now)
        if resolved and matched:
            tool_name, args = resolved
            args["query"] = matched
            return tool_name, args
        return resolved
    return _route_args(evaluation.route, text, evaluation.arguments, actor, now)


async def evaluate_remote(request: dict[str, Any]) -> JevEvaluation:
    if not settings.JEV_ROUTER_ENABLED or not settings.JEV_ROUTER_URL.strip() or not settings.JEV_ROUTER_SHARED_SECRET.strip():
        raise JevUnavailable("Jev router is not configured")
    headers = {"x-jev-router-secret": settings.JEV_ROUTER_SHARED_SECRET, "content-type": "application/json"}
    timeout = aiohttp.ClientTimeout(total=max(0.25, settings.JEV_ROUTER_TIMEOUT_SECONDS))
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(f"{settings.JEV_ROUTER_URL.rstrip('/')}/v1/evaluate", json=request, headers=headers) as response:
                if response.status != 200:
                    raise JevUnavailable(f"Jev router returned {response.status}")
                payload = await response.json()
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
        raise JevUnavailable("Jev router unavailable") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("route"), str):
        raise JevUnavailable("Invalid Jev response")
    confidence = float(payload.get("confidence", 0.0))
    if not math.isfinite(confidence) or confidence < 0 or confidence > 1:
        raise JevUnavailable("Invalid Jev confidence")
    raw_probabilities = payload.get("probabilities") or {}
    probabilities = {str(key): float(value) for key, value in raw_probabilities.items()}
    if any(not math.isfinite(value) or value < 0 or value > 1 for value in probabilities.values()):
        raise JevUnavailable("Invalid Jev probabilities")
    return JevEvaluation(
        route=payload["route"],
        confidence=confidence,
        probabilities=probabilities,
        arguments=dict(payload.get("arguments") or {}),
        model=str(payload.get("model") or settings.JEV_ROUTER_MODEL),
        usage=dict(payload.get("usage") or {}),
    )


def allowed_handlers(registry: ToolRegistry, actor: ActorContext) -> list[str]:
    names = {definition.name for definition in registry.visible_definitions(actor)}
    return [route for route, tool in LOCAL_TO_TOOL.items() if tool in names]
