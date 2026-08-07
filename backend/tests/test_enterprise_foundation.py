from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace

from app.core.security import (
    create_enterprise_access_token,
    decode_token,
    hash_account_password,
    hash_refresh_token,
    new_refresh_token,
    verify_account_password,
)
from app.core.enterprise_deps import ActorContext
from app.main import app
from app.models.models import Base
from app.routers.enterprise import LEGACY_STATUS, WORKFLOW_STATUSES, _birthday_occurrences, _holiday_provider_rows, _task_out
from app.routers.enterprise_auth import TELEGRAM_DEFAULT_ROLE
from app.services.enterprise_events import _json_safe, _redact
from app.services.work_report_service import summarize_work_time


def test_enterprise_passwords_use_argon_and_verify_without_rehash():
    hashed = hash_account_password("a-reasonably-long-password")
    assert hashed.startswith("$argon2")
    assert verify_account_password("a-reasonably-long-password", hashed) == (True, False)
    assert verify_account_password("wrong-password", hashed)[0] is False


def test_enterprise_access_token_carries_account_and_organization():
    token = create_enterprise_access_token(17, 1)
    payload = decode_token(token)
    assert payload["sub"] == "17"
    assert payload["organization_id"] == 1
    assert payload["kind"] == "enterprise"


def test_birthdays_repeat_across_year_boundaries_and_handle_leap_day():
    assert _birthday_occurrences(date(1992, 2, 29), date(2025, 12, 1), date(2026, 3, 1)) == [date(2026, 2, 28)]
    assert _birthday_occurrences(date(1990, 1, 10), date(2025, 12, 1), date(2026, 2, 1)) == [date(2026, 1, 10)]


def test_holiday_provider_errors_are_rejected_before_the_calendar_feed_fails():
    from fastapi import HTTPException

    assert _holiday_provider_rows([{"date": "2026-07-11", "name": "National Day", "localName": "\u0411\u0430\u044f\u0440"}]) == [(date(2026, 7, 11), "National Day", "\u0411\u0430\u044f\u0440")]
    for payload in ({"error": "upstream unavailable"}, [{"date": "not-a-date", "name": "Broken"}], ["not a holiday"]):
        try:
            _holiday_provider_rows(payload)
        except HTTPException as exc:
            assert exc.status_code == 502
        else:
            raise AssertionError("Malformed holiday-provider data must be rejected")


def test_refresh_tokens_are_random_and_only_hash_is_persisted():
    first, first_hash = new_refresh_token()
    second, second_hash = new_refresh_token()
    assert first != second
    assert first_hash != second_hash
    assert hash_refresh_token(first) == first_hash
    assert first not in first_hash


def test_audit_redaction_is_recursive():
    value = {"title": "Safe", "password": "secret", "nested": [{"access_token": "token"}]}
    assert _redact(value) == {"title": "Safe", "password": "[REDACTED]", "nested": [{"access_token": "[REDACTED]"}]}


def test_event_payloads_serialize_datetime_date_uuid_and_decimal_before_jsonb_write():
    value = {"at": datetime(2026, 8, 6, tzinfo=timezone.utc), "day": date(2026, 8, 6), "id": uuid4(), "amount": Decimal("12.50")}
    payload = _json_safe(value)
    assert payload["at"].endswith("+00:00")
    assert payload["day"] == "2026-08-06"
    assert isinstance(payload["id"], str)
    assert payload["amount"] == 12.5


def test_enterprise_schema_registers_required_foundation_tables():
    required = {
        "organizations", "user_accounts", "role_assignments", "teams", "clients", "projects",
        "task_assignees", "task_dependencies", "task_check_items", "checkin_templates", "checkins",
        "objectives", "key_results", "milestones", "audit_logs", "domain_events", "job_queue",
        "calendar_connections", "calendar_event_links", "personal_time_blocks", "project_requests",
        "calendar_entries", "holiday_records", "assistant_conversations", "assistant_messages",
    }
    assert required.issubset(Base.metadata.tables)


def test_versioned_routes_include_auth_clock_tasks_reports_and_realtime():
    paths = {route.path for route in app.routes}
    assert {"/v1/auth/login", "/v1/auth/telegram", "/v1/clock/start", "/v1/tasks", "/v1/reports", "/v1/realtime", "/v1/checkins/today", "/v1/calendar/events", "/v1/analytics/daily"}.issubset(paths)


