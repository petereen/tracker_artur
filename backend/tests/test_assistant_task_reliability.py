import asyncio
import base64
import hashlib
import hmac
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from app.bot import assistant_handlers
from app.core.config import settings
from app.core.enterprise_deps import build_actor_context
from app.core.security import create_action_preview_token, decode_action_preview_token, verify_action_preview_token
from app.services import enterprise_tools
from app.services.ai_gateway import gateway as gateway_module
from app.services.ai_gateway.gateway import AIGateway, Classification, GatewayRequest, GatewayResponse
from app.services.mcp.references import action_reference
from app.services.task_parser import is_simple_self_meeting, task_schedule_fields


TEXT = "би маргааш 16 цагаас хуралтай  шүү даалгавар үүсгэ"
NOW = datetime(2026, 9, 9, 23, 30, tzinfo=ZoneInfo("Asia/Ulaanbaatar"))


def actor(channel="telegram"):
    return build_actor_context(account_id=11, organization_id=1, employee_id=7, email="test@example.test", locale="mn", roles=frozenset({"member"}), channel=channel)


class Session:
    def __init__(self):
        self.added = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass

    @asynccontextmanager
    async def begin_nested(self):
        yield

    async def get(self, *_):
        return SimpleNamespace(name="Тэмүүлэн", telegram_username="test", timezone="Asia/Ulaanbaatar")

    async def scalar(self, *_):
        return None

    async def execute(self, *_):
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))

    def add(self, item):
        self.added.append(item)

    async def flush(self):
        for item in self.added:
            if getattr(item, "id", None) is None:
                item.id = 123
            if isinstance(item, enterprise_tools.Task):
                item.public_id = uuid4()
                item.version = 1

    async def commit(self):
        pass


@pytest.mark.parametrize("action_id", [1, 123, 999999, 2147483647])
def test_actual_telegram_callback_fits_and_remains_bound(action_id):
    token = create_action_preview_token(action_id=action_id, payload_digest="a" * 64, account_id=11, organization_id=1, channel="telegram")
    assert len(token.encode()) <= 64
    assert decode_action_preview_token(token)["action_id"] == str(action_id)
    assert verify_action_preview_token(token, payload_digest="a" * 64, account_id=11, organization_id=1, channel="telegram")
    for changed in ({"account_id": 12}, {"organization_id": 2}, {"channel": "web"}, {"payload_digest": "b" * 64}):
        args = dict(payload_digest="a" * 64, account_id=11, organization_id=1, channel="telegram")
        assert not verify_action_preview_token(token, **{**args, **changed})


def test_previous_signed_tokens_remain_valid():
    ref = base64.b32encode(b"123").decode().rstrip("=").lower()
    expiry = format(int((datetime.now(timezone.utc) + timedelta(minutes=10)).timestamp()), "x")
    canonical = f"{ref}|{'a' * 12}|oldnonce|{expiry}|11|1|telegram"
    signature = base64.urlsafe_b64encode(hmac.new(settings.SECRET_KEY.encode(), canonical.encode(), hashlib.sha256).digest()).decode().rstrip("=")[:16]
    token = f"ap1.{ref}.{'a' * 12}.oldnonce.{expiry}.{signature}"
    assert verify_action_preview_token(token, payload_digest="a" * 64, account_id=11, organization_id=1, channel="telegram")


@pytest.mark.parametrize("text", [TEXT, "би 16 цагаас маргааш хуралтай даалгавар үүсгэ", "Маргааш би 16 цагаас хуралтай даалгавар үүсгэ"])
def test_exact_meeting_time_is_start_without_invented_end(text):
    assert is_simple_self_meeting(text)
    assert task_schedule_fields(text, now=NOW, tz="Asia/Ulaanbaatar") == {"start_at": "2026-09-10T16:00:00+08:00"}


@pytest.mark.parametrize("text", ["Баттай маргааш 16 цагаас хуралтай даалгавар үүсгэ", "маргааш 16 цагаас хуралтай юу?", TEXT + " бас цалингийн тайлан харуул", "маргааш 16 цагаас хуралтай даалгавар үүсгэхгүй"])
def test_complex_or_non_action_requests_do_not_use_self_fast_path(text):
    assert not is_simple_self_meeting(text)


