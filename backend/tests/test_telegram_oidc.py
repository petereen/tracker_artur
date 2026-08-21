import asyncio
import base64
import hashlib
from datetime import datetime, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import Response

from app.main import app
from app.models.models import Base, TelegramOAuthState
from app.routers.enterprise_auth import (
    AuthCapabilities,
    NativeTelegramExchange,
    NativeTelegramStart,
    _telegram_session,
    telegram_web_callback,
)
from app.core.config import settings
from app.services import telegram_oidc


def test_telegram_oauth_state_schema_protects_verifier_and_nonce():
    table = Base.metadata.tables["telegram_oauth_states"]
    assert {"state_hash", "nonce_hash", "encrypted_nonce", "encrypted_code_verifier", "platform", "used_at"}.issubset(table.c.keys())
    assert Base.metadata.tables["user_accounts"].c.telegram_oidc_subject.unique is True
    assert table.c.state_hash.unique is True
    assert table.c.nonce_hash.unique is True
    assert "nonce" not in table.c
    assert "code_verifier" not in table.c


def test_native_telegram_contracts_and_routes_are_registered():
    assert NativeTelegramStart(platform="ios").platform == "ios"
    assert NativeTelegramExchange(code="authorization-code", state="s" * 32).state == "s" * 32
    paths = {route.path for route in app.routes}
    assert "/v1/auth/capabilities" in paths
    assert "/v1/auth/telegram-native/start" in paths
    assert "/v1/auth/telegram-native/exchange" in paths
    assert "/v1/auth/telegram" in paths
    assert "/v1/auth/telegram/callback" in paths
    assert AuthCapabilities(telegram_native=False).telegram_native is False


def test_pkce_and_state_values_are_non_reversible_hashes():
    state, nonce, verifier, state_hash, nonce_hash = telegram_oidc.new_state_values()
    assert state and nonce and verifier
    assert state_hash == hashlib.sha256(state.encode()).hexdigest()
    assert nonce_hash == hashlib.sha256(nonce.encode()).hexdigest()
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert telegram_oidc._code_challenge(verifier) == expected
    assert state not in state_hash
    assert nonce not in nonce_hash


def test_secret_material_is_encrypted_before_state_persistence(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "telegram-oidc-test-secret")
    encrypted_nonce = telegram_oidc.encrypt_nonce("nonce-value")
    encrypted_verifier = telegram_oidc.encrypt_verifier("verifier-value")
    assert "nonce-value" not in encrypted_nonce
    assert "verifier-value" not in encrypted_verifier
    assert telegram_oidc.decrypt_nonce(encrypted_nonce) == "nonce-value"
    assert telegram_oidc.decrypt_verifier(encrypted_verifier) == "verifier-value"


def test_browser_authorization_uses_oidc_pkce_without_legacy_parameters(monkeypatch):
    async def discovery():
        return {"authorization_endpoint": "https://oauth.telegram.org/auth"}

    monkeypatch.setattr(telegram_oidc, "discovery", discovery)
    url = asyncio.run(telegram_oidc.authorization_url("state", "nonce", "verifier", redirect_uri="https://example.com/callback"))
    params = parse_qs(urlparse(url).query)
    assert params["client_id"] == [settings.TELEGRAM_OIDC_CLIENT_ID]
    assert params["response_type"] == ["code"]
    assert params["scope"] == ["openid profile"]
    assert params["code_challenge_method"] == ["S256"]
    assert "bot_id" not in params
    assert "origin" not in params
    assert "auth_date" not in params


