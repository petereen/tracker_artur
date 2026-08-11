from pydantic import ValidationError
import pytest

from app.services.enterprise_tools import (
    CalendarInput,
    FileSearchInput,
    ProjectQueryInput,
    ProjectUpdateInput,
    StatsInput,
    _chunks,
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
    assert CalendarInput(intent="availability", scope="team").scope == "team"
    preview = ProjectUpdateInput(operation="update_task", task_id=4, changes={"workflow_status": "done"})
    assert preview.changes.workflow_status == "done"
    assert {spec["name"] for spec in tool_specs()} == {"file_search_tool", "get_stats_tool", "project_mgmt_tool", "project_mgmt_update_tool", "calendar_tool"}


def test_text_extraction_produces_safe_locations_and_overlap_chunks():
    text = " ".join(f"word{number}" for number in range(1_000)).encode()
    extracted = extract_content("policy.md", text)
    assert extracted
    assert extracted[0][1]["kind"] == "line"
    chunks = _chunks(" ".join(f"word{number}" for number in range(1_000)), {"section": "A"})
    assert len(chunks) == 2
    assert chunks[1][1]["word_start"] == 680
