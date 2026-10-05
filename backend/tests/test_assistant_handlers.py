from __future__ import annotations

import asyncio
from datetime import datetime
from io import BytesIO
from types import SimpleNamespace

import pytz
import pytest

from app.bot import assistant_handlers, tasks_handlers
from app.core.enterprise_deps import build_actor_context
from app.services import voice_service
from app.bot.tasks_handlers import (
    _ambiguous_roster_names,
    _draft_kb,
    _fmt_deadline,
    _resolve_roster_name,
    _resolve_roster_names,
    _structure_from_tool_arguments,
    _targets_all_workers,
    apply_task_draft_edit,
    task_draft_text,
)
from app.services.file_search_service import FileSearchPrincipal


class FakeBot:
    async def download(self, _voice):
        return BytesIO(b"audio")


class FakeMessage:
    def __init__(self, text: str = ""):
        self.text = text
        self.voice = object()
        self.audio = None
        self.video_note = None
        self.bot = FakeBot()
        self.from_user = SimpleNamespace(full_name="Tester", username="tester")
        self.chat = SimpleNamespace(id=1234)
        self.reply_to_message = None
        self.answers = []
        self.audios = []
        self.documents = []

    async def answer(self, text, **kwargs):
        self.answers.append((text, kwargs))

    async def answer_audio(self, audio, **kwargs):
        self.audios.append((audio, kwargs))

    async def answer_document(self, document, **kwargs):
        self.documents.append((document, kwargs))


class FakeState:
    def __init__(self):
        self.state = None
        self.data = {}

    async def set_state(self, state):
        self.state = state

    async def update_data(self, **kwargs):
        self.data.update(kwargs)

    async def get_data(self):
        return dict(self.data)


EMPLOYEE = SimpleNamespace(
    id=7,
    name="Tester",
    timezone="Asia/Ulaanbaatar",
    is_active=True,
)


@pytest.fixture(autouse=True)
def _tts_switch_on(monkeypatch):
    monkeypatch.setattr(assistant_handlers.voice_service, "tts_answers_enabled", lambda: True)


class GatewaySession:
    """Minimal async session for the Telegram route; records added rows."""

    def __init__(self):
        self.added = []
        self.committed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def scalar(self, _statement):
        return None

    async def execute(self, _statement):
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))

    def add(self, record):
        self.added.append(record)

    async def flush(self):
        return None

    async def commit(self):
        self.committed = True

    async def rollback(self):
        return None


async def _available(*_args, **_kwargs):
    return True


async def _stt_token(_organization_id=None):
    return "token", ""


async def _linked_actor(_tg_id, _db):
    return build_actor_context(account_id=11, organization_id=1, employee_id=7, email="tester@example.com", locale="en", roles=frozenset({"member"}))


def _gateway_reply(answer: str, **extra):
    return SimpleNamespace(answer=answer, sources=[], deliveries=[], tool_results=[], memory=[{"tool": "oyuns_tasks_search", "items": [{"title": "Report"}]}], degraded=False, **extra)


def test_chimege_tts_text_normalizes_uppercase_runs():
    assert voice_service._prepare_synthesis_text("OYUNS AI: АСУУЛТ байна уу? ✅") == ": асуулт байна уу?"


def test_voice_transcript_uses_shared_router(monkeypatch):
    captured = {}

    async def available():
        return True

    monkeypatch.setattr(assistant_handlers.voice_service, "transcription_available", available)

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


def test_telegram_linked_account_sends_gateway_answer_and_keeps_memory(monkeypatch):
    session = GatewaySession()
    captured = {}

    async def execute_turn(_db, _actor, history, **kwargs):
        captured.update(kwargs, history=history)
        return _gateway_reply("**Telegram** gateway reply")

    monkeypatch.setattr(assistant_handlers, "AsyncSessionLocal", lambda: session)
    monkeypatch.setattr(assistant_handlers, "actor_from_telegram_id", _linked_actor)
    monkeypatch.setattr(assistant_handlers.ai_gateway, "execute_turn", execute_turn)

    message = FakeMessage("Надад юугаар туслах вэ?")
    handled = asyncio.run(assistant_handlers._enterprise_route(message, FakeState(), message.text, employee=EMPLOYEE, is_manager=False, tg_id="77"))

    assert handled is True
    assert message.answers[-1] == ("<b>Telegram</b> gateway reply", {"parse_mode": "HTML", "reply_markup": None})
    assert captured["input_mode"] == "text"
    assert captured["memory"] == []
    conversation = next(item for item in session.added if isinstance(item, assistant_handlers.AssistantConversation))
    assert conversation.mcp_context == [{"tool": "oyuns_tasks_search", "items": [{"title": "Report"}]}]
    assert session.committed


