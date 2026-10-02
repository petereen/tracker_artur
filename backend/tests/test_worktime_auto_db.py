"""Automatic geofence worktime end to end against PostgreSQL.

Runs only when GEO_TEST_DATABASE_URL points at a throwaway database
(for example ``postgresql+asyncpg://tracker@127.0.0.1:55432/geo_test``).
"""

from __future__ import annotations

import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import pytest

DATABASE_URL = os.environ.get("GEO_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="GEO_TEST_DATABASE_URL is not set")

if DATABASE_URL:
    os.environ.setdefault("DATABASE_URL", DATABASE_URL)
    os.environ.setdefault("SYNC_DATABASE_URL", DATABASE_URL.replace("+asyncpg", "+psycopg2"))
    os.environ.setdefault("SECRET_KEY", "worktime-auto-test-secret-key-0123456789")

OFFICE = {"name": "Төв оффис", "latitude": 47.9184, "longitude": 106.9177, "radius_meters": 150}


def _tables():
    from app.models import models as m
    from app.models import worktime_geo as g

    seeds = [
        m.Organization, m.UserAccount, m.Employee, m.RoleAssignment, m.WorkReport, m.WorkTimeEntry, m.AttendanceLog,
        m.UserNotification, m.JobQueue, m.DomainEvent, m.AuditLog, m.ManagerSettings, m.NotificationOutbox,
        g.WorktimeSite, g.WorktimeLocationConsent, g.MobileDevice, g.WorktimeGeoEvent,
    ]
    tables = {model.__table__ for model in seeds}
    grown = True
    while grown:
        grown = False
        for table in list(tables):
            for foreign_key in table.foreign_keys:
                if foreign_key.column.table not in tables:
                    tables.add(foreign_key.column.table)
                    grown = True
    return list(tables)


@asynccontextmanager
async def _api(monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core import enterprise_deps, tenancy
    from app.core.database import get_db
    from app.core.enterprise_deps import build_actor_context
    from app.models import models as m
    from app.routers import enterprise, worktime_geo

    engine = create_async_engine(DATABASE_URL)
    tables = _tables()
    async with engine.begin() as connection:
        await connection.execute(text("DROP TABLE IF EXISTS " + ", ".join(f'"{table.name}"' for table in tables) + " CASCADE"))
        await connection.run_sync(lambda sync: m.Base.metadata.create_all(sync, tables=tables))
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    actors: dict[str, object] = {}
    ids: dict[str, int] = {}
    async with sessions() as db:
        org = m.Organization(name="Оюунс", slug="oyuns", status="active", license_required=False)
        other = m.Organization(name="Бусад", slug="busad", status="active", license_required=False)
        db.add_all([org, other])
        await db.flush()
        ids.update(org=org.id, other=other.id)

        async def person(key: str, name: str, role: str, organization=org):
            employee = m.Employee(organization_id=organization.id, name=name)
            db.add(employee)
            await db.flush()
            account = m.UserAccount(organization_id=organization.id, employee_id=employee.id, email=f"{key}@test.mn", password_hash="x")
            db.add(account)
            await db.flush()
            db.add(m.RoleAssignment(account_id=account.id, role=role))
            actors[key] = build_actor_context(account_id=account.id, organization_id=organization.id, employee_id=employee.id, email=account.email, locale="mn", roles=frozenset({role}))
            ids[key] = employee.id
            ids[f"{key}_account"] = account.id

        await person("admin", "Админ", "admin")
        await person("hr", "Хүний нөөц", "hr")
        await person("bold", "Болд Менежер", "manager")
        await person("saraa", "Сараа", "member")
        await person("outsider", "Гадны админ", "admin", other)
        await db.commit()

    async def override_db():
        bound = tenancy.current_tenant_id()
        try:
            async with sessions() as session:
                yield session
        finally:
            tenancy.set_current_tenant(bound)

    async def from_token(token, _db):
        return actors[token]

    async def operational(_organization_id):
        return True

    monkeypatch.setattr(enterprise_deps, "actor_from_token", from_token)
    monkeypatch.setattr(worktime_geo, "AsyncSessionLocal", sessions)
    monkeypatch.setattr(worktime_geo, "tenant_is_operational", operational)
    app = FastAPI()
    app.include_router(enterprise.router, prefix="/v1")
    app.include_router(worktime_geo.router, prefix="/v1")
    app.dependency_overrides[get_db] = override_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client, (lambda key: {"Authorization": f"Bearer {key}"}), ids, sessions
    finally:
        await engine.dispose()


def _event(kind: str, site_id: str | None, *, minutes_ago: float = 0, **extra) -> dict:
    occurred = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return {"client_event_id": str(uuid.uuid4()), "kind": kind, "site_id": site_id, "occurred_at": occurred.isoformat(), "accuracy_meters": 15, **extra}


async def _enroll(client, as_, key: str = "saraa") -> dict:
    text_ = (await client.get("/v1/worktime/auto/consent-text?locale=mn", headers=as_(key))).json()
    accepted = await client.post("/v1/worktime/auto/consent", headers=as_(key), json={
        "policy_version": text_["policy_version"], "text_sha256": text_["text_sha256"], "locale": "mn", "app_platform": "android", "app_version": "1.0.7"})
    assert accepted.status_code == 201, accepted.text
    enrolled = await client.post("/v1/mobile/devices", headers=as_(key), json={"platform": "android", "location_permission": "always", "location_accuracy": "precise", "native_version": 2})
    assert enrolled.status_code == 201, enrolled.text
    return enrolled.json()


async def _switch_on(client, as_, mode: str = "on", **settings) -> str:
    saved = await client.put("/v1/settings/worktime-auto", headers=as_("admin"), json={"auto_geofence_mode": mode, "acknowledge_employer_disclaimer": True, **settings})
    assert saved.status_code == 200, saved.text
    site = await client.post("/v1/worktime/sites", headers=as_("admin"), json=OFFICE)
    assert site.status_code == 201, site.text
    return site.json()["id"]


async def _entries(sessions, employee_id: int):
    from sqlalchemy import select

    from app.models import models as m

    async with sessions() as db:
        return list((await db.execute(select(m.WorkTimeEntry).where(m.WorkTimeEntry.employee_id == employee_id).order_by(m.WorkTimeEntry.id))).scalars().all())


def test_settings_sites_consent_and_enrollment(monkeypatch):
    async def scenario():
        async with _api(monkeypatch) as (client, as_, ids, sessions):
            # Only an admin switches it on, and only with the employer acknowledgement.
            assert (await client.put("/v1/settings/worktime-auto", headers=as_("bold"), json={"auto_geofence_mode": "on"})).status_code == 403
            refused = await client.put("/v1/settings/worktime-auto", headers=as_("admin"), json={"auto_geofence_mode": "shadow"})
            assert refused.status_code == 409 and refused.json()["detail"]["code"] == "employer_disclaimer_required"
            # Not available to enroll while it is off.
            early = await client.post("/v1/mobile/devices", headers=as_("saraa"), json={"platform": "ios"})
            assert early.status_code == 409 and early.json()["detail"]["code"] == "worktime_auto_disabled"

            site_id = await _switch_on(client, as_)
            saved = (await client.get("/v1/settings/worktime-auto", headers=as_("saraa"))).json()
            assert saved["auto_geofence_mode"] == "on" and saved["exit_grace_minutes"] == 10 and saved["employer_disclaimer_ack"]["email"] == "admin@test.mn"
            # The QR/location toggles and the automatic settings share one key
            # and must not erase each other.
            assert (await client.put("/v1/settings/worktime-methods", headers=as_("admin"), json={"qr_enabled": False})).status_code == 200
            assert (await client.get("/v1/settings/worktime-auto", headers=as_("admin"))).json()["auto_geofence_mode"] == "on"
            assert (await client.get("/v1/settings/worktime-methods", headers=as_("admin"))).json()["qr_enabled"] is False

            # The first site is the legacy single geofence, in both directions.
            legacy = (await client.get("/v1/settings/worktime-geofence", headers=as_("admin"))).json()
            assert legacy == {"configured": True, "latitude": 47.9184, "longitude": 106.9177, "radius_meters": 150}
            assert (await client.put("/v1/settings/worktime-geofence", headers=as_("admin"), json={"latitude": 47.92, "longitude": 106.91, "radius_meters": 200})).status_code == 200
            sites = (await client.get("/v1/worktime/sites", headers=as_("admin"))).json()
            assert [(site["id"], site["latitude"], site["radius_meters"]) for site in sites] == [(site_id, 47.92, 200)]
            assert (await client.post("/v1/worktime/sites", headers=as_("bold"), json=OFFICE)).status_code == 403
            assert (await client.post("/v1/worktime/sites", headers=as_("admin"), json={**OFFICE, "schedule_start": "08:00"})).status_code == 422
            # Another tenant's admin cannot touch the site.
            assert (await client.put(f"/v1/worktime/sites/{site_id}", headers=as_("outsider"), json=OFFICE)).status_code == 404

            # Consent comes first, and it must be for the text the server serves.
            no_consent = await client.post("/v1/mobile/devices", headers=as_("saraa"), json={"platform": "android"})
            assert no_consent.status_code == 409 and no_consent.json()["detail"]["code"] == "location_consent_required"
            text_ = (await client.get("/v1/worktime/auto/consent-text?locale=mn", headers=as_("saraa"))).json()
            tampered = await client.post("/v1/worktime/auto/consent", headers=as_("saraa"), json={"policy_version": text_["policy_version"], "text_sha256": "0" * 64, "locale": "mn"})
            assert tampered.status_code == 409 and tampered.json()["detail"]["code"] == "consent_text_changed"

            first = await _enroll(client, as_)
            assert first["config"] == {"mode": "on", "min_accuracy_meters": 100} and len(first["sites"]) == 1
            status_ = (await client.get("/v1/worktime/auto/status", headers=as_("saraa"))).json()
            assert status_["available"] and status_["consent"]["policy_version"] == text_["policy_version"] and status_["device"]["location_permission"] == "always"

            # The credential opens the geo endpoints; anything else is refused.
            device_auth = {"Authorization": f"Device {first['credential']}"}
            listed = await client.get("/v1/mobile/geofences", headers=device_auth)
            assert listed.status_code == 200 and listed.json()["sites"][0]["id"] == site_id
            assert (await client.get("/v1/mobile/geofences", headers={"Authorization": f"Device {first['device']['id']}.wrong"})).status_code == 401
            assert (await client.get("/v1/mobile/geofences", headers=as_("saraa"))).status_code == 401
            assert (await client.get("/v1/worktime/auto/status", headers=device_auth)).status_code in {401, 403}

            # One reporting phone per account: enrolling again retires the first.
            second = await _enroll(client, as_)
            assert (await client.get("/v1/mobile/geofences", headers=device_auth)).json()["detail"]["code"] == "device_revoked"
            second_auth = {"Authorization": f"Device {second['credential']}"}
            assert (await client.get("/v1/mobile/geofences", headers=second_auth)).status_code == 200

            # Withdrawing consent stops the phone being trusted at once.
            revoked = (await client.delete("/v1/worktime/auto/consent", headers=as_("saraa"))).json()
            assert revoked == {"revoked": 2, "devices_revoked": 1}
            assert (await client.post("/v1/mobile/geo-events", headers=second_auth, json={"events": []})).status_code == 401
            after = (await client.get("/v1/worktime/auto/status", headers=as_("saraa"))).json()
            assert after["consent"] is None and after["device"] is None

    asyncio.run(scenario())


def test_events_drive_the_clock(monkeypatch):
    async def scenario():
        from sqlalchemy import select

        from app.models import models as m
        from app.models import worktime_geo as g
        from app.services import worktime_auto

        async with _api(monkeypatch) as (client, as_, ids, sessions):
            site_id = await _switch_on(client, as_)
            device = {"Authorization": f"Device {(await _enroll(client, as_))['credential']}"}

            async def report(*events, state=None):
                response = await client.post("/v1/mobile/geo-events", headers=device, json={"events": list(events), "state": state})
                assert response.status_code == 200, response.text
                return [item["result"] for item in response.json()["results"]]

            # Untrusted reports change nothing.
            assert await report(_event("enter", site_id, is_mock=True)) == ["ignored:mock_location"]
            assert await report(_event("enter", site_id, accuracy_meters=400)) == ["ignored:low_accuracy"]
            assert await report(_event("enter", str(uuid.uuid4()))) == ["ignored:unknown_site"]
            assert await report(_event("exit", site_id)) == ["ignored:not_working"]
            assert await _entries(sessions, ids["saraa"]) == []

            # Arrival starts an office entry; a replay is the same event.
            arrival = _event("enter", site_id, minutes_ago=30)
            assert await report(arrival, state={"battery_unrestricted": True}) == ["started"]
            assert await report(arrival) == ["started"]
            entries = await _entries(sessions, ids["saraa"])
            assert len(entries) == 1
            assert (entries[0].source_channel, entries[0].mode, entries[0].work_location_id, entries[0].ended_at) == ("geofence", "in_person", site_id, None)
            assert abs((datetime.now(timezone.utc) - entries[0].started_at) - timedelta(minutes=30)) < timedelta(seconds=30)
            status_ = (await client.get("/v1/worktime/auto/status", headers=as_("saraa"))).json()
            assert status_["device"]["battery_unrestricted"] is True and "started" in [item["result"] for item in status_["recent_events"]]
            clock = (await client.get("/v1/clock/status", headers=as_("saraa"))).json()
            assert clock["active"]["source_channel"] == "geofence"

            # Stepping out and back inside the grace keeps the clock running.
            assert await report(_event("exit", site_id, minutes_ago=4)) == ["pending_stop"]
            assert await report(_event("enter", site_id, minutes_ago=2)) == ["ignored:already_working"]
            assert (await _entries(sessions, ids["saraa"]))[0].ended_at is None
            async with sessions() as db:
                results = (await db.execute(select(g.WorktimeGeoEvent.result).order_by(g.WorktimeGeoEvent.id))).scalars().all()
            assert "ignored:returned" in results and "pending_stop" not in results

            # Leaving for longer than the grace stops it at the exit time: the
            # background sweep does it once the grace has run out.
            leaving = _event("exit", site_id, minutes_ago=1)
            assert await report(leaving) == ["pending_stop"]
            async with sessions() as db:
                assert await worktime_auto.finalize_pending_exits(db) == 0  # still in grace
                assert await worktime_auto.finalize_pending_exits(db, now=datetime.now(timezone.utc) + timedelta(minutes=10)) == 1
                await db.commit()
            closed = (await _entries(sessions, ids["saraa"]))[0]
            assert abs(closed.ended_at - datetime.fromisoformat(leaving["occurred_at"])) < timedelta(seconds=1)

            # A snapshot repairs a missed arrival after an automatic stop …
            assert await report(_event("state_inside", site_id, latitude=47.9184, longitude=106.9177)) == ["started"]
            # … but a phone claiming "inside" from across town is not believed.
            async with sessions() as db:
                reopened = (await db.execute(select(m.WorkTimeEntry).where(m.WorkTimeEntry.ended_at.is_(None)))).scalars().one()
                reopened.ended_at = datetime.now(timezone.utc)  # stopped by hand in the web app
                await db.commit()
            assert await report(_event("state_inside", site_id, latitude=47.9184, longitude=106.9177)) == ["ignored:manual_stop"]
            assert len(await _entries(sessions, ids["saraa"])) == 2

            # A report that arrives late (phone was offline) stops at once.
            assert await report(_event("enter", site_id)) == ["started"]
            assert await report(_event("exit", site_id, minutes_ago=0)) == ["pending_stop"]
            async with sessions() as db:
                await worktime_auto.finalize_pending_exits(db, now=datetime.now(timezone.utc) + timedelta(minutes=11))
                await db.commit()
            assert all(entry.ended_at is not None for entry in await _entries(sessions, ids["saraa"]))

            # The employee was told: one bell notification per start and stop.
            async with sessions() as db:
                kinds = (await db.execute(select(m.UserNotification.kind).where(m.UserNotification.recipient_account_id == ids["saraa_account"]).order_by(m.UserNotification.id))).scalars().all()
                channels = set((await db.execute(select(m.AuditLog.channel).where(m.AuditLog.entity_type == "time_entry"))).scalars().all())
            assert kinds.count("worktime_auto_started") == 3 and kinds.count("worktime_auto_stopped") == 2
            assert channels == {"mobile_geofence"}

            # Location events: admin and HR only, and reading them is audited.
            assert (await client.get("/v1/worktime/auto/events", headers=as_("bold"))).status_code == 403
            assert (await client.get("/v1/worktime/auto/events", headers=as_("saraa"))).status_code == 403
            flagged = (await client.get("/v1/worktime/auto/events?needs_review=true", headers=as_("hr"))).json()["items"]
            assert {item["result"] for item in flagged} == {"ignored:mock_location", "ignored:low_accuracy"}
            assert all(item["employee_name"] == "Сараа" for item in flagged)
            assert (await client.get("/v1/worktime/auto/events", headers=as_("outsider"))).json()["items"] == []
            reviewed = await client.post(f"/v1/worktime/auto/events/{flagged[0]['id']}/reviewed", headers=as_("admin"))
            assert reviewed.status_code == 200 and reviewed.json()["needs_review"] is False
            async with sessions() as db:
                viewed = (await db.execute(select(m.AuditLog).where(m.AuditLog.entity_type == "worktime_geo_events", m.AuditLog.action == "viewed"))).scalars().all()
            assert len(viewed) == 2
            devices = (await client.get("/v1/worktime/auto/devices", headers=as_("hr"))).json()
            assert [(item["employee_name"], item["platform"]) for item in devices] == [("Сараа", "android")]

    asyncio.run(scenario())


def test_shadow_mode_and_the_end_of_day_sweeper(monkeypatch):
    async def scenario():
        from sqlalchemy import select

        from app.models import models as m
        from app.models import worktime_geo as g
        from app.services import worktime_auto

        async with _api(monkeypatch) as (client, as_, ids, sessions):
            site_id = await _switch_on(client, as_, mode="shadow", exit_grace_minutes=0)
            device = {"Authorization": f"Device {(await _enroll(client, as_))['credential']}"}

            async def report(*events):
                response = await client.post("/v1/mobile/geo-events", headers=device, json={"events": list(events)})
                assert response.status_code == 200, response.text
                return [item["result"] for item in response.json()["results"]]

            # Shadow mode records what would have happened and touches nothing.
            assert await report(_event("enter", site_id)) == ["shadow:start"]
            assert await _entries(sessions, ids["saraa"]) == []

            assert (await client.put("/v1/settings/worktime-auto", headers=as_("admin"), json={"auto_geofence_mode": "on"})).status_code == 200
            # Out-of-order delivery in one batch is applied in event order; no grace → stops at once.
            batch = [_event("exit", site_id, minutes_ago=1), _event("enter", site_id, minutes_ago=20)]
            assert sorted(await report(*batch)) == ["started", "stopped"]
            (entry,) = await _entries(sessions, ids["saraa"])
            assert timedelta(minutes=18) < entry.ended_at - entry.started_at < timedelta(minutes=20)

            # A clock a geofence started yesterday and nobody stopped is closed
            # at the last moment the phone was known inside, and flagged.
            start = datetime.now(timezone.utc) - timedelta(days=1, hours=2)
            async with sessions() as db:
                employee = await db.get(m.Employee, ids["saraa"])
                local_day = start.astimezone(__import__("zoneinfo").ZoneInfo(employee.timezone)).date()
                report_row = m.WorkReport(employee_id=employee.id, report_type="daily", period_date=local_day, status="awaiting", title="")
                db.add(report_row)
                await db.flush()
                stale = m.WorkTimeEntry(report_id=report_row.id, employee_id=employee.id, local_work_date=local_day, timezone=employee.timezone, entry_type="work", mode="in_person", started_at=start, source_channel="geofence")
                manual = m.WorkTimeEntry(report_id=report_row.id, employee_id=ids["bold"], local_work_date=local_day, timezone=employee.timezone, entry_type="work", mode="in_person", started_at=start, source_channel="web")
                db.add_all([stale, manual])
                await db.flush()
                device_row = (await db.execute(select(g.MobileDevice).where(g.MobileDevice.revoked_at.is_(None)))).scalars().one()
                db.add(g.WorktimeGeoEvent(organization_id=ids["org"], device_id=device_row.id, account_id=ids["saraa_account"], employee_id=employee.id, client_event_id=uuid.uuid4(), kind="state_inside", occurred_at=start + timedelta(minutes=45), result="ignored:already_working"))
                await db.commit()
                stale_id, manual_id = stale.id, manual.id
                today = datetime.now(timezone.utc).astimezone(__import__("zoneinfo").ZoneInfo(employee.timezone)).date()
                expected = 1 if local_day < today else 0
                assert await worktime_auto.close_stale_entries(db) == expected
                await db.commit()
            async with sessions() as db:
                stale = await db.get(m.WorkTimeEntry, stale_id)
                manual = await db.get(m.WorkTimeEntry, manual_id)
                sweeps = (await db.execute(select(g.WorktimeGeoEvent).where(g.WorktimeGeoEvent.kind == "sweep"))).scalars().all()
            assert manual.ended_at is None  # only geofence-started clocks are swept
            if expected:
                assert stale.ended_at == start + timedelta(minutes=45)
                assert [(sweep.result, sweep.needs_review, sweep.time_entry_id) for sweep in sweeps] == [("stopped", True, stale_id)]

            # Retention: events older than the organization's period are deleted.
            async with sessions() as db:
                before = len((await db.execute(select(g.WorktimeGeoEvent.id))).scalars().all())
                await worktime_auto.purge_geo_events(db, now=datetime.now(timezone.utc) + timedelta(days=89))
                assert len((await db.execute(select(g.WorktimeGeoEvent.id))).scalars().all()) == before
                await worktime_auto.purge_geo_events(db, now=datetime.now(timezone.utc) + timedelta(days=92))
                assert (await db.execute(select(g.WorktimeGeoEvent.id))).scalars().all() == []
                await db.commit()

    asyncio.run(scenario())