def test_deadline_and_multiple_times_are_not_conflated():
    assert task_schedule_fields("тайланг маргааш 16 цаг гэхэд дуусга", now=NOW, tz="Asia/Ulaanbaatar") == {"deadline_at": "2026-09-10T16:00:00+08:00"}
    assert task_schedule_fields("маргааш 16 цагаас 18 цаг хүртэл хурал", now=NOW, tz="Asia/Ulaanbaatar") == {}


@pytest.mark.parametrize("channel", ["web", "telegram"])
def test_fast_meeting_avoids_provider_and_knowledge_dependencies(monkeypatch, channel):
    gateway = AIGateway()
    calls = []

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz)

    async def forbidden(*_, **__):
        pytest.fail("A standalone self meeting must not call AI or knowledge retrieval")

    async def dispatch(name, arguments, _actor, **_):
        calls.append(name)
        assert arguments["start_at"] == "2026-09-10T16:00:00+08:00"
        assert arguments["deadline_at"] is None
        return {"status": "ok", "data": {"pending_action": {**arguments, "assignee_name": "Тэмүүлэн", "action_reference": "test-reference"}}}

    monkeypatch.setattr(gateway_module, "datetime", Clock)
    monkeypatch.setattr(gateway, "_post", forbidden)
    monkeypatch.setattr(gateway, "_preflight_grounding", forbidden)
    monkeypatch.setattr(gateway.tool_registry, "dispatch_tool", dispatch)
    result = asyncio.run(gateway.execute_turn(Session(), actor(channel), [{"role": "user", "content": TEXT}], conversation_id=1))
    assert result.route == "task_fast_path"
    assert "2026-09-10T16:00:00+08:00" in result.answer
    assert not result.degraded
    assert calls == ["oyuns_tasks_prepare_create"]


def test_live_model_missing_time_is_repaired_without_second_model_call(monkeypatch):
    gateway = AIGateway()
    posts = []

    async def classify(_):
        return Classification(category="simple_qa", language="mn", requires_freshness=False, requires_enterprise_tools=True, cache_eligible=False, enterprise_intents=["tasks_write"])

    async def post(*_, **__):
        posts.append(1)
        assert len(posts) == 1
        return {"output": [{"type": "function_call", "name": "oyuns_tasks_prepare_create", "call_id": "call1", "arguments": '{"title":"Хурал","assignee":"self","participants":["Бат"],"start_at":null,"deadline_at":"2026-09-10T07:00:00+08:00"}'}]}

    async def dispatch(_name, arguments, _actor, **_):
        assert arguments["start_at"] == "2026-09-10T16:00:00+08:00"
        assert arguments["deadline_at"] is None
        assert arguments["participants"] == ["Бат"]
        return {"status": "ok", "data": {"pending_action": arguments}}

    async def circuit(_):
        return False

    monkeypatch.setattr(gateway, "_classify", classify)
    monkeypatch.setattr(gateway, "_post", post)
    monkeypatch.setattr(gateway.cache, "circuit_open", circuit)
    monkeypatch.setattr(gateway.tool_registry, "dispatch_tool", dispatch)
    request = GatewayRequest(text="Баттай маргааш 16 цагаас хуралтай даалгавар үүсгэ", history=[], channel="telegram", actor_context=actor(), database=Session(), grounding_context={"current_time": NOW.isoformat(), "timezone": "Asia/Ulaanbaatar"})
    response = asyncio.run(gateway.respond(request.database, request))
    assert "2026-09-10T16:00:00+08:00" in response.answer
    assert len(posts) == 1


