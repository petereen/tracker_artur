import asyncio

from pydantic import ValidationError
import pytest

from app.services.enterprise_tools import (
    AssistantTaskInput,
    CalendarInput,
    can_read_policy,
    DelegateTaskInput,
    FileSearchInput,
    ProjectQueryInput,
    ProjectUpdateInput,
    StatsInput,
    _capability_answer,
    _chunks,
    attachment_metadata,
    _offline_route,
    is_high_confidence_request,
    extract_content,
    tool_specs,
    wants_file_attachment,
)
from app.core.enterprise_deps import ActorContext
from app.models.models import ResourceGrant, ResourcePolicy


def test_tool_schemas_are_strict_and_bounded():
    assert FileSearchInput(query="leave policy", limit=10).limit == 10
    with pytest.raises(ValidationError):
        FileSearchInput(query="policy", unexpected=True)
    with pytest.raises(ValidationError):
        FileSearchInput(query="policy", limit=11)


def test_file_search_supports_directory_listing_without_a_query():
    assert FileSearchInput(operation="list", folder_id=None).query is None
    with pytest.raises(ValidationError):
        FileSearchInput(operation="search")


def test_all_enterprise_function_schemas_satisfy_responses_strict_mode():
    def visit(node):
        if isinstance(node, dict):
            properties = node.get("properties")
            if isinstance(properties, dict):
                assert node.get("additionalProperties") is False
                assert set(node.get("required", [])) == set(properties)
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    for spec in tool_specs():
        visit(spec["parameters"])


def test_governed_tool_inputs_cover_the_public_contract():
    assert StatsInput(metrics=["task_completion"], timeframe="today").metrics == ["task_completion"]
    assert ProjectQueryInput(entity="milestones").entity == "milestones"
    assert ProjectQueryInput(entity="plans").entity == "plans"
    assert CalendarInput(intent="availability", scope="team").scope == "team"
    preview = ProjectUpdateInput(operation="update_task", task_id=4, changes={"workflow_status": "done"})
    assert preview.changes.workflow_status == "done"
    assert {spec["name"] for spec in tool_specs()} == {"file_search_tool", "get_stats_tool", "project_mgmt_tool", "project_mgmt_update_tool", "calendar_tool", "employee_directory_tool", "create_task", "delegate_task"}
    task = AssistantTaskInput(title="Prepare access review", assignee="Ada", priority=1)
    assert task.assignee == "Ada"
    with pytest.raises(ValidationError):
        AssistantTaskInput(title=" ")
    with pytest.raises(ValidationError):
        DelegateTaskInput(title="Prepare access review")
    with pytest.raises(ValidationError):
        AssistantTaskInput(title="Task", organization_id=1)


def test_text_extraction_produces_safe_locations_and_overlap_chunks():
    text = " ".join(f"word{number}" for number in range(1_000)).encode()
    extracted = extract_content("policy.md", text)
    assert extracted
    assert extracted[0][1]["kind"] == "line"
    chunks = _chunks(" ".join(f"word{number}" for number in range(1_000)), {"section": "A"})
    assert len(chunks) == 2
    assert chunks[1][1]["word_start"] == 680


def test_offline_route_recognizes_mongolian_enterprise_requests():
    assert _offline_route("файлын сангаас powerpoint template ол") == (
        "file_search_tool",
        {"query": "файлын сангаас powerpoint template ол", "file_types": [], "limit": 5, "delivery": "none"},
    )
    assert _offline_route("Ажилчдын жагсаалт") == (
        "employee_directory_tool",
        {"include_inactive": False},
    )
    assert _offline_route("компанийн төлөвлөгөө юу вэ") == (
        "project_mgmt_tool",
        {"operation": "query", "entity": "plans", "completion_state": "all", "limit": 20},
    )
    assert _offline_route("компанийн хийгдэж буй төслүүд байгаа юу?") == (
        "project_mgmt_tool",
        {"operation": "query", "entity": "projects", "completion_state": "all", "active_only": True, "limit": 20},
    )
    assert _offline_route("файлын санд ямар файлууд байна?") == (
        "file_search_tool",
        {"operation": "list", "folder_id": None, "file_types": [], "limit": 10, "delivery": "none"},
    )


def test_explicit_file_delivery_requests_create_safe_attachment_metadata():
    assert wants_file_attachment("Надад leave policy файлыг хавсаргаж өгөөч") is True
    assert wants_file_attachment("файлын жагсаалтыг харуул") is False
    assert _offline_route("Надад powerpoint template-ийг илгээ") == (
        "file_search_tool",
        {"query": "Надад powerpoint template-ийг илгээ", "file_types": [], "limit": 5, "delivery": "attachment"},
    )
    deliveries = [
        {"kind": "company_file_attachment", "item_id": 7, "filename": "policy.pdf", "content_type": "application/pdf", "size": 12},
        {"kind": "company_file_attachment", "item_id": 7, "filename": "policy.pdf", "content_type": "application/pdf", "size": 12},
    ]
    assert attachment_metadata(deliveries) == [{
        "item_id": 7,
        "filename": "policy.pdf",
        "content_type": "application/pdf",
        "size": 12,
        "download_url": "/v1/company-files/7/download",
    }]


def test_offline_capability_answer_is_mongolian():
    answer = _capability_answer("Чи юу хийж чадах вэ")
    assert "компанийн файлуудаас" in answer
    assert "календарь" in answer


def test_high_confidence_requests_bypass_legacy_unknown_fallback():
    assert is_high_confidence_request("Чи юу хийж чадах вэ")
    assert is_high_confidence_request("файлын сангаас powerpoint template ол")
    assert is_high_confidence_request("Ажилчдын жагсаалт")
    assert is_high_confidence_request("компанийн төлөвлөгөө юу вэ")
    assert is_high_confidence_request("компанийн хийгдэж буй төслүүд байгаа юу?")


class _GrantRows:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return self.rows


class _AclDb:
    def __init__(self, grants):
        self.grants = grants

    async def execute(self, _statement):
        return _GrantRows(self.grants)


def test_restricted_resource_requires_an_explicit_account_grant():
    policy = ResourcePolicy(id=9, classification="restricted")
    actor = ActorContext(account_id=3, organization_id=1, employee_id=4, email="member@example.com", locale="mn", roles=frozenset({"member"}))
    assert asyncio.run(can_read_policy(_AclDb([]), actor, policy)) is False
    grant = ResourceGrant(policy_id=9, principal_type="account", principal_key="3")
    assert asyncio.run(can_read_policy(_AclDb([grant]), actor, policy)) is True
