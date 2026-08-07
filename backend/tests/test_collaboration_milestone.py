from types import SimpleNamespace

from app.main import app
from app.models.models import NotificationOutbox
from app.routers.enterprise import CheckinSubmitInput, ReportCreateInput
from app.services.collaboration_permissions import ALL_EMPLOYEE_ROLES, configured_assignment_roles
from app.services.reminder_service import _render_outbox


def test_permission_settings_default_open_and_allow_explicit_restriction():
    assert configured_assignment_roles(SimpleNamespace(settings={})) == ALL_EMPLOYEE_ROLES
    restricted = configured_assignment_roles(SimpleNamespace(settings={"task_assignment_roles": ["admin", "manager"]}))
    assert restricted == {"admin", "manager"}


def test_report_create_and_optional_checkin_contracts():
    report = ReportCreateInput(report_type="daily", period_date="2026-08-07")
    assert report.report_type == "daily"
    assert CheckinSubmitInput(answers=[]).answers == []
    paths = {(route.path, method) for route in app.routes for method in getattr(route, "methods", set())}
    assert ("/v1/reports", "POST") in paths
    assert ("/v1/settings/permissions", "GET") in paths
    assert ("/v1/settings/permissions", "PUT") in paths


def test_deadline_outbox_contract_is_retry_capable_and_renderable():
    assert {"attempt_count", "last_error", "lease_owner", "lease_expires_at", "next_attempt_at"}.issubset(set(NotificationOutbox.__table__.c.keys()))
    text, keyboard = _render_outbox({
        "kind": "task_deadline",
        "task_id": 7,
        "task_title": "Ship release",
        "task_description": None,
        "task_deadline_at": None,
        "payload": {"title": "Ship release", "deadline_iso": "2026-08-08T09:00:00+00:00", "when": "1 хоногийн дараа"},
    })
    assert "Ship release" in text
    assert "1 хоногийн дараа" in text
    assert keyboard is not None