def test_telegram_delivers_preview_and_accepts_compact_callback(monkeypatch):
    token = create_action_preview_token(action_id=2147483647, payload_digest="a" * 64, account_id=11, organization_id=1, channel="telegram")
    messages = []

    class TelegramMessage:
        chat = SimpleNamespace(id=99)

        async def answer(self, content, **kwargs):
            keyboard = kwargs.get("reply_markup")
            if keyboard:
                assert len(keyboard.inline_keyboard[0][0].callback_data.encode()) <= 64, "Telegram BUTTON_DATA_INVALID"
            messages.append((content, kwargs))

    async def lookup(*_):
        return actor()

    async def execute_turn(*_, **__):
        return GatewayResponse(answer="Эхлэх: 2026-09-10T16:00:00+08:00", sources=[], route="task_fast_path", model="local", cache="bypass", web_search_used=False, usage={}, tool_results=[{"data": {"pending_action": {"action_reference": action_reference(actor(), token=token, channel="telegram")}}}])

    async def confirm(_db, _actor, received, *, channel):
        assert received == token
        assert verify_action_preview_token(received, payload_digest="a" * 64, account_id=_actor.account_id, organization_id=_actor.organization_id, channel=channel)
        return {"status": "ok", "data": {"created": {"title": "Хурал"}}}

    async def callback_answer(*_, **__):
        pass

    monkeypatch.setattr(assistant_handlers, "AsyncSessionLocal", Session)
    monkeypatch.setattr(assistant_handlers, "actor_from_telegram_id", lookup)
    monkeypatch.setattr(assistant_handlers.ai_gateway, "execute_turn", execute_turn)
    monkeypatch.setattr(enterprise_tools, "confirm_task_update", confirm)
    message = TelegramMessage()
    asyncio.run(assistant_handlers.route_and_respond(message, None, TEXT, employee=None, is_manager=False, tg_id="77", voice_mode=False))
    assert "temporarily unavailable" not in messages[-1][0]
    callback_data = messages[-1][1]["reply_markup"].inline_keyboard[0][0].callback_data
    asyncio.run(assistant_handlers.confirm_enterprise_task_update(SimpleNamespace(data=callback_data, answer=callback_answer, message=message), tg_id="77"))


def test_confirmed_task_retains_start_and_contributors(monkeypatch):
    session = Session()

    async def changed(*_, **__):
        return SimpleNamespace(id=1)

    async def notify(*_, **__):
        return []

    monkeypatch.setattr(enterprise_tools, "record_change", changed)
    monkeypatch.setattr(enterprise_tools, "create_notifications", notify)
    pending = SimpleNamespace(consumed_at=None, expires_at=datetime.now(timezone.utc) + timedelta(minutes=10), payload={"title": "Хурал", "start_at": "2026-09-10T16:00:00+08:00", "deadline_at": None, "assignee_id": 7, "assignee_ids": [7, 8]})
    result = asyncio.run(enterprise_tools._confirm_task_creation(session, actor(), pending, channel="telegram"))
    task = next(item for item in session.added if isinstance(item, enterprise_tools.Task))
    assert task.start_at == datetime.fromisoformat("2026-09-10T16:00:00+08:00")
    assert task.deadline_at is None
    assert result["data"]["created"]["start_at"] == "2026-09-10T16:00:00+08:00"
    assignments = {item.employee_id: item.assignment_role for item in session.added if isinstance(item, enterprise_tools.TaskAssignee)}
    assert assignments == {7: "primary", 8: "contributor"}


def test_fast_preview_timeout_returns_task_error_without_model_retry(monkeypatch):
    gateway = AIGateway()

    async def slow(*_, **__):
        await asyncio.sleep(10)

    async def forbidden(*_, **__):
        pytest.fail("A storage failure must not retry the request through a model")

    monkeypatch.setattr(settings, "AI_GATEWAY_TOOL_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(gateway.tool_registry, "dispatch_tool", slow)
    monkeypatch.setattr(gateway, "_post", forbidden)
    monkeypatch.setattr(gateway, "_preflight_grounding", forbidden)
    result = asyncio.run(gateway.execute_turn(Session(), actor(), [{"role": "user", "content": TEXT}], conversation_id=1))
    assert result.route == "task_preview_unavailable"
    assert result.degraded
    assert "хадгалж чадсангүй" in result.answer


def test_start_requires_a_timezone():
    with pytest.raises(ValueError, match="UTC offset"):
        enterprise_tools.AssistantTaskInput(title="Meeting", start_at="2026-09-10T16:00:00")


@pytest.mark.parametrize(("prompt", "expected"), [
    ("тайланг 2026-09-15 гэхэд дуусгах даалгавар үүсгэ", {"deadline_at": "2026-09-15T00:00:00+08:00"}),
    ("Баттай баасан гарагт уулзах даалгавар үүсгэ", {"start_at": "2026-09-11T00:00:00+08:00"}),
    ("Create a task to finish by Friday", {"deadline_at": "2026-09-11T00:00:00+08:00"}),
    ("маргааш уулзах даалгавар үүсгэ", {"start_at": "2026-09-10T00:00:00+08:00"}),
    ("Meet tomorrow from 4pm until 5pm", {}),
])
def test_date_only_and_ampm_range_recovery(prompt, expected):
    assert task_schedule_fields(prompt, now=NOW, tz="Asia/Ulaanbaatar") == expected
