"""Tenant-enforced two-factor login for workspace accounts."""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core import enterprise_deps
from app.core.security import create_enterprise_access_token, decode_token
from app.core.tenancy import two_factor_setting
from app.routers import enterprise_auth
from app.routers.enterprise_auth import TwoFactorCode
from app.services import totp
from app.services.secret_box import decrypt_secret, encrypt_secret


class FakeDB:
    def __init__(self, account, session=None):
        self.account = account
        self.session = session
        self.executed = []
        self.commits = 0

    async def get(self, model, _id, **_kwargs):
        return self.account if model.__name__ == "UserAccount" else None

    async def scalar(self, _query):
        return self.session

    async def execute(self, statement):
        self.executed.append(statement)

    async def commit(self):
        self.commits += 1


def _account(**values):
    base = dict(id=10, organization_id=1, email="bat", locked_until=None, failed_login_count=0,
                totp_secret_enc=None, totp_enabled_at=None, totp_last_step=None, totp_recovery_codes=[])
    base.update(values)
    return SimpleNamespace(**base)


def _session(**values):
    base = dict(id=77, auth_method="password", mfa_verified_at=None)
    base.update(values)
    return SimpleNamespace(**base)


def _actor():
    return SimpleNamespace(account_id=10, organization_id=1, employee_id=None)


def _enrolled(secret, **values):
    return _account(totp_secret_enc=encrypt_secret(secret), totp_enabled_at=datetime.now(timezone.utc), **values)


@pytest.fixture(autouse=True)
def _no_audit(monkeypatch):
    async def record_change(*_args, **_kwargs):
        return None

    monkeypatch.setattr(enterprise_auth, "record_change", record_change)


def _gate(monkeypatch, required):
    async def actor_from_account_id(_account_id, _db):
        return SimpleNamespace(account_id=10, organization_id=1)

    async def tenant_requires_two_factor(_organization_id):
        return required

    monkeypatch.setattr(enterprise_deps, "actor_from_account_id", actor_from_account_id)
    monkeypatch.setattr(enterprise_deps, "tenant_requires_two_factor", tenant_requires_two_factor)


def test_setting_is_off_unless_the_tenant_switched_it_on():
    assert two_factor_setting(None) is False
    assert two_factor_setting({"security": {}}) is False
    assert two_factor_setting({"security": {"two_factor_required": True}}) is True


def test_access_tokens_carry_the_session_and_the_passed_factor():
    plain = decode_token(create_enterprise_access_token(10, 1, "password"))
    assert "mfa" not in plain and "sid" not in plain
    verified = decode_token(create_enterprise_access_token(10, 1, "password", session_id=77, mfa=True))
    assert verified["mfa"] is True and verified["sid"] == 77


def test_unverified_sessions_are_stopped_while_the_tenant_requires_two_factor(monkeypatch):
    _gate(monkeypatch, required=True)
    with pytest.raises(HTTPException) as error:
        asyncio.run(enterprise_deps.actor_from_token(create_enterprise_access_token(10, 1, "password"), None))
    assert error.value.status_code == 403 and error.value.detail["code"] == "two_factor_required"
    # The setup/verify endpoints still resolve the same session.
    actor, claims = asyncio.run(enterprise_deps.session_actor_from_token(create_enterprise_access_token(10, 1, "password"), None))
    assert actor.account_id == 10 and not claims.get("mfa")
    verified = create_enterprise_access_token(10, 1, "password", session_id=77, mfa=True)
    assert asyncio.run(enterprise_deps.actor_from_token(verified, None)).account_id == 10


def test_tenants_without_the_requirement_are_unaffected(monkeypatch):
    _gate(monkeypatch, required=False)
    assert asyncio.run(enterprise_deps.actor_from_token(create_enterprise_access_token(10, 1, "password"), None)).account_id == 10


