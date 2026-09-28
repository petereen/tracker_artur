"""Tool failures the user can fix must not read as a permission restriction."""
import asyncio

import pytest
from pydantic import ValidationError

from app.core.enterprise_deps import ActorContext
from app.services import enterprise_tools
from app.services.enterprise_tools import AssistantTaskInput, ToolAccessDenied, _is_personal_meeting_task, _is_self_meeting_task
from app.services.mcp import adapters
from app.services.mcp.schemas import KnowledgeSearchInput


def _actor() -> ActorContext:
    return ActorContext(
        account_id=7,
        organization_id=3,
        employee_id=9,
        email="person@example.test",
        locale="mn",
        roles=frozenset({"member"}),
    )


def _execute(tool_name: str, arguments: dict) -> dict:
    return asyncio.run(adapters.execute(None, _actor(), tool_name=tool_name, arguments=arguments, channel="web", request_id="req-1"))


@pytest.mark.parametrize("title,assignee", [
    ("Анужин хуульчтай хурал", "self"),
    ("Анужин менежертэй хурал", None),
    ("Хурал", "self"),
])
def test_own_meeting_with_named_attendee_is_a_self_task(title, assignee):
    task = AssistantTaskInput(title=title, assignee=assignee, participants=["Анужин хуульч"])
    assert _is_self_meeting_task(task, action_type="create_task") is True


def test_meeting_delegated_to_someone_else_is_not_forced_to_self():
    task = AssistantTaskInput(title="Хурал бэлтгэх", assignee="Бат", participants=["Бат"])
    assert _is_personal_meeting_task(task) is False


def test_invalid_task_arguments_are_invalid_input_not_denied():
    result = _execute("oyuns_tasks_prepare_create", {"title": " ", "description": None, "assignee": "self", "participants": None, "reviewer": None, "priority": 2, "start_at": None, "deadline_at": None, "project_ref": None})
    assert result["status"] == "invalid_input"
    assert "title" in result["data"]["reason"]
    assert "ACCESS_DENIED" not in result["warnings"]


def test_free_text_with_line_breaks_and_semicolons_is_accepted():
    assert adapters._sanitize_arguments("Хурал; оффист\nАнужинтай") == "Хурал; оффист\nАнужинтай"
    with pytest.raises(ValueError):
        adapters._sanitize_arguments("bad\x00text")


def test_unresolved_person_reason_reaches_the_model(monkeypatch):
    async def prepare(*_args, **_kwargs):
        raise ValueError("The person 'Анужин хуульч' was not found in the employee directory. Ask the user for the exact employee name or @username.")

    async def audit(*_args, **_kwargs):
        return None

    monkeypatch.setattr(enterprise_tools, "prepare_task_creation", prepare)
    monkeypatch.setattr(enterprise_tools, "audit_tool", audit)
    result = _execute("oyuns_tasks_prepare_create", {"title": "Төсөл", "description": None, "assignee": "self", "participants": ["Анужин хуульч"], "reviewer": None, "priority": 2, "start_at": None, "deadline_at": None, "project_ref": None})
    assert result["status"] == "invalid_input"
    assert "Анужин хуульч" in result["data"]["reason"]


def test_real_permission_failure_stays_denied_with_reason(monkeypatch):
    async def prepare(*_args, **_kwargs):
        raise ToolAccessDenied("Your role is not authorized to assign work to another employee.")

    async def audit(*_args, **_kwargs):
        return None

    monkeypatch.setattr(enterprise_tools, "prepare_task_creation", prepare)
    monkeypatch.setattr(enterprise_tools, "audit_tool", audit)
    result = _execute("oyuns_tasks_prepare_create", {"title": "Тайлан", "description": None, "assignee": "Бат", "participants": None, "reviewer": None, "priority": 2, "start_at": None, "deadline_at": None, "project_ref": None})
    assert result["status"] == "denied"
    assert "not authorized" in result["data"]["reason"]


def test_knowledge_list_browses_files_without_a_query(monkeypatch):
    assert KnowledgeSearchInput(operation="list", query=None).query is None
    with pytest.raises(ValidationError):
        KnowledgeSearchInput(operation="search", query=None)
    captured = {}

    async def execute(_db, _actor, tool_name, arguments, **_kwargs):
        captured.update(arguments)
        return {"status": "ok", "data": {"results": [{"source_id": "company_file:5", "title": "Дүрэм.pdf", "kind": "file"}]}, "sources": [], "deliveries": [], "warnings": []}

    monkeypatch.setattr(enterprise_tools, "execute", execute)
    result = _execute("oyuns_knowledge_search", {"operation": "list", "query": None, "search_mode": "hybrid", "file_types": [], "limit": 20, "delivery": "none"})
    assert captured["operation"] == "list"
    assert captured["limit"] == 20
    assert result["status"] == "ok"
    assert result["data"]["items"][0]["title"] == "Дүрэм.pdf"
