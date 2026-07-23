from __future__ import annotations

import asyncio
from datetime import datetime
from io import BytesIO
from types import SimpleNamespace

import pytz
import pytest

from app.bot import assistant_handlers, tasks_handlers
from app.bot.tasks_handlers import (
    _ambiguous_roster_names,
    _resolve_roster_name,
    _targets_all_workers,
)
from app.services.assistant_ai import (
    AssistantIntent,
    AssistantLanguage,
    AssistantToolName,
    DateRangeKind,
    RouteDecision,
    RouterIntent,
    TaskScope,
)


class FakeBot:
    async def download(self, _voice):
        return BytesIO(b"audio")


class FakeMessage:
    def __init__(self, text: str = ""):
        self.text = text
        self.voice = object()
        self.bot = FakeBot()
        self.from_user = SimpleNamespace(full_name="Tester", username="tester")
        self.answers = []

    async def answer(self, text, **kwargs):
        self.answers.append((text, kwargs))


class FakeState:
    def __init__(self):
        self.state = None
        self.data = {}

    async def set_state(self, state):
        self.state = state

    async def update_data(self, **kwargs):
        self.data.update(kwargs)


EMPLOYEE = SimpleNamespace(
    id=7,
    name="Tester",
    timezone="Asia/Ulaanbaatar",
    is_active=True,
)


@pytest.fixture(autouse=True)
def _empty_worker_directory(monkeypatch):
    monkeypatch.setattr(
        assistant_handlers.employee_directory_service,
        "list_workers",
        lambda: [],
    )


def _decision(intent: AssistantIntent) -> RouteDecision:
    router_intent = {
        AssistantIntent.DELEGATE_TASK: RouterIntent.CREATE_TASK,
        AssistantIntent.QUERY_MY_TASKS: RouterIntent.VIEW_MY_TASKS,
        AssistantIntent.DISCOVER_CAPABILITIES: RouterIntent.AGENT_CAPABILITIES,
    }.get(intent, RouterIntent.UNKNOWN)
    return RouteDecision(
        intent=intent,
        router_intent=router_intent,
        language=AssistantLanguage.EN,
        confidence=0.95,
        task_scope=TaskScope.BOTH,
        date_range=DateRangeKind.NONE,
        start_date=None,
        end_date=None,
        include_completed=False,
        time_budget_minutes=None,
        knowledge_terms=[],
        clarification=None,
    )


def test_voice_transcript_uses_shared_router(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        assistant_handlers.voice_service,
        "transcription_enabled",
        lambda: True,
    )

    async def transcribe(_audio):
        return "What are my tasks?", None

    async def route(message, state, text, **kwargs):
        captured.update({"message": message, "state": state, "text": text, **kwargs})

    monkeypatch.setattr(assistant_handlers.voice_service, "transcribe", transcribe)
    monkeypatch.setattr(assistant_handlers, "route_and_respond", route)

    message = FakeMessage()
    state = object()
    asyncio.run(
        assistant_handlers.msg_assistant_voice(
            message,
            state,
            employee=EMPLOYEE,
            is_manager=False,
            tg_id="77",
        )
    )

    assert captured["text"] == "What are my tasks?"
    assert captured["voice_mode"] is True
    assert captured["employee"] is EMPLOYEE


def test_delegate_route_enters_existing_draft_without_direct_creation(monkeypatch):
    drafted = {}
    tool_arguments = {
        "assignee": "@alex",
        "title": "Review landing page",
        "description": None,
        "priority": 2,
        "deadline_iso": None,
        "assign_to_all": False,
    }

    async def classify(*_args, **_kwargs):
        return _decision(AssistantIntent.DELEGATE_TASK).model_copy(
            update={
                "selected_tool": AssistantToolName.CREATE_TASK,
                "tool_arguments": tool_arguments,
            }
        )

    async def begin(message, state, text, **kwargs):
        drafted.update({"message": message, "state": state, "text": text, **kwargs})

    monkeypatch.setattr(assistant_handlers.assistant_ai, "classify_intent", classify)
    monkeypatch.setattr(assistant_handlers, "begin_task_draft", begin)

    message = FakeMessage("Assign review to @alex")
    state = object()
    asyncio.run(
        assistant_handlers.route_and_respond(
            message,
            state,
            message.text,
            employee=EMPLOYEE,
            is_manager=True,
            tg_id="77",
            voice_mode=False,
        )
    )

    assert drafted["text"] == "Assign review to @alex"
    assert drafted["is_manager"] is True
    assert drafted["tool_arguments"] == tool_arguments