def test_enrolment_verifies_the_session_and_returns_recovery_codes_once(monkeypatch):
    async def state(_organization_id):
        return SimpleNamespace(name="Acme")

    monkeypatch.setattr(enterprise_auth.tenant_directory, "state", state)
    account, session = _account(), _session()
    db = FakeDB(account, session)
    setup = asyncio.run(enterprise_auth.two_factor_setup(db, (_actor(), {})))
    assert setup["issuer"] == "Acme" and setup["account"] == "bat"
    assert decrypt_secret(account.totp_secret_enc) == setup["secret"]
    # Reloading the page shows the same secret.
    assert asyncio.run(enterprise_auth.two_factor_setup(db, (_actor(), {})))["secret"] == setup["secret"]

    with pytest.raises(HTTPException) as wrong:
        asyncio.run(enterprise_auth.two_factor_enable(TwoFactorCode(code="000000"), db, (_actor(), {"sid": 77}), None))
    assert wrong.value.detail["code"] == "invalid_code" and account.totp_enabled_at is None

    code = totp.code_at(setup["secret"], totp.current_step())
    result = asyncio.run(enterprise_auth.two_factor_enable(TwoFactorCode(code=code), db, (_actor(), {"sid": 77}), None))
    assert account.totp_enabled_at is not None and session.mfa_verified_at is not None
    assert len(result["recovery_codes"]) == 10 and not set(result["recovery_codes"]) & set(account.totp_recovery_codes)
    claims = decode_token(result["access_token"])
    assert claims["mfa"] is True and claims["sid"] == 77

    with pytest.raises(HTTPException) as again:
        asyncio.run(enterprise_auth.two_factor_setup(db, (_actor(), {})))
    assert again.value.detail["code"] == "two_factor_already_enabled"


def test_sign_in_accepts_an_app_code_once_or_a_recovery_code():
    secret = totp.generate_secret()
    codes = totp.generate_recovery_codes()
    account = _enrolled(secret, totp_recovery_codes=[totp.hash_recovery_code(code) for code in codes], failed_login_count=2)
    session = _session()
    db = FakeDB(account, session)
    code = totp.code_at(secret, totp.current_step())
    result = asyncio.run(enterprise_auth.two_factor_verify(TwoFactorCode(code=code), db, (_actor(), {"sid": 77}), None))
    assert decode_token(result["access_token"])["mfa"] is True and result["recovery_codes_left"] == 10
    assert session.mfa_verified_at is not None and account.failed_login_count == 0

    # The same code cannot be replayed on another session.
    with pytest.raises(HTTPException) as replay:
        asyncio.run(enterprise_auth.two_factor_verify(TwoFactorCode(code=code), FakeDB(account, _session(id=78)), (_actor(), {"sid": 78}), None))
    assert replay.value.detail["code"] == "invalid_code"

    other = _session(id=79)
    result = asyncio.run(enterprise_auth.two_factor_verify(TwoFactorCode(code=codes[0]), FakeDB(account, other), (_actor(), {"sid": 79}), None))
    assert other.mfa_verified_at is not None and result["recovery_codes_left"] == 9


def test_wrong_codes_lock_the_account():
    account = _enrolled(totp.generate_secret(), failed_login_count=3)
    db = FakeDB(account, _session())
    with pytest.raises(HTTPException) as wrong:
        asyncio.run(enterprise_auth.two_factor_verify(TwoFactorCode(code="aaaaa-aaaaa"), db, (_actor(), {"sid": 77}), None))
    assert wrong.value.status_code == 400 and account.locked_until is None
    with pytest.raises(HTTPException) as locked:
        asyncio.run(enterprise_auth.two_factor_verify(TwoFactorCode(code="aaaaa-aaaaa"), db, (_actor(), {"sid": 77}), None))
    assert locked.value.status_code == 423 and account.locked_until > datetime.now(timezone.utc)
    # Even a correct code waits for the lock to expire.
    with pytest.raises(HTTPException) as still:
        asyncio.run(enterprise_auth.two_factor_verify(TwoFactorCode(code="123456"), db, (_actor(), {"sid": 77}), None))
    assert still.value.status_code == 423


def test_a_token_without_a_live_session_must_refresh_first():
    account = _enrolled(totp.generate_secret())
    with pytest.raises(HTTPException) as error:
        asyncio.run(enterprise_auth.two_factor_verify(TwoFactorCode(code="123456"), FakeDB(account, None), (_actor(), {"sid": 5}), None))
    assert error.value.status_code == 409 and error.value.detail["code"] == "session_refresh_required"


def test_password_step_keeps_the_failure_counter_while_a_code_is_owed(monkeypatch):
    async def required(_organization_id):
        return True

    monkeypatch.setattr(enterprise_auth, "tenant_requires_two_factor", required)
    assert asyncio.run(enterprise_auth._awaits_second_factor(_enrolled(totp.generate_secret()))) is True
    assert asyncio.run(enterprise_auth._awaits_second_factor(_account())) is False


