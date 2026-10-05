"""Automatic geofence worktime: rules, settings, disclaimer, schema and wiring."""

import hashlib
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

from app.main import app
from app.models.models import Base
from app.routers.mobile_updates import _native_supported
from app.services.notification_preferences import category_for
from app.services.worktime_auto import (
    CONSENT_TEXT,
    POLICY_VERSION,
    ActiveEntry,
    auto_settings,
    consent_text,
    decide,
    device_config,
    employer_ack_current,
    within_schedule,
)
from app.services.worktime_geofence import worktime_methods

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 2, 1, 0, tzinfo=timezone.utc)
OFFICE = ActiveEntry("work", "in_person")
REMOTE = ActiveEntry("work", "remote")
BREAK = ActiveEntry("break", None)


def _decide(kind, *, mode="on", active=None, **overrides):
    values = dict(
        kind=kind, mode=mode, occurred_at=NOW, received_at=NOW, accuracy_meters=20.0, is_mock=False,
        site_known=True, in_schedule=True, active=active, had_entry_today=False, last_stop_was_auto=False,
    )
    values.update(overrides)
    return decide(**values)


def test_arrival_starts_and_departure_stops_the_clock():
    assert _decide("enter").action == "start"
    assert _decide("enter").result == "started"
    leaving = _decide("exit", active=OFFICE)
    # The stop waits for the exit grace; the entry then ends at the exit time.
    assert (leaving.action, leaving.result) == ("stop", "pending_stop")
    assert _decide("state_outside", active=OFFICE).action == "stop"
    # An exit always stops the clock, also during a break.
    assert _decide("exit", active=BREAK).action == "stop"


def test_returning_within_the_grace_voids_the_pending_exit():
    back = _decide("enter", active=OFFICE)
    assert (back.action, back.result, back.cancel_pending) == ("none", "ignored:already_working", True)
    assert _decide("state_inside", active=BREAK).cancel_pending is True


def test_manual_and_remote_sessions_are_left_alone():
    assert _decide("enter", active=REMOTE).result == "ignored:remote_session"
    assert _decide("exit", active=REMOTE).result == "ignored:remote_session"
    assert _decide("exit").result == "ignored:not_working"
    # A snapshot repairs a missed arrival, but never restarts a clock the
    # employee stopped by hand while still in the office.
    assert _decide("state_inside").action == "start"
    assert _decide("state_inside", had_entry_today=True, last_stop_was_auto=True).action == "start"
    assert _decide("state_inside", had_entry_today=True, last_stop_was_auto=False).result == "ignored:manual_stop"
    # A real arrival starts it again either way.
    assert _decide("enter", had_entry_today=True).action == "start"


def test_untrusted_reports_change_nothing_and_are_flagged():
    mock = _decide("enter", is_mock=True)
    assert (mock.action, mock.result, mock.needs_review) == ("none", "ignored:mock_location", True)
    vague = _decide("enter", accuracy_meters=101.0)
    assert (vague.result, vague.needs_review) == ("ignored:low_accuracy", True)
    assert _decide("enter", accuracy_meters=100.0).action == "start"
    assert _decide("enter", accuracy_meters=None).action == "start"
    stale = _decide("exit", active=OFFICE, occurred_at=NOW - timedelta(hours=7))
    assert (stale.result, stale.needs_review) == ("ignored:stale", True)
    assert _decide("enter", site_known=False).result == "ignored:unknown_site"
    assert _decide("enter", in_schedule=False).result == "ignored:outside_schedule"
    # Leaving outside the site's schedule still stops the clock.
    assert _decide("exit", active=OFFICE, in_schedule=False).action == "stop"


def test_off_and_shadow_modes_never_touch_the_clock():
    assert _decide("enter", mode="off").result == "ignored:auto_off"
    assert _decide("enter", mode="shadow") == _decide("enter", mode="shadow").__class__("none", "shadow:start")
    assert _decide("exit", mode="shadow", active=OFFICE).result == "shadow:stop"
    assert _decide("exit", mode="shadow", active=OFFICE).action == "none"


def test_site_schedule_window():
    assert within_schedule(None, None, time(3, 0))
    assert within_schedule(time(7, 0), time(20, 0), time(8, 30))
    assert not within_schedule(time(7, 0), time(20, 0), time(21, 0))
    # Night shift window crossing midnight.
    assert within_schedule(time(22, 0), time(6, 0), time(23, 30))
    assert within_schedule(time(22, 0), time(6, 0), time(5, 0))
    assert not within_schedule(time(22, 0), time(6, 0), time(12, 0))


