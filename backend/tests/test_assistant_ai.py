from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from app.services.assistant_ai import (
    AssistantIntent,
    AssistantLanguage,
    AssistantReply,
    AssistantToolName,
    DateRangeKind,
    IntentClassification,
    PlanBlock,
    RouteDecision,
    RouterIntent,
    TaskScope,
    WorkPlan,
    classify_intent,
    detect_language,
    generate_general_reply,
    fallback_route,
    is_scheduled_task,
    is_task_query,
    is_worker_directory_query,
    is_information_question,
    native_tool_specs,
    normalize_work_plan,
    parse_native_tool_message,
)


def test_acceptance_routes_delegate_task():
    decision = fallback_route(
        "Assign review of the landing page to @alex by 5 PM.",
        is_manager=True,
    )
    assert decision.intent == AssistantIntent.DELEGATE_TASK


def test_acceptance_routes_today_priorities():
    decision = fallback_route("What are my priorities for today?")
    assert decision.intent == AssistantIntent.QUERY_MY_TASKS
    assert decision.date_range == DateRangeKind.TODAY


def test_acceptance_routes_three_hour_plan():
    decision = fallback_route(
        "I have 3 hours today, help me plan how to tackle my pending tasks."
    )
    assert decision.intent == AssistantIntent.PLAN_WORK
    assert decision.time_budget_minutes == 180


def test_acceptance_routes_capabilities():
    decision = fallback_route("What can you do to help my workflow?")
    assert decision.intent == AssistantIntent.DISCOVER_CAPABILITIES


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Please plan my work", AssistantLanguage.EN),
        ("Мои задачи на сегодня", AssistantLanguage.RU),
        ("Миний өнөөдрийн даалгавар", AssistantLanguage.MN),
    ],
)
def test_language_detection(text, expected):
    assert detect_language(text) == expected


def test_non_manager_team_scope_is_not_inferred():
    decision = fallback_route("Summarize the team workload")
    assert decision.task_scope == TaskScope.BOTH


def test_manager_team_scope_is_inferred():
    decision = fallback_route("Summarize the team workload", is_manager=True)
    assert decision.task_scope == TaskScope.TEAM
    assert decision.intent == AssistantIntent.GENERAL_PRODUCTIVITY


def test_manager_company_question_does_not_become_task():
    decision = fallback_route("What is our annual leave policy?", is_manager=True)
    assert decision.intent == AssistantIntent.GENERAL_PRODUCTIVITY


@pytest.mark.parametrize(
    "text",
    [
        "Show me the worker list",
        "Компаний ажилтны жагсаалт өг",
        "Ажилтнуудын жагсаалт харуул",
        "Покажи список сотрудников",
    ],
)
def test_worker_directory_requests_are_recognized(text):
    assert is_worker_directory_query(text)


def test_company_worker_list_is_detected_as_mongolian():
    assert detect_language("Компаний ажилтнуудын жагсаалт") == AssistantLanguage.MN


def test_mongolian_company_question_is_recognized():
    assert is_information_question("Чөлөө хэрхэн авах вэ?")


def test_manager_team_task_query_never_becomes_delegation():
    text = "Бүх ажилтны даалгавруудыг харуул"
    assert is_task_query(text)
    decision = fallback_route(text, is_manager=True)
    assert decision.intent == AssistantIntent.QUERY_MY_TASKS
    assert decision.task_scope == TaskScope.TEAM


def test_assigned_to_me_question_is_assigned_task_query():
    text = "Надад оногдсон даалгавар байна уу"
    assert is_task_query(text)
    decision = fallback_route(text, is_manager=True)
    assert decision.intent == AssistantIntent.QUERY_MY_TASKS
    assert decision.task_scope == TaskScope.ASSIGNED


@pytest.mark.parametrize(
    "text",
    [
        "Надад даалгавар маргааш 15 цагт хуралтай",
        "Маргааш би 15 цагаас хуралтай",
        "Маргааш анужин менежер 15 цагт хуралтай",
    ],
)
def test_mongolian_scheduled_meeting_is_a_task_draft(text):
    assert detect_language(text) == AssistantLanguage.MN
    assert is_scheduled_task(text)
    decision = fallback_route(text, is_manager=True)
    assert decision.intent == AssistantIntent.DELEGATE_TASK
    assert decision.router_intent == RouterIntent.CREATE_TASK


def test_ambiguous_manager_action_is_unknown_not_task_creation():
    decision = fallback_route("Prepare the weekly sales report", is_manager=True)
    assert decision.intent == AssistantIntent.GENERAL_PRODUCTIVITY
    assert decision.router_intent == RouterIntent.UNKNOWN


def test_public_router_contract_accepts_only_requested_fields():
    result = IntentClassification.model_validate(
        {"intent": "COMPANY_INFO", "confidence": 0.91}
    )
    assert result.intent == RouterIntent.COMPANY_INFO
    with pytest.raises(ValidationError):
        IntentClassification.model_validate(
            {"intent": "COMPANY_INFO", "confidence": 0.91, "language": "mn"}
        )


def _tool_message(name: str, arguments: dict) -> dict:
    return {
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(arguments, ensure_ascii=False),
                },
            }
        ]
    }


def test_native_tool_schemas_are_strict():
    assert [tool["function"]["name"] for tool in native_tool_specs()] == [
        "create_task_draft",
        "get_user_tasks",
        "search_company_knowledge",
    ]
    for tool in native_tool_specs():
        function = tool["function"]
        parameters = function["parameters"]
        assert function["strict"] is True
        assert parameters["additionalProperties"] is False
        assert set(parameters["required"]) == set(parameters["properties"])


