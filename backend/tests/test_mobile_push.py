import hashlib
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import Response

from app.main import app
from app.models.models import Base, UserAccount
from app.routers.enterprise_auth import _complete_session, _is_native_origin
from app.routers.mobile import PushRegistrationInput, _token_hash
from app.services.secret_box import decrypt_secret, encrypt_secret


def test_mobile_push_schema_is_tenant_and_account_scoped_without_plaintext_token_column():
    table = Base.metadata.tables["mobile_push_registrations"]
    assert {"organization_id", "account_id", "platform", "provider", "token_hash", "encrypted_token", "revoked_at"}.issubset(table.c.keys())
    assert "token" not in table.c
    assert table.c.token_hash.unique is True


def test_push_registration_enforces_native_provider_mapping():
    assert PushRegistrationInput(platform="ios", provider="apns", token="a" * 64).provider == "apns"
    assert PushRegistrationInput(platform="android", provider="fcm", token="b" * 64).provider == "fcm"
    with pytest.raises(ValueError):
        PushRegistrationInput(platform="ios", provider="fcm", token="c" * 64)
    with pytest.raises(ValueError):
        PushRegistrationInput(platform="android", provider="apns", token="d" * 64)


def test_push_tokens_are_hashed_for_lookup_and_encrypted_for_recovery():
    token = "example-native-provider-token-123456789"
    assert _token_hash(token) == hashlib.sha256(token.encode()).hexdigest()
    encrypted = encrypt_secret(token)
    assert token not in encrypted
    assert decrypt_secret(encrypted) == token


def test_mobile_routes_are_registered():
    paths = {route.path for route in app.routes}
    assert "/v1/mobile/push-registration" in paths


def test_refresh_token_is_returned_only_for_allowlisted_native_origins():
    account = UserAccount(id=7, organization_id=3, email="native@example.com", password_hash="unused", status="active")
    native_response = Response()
    expires_at = datetime.now(timezone.utc) + timedelta(days=30)
    native_result = _complete_session(native_response, account, "native-refresh-token", expires_at, "capacitor://localhost")
    assert _is_native_origin("capacitor://localhost")
    assert native_result.refresh_token == "native-refresh-token"
    assert "set-cookie" not in native_response.headers

    web_response = Response()
    web_result = _complete_session(web_response, account, "web-refresh-token", expires_at, "https://erp.oyuns.mn")
    assert not _is_native_origin("https://erp.oyuns.mn")
    assert web_result.refresh_token is None
    assert "httponly" in web_response.headers["set-cookie"].lower()