def test_settings_defaults_and_clamps():
    assert auto_settings(None) == {
        "auto_geofence_mode": "off", "exit_grace_minutes": 10, "min_accuracy_meters": 100,
        "geo_retention_days": 90, "employer_disclaimer_ack": None, "policy_version": POLICY_VERSION,
    }
    custom = {"worktime_methods": {"auto_geofence_mode": "shadow", "exit_grace_minutes": 999, "min_accuracy_meters": 1, "geo_retention_days": True}}
    values = auto_settings(custom)
    assert (values["auto_geofence_mode"], values["exit_grace_minutes"], values["min_accuracy_meters"], values["geo_retention_days"]) == ("shadow", 120, 10, 90)
    assert auto_settings({"worktime_methods": {"auto_geofence_mode": "always"}})["auto_geofence_mode"] == "off"
    assert device_config(custom) == {"mode": "shadow", "min_accuracy_meters": 10}
    # The QR/location toggles keep their exact shape next to the new keys.
    assert worktime_methods(custom) == {"qr_enabled": True, "location_enabled": True, "qr_rotation_seconds": 30}


def test_employer_acknowledgement_is_bound_to_the_policy_version():
    assert not employer_ack_current(None)
    assert not employer_ack_current({"worktime_methods": {"employer_disclaimer_ack": {"policy_version": "2020-01-01"}}})
    assert employer_ack_current({"worktime_methods": {"employer_disclaimer_ack": {"policy_version": POLICY_VERSION}}})


def test_disclaimer_exists_in_every_language_with_a_stable_hash():
    assert set(CONSENT_TEXT) == {"mn", "ru", "en"}
    for locale, text in CONSENT_TEXT.items():
        served = consent_text(locale)
        assert served == {"policy_version": POLICY_VERSION, "locale": locale, "text": text, "text_sha256": hashlib.sha256(text.encode()).hexdigest()}
    assert consent_text("de")["locale"] == "mn"
    assert consent_text("en-US")["locale"] == "en"
    # The employee is told it is optional and what is (not) kept.
    assert "QR" in CONSENT_TEXT["en"] and "not stored" in CONSENT_TEXT["en"] and "withdraw" in CONSENT_TEXT["en"]


def test_schema_is_tenant_scoped_and_stores_no_credential_or_coordinates():
    tables = Base.metadata.tables
    for name in ("worktime_sites", "worktime_location_consents", "mobile_devices", "worktime_geo_events"):
        assert "organization_id" in tables[name].c, name
    devices = tables["mobile_devices"]
    assert "credential" not in devices.c and devices.c.credential_hash.unique is True
    events = tables["worktime_geo_events"]
    assert not {"latitude", "longitude"} & set(events.c.keys())
    assert {"client_event_id", "kind", "occurred_at", "received_at", "accuracy_meters", "is_mock", "result", "time_entry_id"}.issubset(events.c.keys())
    assert any({"device_id", "client_event_id"} == {column.name for column in constraint.columns} for constraint in events.constraints)
    assert "min_native_version" in tables["mobile_update_bundles"].c


def test_migration_adds_row_level_security_to_every_new_table():
    migration = (ROOT / "alembic" / "versions" / "7d9b3f5a1e48_worktime_geofence_auto.py").read_text()
    assert 'TABLES = ("worktime_sites", "worktime_location_consents", "mobile_devices", "worktime_geo_events")' in migration
    assert "FORCE ROW LEVEL SECURITY" in migration and "tenant_row_visible(organization_id)" in migration
    # Frozen definitions: the migration must not build tables from live models.
    assert "Base.metadata" not in migration


def test_routes_are_registered():
    routes = {(route.path, method) for route in app.routes for method in getattr(route, "methods", set())}
    for path, method in (
        ("/v1/worktime/auto/status", "GET"), ("/v1/worktime/auto/consent-text", "GET"),
        ("/v1/worktime/auto/consent", "POST"), ("/v1/worktime/auto/consent", "DELETE"),
        ("/v1/mobile/devices", "POST"), ("/v1/mobile/devices/{device_id}", "DELETE"),
        ("/v1/mobile/geofences", "GET"), ("/v1/mobile/geo-events", "POST"),
        ("/v1/settings/worktime-auto", "PUT"), ("/v1/worktime/sites", "POST"),
        ("/v1/worktime/auto/events", "GET"), ("/v1/worktime/auto/devices", "GET"),
    ):
        assert (path, method) in routes, (path, method)


def test_location_events_are_admin_and_hr_only_and_reads_are_audited():
    source = (ROOT / "app" / "routers" / "worktime_geo.py").read_text()
    assert 'LOCATION_EVENT_ROLES = ("admin", "hr")' in source
    listing = source.split("async def list_events(")[1].split("@router.post")[0]
    assert "require_roles(*LOCATION_EVENT_ROLES)" in listing and 'operation="viewed"' in listing
    # The native layer never authenticates with the session token.
    assert "Depends(get_device)" in source.split("async def report_geo_events(")[1].split(":\n")[0]


