import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import psycopg2
from fastapi import HTTPException

from app.core.enterprise_deps import ActorContext
from app.routers import enterprise
from app.services.secret_box import encrypt_secret


FIXTURES = Path(__file__).parent / "fixtures"


class _Result:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _WebhookDB:
    def __init__(self, connection):
        self.connection = connection
        self.added = []

    async def execute(self, _query):
        return _Result(self.connection)

    async def scalar(self, _query):
        return None

    def add(self, item):
        self.added.append(item)

    async def commit(self):
        return None


def _connection():
    return SimpleNamespace(
        id=7,
        webhook_resource_id="resource",
        encrypted_channel_token=encrypt_secret("channel-secret"),
        channel_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        last_webhook_message_number=None,
    )


def test_calendar_webhook_validates_token_and_deduplicates_messages():
    db = _WebhookDB(_connection())
    first = asyncio.run(enterprise.google_calendar_webhook("channel", "resource", "channel-secret", "12", "exists", db))
    assert first["status"] == "queued"
    assert db.connection.last_webhook_message_number == "12"
    assert db.added[0].dedup_key == "calendar-inbound:7:12"
    second = asyncio.run(enterprise.google_calendar_webhook("channel", "resource", "channel-secret", "12", "exists", db))
    assert second["status"] == "duplicate"


def test_calendar_webhook_rejects_wrong_channel_token():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(enterprise.google_calendar_webhook("channel", "resource", "wrong", "1", "exists", _WebhookDB(_connection())))
    assert exc.value.status_code == 403


def test_contractor_cannot_open_employee_analytics_drilldown():
    actor = ActorContext(account_id=1, organization_id=1, employee_id=3, email="worker", locale="mn", roles=frozenset({"contractor"}))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(enterprise.analytics_drilldown("utilization", db=SimpleNamespace(), actor=actor))
    assert exc.value.status_code == 403


def test_analytics_fixture_has_stable_formula_inputs_and_snapshots():
    fixture = json.loads((FIXTURES / "analytics_drilldown.json").read_text())
    employee = fixture["employee"]
    assert employee["approved_minutes"] / employee["capacity_minutes"] * 100 == 75
    assert round(employee["billable_minutes"] / employee["approved_minutes"] * 100, 2) == 66.67
    assert fixture["exchange_snapshot"]["captured_at"] == "2026-07-15T00:00:00Z"
    assert fixture["deadlines"] == {"total": 4, "healthy": 3, "overdue": 1}
    assert fixture["reports"]["expected"] == 4


@pytest.mark.skipif(os.getenv("RUN_POSTGRES_TESTS") != "1", reason="requires isolated PostgreSQL")
def test_postgres_event_replay_order_and_job_deduplication():
    dsn = os.environ["SYNC_DATABASE_URL"].replace("postgresql+psycopg2://", "postgresql://")
    connection = psycopg2.connect(dsn)
    connection.autocommit = False
    try:
        with connection.cursor() as cursor:
            # Some supported migration heads contain explicit seed identifiers
            # without advancing the backing sequence. Avoid depending on its
            # position while exercising replay ordering in an isolated database.
            cursor.execute("INSERT INTO organizations(id, name) SELECT COALESCE(MAX(id), 0) + 1, 'hardening-test' FROM organizations RETURNING id")
            organization_id = cursor.fetchone()[0]
            cursor.execute("INSERT INTO domain_events(organization_id,topic,aggregate_type,aggregate_id,aggregate_version,operation,payload) VALUES (%s,'tasks','task',41,1,'created','{}'),(%s,'tasks','task',41,2,'updated','{}') RETURNING id", (organization_id, organization_id))
            inserted = [row[0] for row in cursor.fetchall()]
            cursor.execute("SELECT id, aggregate_version FROM domain_events WHERE organization_id=%s AND id>%s ORDER BY id", (organization_id, inserted[0] - 1))
            assert cursor.fetchall() == [(inserted[0], 1), (inserted[1], 2)]
            cursor.execute("INSERT INTO job_queue(job_type,payload,dedup_key) VALUES ('healthcheck','{}','postgres-dedup-check')")
            cursor.execute("SAVEPOINT duplicate_job")
            with pytest.raises(psycopg2.errors.UniqueViolation):
                cursor.execute("INSERT INTO job_queue(job_type,payload,dedup_key) VALUES ('healthcheck','{}','postgres-dedup-check')")
            cursor.execute("ROLLBACK TO SAVEPOINT duplicate_job")
    finally:
        connection.rollback()
        connection.close()