def test_reply_to_task_draft_is_passed_to_the_agent(monkeypatch):
    captured = {}

    async def execute_turn(_db, _actor, history, **_kwargs):
        captured["history"] = history
        return _gateway_reply("ok")

    monkeypatch.setattr(assistant_handlers, "AsyncSessionLocal", GatewaySession)
    monkeypatch.setattr(assistant_handlers, "actor_from_telegram_id", _linked_actor)
    monkeypatch.setattr(assistant_handlers.ai_gateway, "execute_turn", execute_turn)
    message = FakeMessage("Хугацааг маргааш 17:00 болго")
    message.reply_to_message = SimpleNamespace(text="🤖 Даалгаврын ноорог\n\nТайлан бэлдэх", caption=None, from_user=SimpleNamespace(is_bot=True))
    asyncio.run(assistant_handlers._enterprise_route(message, FakeState(), message.text, employee=EMPLOYEE, is_manager=False, tg_id="77"))

    assert captured["history"][-2] == {"role": "assistant", "content": "<task draft being edited>\n🤖 Даалгаврын ноорог\n\nТайлан бэлдэх\n</task draft being edited>"}
    assert captured["history"][-1] == {"role": "user", "content": "Хугацааг маргааш 17:00 болго"}


def test_voice_turn_is_flagged_and_answered_with_chimege_audio(monkeypatch):
    captured = {}

    async def execute_turn(_db, _actor, _history, **kwargs):
        captured.update(kwargs)
        return _gateway_reply("Танд 2 нээлттэй даалгавар байна.")

    async def synthesize(text):
        captured["tts"] = text
        return b"wav", None

    monkeypatch.setattr(assistant_handlers, "AsyncSessionLocal", GatewaySession)
    monkeypatch.setattr(assistant_handlers, "actor_from_telegram_id", _linked_actor)
    monkeypatch.setattr(assistant_handlers.ai_gateway, "execute_turn", execute_turn)
    monkeypatch.setattr(assistant_handlers.voice_service, "synthesis_available", _available)
    monkeypatch.setattr(assistant_handlers.voice_service, "synthesize", synthesize)
    message = FakeMessage("миний даалгавар")
    asyncio.run(assistant_handlers._enterprise_route(message, FakeState(), message.text, employee=EMPLOYEE, is_manager=False, tg_id="77", voice_mode=True))

    assert captured["input_mode"] == "voice"
    assert captured["tts"] == "Танд 2 нээлттэй даалгавар байна."
    assert message.audios[0][1]["title"] == "OYUNS хариулт"


def test_voice_task_preview_is_not_read_aloud(monkeypatch):
    async def execute_turn(*_args, **_kwargs):
        return SimpleNamespace(answer="Даалгаврын ноорог", sources=[], deliveries=[], memory=[], degraded=False, tool_results=[{"data": {"pending_action": {"token": "tok"}}}])

    async def synthesize(_text):
        raise AssertionError("a task preview must not be synthesized")

    monkeypatch.setattr(assistant_handlers, "AsyncSessionLocal", GatewaySession)
    monkeypatch.setattr(assistant_handlers, "actor_from_telegram_id", _linked_actor)
    monkeypatch.setattr(assistant_handlers.ai_gateway, "execute_turn", execute_turn)
    monkeypatch.setattr(assistant_handlers.voice_service, "synthesis_available", _available)
    monkeypatch.setattr(assistant_handlers.voice_service, "synthesize", synthesize)
    message = FakeMessage("маргааш хурал")
    asyncio.run(assistant_handlers._enterprise_route(message, FakeState(), message.text, employee=EMPLOYEE, is_manager=False, tg_id="77", voice_mode=True))

    assert message.audios == []
    assert message.answers[-1][1]["reply_markup"].inline_keyboard[0][0].callback_data == "ac:tok"


