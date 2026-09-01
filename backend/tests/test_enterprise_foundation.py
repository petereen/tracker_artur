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
from app.models.models import Base, Task
from app.routers import enterprise
from app.routers.enterprise import LEGACY_STATUS, WORKFLOW_STATUSES, _birthday_occurrences, _calendar_task_visible_to_employee, _holiday_provider_rows, _task_out
from app.routers.enterprise_auth import TELEGRAM_DEFAULT_ROLE, WorkspaceModePreferences, WorldClockPreferences, _clear_login_lock, workspace_mode_preferences
from app.services.enterprise_events import _json_safe, _redact
from app.services.work_report_service import summarize_work_time


def test_enterprise_passwords_use_argon_and_verify_without_rehash():
    hashed = hash_account_password("a-reasonably-long-password")
    assert hashed.startswith("$argon2")
    assert verify_account_password("a-reasonably-long-password", hashed) == (True, False)
    assert verify_account_password("wrong-password", hashed)[0] is False


def test_admin_recovery_clears_temporary_login_lock_state():
    account = SimpleNamespace(failed_login_count=5, locked_until=datetime.now(timezone.utc) + timedelta(minutes=15))
    _clear_login_lock(account)
    assert account.failed_login_count == 0
    assert account.locked_until is None


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
    assert _holiday_provider_rows([{"date": "2026-07-11", "name": "National Day"}, {"date": "2026-07-11", "name": "National Day"}]) == [(date(2026, 7, 11), "National Day", None)]
    for payload in ({"error": "upstream unavailable"}, [{"date": "not-a-date", "name": "Broken"}], ["not a holiday"]):
        try:
            _holiday_provider_rows(payload)
        except HTTPException as exc:
            assert exc.status_code == 502
        else:
            raise AssertionError("Malformed holiday-provider data must be rejected")


def test_calendar_internal_task_query_uses_a_concrete_empty_priority():
    captured: dict[str, object] = {}

    async def fake_list_tasks(**kwargs):
        captured.update(kwargs)
        return []

    class EmptyRows:
        def scalars(self): return self
        def all(self): return []

    class CalendarDb:
        async def execute(self, *_args): return EmptyRows()
        async def get(self, *_args): return SimpleNamespace(settings={})
        async def scalar(self, *_args): return 1

    original = enterprise.list_tasks
    enterprise.list_tasks = fake_list_tasks
    try:
        import asyncio
        asyncio.run(enterprise.calendar_events(
            scope="private", date_from=date(2026, 7, 27), date_to=date(2026, 9, 6), db=CalendarDb(),
            actor=ActorContext(account_id=1, organization_id=1, employee_id=2, email="member@example.com", locale="mn", roles=frozenset({"member"})),
        ))
    finally:
        enterprise.list_tasks = original
    assert captured["priority"] is None


def test_private_calendar_keeps_primary_owner_tasks_without_assignee_link_rows():
    assert _calendar_task_visible_to_employee({"primary_owner_id": 7, "assignee_ids": []}, 7)
    assert _calendar_task_visible_to_employee({"primary_owner_id": None, "assignee_ids": [7]}, 7)
    assert not _calendar_task_visible_to_employee({"primary_owner_id": 8, "assignee_ids": []}, 7)


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
        "assistant_pending_actions", "assistant_tool_audits", "knowledge_documents", "knowledge_chunks",
    }
    assert required.issubset(Base.metadata.tables)


def test_assistant_pending_actions_support_creation_and_update_contracts():
    table = Base.metadata.tables["assistant_pending_actions"]
    assert table.c.action_type.nullable is False
    assert table.c.task_id.nullable is True
    assert table.c.expected_version.nullable is True


def test_versioned_routes_include_auth_clock_tasks_reports_realtime_and_workspace_mode():
    paths = {route.path for route in app.routes}
    assert {"/v1/auth/login", "/v1/auth/telegram", "/v1/auth/profile", "/v1/auth/profile/password", "/v1/auth/preferences/world-clock", "/v1/auth/preferences/workspace-mode", "/v1/clock/start", "/v1/tasks", "/v1/reports", "/v1/realtime", "/v1/checkins/today", "/v1/calendar/events", "/v1/analytics/daily", "/v1/analytics/work-hours"}.issubset(paths)


def test_world_clock_preferences_default_and_boundary_validation():
    default = WorldClockPreferences()
    assert default.clocks == ["Asia/Ulaanbaatar"]
    assert default.display_mode == "digital"
    assert default.hour_format == "24"
    assert WorldClockPreferences(clocks=[]).clocks == []
    assert len(WorldClockPreferences(clocks=["UTC", "Asia/Tokyo", "Europe/London", "America/New_York", "Australia/Sydney", "Africa/Cairo"]).clocks) == 6


