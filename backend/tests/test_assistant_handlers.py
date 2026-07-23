from __future__ import annotations

import asyncio
from io import BytesIO
from types import SimpleNamespace

from app.bot import assistant_handlers
from app.services.assistant_ai import (
    AssistantIntent,
    AssistantLanguage,
    DateRangeKind,
    RouteDecision,
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


EMPLOYEE = SimpleNamespace(
    id=7,
    name="Tester",
    timezone="Asia/Ulaanbaatar",
    is_active=True,
)


def _decision(intent: AssistantIntent) -> RouteDecision:
    return RouteDecision(
        intent=intent,
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

    async def classify(*_args, **_kwargs):
        return _decision(AssistantIntent.DELEGATE_TASK)

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