def test_voice_message_types_all_reach_the_agent(monkeypatch):
    routed = []

    async def transcribe(_audio):
        return "Сайн байна уу", None

    async def route(_message, _state, text, **kwargs):
        routed.append((text, kwargs["voice_mode"]))

    async def available():
        return True

    monkeypatch.setattr(assistant_handlers.voice_service, "transcription_available", available)
    monkeypatch.setattr(assistant_handlers.voice_service, "transcribe", transcribe)
    monkeypatch.setattr(assistant_handlers, "route_and_respond", route)
    for attribute in ("voice", "audio", "video_note"):
        message = FakeMessage()
        message.voice = message.audio = message.video_note = None
        setattr(message, attribute, object())
        asyncio.run(assistant_handlers.msg_assistant_voice(message, object(), employee=EMPLOYEE, tg_id="77"))
        assert message.answers[0][0].startswith("🎙")
    assert routed == [("Сайн байна уу", True)] * 3


def test_telegram_html_escapes_before_formatting():
    assert assistant_handlers.telegram_html("## Гарчиг\n- **a<b** `x`") == "<b>Гарчиг</b>\n• <b>a&lt;b</b> <code>x</code>"


def test_rejected_html_falls_back_to_plain_text():
    from aiogram.exceptions import TelegramBadRequest

    class Strict(FakeMessage):
        async def answer(self, text, **kwargs):
            if kwargs.get("parse_mode") == "HTML":
                raise TelegramBadRequest(method=None, message="can't parse entities")
            await super().answer(text, **kwargs)

    message = Strict()
    asyncio.run(assistant_handlers._answer(message, "**bold**", parse_mode="HTML"))
    assert message.answers == [("**bold**", {"parse_mode": None, "reply_markup": None})]


def test_telegram_route_reports_unexpected_failure_instead_of_silence(monkeypatch):
    async def fail(*_args, **_kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(assistant_handlers, "_enterprise_route", fail)
    message = FakeMessage("What can you help me with?")

    asyncio.run(
        assistant_handlers.route_and_respond(
            message,
            FakeState(),
            message.text,
            employee=EMPLOYEE,
            is_manager=False,
            tg_id="77",
            voice_mode=False,
            language="en",
        )
    )

    assert "temporarily unavailable" in message.answers[-1][0]


def test_missing_telegram_attachment_does_not_replace_successful_answer(monkeypatch):
    async def authorized(_db, _principal, _item_id):
        return [SimpleNamespace(id=9, name="Brand deck.pptx", storage_key="1/library/missing")]

    async def missing(_storage_key):
        raise FileNotFoundError("attachment volume is missing the object")

    monkeypatch.setattr(assistant_handlers, "authorized_file", authorized)
    monkeypatch.setattr(assistant_handlers, "get_attachment", missing)
    message = FakeMessage("Send me the brand deck")

    asyncio.run(
        assistant_handlers._deliver_company_file_attachment(
            message,
            object(),
            FileSearchPrincipal(organization_id=1, employee_id=7, channel="telegram"),
            {"item_id": 9},
            language="en",
        )
    )

    assert message.documents == []
    assert "attachment is currently unavailable" in message.answers[-1][0]


def test_verified_telegram_employee_can_search_without_workspace_account(monkeypatch):
    class Session:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *_args):
            return None

    async def no_account(_tg_id, _db):
        return None

    async def principal_lookup(_tg_id, _db):
        return FileSearchPrincipal(organization_id=1, employee_id=7, channel="telegram")

    async def search(_db, _principal, _request):
        return {
            "status": "indexing",
            "data": {"results": [{"title": "Brand deck.pptx", "content_state": "indexing"}]},
            "deliveries": [],
        }

    monkeypatch.setattr(assistant_handlers, "AsyncSessionLocal", lambda: Session())
    monkeypatch.setattr(assistant_handlers, "actor_from_telegram_id", no_account)
    monkeypatch.setattr(assistant_handlers, "file_search_principal_from_telegram_id", principal_lookup)
    monkeypatch.setattr(assistant_handlers, "search_files", search)

    message = FakeMessage("презентаци загвар")
    handled = asyncio.run(assistant_handlers._enterprise_route(message, FakeState(), message.text, employee=EMPLOYEE, is_manager=False, tg_id="77"))
    assert handled is True
    assert "indexing" in message.answers[0][0]


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
        "🔎 Хянагч: <b>Сонгоогүй</b>\n"
        "🟡 Тэргүүлэх зэрэг: 2\n"
        "🕒 Хугацаа: <b>24.07 18:00 УБ</b>"
    )