def test_refresh_sessions_record_the_authentication_method():
    refresh_sessions = Base.metadata.tables["refresh_sessions"]
    assert "auth_method" in refresh_sessions.c
    assert refresh_sessions.c.auth_method.server_default.arg == "password"


def test_work_time_exchange_rate_column_has_a_follow_up_migration():
    work_time_entries = Base.metadata.tables["work_time_entries"]
    migration_path = Path(__file__).parents[1] / "alembic/versions/t8u9v0w1x2y3_add_work_time_exchange_rate_snapshot.py"
    migration_spec = spec_from_file_location("work_time_exchange_migration", migration_path)
    assert migration_spec and migration_spec.loader
    migration = module_from_spec(migration_spec)
    migration_spec.loader.exec_module(migration)

    assert "exchange_rate_snapshot_id" in work_time_entries.c
    assert migration.down_revision == "s7t8u9v0w1x2"
    assert migration.revision == "t8u9v0w1x2y3"
    assert any(
        fk.target_fullname == "exchange_rate_snapshots.id"
        for fk in work_time_entries.c.exchange_rate_snapshot_id.foreign_keys
    )


def test_workflow_statuses_have_legacy_compatibility_mapping():
    assert WORKFLOW_STATUSES == {"backlog", "to_do", "in_progress", "review", "done", "cancelled"}
    assert LEGACY_STATUS["review"] == "open"
    assert LEGACY_STATUS["done"] == "done"


def test_task_serialization_computes_overdue_without_mutating_workflow():
    task = SimpleNamespace(
        id=1,
        public_id="public",
        project_id=None,
        parent_task_id=None,
        title="Review proposal",
        description=None,
        workflow_status="review",
        priority=2,
        assignee_id=4,
        start_at=None,
        deadline_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        estimate_minutes=30,
        work_location_type="office",
        work_location="HQ",
        sort_position=1,
        version=3,
        is_archived=False,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )
    output = _task_out(task)
    assert output["workflow_status"] == "review"
    assert output["is_overdue"] is True
    assert output["version"] == 3
    assert output["work_location_type"] == "office"
    assert output["work_location"] == "HQ"


def test_planning_migration_follows_current_head_and_models_nullable_location():
    tasks = Base.metadata.tables["tasks"]
    blocks = Base.metadata.tables["personal_time_blocks"]
    migration_path = Path(__file__).parents[1] / "alembic/versions/u9v0w1x2y3z4_planning_calendar_reliability.py"
    migration_spec = spec_from_file_location("planning_calendar_migration", migration_path)
    assert migration_spec and migration_spec.loader
    migration = module_from_spec(migration_spec)
    migration_spec.loader.exec_module(migration)
    assert migration.down_revision == "t8u9v0w1x2y3"
    assert tasks.c.work_location_type.nullable is True
    assert tasks.c.work_location.nullable is True
    assert {"organization_id", "account_id", "starts_at", "ends_at", "version"}.issubset(blocks.c)


def test_work_time_summary_excludes_breaks_from_productive_total():
    start = datetime(2026, 8, 5, 1, 0, tzinfo=timezone.utc)
    entries = [
        SimpleNamespace(id=1, entry_type="work", mode="in_person", started_at=start, ended_at=start + timedelta(hours=2)),
        SimpleNamespace(id=2, entry_type="break", mode=None, started_at=start + timedelta(hours=2), ended_at=start + timedelta(hours=2, minutes=30)),
        SimpleNamespace(id=3, entry_type="work", mode="remote", started_at=start + timedelta(hours=2, minutes=30), ended_at=start + timedelta(hours=3, minutes=30)),
    ]
    summary = summarize_work_time(entries, now=start + timedelta(hours=4))
    assert summary["total_minutes"] == 180
    assert summary["break_minutes"] == 30
    assert summary["remote_minutes"] == 60
    assert summary["in_person_minutes"] == 120


def test_actor_role_checks_are_explicit_and_deny_unassigned_roles():
    actor = ActorContext(
        account_id=1,
        organization_id=1,
        employee_id=4,
        email="worker@example.com",
        locale="mn",
        roles=frozenset({"member"}),
    )
    assert actor.has_any_role("member") is True
    assert actor.has_any_role("admin", "manager", "team_lead") is False


def test_new_telegram_web_accounts_default_to_member_access():
    assert TELEGRAM_DEFAULT_ROLE == "member"
    paths = {route.path for route in app.routes}
    assert "/v1/auth/accounts/{account_id}" in paths