def test_native_create_task_call_is_validated():
    selection = parse_native_tool_message(
        _tool_message(
            "create_task_draft",
            {
                "assignee": "Анужин менежер",
                "title": "Хуралд оролцох",
                "priority": 2,
                "due_date": "2026-07-24T15:00:00+08:00",
            },
        )
    )
    assert selection is not None
    assert selection.tool_name == AssistantToolName.CREATE_TASK
    assert selection.arguments["assignee"] == "Анужин менежер"


def test_native_tool_call_rejects_extra_or_invalid_arguments():
    assert (
        parse_native_tool_message(
            _tool_message(
                "get_user_tasks",
                {
                    "timeframe": "tomorrow",
                    "unexpected": True,
                },
            )
        )
        is None
    )
    assert (
        parse_native_tool_message(
            _tool_message(
                "create_task_draft",
                {
                    "assignee": "self",
                    "title": "Хурал",
                    "due_date": "2026-07-24T15:00:00",
                    "priority": 2,
                },
            )
        )
        is None
    )


def test_native_direct_answer_is_preserved():
    selection = parse_native_tool_message(
        {"content": "OYUNS can help organize corporate work."}
    )
    assert selection is not None
    assert selection.tool_name is None
    assert selection.direct_answer.startswith("OYUNS")


def test_capability_question_can_use_direct_model_answer(monkeypatch):
    async def native(**_kwargs):
        return parse_native_tool_message(
            {"content": "OYUNS can retrieve tasks, prepare drafts, and search policy."}
        )

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr("app.services.assistant_ai._call_native_router", native)
    decision = asyncio.run(
        classify_intent(
            "What can you do?",
            now=datetime.now(timezone.utc),
            timezone_name="Asia/Ulaanbaatar",
            is_manager=False,
            workers=[],
        )
    )
    assert decision.selected_tool is None
    assert decision.direct_answer is not None


def test_native_get_user_tasks_maps_to_planning(monkeypatch):
    async def native(**_kwargs):
        return parse_native_tool_message(
            _tool_message(
                "get_user_tasks",
                {"timeframe": "today"},
            )
        )

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr("app.services.assistant_ai._call_native_router", native)
    decision = asyncio.run(
        classify_intent(
            "I have 3 hours. Help me plan my tasks.",
            now=datetime.now(timezone.utc),
            timezone_name="Asia/Ulaanbaatar",
            is_manager=False,
            workers=[],
        )
    )
    assert decision.intent == AssistantIntent.PLAN_WORK
    assert decision.selected_tool == AssistantToolName.GET_MY_TASKS
    assert decision.time_budget_minutes == 180
    assert decision.date_range == DateRangeKind.TODAY


def test_custom_range_requires_both_dates():
    with pytest.raises(ValidationError):
        RouteDecision(
            intent=AssistantIntent.QUERY_MY_TASKS,
            language=AssistantLanguage.EN,
            confidence=0.9,
            task_scope=TaskScope.BOTH,
            date_range=DateRangeKind.CUSTOM,
            start_date=date(2026, 7, 1),
            end_date=None,
            include_completed=False,
            time_budget_minutes=None,
            knowledge_terms=[],
            clarification=None,
        )


def test_custom_range_rejects_reverse_order():
    with pytest.raises(ValidationError):
        RouteDecision(
            intent=AssistantIntent.QUERY_MY_TASKS,
            language=AssistantLanguage.EN,
            confidence=0.9,
            task_scope=TaskScope.BOTH,
            date_range=DateRangeKind.CUSTOM,
            start_date=date(2026, 7, 2),
            end_date=date(2026, 7, 1),
            include_completed=False,
            time_budget_minutes=None,
            knowledge_terms=[],
            clarification=None,
        )


def test_work_plan_is_clamped_to_budget():
    plan = WorkPlan(
        summary="Focus plan",
        blocks=[
            PlanBlock(label="One", minutes=120, action="Do one", task_id=1),
            PlanBlock(label="Two", minutes=120, action="Do two", task_id=2),
        ],
        next_action="Start",
    )
    normalized = normalize_work_plan(plan, 180)
    assert sum(block.minutes for block in normalized.blocks) == 180
    assert normalized.blocks[1].minutes == 60


def test_route_schema_forbids_unknown_fields():
    payload = {
        "intent": "GENERAL_PRODUCTIVITY",
        "language": "en",
        "confidence": 0.8,
        "task_scope": "both",
        "date_range": "none",
        "start_date": None,
        "end_date": None,
        "include_completed": False,
        "time_budget_minutes": None,
        "knowledge_terms": [],
        "clarification": None,
        "unexpected": "no",
    }
    with pytest.raises(ValidationError):
        RouteDecision.model_validate(payload)


def test_general_reply_rejects_wrong_output_language(monkeypatch):
    async def structured(*_args, **_kwargs):
        return AssistantReply(
            language=AssistantLanguage.RU,
            answer="Ответ на русском языке.",
            used_knowledge_ids=[],
        )

    monkeypatch.setattr("app.services.assistant_ai._call_structured", structured)
    result = asyncio.run(
        generate_general_reply(
            user_text="Чөлөө хэрхэн авах вэ?",
            language=AssistantLanguage.MN,
            tasks=[],
            knowledge=[],
            workers=[],
            voice_mode=False,
        )
    )
    assert result is None