def test_token_exchange_uses_basic_auth_and_keeps_secret_out_of_form(monkeypatch):
    calls = {}

    class FakeResponse:
        status = 200

        async def json(self, content_type=None):
            return {"id_token": "signed-id-token"}

    class Context:
        async def __aenter__(self):
            return FakeResponse()

        async def __aexit__(self, *_args):
            return None

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def post(self, url, **kwargs):
            calls.update(url=url, **kwargs)
            return Context()

    async def discovery():
        return {"token_endpoint": "https://oauth.telegram.org/token"}

    monkeypatch.setattr(telegram_oidc, "discovery", discovery)
    monkeypatch.setattr(telegram_oidc.aiohttp, "ClientSession", lambda **_kwargs: Session())
    asyncio.run(telegram_oidc.exchange_code("code", "verifier", redirect_uri="https://example.com/callback"))
    assert calls["auth"].login == settings.TELEGRAM_OIDC_CLIENT_ID
    assert calls["auth"].password == settings.TELEGRAM_OIDC_CLIENT_SECRET
    assert "client_secret" not in calls["data"]


def test_invalid_id_token_claims_are_rejected_after_decode(monkeypatch):
    async def discovery():
        return {"issuer": settings.TELEGRAM_OIDC_ISSUER, "jwks_uri": "https://oauth.telegram.org/.well-known/jwks.json"}

    async def keys(_url):
        return {"keys": [{"kid": "test"}]}

    monkeypatch.setattr(telegram_oidc, "discovery", discovery)
    monkeypatch.setattr(telegram_oidc, "_get_json", keys)
    monkeypatch.setattr(telegram_oidc.jwt, "decode", lambda *_args, **_kwargs: {"sub": "123", "aud": settings.TELEGRAM_OIDC_CLIENT_ID, "iss": settings.TELEGRAM_OIDC_ISSUER, "exp": 4_000_000_000})
    telegram_oidc._jwks_cache = None
    with pytest.raises(telegram_oidc.TelegramOIDCError, match="invalid"):
        asyncio.run(telegram_oidc.validate_id_token("token", "nonce"))


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _CallbackDb:
    def __init__(self, record):
        self.record = record
        self.commits = 0

    async def execute(self, _statement):
        return _ScalarResult(self.record)

    async def commit(self):
        self.commits += 1


def _web_callback_record(state: str):
    return SimpleNamespace(
        state_hash=hashlib.sha256(state.encode()).hexdigest(),
        platform="web",
        used_at=None,
        expires_at=datetime.now(timezone.utc) + telegram_oidc.STATE_TTL,
        encrypted_nonce=telegram_oidc.encrypt_nonce("nonce"),
        encrypted_code_verifier=telegram_oidc.encrypt_verifier("verifier"),
    )


def test_successful_browser_callback_validates_state_and_issues_existing_session(monkeypatch):
    state = "s" * 48
    db = _CallbackDb(_web_callback_record(state))
    captured = {}
    monkeypatch.setattr(telegram_oidc, "is_configured", lambda: True)

    async def exchange(code, verifier, *, redirect_uri):
        captured.update(code=code, verifier=verifier, redirect_uri=redirect_uri)
        return {"id_token": "signed"}

    async def validate(token, nonce):
        assert token == "signed"
        assert nonce == "nonce"
        return {"sub": "123", "preferred_username": "alice"}

    async def session(response, _db, telegram_id, username, device_label, origin):
        captured.update(telegram_id=telegram_id, username=username, device_label=device_label, origin=origin)

    monkeypatch.setattr(telegram_oidc, "exchange_code", exchange)
    monkeypatch.setattr(telegram_oidc, "validate_id_token", validate)
    monkeypatch.setattr("app.routers.enterprise_auth._telegram_session", session)
    response = asyncio.run(telegram_web_callback(code="authorization-code", state=state, state_cookie=telegram_oidc.encrypt_state(state), db=db))
    assert response.headers["location"] == settings.PUBLIC_APP_URL.rstrip("/") + "/"
    assert captured["telegram_id"] == "123"
    assert captured["device_label"] == "telegram-oidc-web"
    assert db.record.used_at is not None


def test_browser_callback_rejects_invalid_state_before_database_lookup(monkeypatch):
    class NoLookupDb:
        async def execute(self, _statement):
            raise AssertionError("invalid state must not query the transaction")

    monkeypatch.setattr(telegram_oidc, "is_configured", lambda: True)
    response = asyncio.run(telegram_web_callback(state="s" * 48, state_cookie=telegram_oidc.encrypt_state("different"), db=NoLookupDb()))
    assert "telegram_auth_error=invalid_state" in response.headers["location"]


