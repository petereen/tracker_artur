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
    _chunks,
    attachment_metadata,
    _is_personal_meeting_task,
    _is_self_meeting_task,
    _meeting_description,
    extract_content,
    wants_file_attachment,
)
from app.core.enterprise_deps import ActorContext
from app.services.mcp.catalog import CATALOG, _strict_schema
from app.models.models import ResourceGrant, ResourcePolicy


def test_tool_schemas_are_strict_and_bounded():
    assert FileSearchInput(query="leave policy", limit=10).limit == 10
    with pytest.raises(ValidationError):
        FileSearchInput(query="policy", unexpected=True)
    with pytest.raises(ValidationError):
        FileSearchInput(query="policy", limit=31)


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

    for tool in CATALOG:
        visit(_strict_schema(tool.model))


def test_governed_tool_inputs_cover_the_public_contract():
    assert StatsInput(metrics=["task_completion"], timeframe="today").metrics == ["task_completion"]
    assert ProjectQueryInput(entity="milestones").entity == "milestones"
    assert ProjectQueryInput(entity="plans").entity == "plans"
    assert CalendarInput(intent="availability", scope="team").scope == "team"
    preview = ProjectUpdateInput(operation="update_task", task_id=4, changes={"workflow_status": "done"})
    assert preview.changes.workflow_status == "done"
    task = AssistantTaskInput(title="Prepare access review", assignee="Ada", priority=1, start_at="2026-06-02T08:00:00+08:00")
    assert task.assignee == "Ada"
    assert task.start_at is not None
    participants = AssistantTaskInput(title="Team review", participants=["Ada", "Bat"])
    assert participants.participants == ["Ada", "Bat"]
    with pytest.raises(ValidationError):
        AssistantTaskInput(title=" ")
    with pytest.raises(ValidationError):
        DelegateTaskInput(title="Prepare access review")
    with pytest.raises(ValidationError):
        AssistantTaskInput(title="Task", organization_id=1)


def test_meeting_attendees_do_not_become_delegated_task_assignees():
    meeting = AssistantTaskInput(
        title="Хурал",
        description="Маргааш 17 цагаас оффист Анужин менежертэй хуралтай",
        assignee="self",
        participants=["Анужин менежер"],
    )
    assert _is_self_meeting_task(meeting, action_type="create_task") is True
    assert _is_self_meeting_task(meeting, action_type="delegate_task") is False
    named_assignee = meeting.model_copy(update={"assignee": "Анужин менежер"})
    assert _is_personal_meeting_task(named_assignee) is True
    assert _meeting_description(meeting) == (
        "Маргааш 17 цагаас оффист Анужин менежертэй хуралтай\n"
        "Оролцогчид: Анужин менежер"
    )


def test_text_extraction_produces_safe_locations_and_overlap_chunks():
    text = " ".join(f"word{number}" for number in range(1_000)).encode()
    extracted = extract_content("policy.md", text)
    assert extracted
    assert extracted[0][1]["kind"] == "line"
    chunks = _chunks(" ".join(f"word{number}" for number in range(1_000)), {"section": "A"})
    assert len(chunks) == 2
    assert chunks[1][1]["word_start"] == 680


def test_explicit_file_delivery_requests_create_safe_attachment_metadata():
    assert wants_file_attachment("Надад leave policy файлыг хавсаргаж өгөөч") is True
    assert wants_file_attachment("файлын жагсаалтыг харуул") is False
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
