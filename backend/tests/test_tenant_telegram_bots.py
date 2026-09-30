"""Per-tenant Telegram bots: registry, handshake, Mini App signatures, bot
middleware isolation, manager recipients and worker Telegram ID gating."""

import asyncio
import hashlib
import hmac
import json
import time
from types import SimpleNamespace
from urllib.parse import urlencode

import httpx
import pytest

from app.core import telegram_auth
from app.core.config import settings
from app.core.tenancy import current_tenant_id, tenant_scope
from app.services import telegram_bots
from app.services.manager_recipients import manager_telegram_ids
from app.services.secret_box import encrypt_secret
from app.services.telegram_bots import TenantBot, TelegramBotError

TOKEN_A = "111111:" + "A" * 35
TOKEN_B = "222222:" + "B" * 35
PLATFORM = "999999:" + "P" * 35


def _row(organization_id, token, status="active", username=None):
    return SimpleNamespace(
        organization_id=organization_id, bot_id=telegram_bots.token_bot_id(token), token_enc=encrypt_secret(token),
        bot_username=username, status=status,
    )


def _signed_init_data(token: str, user: dict) -> str:
    pairs = {"auth_date": str(int(time.time())), "query_id": "q1", "user": json.dumps(user)}
    check = "\n".join(f"{key}={pairs[key]}" for key in sorted(pairs))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    pairs["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(pairs)


def test_token_helpers():
    assert telegram_bots.token_bot_id(TOKEN_A) == 111111
    assert telegram_bots.token_bot_id("not-a-token") is None
    assert telegram_bots.mask_token(TOKEN_A) == "111111:…AAAA"


def test_registry_keeps_the_platform_bot_for_the_primary_tenant_only(monkeypatch):
    monkeypatch.setattr(settings, "BOT_TOKEN", PLATFORM)
    bots = telegram_bots._build([_row(2, TOKEN_A)], primary_id=1)
    assert [(bot.organization_id, bot.source) for bot in bots] == [(2, "tenant"), (1, "platform")]

    # Once the primary tenant connects its own bot the platform bot steps aside.
    bots = telegram_bots._build([_row(1, TOKEN_B), _row(2, TOKEN_A)], primary_id=1)
    assert {bot.source for bot in bots} == {"tenant"}
    # Pending bots are polled (handshake) but do not deliver notifications.
    pending = telegram_bots._build([_row(2, TOKEN_A, status="pending")], primary_id=1)[0]
    assert pending.status == "pending" and not pending.delivers


def test_registry_lookup_by_tenant_only_returns_delivering_bots(monkeypatch):
    registry = telegram_bots.BotRegistry()
    bots = [TenantBot(2, 111111, TOKEN_A, "a_bot", "pending", "tenant"), TenantBot(1, 999999, PLATFORM, None, "active", "platform")]
    monkeypatch.setattr(registry, "load_sync", lambda: registry._store(bots))
    assert registry.for_organization_sync(2) is None
    assert registry.for_organization_sync(2, delivering=False).bot_id == 111111
    assert registry.for_organization_sync(1).source == "platform"
    assert registry.for_bot_id_sync(111111).organization_id == 2


def _mock_telegram(monkeypatch, handler):
    real_client = httpx.AsyncClient
    monkeypatch.setattr(telegram_bots.httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))


def test_fetch_bot_identity_reads_get_me(monkeypatch):
    _mock_telegram(monkeypatch, lambda request: httpx.Response(200, json={"ok": True, "result": {"id": 111111, "is_bot": True, "first_name": "Acme", "username": "acme_bot"}}))
    identity = asyncio.run(telegram_bots.fetch_bot_identity(TOKEN_A))
    assert (identity.id, identity.username, identity.name) == (111111, "acme_bot", "Acme")


@pytest.mark.parametrize("token, response, code", [
    ("garbage", None, "invalid_token"),
    (TOKEN_A, httpx.Response(401, json={"ok": False, "error_code": 401}), "token_rejected"),
    (TOKEN_A, httpx.Response(200, json={"ok": True, "result": {"id": 5, "is_bot": True}}), "invalid_token"),
])
def test_fetch_bot_identity_rejects_bad_tokens(monkeypatch, token, response, code):
    _mock_telegram(monkeypatch, lambda request: response)
    with pytest.raises(TelegramBotError) as error:
        asyncio.run(telegram_bots.fetch_bot_identity(token))
    assert error.value.code == code


