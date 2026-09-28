"""Report policy, department reports and workspace-mode scope against PostgreSQL.

Runs only when SHARE_TEST_DATABASE_URL points at a throwaway database
(for example ``postgresql+asyncpg://tracker@127.0.0.1:55432/share_test``).
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import date

import pytest

DATABASE_URL = os.environ.get("SHARE_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="SHARE_TEST_DATABASE_URL is not set")

if DATABASE_URL:
    os.environ.setdefault("DATABASE_URL", DATABASE_URL)
    os.environ.setdefault("SYNC_DATABASE_URL", DATABASE_URL.replace("+asyncpg", "+psycopg2"))
    os.environ.setdefault("SECRET_KEY", "report-policy-test-secret-key-0123456789")


def _tables():
    from app.models import models as m

    seeds = [
        m.Organization, m.UserAccount, m.Employee, m.RoleAssignment, m.Department, m.EmployeeDetails,
        m.WorkReport, m.WorkReportRevision, m.WorkReportPrompt, m.WorkTimeEntry, m.ReportComment, m.UserNotification,
        m.JobQueue, m.DomainEvent, m.AuditLog, m.ManagerSettings, m.NotificationOutbox,
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

    from app.core import enterprise_deps
    from app.core.database import get_db
    from app.core.enterprise_deps import build_actor_context
    from app.models import models as m
    from app.routers import enterprise

    engine = create_async_engine(DATABASE_URL)
    tables = _tables()
    async with engine.begin() as connection:
        await connection.execute(text("DROP TABLE IF EXISTS " + ", ".join(f'"{table.name}"' for table in tables) + " CASCADE"))
        await connection.run_sync(lambda sync: m.Base.metadata.create_all(sync, tables=tables))
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    actors: dict[str, object] = {}
    ids: dict[str, int] = {}
    async with sessions() as db:
        org = m.Organization(name="Оюунс")
        db.add(org)
        await db.flush()
        sales = m.Department(organization_id=org.id, code="SAL", name="Борлуулалт")
        finance = m.Department(organization_id=org.id, code="FIN", name="Санхүү")
        db.add_all([sales, finance])
        await db.flush()
        ids.update(org=org.id, sales=sales.id, finance=finance.id)

        async def person(key: str, name: str, role: str, department):
            employee = m.Employee(organization_id=org.id, name=name)
            db.add(employee)
            await db.flush()
            account = m.UserAccount(organization_id=org.id, employee_id=employee.id, email=f"{key}@test.mn", password_hash="x")
            db.add(account)
            await db.flush()
            db.add(m.RoleAssignment(account_id=account.id, role=role))
            if department is not None:
                db.add(m.EmployeeDetails(organization_id=org.id, employee_id=employee.id, department_id=department.id))
            actors[key] = build_actor_context(account_id=account.id, organization_id=org.id, employee_id=employee.id, email=account.email, locale="mn", roles=frozenset({role}))
            ids[key] = employee.id

        await person("admin", "Админ", "admin", None)
        await person("bold", "Болд Менежер", "manager", sales)
        await person("saraa", "Сараа", "member", sales)
        await person("dorj", "Дорж", "member", finance)
        sales.manager_employee_id = ids["bold"]
        # Reports that existed before the policy: an untouched daily row and a
        # daily report Сараа already wrote.
        db.add_all([
            m.WorkReport(employee_id=ids["saraa"], report_type="daily", period_date=date(2026, 9, 25), status="awaiting", title=""),
            m.WorkReport(employee_id=ids["saraa"], report_type="daily", period_date=date(2026, 9, 24), status="submitted", title="Өчигдөр"),
            m.WorkReport(employee_id=ids["dorj"], report_type="monthly", period_date=date(2026, 9, 1), status="submitted", title="Доржийн сар"),
        ])
        await db.commit()

    async def override_db():
        async with sessions() as session:
            yield session

    async def from_token(token, _db):
        return actors[token]

    monkeypatch.setattr(enterprise_deps, "actor_from_token", from_token)
    app = FastAPI()
    app.include_router(enterprise.router, prefix="/v1")
    app.dependency_overrides[get_db] = override_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            def as_(key: str, mode: str | None = None) -> dict:
                headers = {"Authorization": f"Bearer {key}"}
                if mode:
                    headers["X-Workspace-Mode"] = mode
                return headers

            yield client, as_, ids
    finally:
        await engine.dispose()


def test_report_policy_drives_options_creation_listing_and_review(monkeypatch):
    async def scenario():
        async with _api(monkeypatch) as (client, as_, ids):
            # Only admins configure the policy.
            policy = {
                "worker_frequencies": ["weekly", "custom:sprint"],
                "custom_periods": [{"id": "sprint", "label": "Спринт", "unit": "week", "interval": 2, "anchor_date": "2026-09-07"}],
                "departments": [{"department_id": ids["finance"], "worker_frequencies": ["monthly"], "department_frequencies": []},
                                {"department_id": ids["sales"], "worker_frequencies": None, "department_frequencies": ["quarterly"]}],
                "reminder_days": 2,
            }
            assert (await client.put("/v1/settings/report-policy", headers=as_("bold"), json=policy)).status_code == 403
            unknown = {**policy, "departments": [{"department_id": 999999, "department_frequencies": ["yearly"]}]}
            assert (await client.put("/v1/settings/report-policy", headers=as_("admin"), json=unknown)).status_code == 422
            saved = await client.put("/v1/settings/report-policy", headers=as_("admin"), json=policy)
            assert saved.status_code == 200, saved.text
            assert {item["value"] for item in saved.json()["available_frequencies"]} >= {"weekly", "custom:sprint"}

            # Сараа (sales) gets the company frequencies; Дорж (finance) the override.
            saraa_options = (await client.get("/v1/reports/options", headers=as_("saraa"))).json()
            assert [item["frequency"] for item in saraa_options["personal"]] == ["weekly", "custom:sprint"]
            assert saraa_options["department"] == []
            dorj_options = (await client.get("/v1/reports/options", headers=as_("dorj"))).json()
            assert [item["frequency"] for item in dorj_options["personal"]] == ["monthly"]

            # Creation follows the policy and snaps to the period.
            denied = await client.post("/v1/reports", headers=as_("saraa"), json={"report_type": "daily", "period_date": "2026-09-28"})
            assert denied.status_code == 403
            weekly = await client.post("/v1/reports", headers=as_("saraa"), json={"report_type": "weekly", "period_date": "2026-10-01"})
            assert weekly.status_code == 201, weekly.text
            assert weekly.json()["period_date"] == "2026-09-28" and weekly.json()["period_end"] == "2026-10-04"
            again = await client.post("/v1/reports", headers=as_("saraa"), json={"report_type": "weekly", "period_date": "2026-09-30"})
            assert again.json()["id"] == weekly.json()["id"]
            sprint = await client.post("/v1/reports", headers=as_("saraa"), json={"report_type": "custom", "period_key": "sprint", "period_date": "2026-09-28"})
            assert sprint.json()["period_date"] == "2026-09-21" and sprint.json()["period_end"] == "2026-10-04"

            # The sales head writes the quarterly department report.
            bold_options = (await client.get("/v1/reports/options", headers=as_("bold", "member"))).json()
            assert [(item["frequency"], item["department_name"]) for item in bold_options["department"]] == [("quarterly", "Борлуулалт")]
            not_head = await client.post("/v1/reports", headers=as_("saraa"), json={"report_type": "quarterly", "period_date": "2026-09-28", "department_id": ids["sales"]})
            assert not_head.status_code == 403
            department = await client.post("/v1/reports", headers=as_("bold", "member"), json={"report_type": "quarterly", "period_date": "2026-09-28", "department_id": ids["sales"]})
            assert department.status_code == 201 and department.json()["period_date"] == "2026-07-01"
            # A personal quarterly report of the head would not collide with it.
            draft = await client.put(f"/v1/reports/{department.json()['id']}/draft", headers=as_("bold", "member"), json={"title": "Q3", "markdown": "Борлуулалт 12% өссөн"})
            assert draft.status_code == 200, draft.text
            assert (await client.post(f"/v1/reports/{department.json()['id']}/submit", headers=as_("bold", "member"))).status_code == 200

            # Workers only see the report kinds asked of them; written history stays.
            period = {"date_from": "2026-09-01", "date_to": "2026-12-31"}
            saraa_list = (await client.get("/v1/reports", headers=as_("saraa"), params=period)).json()
            kinds = sorted((item["report_type"], item["status"]) for item in saraa_list)
            assert kinds == [("custom", "awaiting"), ("daily", "submitted"), ("weekly", "awaiting")]
            assert next(item for item in saraa_list if item["report_type"] == "custom")["frequency_label"] == "Спринт"

            # Member mode: the manager sees only their own and led-department reports.
            bold_member = (await client.get("/v1/reports", headers=as_("bold", "member"), params=period)).json()
            assert [(item["report_type"], item["department_name"]) for item in bold_member] == [("quarterly", "Борлуулалт")]
            assert (await client.post(f"/v1/reports/{department.json()['id']}/approve", headers=as_("bold", "member"))).status_code == 403
            # Manager mode: company-wide list, and periodic reports can be approved.
            bold_manager = (await client.get("/v1/reports", headers=as_("bold"), params=period)).json()
            assert {item["employee_id"] for item in bold_manager} == {ids["saraa"], ids["dorj"], ids["bold"]}
            approved = await client.post(f"/v1/reports/{department.json()['id']}/approve", headers=as_("admin"))
            assert approved.status_code == 200 and approved.json()["status"] == "approved"

    asyncio.run(scenario())


def test_scheduler_prompts_personal_and_department_periods(monkeypatch):
    from app.bot import scheduler
    from app.services import work_report_service

    sent: list[tuple[str, str]] = []
    mirrored: list[dict] = []

    class FakeBot:
        def __init__(self):
            self.session = self

        async def send_message(self, chat_id, text, **_kwargs):
            sent.append((chat_id, text))
            return type("Sent", (), {"message_id": len(sent)})()

        async def close(self):
            return None

    async def scenario():
        async with _api(monkeypatch) as (client, as_, ids):
            policy = {
                "worker_frequencies": ["daily", "weekly"],
                "custom_periods": [],
                "departments": [{"department_id": ids["sales"], "worker_frequencies": None, "department_frequencies": ["monthly"]}],
                "reminder_days": 3,
            }
            assert (await client.put("/v1/settings/report-policy", headers=as_("admin"), json=policy)).status_code == 200
        return ids

    ids = asyncio.run(scenario())
    from app.bot import db as bot_db
    from app.models import models as m

    with bot_db.get_session() as s:
        s.get(m.Employee, ids["bold"]).telegram_id = "555"
        s.commit()
    monkeypatch.setattr(scheduler, "_make_bot", FakeBot)
    monkeypatch.setattr(scheduler, "_local_today", lambda _tz: date(2026, 9, 30))
    monkeypatch.setattr("app.services.user_notifications.mirror_existing_telegram_notification", lambda **kwargs: mirrored.append(kwargs))

    scope = work_report_service.employee_report_scope(ids["bold"])
    assert scope["frequencies"] == ["daily", "weekly"] and scope["led_departments"] == {ids["sales"]: ["monthly"]}
    assert work_report_service.daily_reports_enabled(ids["dorj"])

    asyncio.run(scheduler.send_periodic_report_prompts(ids["bold"]))
    # Wednesday 30 Sep: the department's monthly window is open, the weekly one is not.
    assert len(sent) == 1 and "Сарын тайлан (хэлтсийн)" in sent[0][1]
    assert mirrored[0]["kind"] == "periodic_report" and mirrored[0]["title"].startswith("Борлуулалт")
    with bot_db.get_session() as s:
        report = s.query(m.WorkReport).filter(m.WorkReport.department_id == ids["sales"]).one()
        assert (report.report_type, report.period_date, report.period_end, report.employee_id) == ("monthly", date(2026, 9, 1), date(2026, 9, 30), ids["bold"])
    # A second run the same day neither duplicates the report nor re-sends.
    asyncio.run(scheduler.send_periodic_report_prompts(ids["bold"]))
    assert len(sent) == 1
    with bot_db.get_session() as s:
        assert s.query(m.WorkReport).filter(m.WorkReport.department_id == ids["sales"]).count() == 1
