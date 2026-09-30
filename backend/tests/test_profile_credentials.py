"""Username/password editing for accounts that sign in through Telegram."""

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.security import create_enterprise_access_token, decode_token, hash_account_password
from app.routers import enterprise_auth
from app.routers.enterprise_auth import ProfilePasswordChange, ProfilePatch


class FakeDB:
    def __init__(self, account, scalars=()):
        self.account = account
        self.scalars = list(scalars)
        self.executed = []
        self.committed = False

    async def get(self, model, _id, **_kwargs):
        return self.account if model.__name__ == "UserAccount" else None

    async def scalar(self, _query):
        return self.scalars.pop(0) if self.scalars else None

    async def execute(self, statement):
        self.executed.append(statement)

    async def commit(self):
        self.committed = True


def _account(**values):
    base = dict(id=10, organization_id=1, email="telegram-555", password_hash=hash_account_password("old-password-123"),
                must_change_password=False, locale="mn")
    base.update(values)
    return SimpleNamespace(**base)


def _actor():
    return SimpleNamespace(account_id=10, organization_id=1, employee_id=None, granted_roles=frozenset({"member"}))


def _bearer(method):
    return f"Bearer {create_enterprise_access_token(10, 1, method)}"


def test_access_tokens_name_the_sign_in_method():
    assert decode_token(create_enterprise_access_token(10, 1, "telegram"))["amr"] == "telegram"
    assert "amr" not in decode_token(create_enterprise_access_token(10, 1))


def test_telegram_session_changes_username_without_the_old_password():
    account = _account()
    db = FakeDB(account)
    result = asyncio.run(enterprise_auth.update_profile(ProfilePatch(username="Bat.Erdene"), db, _actor(), _bearer("telegram"), None))
    assert account.email == "bat.erdene" and db.committed
    assert result["telegram_session"] is True and result["credentials_require_current_password"] is False
    assert result["requires_password_setup"] is False


def test_password_session_still_needs_the_current_password():
    account = _account(email="bat")
    with pytest.raises(HTTPException) as error:
        asyncio.run(enterprise_auth.update_profile(ProfilePatch(username="bold"), FakeDB(account), _actor(), _bearer("password"), None))
    assert error.value.status_code == 400
    asyncio.run(enterprise_auth.update_profile(ProfilePatch(username="bold", current_password="old-password-123"), FakeDB(account), _actor(), _bearer("password"), None))
    assert account.email == "bold"


def test_taken_and_reserved_usernames_are_refused():
    with pytest.raises(HTTPException) as taken:
        asyncio.run(enterprise_auth.update_profile(ProfilePatch(username="bold"), FakeDB(_account(), scalars=[99]), _actor(), _bearer("telegram"), None))
    assert taken.value.status_code == 409
    with pytest.raises(HTTPException) as reserved:
        asyncio.run(enterprise_auth.update_profile(ProfilePatch(username="telegram-777"), FakeDB(_account()), _actor(), _bearer("telegram"), None))
    assert reserved.value.status_code == 422


def test_telegram_session_sets_a_password_and_stays_signed_in():
    account = _account()
    db = FakeDB(account, scalars=[SimpleNamespace(id=3, auth_method="telegram")])
    result = asyncio.run(enterprise_auth.change_profile_password(
        ProfilePasswordChange(new_password="brand-new-password"), db, _actor(), _bearer("telegram"), "refresh-cookie",
    ))
    assert result["password_changed"] and result["username"] == "telegram-555"
    assert enterprise_auth.verify_account_password("brand-new-password", account.password_hash)[0]
    revoke_sql = str(db.executed[0])
    assert "refresh_sessions.id !=" in revoke_sql  # every other session is signed out, not this one


def test_password_session_needs_the_current_password_to_change_it():
    with pytest.raises(HTTPException) as error:
        asyncio.run(enterprise_auth.change_profile_password(
            ProfilePasswordChange(new_password="brand-new-password"), FakeDB(_account()), _actor(), _bearer("password"), None,
        ))
    assert error.value.status_code == 400


def test_old_tokens_fall_back_to_the_refresh_session_method():
    db = FakeDB(_account(), scalars=[SimpleNamespace(id=3, auth_method="telegram")])
    method, session = asyncio.run(enterprise_auth._current_session(db, 10, f"Bearer {create_enterprise_access_token(10, 1)}", "cookie"))
    assert method == "telegram" and session.id == 3