def test_browser_callback_reports_token_exchange_failure(monkeypatch):
    state = "s" * 48
    db = _CallbackDb(_web_callback_record(state))
    monkeypatch.setattr(telegram_oidc, "is_configured", lambda: True)

    async def exchange(*_args, **_kwargs):
        raise telegram_oidc.TelegramOIDCError("provider rejected code")

    monkeypatch.setattr(telegram_oidc, "exchange_code", exchange)
    response = asyncio.run(telegram_web_callback(code="bad-code", state=state, state_cookie=telegram_oidc.encrypt_state(state), db=db))
    assert "telegram_auth_error=token_exchange_failed" in response.headers["location"]


def test_telegram_session_creates_and_reuses_accounts_by_existing_telegram_identity():
    employee = SimpleNamespace(id=7, telegram_id="123", telegram_username="alice", email=None, is_active=True, primary_language="mn")
    existing = SimpleNamespace(id=9, status="active", failed_login_count=2, locked_until=None, last_login_at=None, organization_id=1)

    class Roles:
        def scalars(self): return self
        def all(self): return ["member"]

    class ExistingDb:
        def __init__(self): self.added = []
        async def scalar(self, _statement): return employee if not hasattr(self, "employee_seen") else existing
        async def execute(self, _statement): return Roles()
        def add(self, value): self.added.append(value)
        async def commit(self): pass

    existing_db = ExistingDb()
    existing_db.employee_seen = False
    async def scalar_existing(statement):
        if not existing_db.employee_seen:
            existing_db.employee_seen = True
            return employee
        return existing
    existing_db.scalar = scalar_existing
    result = asyncio.run(_telegram_session(Response(), existing_db, "123", "alice", "telegram-oidc-web", None))
    assert result.access_token
    assert existing.last_login_at is not None
    assert any(type(item).__name__ == "RefreshSession" for item in existing_db.added)

    class NewDb(ExistingDb):
        def __init__(self):
            super().__init__()
            self.calls = 0
        async def scalar(self, _statement):
            self.calls += 1
            return employee if self.calls == 1 else None
        async def get(self, _model, _id): return SimpleNamespace(id=1)
        async def flush(self): pass
        async def execute(self, _statement): return RolesEmpty()

    class RolesEmpty(Roles):
        def all(self): return []

    new_db = NewDb()
    asyncio.run(_telegram_session(Response(), new_db, "123", "alice", "telegram-oidc-web", None))
    assert any(getattr(item, "email", None) == "telegram-123" for item in new_db.added)


def test_oidc_subject_reuses_existing_account_and_is_persisted_for_new_account():
    employee = SimpleNamespace(id=7, telegram_id="456", telegram_username="bob", email=None, is_active=True, primary_language="mn")
    existing = SimpleNamespace(id=10, employee_id=7, telegram_oidc_subject="stable-subject", status="active", failed_login_count=0, locked_until=None, last_login_at=None, organization_id=1)

    class Roles:
        def scalars(self): return self
        def all(self): return ["member"]

    class SubjectDb:
        def __init__(self, values): self.values, self.added = list(values), []
        async def scalar(self, _statement): return self.values.pop(0)
        async def execute(self, _statement): return Roles()
        def add(self, value): self.added.append(value)
        async def commit(self): pass
        async def flush(self): pass
        async def get(self, _model, _id): return SimpleNamespace(id=1)

    existing_db = SubjectDb([existing, employee])
    asyncio.run(_telegram_session(Response(), existing_db, "999", "changed-name", "telegram-oidc-web", None, "stable-subject"))
    assert existing.last_login_at is not None
    assert not any(type(item).__name__ == "UserAccount" for item in existing_db.added)

    new_db = SubjectDb([None, employee, None])
    asyncio.run(_telegram_session(Response(), new_db, "456", "bob", "telegram-oidc-web", None, "new-subject"))
    account = next(item for item in new_db.added if type(item).__name__ == "UserAccount")
    assert account.telegram_oidc_subject == "new-subject"
