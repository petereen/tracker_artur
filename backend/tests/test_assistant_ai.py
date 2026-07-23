from __future__ import annotations

import asyncio
from datetime import date

import pytest
from pydantic import ValidationError

from app.services.assistant_ai import (
    AssistantIntent,
    AssistantLanguage,
    AssistantReply,
    DateRangeKind,
    PlanBlock,
    RouteDecision,
    TaskScope,
    WorkPlan,
    detect_language,
    generate_general_reply,
    fallback_route,
    is_task_query,
    is_worker_directory_query,
    is_information_question,
    normalize_work_plan,
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


def test_ambiguous_manager_action_preserves_legacy_task_default():
    decision = fallback_route("Prepare the weekly sales report", is_manager=True)
    assert decision.intent == AssistantIntent.DELEGATE_TASK


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