def test_task_draft_reply_preserves_fields_and_applies_explicit_changes(monkeypatch):
    zone = pytz.timezone("Asia/Ulaanbaatar")
    original_deadline = zone.localize(datetime(2026, 6, 1, 12, 0))
    monkeypatch.setattr(tasks_handlers, "_now_tz", lambda _tz: zone.localize(datetime(2026, 6, 1, 10, 0)))

    state = FakeState()
    state.data["draft"] = {
        "title": "Тайлан бэлдэх",
        "description": "Эхний хувилбар",
        "assignee_id": EMPLOYEE.id,
        "assignee_ids": [EMPLOYEE.id],
        "assignee_name": EMPLOYEE.name,
        "assign_to_all": False,
        "deadline_at": original_deadline,
        "priority": 2,
    }
    message = FakeMessage("Хугацааг маргааш 17 цагт болгож, яаралтай болго.")

    edited = asyncio.run(
        apply_task_draft_edit(
            message,
            state,
            message.text,
            employee=EMPLOYEE,
            is_manager=False,
        )
    )

    draft = state.data["draft"]
    assert edited is True
    assert draft["title"] == "Тайлан бэлдэх"
    assert draft["description"] == "Эхний хувилбар"
    assert draft["deadline_at"] == zone.localize(datetime(2026, 6, 2, 17, 0))
    assert draft["priority"] == 1
    assert "02.06 17:00 УБ" in message.answers[-1][0]
    assert "🔴 Тэргүүлэх зэрэг: 1" in message.answers[-1][0]


def test_task_draft_reply_accepts_numeric_priority(monkeypatch):
    zone = pytz.timezone("Asia/Ulaanbaatar")
    monkeypatch.setattr(tasks_handlers, "_now_tz", lambda _tz: zone.localize(datetime(2026, 6, 1, 10, 0)))
    state = FakeState()
    state.data["draft"] = {
        "title": "Тайлан бэлдэх",
        "assignee_id": EMPLOYEE.id,
        "assignee_ids": [EMPLOYEE.id],
        "assignee_name": EMPLOYEE.name,
        "assign_to_all": False,
        "deadline_at": None,
        "priority": 2,
    }

    asyncio.run(
        apply_task_draft_edit(
            FakeMessage("Тэргүүлэх зэрэг: 3"),
            state,
            "Тэргүүлэх зэрэг: 3",
            employee=EMPLOYEE,
            is_manager=False,
        )
    )

    assert state.data["draft"]["priority"] == 3


def test_task_draft_reply_accepts_mongolian_title_edit(monkeypatch):
    zone = pytz.timezone("Asia/Ulaanbaatar")
    monkeypatch.setattr(tasks_handlers, "_now_tz", lambda _tz: zone.localize(datetime(2026, 6, 1, 10, 0)))
    state = FakeState()
    state.data["draft"] = {
        "title": "Хуучин гарчиг",
        "assignee_id": EMPLOYEE.id,
        "assignee_ids": [EMPLOYEE.id],
        "assignee_name": EMPLOYEE.name,
        "assign_to_all": False,
        "deadline_at": None,
        "priority": 2,
    }

    asyncio.run(
        apply_task_draft_edit(
            FakeMessage("Гарчгийг Шинэ тайлан бэлдэх болго"),
            state,
            "Гарчгийг Шинэ тайлан бэлдэх болго",
            employee=EMPLOYEE,
            is_manager=False,
        )
    )

    assert state.data["draft"]["title"] == "Шинэ тайлан бэлдэх"


