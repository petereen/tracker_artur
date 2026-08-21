import base64
import hashlib

from app.main import app
from app.models.models import Base, TelegramOAuthState
from app.routers.enterprise_auth import AuthCapabilities, NativeTelegramExchange, NativeTelegramStart
from app.services import telegram_oidc


def test_telegram_oauth_state_schema_protects_verifier_and_nonce():
    table = Base.metadata.tables["telegram_oauth_states"]
    assert {"state_hash", "nonce_hash", "encrypted_nonce", "encrypted_code_verifier", "platform", "used_at"}.issubset(table.c.keys())
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