def test_task_query_is_scoped_to_current_actor(monkeypatch):
    captured = {}

    async def classify(*_args, **_kwargs):
        return _decision(AssistantIntent.QUERY_MY_TASKS)

    def list_for_actor(**kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(assistant_handlers.assistant_ai, "classify_intent", classify)
    monkeypatch.setattr(assistant_handlers.task_service, "list_for_actor", list_for_actor)

    message = FakeMessage("What are my tasks?")
    asyncio.run(
        assistant_handlers.route_and_respond(
            message,
            object(),
            message.text,
            employee=EMPLOYEE,
            is_manager=False,
            tg_id="77",
            voice_mode=False,
        )
    )

    assert captured["employee_id"] == EMPLOYEE.id
    assert captured["tg_id"] == "77"
    assert captured["scope"] == "both"


def test_worker_directory_is_read_only_and_deterministic(monkeypatch):
    async def classify(*_args, **_kwargs):
        return _decision(AssistantIntent.GENERAL_PRODUCTIVITY).model_copy(
            update={
                "router_intent": RouterIntent.COMPANY_INFO,
                "selected_tool": AssistantToolName.GET_COMPANY_INFO,
                "tool_arguments": {
                    "topic": "worker directory",
                    "kind": "worker_directory",
                    "search_terms": ["workers"],
                },
            }
        )

    monkeypatch.setattr(assistant_handlers.assistant_ai, "classify_intent", classify)
    monkeypatch.setattr(
        assistant_handlers.employee_directory_service,
        "list_workers",
        lambda: [
            {
                "id": 7,
                "name": "Alex",
                "telegram_username": "alex",
                "is_active": True,
                "is_manager": False,
            }
        ],
    )

    message = FakeMessage("Show me the worker list")
    asyncio.run(
        assistant_handlers.route_and_respond(
            message,
            object(),
            message.text,
            employee=EMPLOYEE,
            is_manager=False,
            tg_id="77",
            voice_mode=False,
        )
    )

    assert "Alex" in message.answers[-1][0]
    assert "@alex" in message.answers[-1][0]


def test_all_worker_assignment_requests_are_recognized():
    assert _targets_all_workers("Assign the company meeting to all workers")
    assert _targets_all_workers("Бүх ажилтанд арга хэмжээний даалгавар өг")
    assert _targets_all_workers("Назначь встречу всем сотрудникам")


def test_worker_directory_normalizes_stored_at_username():
    text = assistant_handlers._format_worker_directory(
        [
            {
                "name": "Анужин",
                "telegram_username": "@anujin4x",
                "is_active": True,
                "is_manager": False,
            }
        ],
        AssistantLanguage.MN,
        voice_mode=False,
    )
    assert "@anujin4x" in text
    assert "@@anujin4x" not in text


def test_deterministic_task_query_overrides_wrong_llm_delegation(monkeypatch):
    async def classify(*_args, **_kwargs):
        return _decision(AssistantIntent.DELEGATE_TASK)

    captured = {}

    def list_for_actor(**kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(assistant_handlers.assistant_ai, "classify_intent", classify)
    monkeypatch.setattr(assistant_handlers.task_service, "list_for_actor", list_for_actor)

    message = FakeMessage("Бүх ажилтны даалгавруудыг харуул")
    asyncio.run(
        assistant_handlers.route_and_respond(
            message,
            object(),
            message.text,
            employee=EMPLOYEE,
            is_manager=True,
            tg_id="77",
            voice_mode=False,
        )
    )

    assert captured["scope"] == "team"


def test_scheduled_meeting_overrides_wrong_llm_unknown(monkeypatch):
    async def classify(*_args, **_kwargs):
        return _decision(AssistantIntent.GENERAL_PRODUCTIVITY)

    drafted = {}

    async def begin(message, state, text, **kwargs):
        drafted.update({"text": text, **kwargs})

    monkeypatch.setattr(assistant_handlers.assistant_ai, "classify_intent", classify)
    monkeypatch.setattr(assistant_handlers.knowledge_service, "search_knowledge", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(assistant_handlers, "begin_task_draft", begin)

    message = FakeMessage("Маргааш би 15 цагаас хуралтай")
    asyncio.run(
        assistant_handlers.route_and_respond(
            message,
            object(),
            message.text,
            employee=EMPLOYEE,
            is_manager=True,
            tg_id="77",
            voice_mode=False,
        )
    )

    assert drafted["text"] == message.text
    assert drafted["employee"] is EMPLOYEE
    assert not message.answers


def test_full_employee_name_resolves_ambiguous_first_name():
    roster = [
        {"id": 1, "name": "Анужин юрист"},
        {"id": 2, "name": "Анужин менежер"},
    ]
    assert _resolve_roster_name("Маргааш Анужин менежер 15 цагт хуралтай", roster) == 2
    assert _resolve_roster_name("Анужин менежерт даалгавар өг", roster) == 2
    assert _resolve_roster_name("Анужин маргааш хуралтай", roster) is None
    assert _ambiguous_roster_names("Анужинд маргааш даалгавар өг", roster) == [
        "Анужин юрист",
        "Анужин менежер",
    ]


def test_task_draft_prefers_deterministic_mongolian_local_time(monkeypatch):
    zone = pytz.timezone("Asia/Ulaanbaatar")

    async def structure(*_args, **_kwargs):
        return {
            "title": "Хурал",
            "description": None,
            "assignee_id": EMPLOYEE.id,
            "assign_to_all": False,
            "deadline_at": zone.localize(datetime(2026, 6, 2, 7, 0)),
            "priority": 2,
        }

    monkeypatch.setattr(tasks_handlers, "_now_tz", lambda _tz: zone.localize(datetime(2026, 6, 1, 10, 0)))
    monkeypatch.setattr(
        tasks_handlers,
        "_roster",
        lambda: [{"id": EMPLOYEE.id, "name": EMPLOYEE.name, "username": "tester"}],
    )
    monkeypatch.setattr(tasks_handlers.task_ai, "ai_enabled", lambda: True)
    monkeypatch.setattr(tasks_handlers.task_ai, "structure_task", structure)

    message = FakeMessage("Маргааш би 15 цагаас хуралтай")
    state = FakeState()
    asyncio.run(
        tasks_handlers.begin_task_draft(
            message,
            state,
            message.text,
            employee=EMPLOYEE,
            is_manager=True,
            tg_id="77",
        )
    )

    deadline = state.data["draft"]["deadline_at"]
    assert deadline.date() == datetime(2026, 6, 2).date()
    assert deadline.hour == 15
    assert "02.06 15:00 УБ" in message.answers[-1][0]


def test_native_task_arguments_skip_legacy_task_extraction_call(monkeypatch):
    zone = pytz.timezone("Asia/Ulaanbaatar")

    async def structure(*_args, **_kwargs):
        raise AssertionError("native create_task arguments should be reused")

    monkeypatch.setattr(tasks_handlers, "_now_tz", lambda _tz: zone.localize(datetime(2026, 6, 1, 10, 0)))
    monkeypatch.setattr(
        tasks_handlers,
        "_roster",
        lambda: [{"id": EMPLOYEE.id, "name": EMPLOYEE.name, "username": "tester"}],
    )
    monkeypatch.setattr(tasks_handlers.task_ai, "ai_enabled", lambda: True)
    monkeypatch.setattr(tasks_handlers.task_ai, "structure_task", structure)

    message = FakeMessage("Маргааш би 15 цагаас хуралтай")
    state = FakeState()
    asyncio.run(
        tasks_handlers.begin_task_draft(
            message,
            state,
            message.text,
            employee=EMPLOYEE,
            is_manager=True,
            tg_id="77",
            tool_arguments={
                "assignee": None,
                "title": "Маргаашийн хурал",
                "description": None,
                "priority": 2,
                "deadline_iso": "2026-06-02T07:00:00+08:00",
                "assign_to_all": False,
            },
        )
    )

    assert state.data["draft"]["title"] == "Маргаашийн хурал"
    assert state.data["draft"]["deadline_at"].hour == 15


def test_company_tool_retrieves_postgres_knowledge(monkeypatch):
    async def classify(*_args, **_kwargs):
        return _decision(AssistantIntent.GENERAL_PRODUCTIVITY).model_copy(
            update={
                "router_intent": RouterIntent.COMPANY_INFO,
                "language": AssistantLanguage.MN,
                "selected_tool": AssistantToolName.GET_COMPANY_INFO,
                "tool_arguments": {
                    "topic": "Чөлөө авах журам",
                    "kind": "knowledge",
                    "search_terms": ["чөлөө", "журам"],
                },
                "knowledge_terms": ["чөлөө", "журам"],
            }
        )

    monkeypatch.setattr(assistant_handlers.assistant_ai, "classify_intent", classify)
    monkeypatch.setattr(
        assistant_handlers.knowledge_service,
        "search_knowledge",
        lambda *_args, **_kwargs: [
            {
                "id": 11,
                "title": "Чөлөө авах журам",
                "category": "Хүний нөөц",
                "content": "Чөлөө авахын тулд Анужин менежерт өмнөх өдөр мэдэгдэнэ.",
            }
        ],
    )

    message = FakeMessage("Чөлөө хэрхэн авах вэ?")
    asyncio.run(
        assistant_handlers.route_and_respond(
            message,
            object(),
            message.text,
            employee=EMPLOYEE,
            is_manager=True,
            tg_id="77",
            voice_mode=False,
        )
    )

    answer = message.answers[-1][0]
    assert "Анужин" in answer
    assert "Чөлөө авах журам" in answer


def test_unknown_request_is_stored_without_task_draft(monkeypatch):
    async def classify(*_args, **_kwargs):
        return _decision(AssistantIntent.GENERAL_PRODUCTIVITY)

    captured = {}

    def record(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(assistant_handlers.assistant_ai, "classify_intent", classify)
    monkeypatch.setattr(assistant_handlers.knowledge_service, "search_knowledge", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(assistant_handlers.unknown_request_service, "record_unknown_request", record)

    message = FakeMessage("Do something unexpected")
    asyncio.run(
        assistant_handlers.route_and_respond(
            message,
            object(),
            message.text,
            employee=EMPLOYEE,
            is_manager=True,
            tg_id="77",
            voice_mode=False,
        )
    )

    assert captured["text"] == message.text
    assert captured["channel"] == "text"
    assert "saved" in message.answers[-1][0].lower()
