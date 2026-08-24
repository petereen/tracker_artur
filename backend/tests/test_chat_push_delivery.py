import asyncio
import inspect
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx

from app.core.config import settings
from app.services import mobile_push_delivery
from app import worker


def test_fcm_chat_payload_uses_custom_channel_and_safe_deep_link(monkeypatch):
    requests = []

    async def token(_client, _service_account):
        return "access-token"

    async def run():
        async def handler(request: httpx.Request):
            requests.append(request)
            return httpx.Response(200, json={"name": "projects/test/messages/1"})

        monkeypatch.setattr(mobile_push_delivery, "_fcm_token", token)
        monkeypatch.setattr(settings, "FCM_PROJECT_ID", "test-project")
        monkeypatch.setattr(settings, "FCM_SERVICE_ACCOUNT_JSON", json.dumps({"project_id": "test-project"}))
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            assert await mobile_push_delivery._send_fcm(client, "device-token", title="Chat", body="Hello", target_url="/chat/c1?message=7", message_id=7, conversation_public_id="c1")

    asyncio.run(run())
    payload = json.loads(requests[0].content)
    assert payload["message"]["android"]["notification"]["channel_id"] == "oyuns-chat-v1"
    assert payload["message"]["data"]["target_url"] == "/chat/c1?message=7"


def test_apns_chat_payload_uses_custom_sound_and_collapse_id(monkeypatch):
    requests = []

    async def run():
        async def handler(request: httpx.Request):
            requests.append(request)
            return httpx.Response(200)

        monkeypatch.setattr(mobile_push_delivery, "_apns_token", lambda: "provider-token")
        monkeypatch.setattr(settings, "APNS_BUNDLE_ID", "mn.oyuns.workspace")
        monkeypatch.setattr(settings, "APNS_USE_SANDBOX", True)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            assert await mobile_push_delivery._send_apns(client, "device-token", title="Chat", body="Hello", target_url="/chat/c1?message=7", message_id=7, conversation_public_id="c1")

    asyncio.run(run())
    payload = json.loads(requests[0].content)
    assert payload["aps"]["sound"] == "public/sounds/oyuns_chat_notification.caf"
    assert requests[0].headers["apns-collapse-id"] == "chat-message-7"


def test_disabled_delivery_returns_before_loading_database(monkeypatch):
    class NoDatabaseAccess:
        async def execute(self, _statement):
            raise AssertionError("disabled push delivery must not query the database")

    monkeypatch.setattr(settings, "MOBILE_PUSH_DELIVERY_ENABLED", False)
    asyncio.run(mobile_push_delivery.deliver_chat_push(NoDatabaseAccess(), 7, 2))


def test_muted_deleted_and_sender_notifications_are_suppressed():
    now = datetime.now(timezone.utc)
    active_message = SimpleNamespace(deleted_at=None, sender_account_id=1)
    active_participant = SimpleNamespace(muted_until=None)
    assert mobile_push_delivery._chat_push_allowed(active_message, active_participant, 2)
    assert not mobile_push_delivery._chat_push_allowed(active_message, SimpleNamespace(muted_until=now + timedelta(hours=1)), 2)
    assert not mobile_push_delivery._chat_push_allowed(SimpleNamespace(deleted_at=now, sender_account_id=1), active_participant, 2)
    assert not mobile_push_delivery._chat_push_allowed(active_message, active_participant, 1)


def test_provider_invalid_tokens_are_reported_for_revocation(monkeypatch):
    async def fcm_token(_client, _service_account):
        return "access-token"

    async def run():
        monkeypatch.setattr(mobile_push_delivery, "_fcm_token", fcm_token)
        monkeypatch.setattr(mobile_push_delivery, "_apns_token", lambda: "provider-token")
        monkeypatch.setattr(settings, "FCM_PROJECT_ID", "test-project")
        monkeypatch.setattr(settings, "FCM_SERVICE_ACCOUNT_JSON", json.dumps({"project_id": "test-project"}))
        monkeypatch.setattr(settings, "APNS_BUNDLE_ID", "mn.oyuns.workspace")
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _request: httpx.Response(404, text="UNREGISTERED"))) as client:
            assert not await mobile_push_delivery._send_fcm(client, "invalid", title="Chat", body="Hi", target_url="/chat/c1", message_id=7, conversation_public_id="c1")
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _request: httpx.Response(410, json={"reason": "Unregistered"}))) as client:
            assert not await mobile_push_delivery._send_apns(client, "invalid", title="Chat", body="Hi", target_url="/chat/c1", message_id=7, conversation_public_id="c1")

    asyncio.run(run())


def test_worker_retries_transient_chat_push_failures_with_backoff():
    source = inspect.getsource(worker.execute_job)
    assert 'job.job_type == "chat_push"' in source
    assert 'job.state = "pending"' in source
    assert "15 * 2 ** job.attempts" in source