def test_admin_reset_drops_the_enrolment_and_unverifies_sessions():
    account = _enrolled(totp.generate_secret(), totp_last_step=5, totp_recovery_codes=["x"],
                        locked_until=datetime.now(timezone.utc) + timedelta(minutes=5), failed_login_count=5)
    db = FakeDB(account)
    asyncio.run(enterprise_auth.reset_account_two_factor(10, db, SimpleNamespace(account_id=1, organization_id=1)))
    assert account.totp_secret_enc is None and account.totp_enabled_at is None and account.totp_recovery_codes == []
    assert account.locked_until is None and db.executed and db.commits == 1
    with pytest.raises(HTTPException) as foreign:
        asyncio.run(enterprise_auth.reset_account_two_factor(10, db, SimpleNamespace(account_id=1, organization_id=2)))
    assert foreign.value.status_code == 404


# ── Operator console: a tenant whose only admin is locked out ────────────────

class ConsoleDB(FakeDB):
    def __init__(self, account, organization, admin_role=1):
        super().__init__(account)
        self.organization = organization
        self.admin_role = admin_role
        self.added = []

    async def get(self, model, _id, **_kwargs):
        return {"UserAccount": self.account, "Organization": self.organization}.get(model.__name__)

    async def scalar(self, _query):
        return self.admin_role

    def add(self, row):
        self.added.append(row)


def _console(account, **kwargs):
    organization = SimpleNamespace(id=1, status=kwargs.pop("tenant_status", "active"))
    request = SimpleNamespace(client=SimpleNamespace(host="10.0.0.1"), headers={})
    operator = SimpleNamespace(id=3, role="superadmin")
    return ConsoleDB(account, organization, **kwargs), request, operator


def test_operator_removes_a_locked_out_admins_two_factor():
    from app.routers import platform

    account = _enrolled(totp.generate_secret(), status="active", last_login_at=None, password_hash="old", must_change_password=False,
                        locked_until=datetime.now(timezone.utc) + timedelta(minutes=5), failed_login_count=5)
    db, request, operator = _console(account)
    view = asyncio.run(platform.recover_tenant_admin(1, 10, platform.AdminRecovery(reset_two_factor=True), request, db, operator))
    assert view["two_factor_enabled"] is False and view["locked"] is False
    assert account.totp_secret_enc is None and account.password_hash == "old" and db.commits == 1
    assert [row.action for row in db.added] == ["tenant.admin_recovered"]
    assert db.added[0].details == {"admin": "bat", "password_reset": False, "two_factor_reset": True}


def test_operator_reissues_an_admin_password_and_ends_its_sessions():
    from app.core.security import verify_account_password
    from app.routers import platform

    account = _enrolled(totp.generate_secret(), status="locked", last_login_at=None, password_hash="old", must_change_password=False)
    db, request, operator = _console(account)
    asyncio.run(platform.recover_tenant_admin(1, 10, platform.AdminRecovery(password="temporary-pass-1"), request, db, operator))
    assert verify_account_password("temporary-pass-1", account.password_hash)[0] and account.must_change_password is True
    assert account.status == "active" and db.executed  # sessions revoked
    # 2FA stays unless the operator asks for its removal too.
    assert account.totp_enabled_at is not None


def test_console_recovery_is_limited_to_the_tenants_admins():
    from pydantic import ValidationError

    from app.routers import platform

    with pytest.raises(ValidationError):
        platform.AdminRecovery()
    account = _enrolled(totp.generate_secret(), status="active")
    db, request, operator = _console(account, admin_role=None)
    with pytest.raises(HTTPException) as member:
        asyncio.run(platform.recover_tenant_admin(1, 10, platform.AdminRecovery(reset_two_factor=True), request, db, operator))
    assert member.value.status_code == 404 and account.totp_enabled_at is not None
    db, request, operator = _console(_enrolled(totp.generate_secret(), organization_id=2, status="active"))
    with pytest.raises(HTTPException) as foreign:
        asyncio.run(platform.recover_tenant_admin(1, 10, platform.AdminRecovery(reset_two_factor=True), request, db, operator))
    assert foreign.value.status_code == 404
    db, request, operator = _console(account, tenant_status="terminated")
    with pytest.raises(HTTPException) as closed:
        asyncio.run(platform.recover_tenant_admin(1, 10, platform.AdminRecovery(reset_two_factor=True), request, db, operator))
    assert closed.value.status_code == 409