def test_handshake_links_use_a_start_payload():
    code = telegram_bots.new_handshake_code()
    assert len(telegram_bots.handshake_payload(code)) <= 64
    assert telegram_bots.handshake_url("acme_bot", code) == f"https://t.me/acme_bot?start=oyuns-{code}"
    assert telegram_bots.handshake_url(None, code) is None
    row = SimpleNamespace(handshake_code_enc=None, handshake_expires_at=None)
    issued = telegram_bots.issue_handshake(row)
    assert telegram_bots.read_handshake_code(row) == issued


class _FakeResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _HandshakeSession:
    def __init__(self, row, account=None, employee=None, taken=None):
        self.row, self.account, self.employee, self.taken = row, account, employee, taken
        self.calls = 0
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, _query):
        self.calls += 1
        return _FakeResult(self.row if self.calls == 1 else self.taken)

    def get(self, model, _id):
        return self.account if model.__name__ == "UserAccount" else self.employee

    def commit(self):
        self.committed = True


def test_handshake_activates_the_bot_and_links_the_admin(monkeypatch):
    row = SimpleNamespace(organization_id=2, status="pending", handshake_code_enc=None, handshake_expires_at=None,
                          handshake_completed_at=None, handshake_telegram_id=None, last_error="x", connected_by_account_id=7)
    code = telegram_bots.issue_handshake(row)
    employee = SimpleNamespace(organization_id=2, telegram_id=None, telegram_username=None, name="Admin")
    session = _HandshakeSession(row, account=SimpleNamespace(employee_id=3), employee=employee)
    monkeypatch.setattr("app.bot.db.get_session", lambda: session)

    error, linked = telegram_bots.complete_handshake_sync(111111, code, SimpleNamespace(id=555, username="boss"))
    assert error is None and linked == "Admin"
    assert row.status == "active" and row.handshake_telegram_id == "555" and row.handshake_code_enc is None
    assert employee.telegram_id == "555" and session.committed


def test_handshake_rejects_wrong_codes(monkeypatch):
    row = SimpleNamespace(organization_id=2, status="pending", handshake_code_enc=None, handshake_expires_at=None, connected_by_account_id=None)
    telegram_bots.issue_handshake(row)
    monkeypatch.setattr("app.bot.db.get_session", lambda: _HandshakeSession(row))
    assert telegram_bots.complete_handshake_sync(111111, "wrong-ö", SimpleNamespace(id=1))[0] == "invalid"
    assert row.status == "pending"


def test_mini_app_data_is_attributed_to_the_signing_bot(monkeypatch):
    bots = [TenantBot(1, 999999, PLATFORM, None, "active", "platform"), TenantBot(2, 111111, TOKEN_A, "a_bot", "active", "tenant")]

    async def fake_bots():
        return bots

    monkeypatch.setattr(telegram_bots.registry, "bots", fake_bots)
    init_data = _signed_init_data(TOKEN_A, {"id": 42, "username": "worker"})
    user, tenant = asyncio.run(telegram_auth.verify_tenant_init_data(init_data))
    assert user["id"] == 42 and tenant == 2

    # On another tenant's host the same signature is not accepted.
    with tenant_scope(1):
        assert asyncio.run(telegram_auth.verify_tenant_init_data(init_data)) == (None, None)
    assert asyncio.run(telegram_auth.verify_tenant_init_data(_signed_init_data(TOKEN_B, {"id": 1}))) == (None, None)


def test_manager_fallback_id_belongs_to_the_primary_tenant(monkeypatch):
    monkeypatch.setattr(settings, "MANAGER_TG_ID", "777")
    assert manager_telegram_ids(None) == ["777"]
    assert manager_telegram_ids(None, primary=False) == []
    configured = SimpleNamespace(telegram_admin_ids=["1", "2", "1"], telegram_id="3")
    assert manager_telegram_ids(configured, primary=False) == ["3", "1", "2"]


