from pydantic import ValidationError
import pytest

from app.services.enterprise_tools import (
    CalendarInput,
    FileSearchInput,
    ProjectQueryInput,
    ProjectUpdateInput,
    StatsInput,
    _capability_answer,
    _chunks,
    _offline_route,
    is_high_confidence_request,
    extract_content,
    tool_specs,
)


def test_tool_schemas_are_strict_and_bounded():
    assert FileSearchInput(query="leave policy", limit=10).limit == 10
    with pytest.raises(ValidationError):
        FileSearchInput(query="policy", unexpected=True)
    with pytest.raises(ValidationError):
        FileSearchInput(query="policy", limit=11)


def test_governed_tool_inputs_cover_the_public_contract():
    assert StatsInput(metrics=["task_completion"], timeframe="today").metrics == ["task_completion"]
    assert ProjectQueryInput(entity="milestones").entity == "milestones"
    assert ProjectQueryInput(entity="plans").entity == "plans"
    assert CalendarInput(intent="availability", scope="team").scope == "team"
    preview = ProjectUpdateInput(operation="update_task", task_id=4, changes={"workflow_status": "done"})
    assert preview.changes.workflow_status == "done"
    assert {spec["name"] for spec in tool_specs()} == {"file_search_tool", "get_stats_tool", "project_mgmt_tool", "project_mgmt_update_tool", "calendar_tool", "employee_directory_tool"}


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
        {"query": "файлын сангаас powerpoint template ол", "file_types": ["pptx", "potx", "potm"], "limit": 5, "delivery": "none"},
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
