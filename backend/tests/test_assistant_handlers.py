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
    task_draft_text,
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
        self.reply_to_message = None
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
    assistant_handlers._conversation_history.clear()
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


def _react_decision(intent: AssistantIntent, tool: AssistantToolName, arguments: dict):
    return _decision(intent).model_copy(
        update={
            "selected_tool": tool,
            "tool_arguments": arguments,
            "react_messages": [{"role": "user", "content": "request"}],
            "assistant_tool_message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "call_1", "type": "function"}],
            },
            "tool_call_id": "call_1",
        }
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
        "priority": 2,
        "due_date": None,
    }

    async def classify(*_args, **_kwargs):
        return _react_decision(
            AssistantIntent.DELEGATE_TASK,
            AssistantToolName.CREATE_TASK_DRAFT,
            tool_arguments,
        )

    async def begin(message, state, text, **kwargs):
        drafted.update({"message": message, "state": state, "text": text, **kwargs})
        return {
            "ok": True,
            "_presentation": "🤖 <b>Даалгаврын ноорог</b>",
            "draft": {
                "title": "Review landing page",
                "assignee": "Alex",
                "requires_confirmation": True,
            },
        }

    async def synthesize(**kwargs):
        raise AssertionError("A task draft should not need a second model request")

    monkeypatch.setattr(assistant_handlers.assistant_ai, "classify_intent", classify)
    monkeypatch.setattr(assistant_handlers.assistant_ai, "synthesize_tool_result", synthesize)
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
    assert drafted["show_preview"] is False
    assert message.answers[-1][0] == "🤖 <b>Даалгаврын ноорог</b>"
    assert message.answers[-1][1]["parse_mode"] == "HTML"
    assert message.answers[-1][1]["reply_markup"] is not None


def test_task_draft_uses_the_required_mongolian_format():
    zone = pytz.timezone("Asia/Ulaanbaatar")
    text = task_draft_text(
        {
            "title": "Оюукаад хуралтай тухай мэдээлэл",
            "description": "Оюукаад маргааш 18 цагаас хуралтай гэж хэлэх.",
            "assignee_name": "Оюукаа",
            "priority": 2,
            "deadline_at": zone.localize(datetime(2026, 7, 24, 18, 0)),
        }
    )
    assert text == (
        "🤖 <b>Даалгаврын ноорог</b>\n\n"
        "<b>Оюукаад хуралтай тухай мэдээлэл</b>\n"
        "📝 Оюукаад маргааш 18 цагаас хуралтай гэж хэлэх.\n"
        "👤 Гүйцэтгэгч: <b>Оюукаа</b>\n"
        "🟡 Тэргүүлэх зэрэг: 2\n"
        "🕒 Хугацаа: <b>24.07 18:00 УБ</b>"
    )


def test_task_query_is_scoped_to_current_actor(monkeypatch):
    captured = {}

    async def classify(*_args, **_kwargs):
        return _react_decision(
            AssistantIntent.QUERY_MY_TASKS,
            AssistantToolName.GET_USER_TASKS,
            {"timeframe": "all"},
        )

    def list_for_actor(**kwargs):
        captured.update(kwargs)
        return [{"title": "Review", "status": "open", "priority": 1}]

    async def synthesize(**kwargs):
        captured["raw_result"] = kwargs["raw_result"]
        return "Your highest priority is Review."

    monkeypatch.setattr(assistant_handlers.assistant_ai, "classify_intent", classify)
    monkeypatch.setattr(assistant_handlers.assistant_ai, "synthesize_tool_result", synthesize)
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
    assert captured["scope"] == "assigned"
    assert captured["raw_result"]["tasks"][0]["title"] == "Review"
    assert message.answers[-1][0] == "Your highest priority is Review."


def test_worker_directory_is_supplied_as_context_for_direct_answer(monkeypatch):
    captured = {}

    async def classify(*_args, **kwargs):
        captured["workers"] = kwargs["workers"]
        return _decision(AssistantIntent.GENERAL_PRODUCTIVITY).model_copy(
            update={"direct_answer": "Alex (@alex) is active."}
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
    assert captured["workers"][0]["name"] == "Alex"


def test_previous_turn_is_passed_to_context_first_router(monkeypatch):
    histories = []

    async def classify(*_args, **kwargs):
        histories.append(kwargs["chat_history"])
        return _decision(AssistantIntent.GENERAL_PRODUCTIVITY).model_copy(
            update={"direct_answer": "Understood."}
        )

    monkeypatch.setattr(assistant_handlers.assistant_ai, "classify_intent", classify)

    first = FakeMessage("Tomorrow I have a meeting.")
    second = FakeMessage("What time was it?")
    for message in (first, second):
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

    assert histories[0] == []
    assert histories[1] == [
        {"role": "user", "content": "Tomorrow I have a meeting."},
        {"role": "assistant", "content": "Understood."},
    ]


def test_replied_message_is_added_to_openai_context(monkeypatch):
    captured = {}

    async def classify(*_args, **kwargs):
        captured["history"] = kwargs["chat_history"]
        return _decision(AssistantIntent.GENERAL_PRODUCTIVITY).model_copy(
            update={"direct_answer": "Understood."}
        )

    monkeypatch.setattr(assistant_handlers.assistant_ai, "classify_intent", classify)
    message = FakeMessage("Тэгвэл үүнийг зас.")
    message.reply_to_message = SimpleNamespace(
        text="Өмнөх даалгаврын ноорог",
        caption=None,
        from_user=SimpleNamespace(is_bot=True),
    )
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

    assert captured["history"] == [
        {
            "role": "assistant",
            "content": "<previous assistant reply>\nӨмнөх даалгаврын ноорог\n</previous assistant reply>",
        }
    ]


def test_all_worker_assignment_requests_are_recognized():
    assert _targets_all_workers("Assign the company meeting to all workers")
    assert _targets_all_workers("Бүх ажилтанд арга хэмжээний даалгавар өг")
    assert _targets_all_workers("Назначь встречу всем сотрудникам")


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

    message = FakeMessage("Маргааш 15 цагаас хуралтай")
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
                "assignee": "self",
                "title": "Маргаашийн хурал",
                "priority": 2,
                "due_date": "2026-06-02T07:00:00+08:00",
            },
        )
    )

    assert state.data["draft"]["title"] == "Маргаашийн хурал"
    assert state.data["draft"]["deadline_at"].hour == 15


def test_company_tool_retrieves_postgres_knowledge(monkeypatch):
    captured = {}

    async def classify(*_args, **_kwargs):
        return _react_decision(
            AssistantIntent.GENERAL_PRODUCTIVITY,
            AssistantToolName.SEARCH_COMPANY_KNOWLEDGE,
            {"query": "Чөлөө авах журам"},
        ).model_copy(
            update={"router_intent": RouterIntent.COMPANY_INFO, "language": AssistantLanguage.MN}
        )

    async def synthesize(**kwargs):
        captured["raw_result"] = kwargs["raw_result"]
        return "Чөлөө авахын тулд Анужин менежерт өмнөх өдөр мэдэгдэнэ."

    monkeypatch.setattr(assistant_handlers.assistant_ai, "classify_intent", classify)
    monkeypatch.setattr(assistant_handlers.assistant_ai, "synthesize_tool_result", synthesize)
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
    assert captured["raw_result"]["documents"][0]["title"] == "Чөлөө авах журам"
    assert "id" not in captured["raw_result"]["documents"][0]


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