def test_bot_middleware_ignores_workers_of_other_tenants_and_binds_the_bot_tenant(monkeypatch):
    from app.bot import middlewares

    worker = SimpleNamespace(id=5, organization_id=1, name="Primary worker")
    monkeypatch.setattr(middlewares, "get_employee_by_tg", lambda tg_id: worker)
    linked = []
    monkeypatch.setattr(middlewares, "link_employee_telegram", lambda *args: linked.append(args))
    monkeypatch.setattr(middlewares, "get_manager_settings", lambda organization_id=None: None)
    monkeypatch.setattr(middlewares, "is_primary_tenant", lambda organization_id: organization_id == 1)

    async def operational(_tenant_id):
        return True

    monkeypatch.setattr(middlewares, "_tenant_operational", operational)
    seen = {}

    async def handler(event, data):
        seen.update(data, tenant=current_tenant_id())

    data = {"bot_tenant_id": 2, "event_from_user": SimpleNamespace(id=100, username="worker")}
    asyncio.run(middlewares.EmployeeMiddleware()(handler, SimpleNamespace(), data))
    assert seen["employee"] is None and seen["foreign_tenant"] is True
    assert seen["tenant"] == 2 and linked == []
    assert current_tenant_id() is None

    data = {"bot_tenant_id": 1, "event_from_user": SimpleNamespace(id=100, username="worker")}
    asyncio.run(middlewares.EmployeeMiddleware()(handler, SimpleNamespace(), data))
    assert seen["employee"] is worker and seen["foreign_tenant"] is False and seen["tenant"] == 1


def test_suspended_tenant_bots_answer_without_running_handlers(monkeypatch):
    from aiogram.types import Message

    from app.bot import middlewares

    async def not_operational(_tenant_id):
        return False

    monkeypatch.setattr(middlewares, "_tenant_operational", not_operational)
    answers = []

    class FakeMessage(Message):
        pass

    message = FakeMessage.model_construct(message_id=1, date=0, chat=None)
    object.__setattr__(message, "answer", lambda text: answers.append(text) or asyncio.sleep(0))

    async def handler(event, data):  # pragma: no cover - must not run
        raise AssertionError("handler ran for a suspended tenant")

    asyncio.run(middlewares.EmployeeMiddleware()(handler, message, {"bot_tenant_id": 3}))
    assert answers == [middlewares.WORKSPACE_UNAVAILABLE]


class _ScalarDB:
    def __init__(self, *values):
        self.values = list(values)

    async def scalar(self, _query):
        return self.values.pop(0)


def test_worker_telegram_ids_need_a_connected_bot(monkeypatch):
    monkeypatch.setattr(settings, "BOT_TOKEN", "")
    # No tenant bot row, not the primary tenant → rejected.
    with pytest.raises(TelegramBotError) as error:
        asyncio.run(telegram_bots.require_bot_for_telegram_id(_ScalarDB(None), 2, "12345"))
    assert error.value.code == "telegram_bot_not_connected" and error.value.status_code == 409
    # A pending (not yet handshaken) bot does not count either.
    assert asyncio.run(telegram_bots.organization_has_bot(_ScalarDB("pending"), 2)) is False
    assert asyncio.run(telegram_bots.organization_has_bot(_ScalarDB("active"), 2)) is True
    # Empty IDs never need a bot.
    asyncio.run(telegram_bots.require_bot_for_telegram_id(_ScalarDB(), 2, None))
    # The primary tenant keeps the platform bot.
    monkeypatch.setattr(settings, "BOT_TOKEN", PLATFORM)
    assert asyncio.run(telegram_bots.organization_has_bot(_ScalarDB(None, True), 1)) is True


def test_tenant_urls_prefer_custom_domain_then_subdomain(monkeypatch):
    monkeypatch.setattr(settings, "TENANT_BASE_DOMAIN", "oyunserp.com")
    monkeypatch.setattr(settings, "PUBLIC_APP_URL", "https://erp.oyuns.mn/")
    assert telegram_bots._tenant_base_url("acme", False, "erp.acme.mn") == "https://erp.acme.mn"
    assert telegram_bots._tenant_base_url("acme", False, None) == "https://acme.oyunserp.com"
    assert telegram_bots._tenant_base_url("oyuns", True, None) == "https://erp.oyuns.mn"