def test_all_worker_assignment_requests_are_recognized():
    assert _targets_all_workers("Assign the company meeting to all workers")
    assert _targets_all_workers("Бүх ажилтанд арга хэмжээний даалгавар өг")
    assert _targets_all_workers("Назначь встречу всем сотрудникам")
    assert _targets_all_workers("Хоёр цагийн дараа бүгд офис дээр цуглаарай")
    assert _targets_all_workers("Офис дээр бүгдээрээ 2 цагийн дараа цугламаар байна")


def test_native_all_assignee_becomes_all_worker_draft():
    structured = _structure_from_tool_arguments(
        {
            "assignee": "all",
            "title": "Офисын уулзалт",
            "priority": 2,
            "due_date": "2026-07-24T15:00:00+08:00",
        },
        roster=[],
        timezone_name="Asia/Ulaanbaatar",
    )
    assert structured is not None
    assert structured["assign_to_all"] is True


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


def test_multiple_explicit_employee_names_become_multiple_draft_assignees(monkeypatch):
    roster = [
        {"id": 1, "name": "Анужин менежер", "username": "anujin"},
        {"id": 2, "name": "Тэмүүлэн", "username": "temuulen"},
    ]
    text = "Анужин менежер, Тэмүүлэн хоёрт Маргааш офис дээр 13 цагт уулзах даалгавар өг"
    monkeypatch.setattr(tasks_handlers, "_roster", lambda: roster)

    message = FakeMessage(text)
    state = FakeState()
    asyncio.run(
        tasks_handlers.begin_task_draft(
            message,
            state,
            text,
            employee=EMPLOYEE,
            is_manager=True,
            tg_id="77",
            allow_ai_structuring=False,
        )
    )

    assert _resolve_roster_names(text, roster) == [1, 2]
    assert state.data["draft"]["assignee_ids"] == [1, 2]
    assert state.data["draft"]["assignee_name"] == "Анужин менежер, Тэмүүлэн"
    assert "Гүйцэтгэгчид: <b>Анужин менежер, Тэмүүлэн</b>" in message.answers[-1][0]


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



def test_transcription_uses_chimege_first_then_openai(monkeypatch):
    from app.services.ai_gateway import runtime

    calls = []

    async def chimege(_audio, _token):
        calls.append("chimege")
        return None, "Chimege down"

    async def openai(_audio, key, _filename, **_kwargs):
        calls.append(("openai", key))
        return "Сайн байна уу", None

    async def key(_organization_id=None):
        return "sk-org-key"

    monkeypatch.setattr(runtime, "chimege_tokens", _stt_token)
    monkeypatch.setattr(voice_service, "_transcribe_chimege", chimege)
    monkeypatch.setattr(voice_service, "_transcribe_openai", openai)
    monkeypatch.setattr(runtime, "openai_api_key", key)
    assert asyncio.run(voice_service.transcribe(b"audio")) == ("Сайн байна уу", None)
    assert calls == ["chimege", ("openai", "sk-org-key")]


def test_chimege_success_skips_openai(monkeypatch):
    from app.services.ai_gateway import runtime

    async def chimege(_audio, _token):
        return "Маргааш хурал", None

    async def openai(*_args):
        raise AssertionError("OpenAI must not be called when Chimege succeeds")

    monkeypatch.setattr(runtime, "chimege_tokens", _stt_token)
    monkeypatch.setattr(voice_service, "_transcribe_chimege", chimege)
    monkeypatch.setattr(voice_service, "_transcribe_openai", openai)
    assert asyncio.run(voice_service.transcribe(b"audio")) == ("Маргааш хурал", None)


def test_task_draft_preview_and_controls_use_english_labels():
    draft = {
        "title": "Prepare report",
        "description": "Review the customer data",
        "assignee_name": "Alex",
        "assignee_ids": [4],
        "reviewer_name": None,
        "priority": 2,
        "deadline_at": None,
    }
    text = task_draft_text(draft, "en")
    assert "Task draft" in text
    assert "Assignee: <b>Alex</b>" in text
    assert "Reviewer: <b>Unassigned</b>" in text
    assert "Due: <b>No deadline</b>" in text
    assert [button.text for button in _draft_kb("en").inline_keyboard[0]] == ["✅ Create", "✏️ Edit", "❌ Delete"]
    assert _fmt_deadline(None, "en") == "No deadline"
