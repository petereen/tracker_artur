import asyncio
from urllib.parse import parse_qs, urlparse

from app.core.config import settings
from app.main import app
from app.models.models import Base
from app.services import attachment_storage, google_calendar
from app.services.secret_box import decrypt_secret, encrypt_secret


def test_followup_schema_and_routes_are_registered():
    assert "password_reset_tokens" in Base.metadata.tables
    paths = {route.path for route in app.routes}
    assert {
        "/v1/auth/telegram",
        "/v1/auth/accounts/invite",
        "/v1/auth/password-reset/request",
        "/v1/auth/password-reset/confirm",
        "/v1/attachments",
        "/v1/saved-views",
        "/v1/integrations/google-calendar/callback",
        "/v1/integrations/google-calendar/sync",
        "/v1/integrations/google-calendar/status",
        "/v1/integrations/google-calendar/sync-mode",
        "/v1/integrations/google-calendar/webhook",
        "/v1/analytics/drilldown",
        "/v1/tasks/{task_id}/activity",
    }.issubset(paths)


def test_sensitive_job_payloads_can_be_authenticated_and_decrypted():
    encrypted = encrypt_secret("https://example.com/reset?token=secret")
    assert "secret" not in encrypted
    assert decrypt_secret(encrypted) == "https://example.com/reset?token=secret"


def test_google_oauth_url_uses_signed_state_and_minimal_offline_scope(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "client-secret")
    monkeypatch.setattr(settings, "GOOGLE_REDIRECT_URI", "https://example.com/api/v1/integrations/google-calendar/callback")
    url = google_calendar.authorization_url(27)
    query = parse_qs(urlparse(url).query)
    assert query["access_type"] == ["offline"]
    assert query["scope"] == [google_calendar.SCOPE]
    assert query["redirect_uri"] == [settings.GOOGLE_REDIRECT_URI]
    assert google_calendar.account_from_state(query["state"][0]) == 27


def test_google_webhook_url_defaults_to_public_dokploy_domain(monkeypatch):
    monkeypatch.setattr(settings, "PUBLIC_APP_URL", "https://erp.oyuns.mn")
    monkeypatch.setattr(settings, "GOOGLE_WEBHOOK_URL", "")
    assert google_calendar.webhook_url() == "https://erp.oyuns.mn/api/v1/integrations/google-calendar/webhook"


def test_google_event_datetime_requires_timed_events():
    assert google_calendar._event_datetime({"date": "2026-08-10"}) is None
    assert google_calendar._event_datetime({"dateTime": "2026-08-10T09:30:00Z"}).isoformat() == "2026-08-10T09:30:00+00:00"


def test_local_attachment_storage_never_uses_user_filenames(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ATTACHMENT_STORAGE_BACKEND", "local")
    monkeypatch.setattr(settings, "ATTACHMENT_UPLOAD_DIR", str(tmp_path))
    key = "1/task/42/internal-key"
    asyncio.run(attachment_storage.put_attachment(key, b"safe", "text/plain"))
    assert asyncio.run(attachment_storage.get_attachment(key)) == b"safe"
    asyncio.run(attachment_storage.delete_attachment(key))
    assert not (tmp_path / key).exists()
