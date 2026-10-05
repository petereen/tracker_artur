from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi import Response

from app.core.config import settings
from app.routers.enterprise_auth import LoginInput, _is_session_only, _set_refresh_cookie


def _session(lifetime: timedelta, auth_method: str = "password"):
    created = datetime.now(timezone.utc)
    return SimpleNamespace(auth_method=auth_method, created_at=created, expires_at=created + lifetime)


def test_login_remembers_by_default():
    assert LoginInput(email="A@b.c", password="x").remember_me is True


def test_short_password_session_stays_session_only_across_rotation():
    assert _is_session_only(_session(timedelta(hours=settings.SESSION_REFRESH_TOKEN_HOURS)))
    assert not _is_session_only(_session(timedelta(days=settings.REFRESH_TOKEN_DAYS)))


def test_telegram_sessions_are_never_session_only():
    assert not _is_session_only(_session(timedelta(hours=1), auth_method="telegram"))


def test_cookie_is_a_session_cookie_without_remember_me():
    expires = datetime.now(timezone.utc) + timedelta(days=30)
    remembered, forgotten = Response(), Response()
    _set_refresh_cookie(remembered, "t" * 40, expires)
    _set_refresh_cookie(forgotten, "t" * 40, expires, persistent=False)
    assert "Max-Age" in remembered.headers["set-cookie"]
    assert "Max-Age" not in forgotten.headers["set-cookie"]