def test_world_clock_preferences_reject_duplicate_invalid_and_over_capacity_timezones():
    import pytest

    with pytest.raises(ValueError):
        WorldClockPreferences(clocks=["UTC", "UTC"])
    with pytest.raises(ValueError):
        WorldClockPreferences(clocks=["Mars/Phobos"])
    with pytest.raises(ValueError):
        WorldClockPreferences(clocks=["UTC"] * 7)


def test_workspace_mode_preferences_default_and_enum_validation():
    assert WorkspaceModePreferences().mode == "manager"
    assert WorkspaceModePreferences(mode="member").mode == "member"
    import pytest
    with pytest.raises(ValueError):
        WorkspaceModePreferences(mode="company")


def test_workspace_mode_preferences_fall_back_to_manager_for_corrupt_saved_values():
    class Db:
        async def get(self, *_args):
            return SimpleNamespace(preferences={"workspace_mode": {"mode": "corrupt"}})

    actor = ActorContext(account_id=1, organization_id=1, employee_id=2, email="manager@example.com", locale="mn", roles=frozenset({"manager"}))
    import asyncio
    assert asyncio.run(workspace_mode_preferences(db=Db(), actor=actor)).mode == "manager"


def test_workspace_mode_preferences_force_member_for_non_management_roles():
    class Db:
        async def get(self, *_args):
            return SimpleNamespace(preferences={"workspace_mode": {"mode": "manager"}})

    actor = ActorContext(account_id=1, organization_id=1, employee_id=2, email="member@example.com", locale="mn", roles=frozenset({"member"}))
    import asyncio
    assert asyncio.run(workspace_mode_preferences(db=Db(), actor=actor)).mode == "member"


def test_work_hour_analytics_aggregates_modes_and_returns_total():
    class Rows:
        def all(self):
            return [("remote", 125.4), ("in_person", 180.2)]

    class Db:
        async def execute(self, statement):
            self.statement = statement
            return Rows()

    actor = ActorContext(account_id=1, organization_id=1, employee_id=3, email="manager", locale="mn", roles=frozenset({"manager"}))
    db = Db()
    result = asyncio.run(enterprise.analytics_work_hours(date(2026, 8, 1), date(2026, 8, 7), db=db, actor=actor))

    assert result["remote_minutes"] == 125
    assert result["office_minutes"] == 180
    assert result["total_minutes"] == 305
    assert result["scope"] == "organization"
    assert "entry_type" in str(db.statement)
    assert "mode" in str(db.statement)
    assert "coalesce" in str(db.statement).lower()


def test_hr_work_hour_analytics_can_open_the_organization_total():
    class Rows:
        def all(self):
            return [("remote", 60), ("in_person", 120)]

    class Db:
        async def execute(self, _statement):
            return Rows()

    actor = ActorContext(account_id=1, organization_id=1, employee_id=3, email="hr", locale="mn", roles=frozenset({"hr"}))
    result = asyncio.run(enterprise.analytics_work_hours(date(2026, 8, 1), date(2026, 8, 7), db=Db(), actor=actor))

    assert result["scope"] == "organization"
    assert result["employee_id"] is None
    assert result["total_minutes"] == 180


def test_work_hour_analytics_rejects_out_of_scope_employee():
    from fastapi import HTTPException

    actor = ActorContext(account_id=1, organization_id=1, employee_id=3, email="worker", locale="mn", roles=frozenset({"member"}))
    try:
        asyncio.run(enterprise.analytics_work_hours(date(2026, 8, 1), date(2026, 8, 7), employee_id=4, db=SimpleNamespace(), actor=actor))
    except HTTPException as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("Worker analytics must reject another employee's work-hour data")


def test_work_hour_analytics_returns_zeroes_for_an_empty_period():
    class Rows:
        def all(self):
            return []

    class Db:
        async def execute(self, _statement):
            return Rows()

    actor = ActorContext(account_id=1, organization_id=1, employee_id=3, email="manager", locale="mn", roles=frozenset({"manager"}))
    result = asyncio.run(enterprise.analytics_work_hours(date(2026, 8, 1), date(2026, 8, 7), db=Db(), actor=actor))

    assert result["remote_minutes"] == 0
    assert result["office_minutes"] == 0
    assert result["total_minutes"] == 0


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


def test_tasks_expose_an_optional_reviewer_for_the_review_workflow():
    assert "reviewer_id" in Base.metadata.tables["tasks"].c
    task = Task(title="Review", reviewer_id=9)
    assert _task_out(task)["reviewer_id"] == 9


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