def test_worktime_methods_update_keeps_the_automatic_settings():
    enterprise = (ROOT / "app" / "routers" / "enterprise.py").read_text()
    update = enterprise.split("async def update_worktime_methods(")[1].split("@router")[0]
    assert "(organization.settings or {}).get(WORKTIME_METHODS_KEY)" in update


def test_ota_bundle_is_not_offered_to_a_binary_that_is_too_old():
    assert _native_supported(None, None)
    assert _native_supported(1, None)  # binaries without the capability plugin are build 1
    assert not _native_supported(2, None)
    assert not _native_supported(3, 2)
    assert _native_supported(2, 2) and _native_supported(2, 5)


def test_every_bell_notification_gets_a_native_push_job():
    notifications = (ROOT / "app" / "services" / "user_notifications.py").read_text()
    assert notifications.count('job_type="notification_push"') == 2
    worker = (ROOT / "app" / "worker.py").read_text()
    assert 'job.job_type == "notification_push"' in worker
    for upkeep in ("finalize_pending_exits", "close_stale_entries", "purge_geo_events"):
        assert f'_geofence_maintenance("{upkeep}")' in worker
    assert category_for("worktime_auto_started") == "worktime" and category_for("worktime_auto_stopped") == "worktime"


def test_notification_push_is_delivered_on_the_default_channel_with_a_safe_link(monkeypatch):
    import asyncio
    import json
    from types import SimpleNamespace

    import httpx

    from app.core.config import settings
    from app.services import mobile_push_delivery
    from app.services.secret_box import encrypt_secret

    sent: list[httpx.Request] = []
    notification = SimpleNamespace(
        id=42, organization_id=3, recipient_account_id=7, kind="worktime_auto_started", read_at=None,
        title="Ажлын цаг автоматаар эхэллээ", body="Оффисын бүсэд орсон тул ажлын цаг эхэллээ.", target_url="//evil.example/steal",
    )
    registrations = [
        SimpleNamespace(id=1, provider="fcm", encrypted_token=encrypt_secret("android-token"), is_active=True, revoked_at=None),
        SimpleNamespace(id=2, provider="apns", encrypted_token=encrypt_secret("ios-token"), is_active=True, revoked_at=None),
    ]

    class Database:
        async def get(self, _model, _id):
            return notification

        async def execute(self, _statement):
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: registrations))

    async def handler(request: httpx.Request):
        sent.append(request)
        # Apple no longer knows the iPhone's token: the registration must be retired.
        return httpx.Response(410) if "push.apple.com" in str(request.url) else httpx.Response(200, json={"name": "ok"})

    async def token(_client, _service_account):
        return "access-token"

    real_client = httpx.AsyncClient
    monkeypatch.setattr(mobile_push_delivery.httpx, "AsyncClient", lambda **_kwargs: real_client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(mobile_push_delivery, "_fcm_token", token)
    monkeypatch.setattr(mobile_push_delivery, "_apns_token", lambda: "provider-token")
    for name, value in (("FCM_PROJECT_ID", "test"), ("FCM_SERVICE_ACCOUNT_JSON", json.dumps({"project_id": "test"})), ("APNS_TEAM_ID", "T"), ("APNS_KEY_ID", "K"), ("APNS_PRIVATE_KEY", "P")):
        monkeypatch.setattr(settings, name, value)

    # Off by default: nothing is read, nothing is sent.
    monkeypatch.setattr(settings, "MOBILE_PUSH_DELIVERY_ENABLED", False)
    asyncio.run(mobile_push_delivery.deliver_notification_push(Database(), 42))
    assert sent == []

    monkeypatch.setattr(settings, "MOBILE_PUSH_DELIVERY_ENABLED", True)
    asyncio.run(mobile_push_delivery.deliver_notification_push(Database(), 42))
    android = json.loads(sent[0].content)["message"]
    assert android["android"]["notification"]["channel_id"] == "oyuns-default"
    # An off-site link is never forwarded to the phone.
    assert android["data"] == {"target_url": "/", "notification_id": "42", "kind": "worktime_auto_started"}
    assert sent[1].headers["apns-collapse-id"] == "notification-42"
    assert registrations[0].is_active is True and registrations[1].is_active is False

    # Already read on another device: no push.
    sent.clear()
    notification.read_at = "2026-10-02T00:00:00Z"
    asyncio.run(mobile_push_delivery.deliver_notification_push(Database(), 42))
    assert sent == []
