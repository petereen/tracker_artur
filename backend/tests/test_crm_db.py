"""CRM customer master, activity log, and reminders against PostgreSQL.

Runs only when CRM_TEST_DATABASE_URL points at a throwaway database
(for example ``postgresql+asyncpg://tracker@127.0.0.1:55433/crm_test``).
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import pytest

DATABASE_URL = os.environ.get("CRM_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="CRM_TEST_DATABASE_URL is not set")

if DATABASE_URL:
    os.environ.setdefault("DATABASE_URL", DATABASE_URL)
    os.environ.setdefault("SYNC_DATABASE_URL", DATABASE_URL.replace("+asyncpg", "+psycopg2"))
    os.environ.setdefault("SECRET_KEY", "crm-test-secret-key-0123456789abcdef")


def _tables():
    from app.models import contracts as c
    from app.models import crm
    from app.models import models as m

    seeds = [
        m.Organization, m.UserAccount, m.Employee, m.RoleAssignment, m.ERPParty, m.ERPDocument, m.ERPSequence, m.ERPCustomField,
        m.ERPModuleConfig, m.ERPAccessRole, m.ERPCapability, m.ERPAccountRole, m.ERPTeamRole, m.TeamMember, m.ERPPriceList, m.ERPAccount,
        m.Task, m.TaskAssignee, m.Project, m.Attachment, m.AuditLog, m.DomainEvent, m.UserNotification, m.NotificationOutbox, m.ManagerSettings,
        c.ContractDocument, crm.ERPPartyGroup, crm.ERPPaymentTerm, crm.ERPPartyContact, crm.ERPPartyBankAccount, crm.ERPStatus,
        crm.CRMActivityType, crm.CRMActivity,
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
async def _api():
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.database import get_db
    from app.core.enterprise_deps import ActorContext, get_actor
    from app.erp import router as erp
    from app.models import models as m

    engine = create_async_engine(DATABASE_URL)
    tables = _tables()
    async with engine.begin() as connection:
        await connection.execute(text("DROP TABLE IF EXISTS " + ", ".join(f'"{table.name}"' for table in tables) + " CASCADE"))
        await connection.run_sync(lambda sync: m.Base.metadata.create_all(sync, tables=tables))
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async with sessions() as db:
        org = m.Organization(name="Оюунс")
        db.add(org)
        await db.flush()
        boss = m.Employee(organization_id=org.id, name="Удирдлага Бат")
        db.add(boss)
        await db.flush()
        seller = m.Employee(organization_id=org.id, name="Борлуулагч Сараа", manager_id=boss.id)
        outsider = m.Employee(organization_id=org.id, name="Гишүүн Дорж")
        db.add_all([seller, outsider])
        await db.flush()
        accounts = {}
        for key, employee, role in (("admin", seller, "admin"), ("boss", boss, "manager"), ("member", outsider, "member")):
            account = m.UserAccount(organization_id=org.id, employee_id=employee.id, email=f"{key}@crm.test", password_hash="x")
            db.add(account)
            await db.flush()
            db.add(m.RoleAssignment(account_id=account.id, role=role))
            accounts[key] = ActorContext(account_id=account.id, organization_id=org.id, employee_id=employee.id, email=account.email, locale="mn", roles=frozenset({role}))
        await db.commit()
        ids = {"org": org.id, "seller": seller.id, "boss": boss.id}

    current = {"actor": accounts["admin"]}
    api = FastAPI()
    api.include_router(erp.router, prefix="/v1/erp")

    async def override_db():
        async with sessions() as session:
            yield session

    api.dependency_overrides[get_db] = override_db
    api.dependency_overrides[get_actor] = lambda: current["actor"]
    async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:
        yield client, current, accounts, ids, sessions
    await engine.dispose()


def test_crm_customer_master_activities_and_reminders(monkeypatch):
    async def run():
        async with _api() as (client, current, accounts, ids, sessions):
            base = "/v1/erp/crm"

            # Capabilities: admin can do everything; a plain member cannot see CRM.
            caps = (await client.get(f"{base}/capabilities")).json()
            assert caps["parties"]["create"] and caps["activities"]["archive"]
            current["actor"] = accounts["member"]
            assert (await client.get(f"{base}/capabilities")).json()["parties"]["view"] is False
            assert (await client.get(f"{base}/parties")).status_code == 403
            current["actor"] = accounts["admin"]

            lookups = (await client.get(f"{base}/lookups")).json()
            assert [row["name"] for row in lookups["statuses"]] == ["Шинэ", "Хийгдэж байгаа", "Хүлээгдэж байгаа", "Дууссан"]
            assert {"Уулзалт", "Утас", "Мэйл"} <= {row["name"] for row in lookups["activity_types"]}
            assert lookups["party_groups"][0]["is_default"] is True

            # Customer master: auto code from 10001, default group, TIN duplicate guard.
            created = await client.post(f"{base}/parties", json={"name": "Даянсофт ХХК", "tax_id": "5922364", "registry_no": "5922364", "vat_payer": True, "tags": ["VIP", "vip"]})
            assert created.status_code == 201, created.text
            party = created.json()
            assert party["code"] == "10001" and party["group_name"] == "Харилцагчид" and party["tags"] == ["VIP"] and party["is_customer"]
            duplicate = await client.post(f"{base}/parties", json={"name": "Даянсофт салбар", "tax_id": "5922364"})
            assert duplicate.status_code == 409 and duplicate.json()["detail"]["code"] == "crm_party_duplicate_tin"
            branch = await client.post(f"{base}/parties", json={"name": "Даянсофт салбар", "tax_id": "5922364", "parent_party_id": party["id"], "confirm_duplicate_tin": True})
            assert branch.status_code == 201 and branch.json()["code"] == "10002" and branch.json()["parent_name"] == "Даянсофт ХХК"
            cycle = await client.patch(f"{base}/parties/{party['id']}", json={"parent_party_id": branch.json()["id"]})
            assert cycle.status_code == 422 and cycle.json()["detail"]["code"] == "crm_party_parent_cycle"
            supplier = (await client.post(f"{base}/parties", json={"name": "Нийлүүлэгч ХХК", "party_type": "supplier"})).json()
            assert supplier["is_supplier"] and not supplier["is_customer"] and supplier["party_type"] == "supplier"

            updated = await client.patch(f"{base}/parties/{party['id']}", json={"name": "Даянсофт", "credit_limit": "2000000", "version": party["version"]})
            assert updated.status_code == 200 and updated.json()["version"] == party["version"] + 1
            stale = await client.patch(f"{base}/parties/{party['id']}", json={"name": "Хуучин", "version": party["version"]})
            assert stale.status_code == 409 and stale.json()["detail"]["code"] == "crm_version_conflict"
            history = (await client.get(f"{base}/parties/{party['id']}/history")).json()
            assert history[0]["action"] == "updated" and history[0]["after"]["name"] == "Даянсофт" and history[0]["before"]["name"] == "Даянсофт ХХК"

            listed = (await client.get(f"{base}/parties", params={"duplicates_only": True})).json()
            assert {row["code"] for row in listed["items"]} == {"10001", "10002"} and all(row["duplicate_tax_id"] for row in listed["items"])
            assert (await client.get(f"{base}/parties", params={"kind": "supplier"})).json()["total"] == 1

            # Contacts: first becomes default; a later default replaces it.
            first = (await client.post(f"{base}/parties/{party['id']}/contacts", json={"name": "Болд", "phone": "99112233", "email": "bold@dayansoft.mn"})).json()
            assert first["is_default"] is True
            second = (await client.post(f"{base}/parties/{party['id']}/contacts", json={"name": "Сэцэн", "is_default": True})).json()
            detail = (await client.get(f"{base}/parties/{party['id']}")).json()
            defaults = {row["name"]: row["is_default"] for row in detail["contacts"]}
            assert defaults == {"Болд": False, "Сэцэн": True} and detail["children"][0]["code"] == "10002"
            bank = await client.post(f"{base}/parties/{party['id']}/bank-accounts", json={"bank_name": "Хаан банк", "account_no": "5000123456"})
            assert bank.status_code == 201 and bank.json()["is_default"]

            # Activity: typed-in type is created, contact snapshot, default status, overdue maths.
            yesterday = (datetime.now(timezone.utc) - timedelta(days=1, hours=2)).isoformat()
            response = await client.post(f"{base}/activities", json={
                "party_id": party["id"], "contact_id": first["id"], "subject": "100 ширхэг бараа авах хүсэлт", "type_name": "Үзэсгэлэн",
                "due_at": yesterday, "expected_revenue": "5000000", "is_important": True,
            })
            assert response.status_code == 201, response.text
            activity = response.json()
            assert activity["number"] == "CRM-000001" and activity["type_name"] == "Үзэсгэлэн" and activity["contact_phone"] == "99112233"
            assert activity["status"]["name"] == "Шинэ" and activity["responsible_employee_id"] == ids["seller"]
            assert activity["is_overdue"] and activity["overdue_days"] >= 1
            mismatch = await client.post(f"{base}/activities", json={"party_id": supplier["id"], "contact_id": first["id"], "subject": "Буруу"})
            assert mismatch.status_code == 422

            overdue = (await client.get(f"{base}/activities", params={"overdue": True})).json()
            assert [row["id"] for row in overdue["items"]] == [activity["id"]]
            family = (await client.get(f"{base}/activities", params={"party_id": party["id"], "include_children": True})).json()
            assert family["total"] == 1

            # Follow-up reminders: overdue ping to the owner, escalation to their manager.
            from app.services import crm_reminders

            monkeypatch.setattr(crm_reminders, "AsyncSessionLocal", sessions)
            await crm_reminders.reconcile_crm_activity_reminders(now=datetime.now(timezone.utc) + timedelta(days=10))
            await crm_reminders.reconcile_crm_activity_reminders(now=datetime.now(timezone.utc) + timedelta(days=10))
            from sqlalchemy import select
            from app.models.models import UserNotification

            async with sessions() as db:
                kinds = sorted((await db.execute(select(UserNotification.kind, UserNotification.recipient_employee_id))).all())
            assert kinds == [("crm_activity_escalated", ids["boss"]), ("crm_activity_overdue", ids["seller"])]

            summary = (await client.get(f"{base}/summary")).json()
            assert summary["open"] == 1 and summary["overdue"] == 1 and summary["important"] == 1
            assert summary["expected_revenue"] == [{"currency": "MNT", "amount": "5000000.0000"}]

            # Clone, close, reopen, review.
            clone = (await client.post(f"{base}/activities/{activity['id']}/clone")).json()
            assert clone["number"] == "CRM-000002" and clone["status"]["name"] == "Шинэ" and clone["completed_at"] is None
            closed = (await client.post(f"{base}/activities/{activity['id']}/close", json={"completion_note": "Гэрээ байгуулсан"})).json()
            assert closed["is_closed"] and closed["completed_at"] and closed["status"]["category"] == "done" and not closed["is_open"]
            assert (await client.get(f"{base}/activities", params={"overdue": True})).json()["total"] == 0
            reopened = (await client.post(f"{base}/activities/{activity['id']}/reopen")).json()
            assert reopened["is_open"] and reopened["closed_at"] is None
            reviewed = (await client.post(f"{base}/activities/{activity['id']}/review")).json()
            assert reviewed["reviewed_by_name"] == "Борлуулагч Сараа"

            # Marking the status done fills the completion date automatically.
            done_status = next(row for row in lookups["statuses"] if row["category"] == "done")
            finished = (await client.patch(f"{base}/activities/{clone['id']}", json={"status_id": done_status["id"], "version": clone["version"]})).json()
            assert finished["completed_at"] and not finished["is_open"]

            # Reassignment notifies the new owner.
            current["actor"] = accounts["boss"]
            reassigned = await client.patch(f"{base}/activities/{activity['id']}", json={"responsible_employee_id": ids["seller"], "subject": "Шинэчилсэн"})
            assert reassigned.status_code == 200
            current["actor"] = accounts["admin"]
            # The form sends type_id=null together with a typed-in new type.
            retyped = (await client.patch(f"{base}/activities/{activity['id']}", json={"type_id": None, "type_name": "Вебинар"})).json()
            assert retyped["type_name"] == "Вебинар"

            # Bulk create uses each party's default contact.
            bulk = await client.post(f"{base}/activities/bulk", json={"party_ids": [party["id"], supplier["id"]], "template": {"subject": "Шинэ жилийн мэндчилгээ", "type_id": lookups["activity_types"][0]["id"]}})
            assert bulk.status_code == 201 and bulk.json()["created"] == 2
            by_party = {row["party_id"]: row for row in bulk.json()["items"]}
            assert by_party[party["id"]]["contact_name"] == "Сэцэн" and by_party[supplier["id"]]["contact_name"] is None

            # Linked follow-up task.
            task = await client.post(f"{base}/activities/{activity['id']}/task", json={})
            assert task.status_code == 201 and task.json()["activity"]["task_id"] == task.json()["task_id"]
            assert (await client.post(f"{base}/activities/{activity['id']}/task", json={})).status_code == 409

            # Parties with history cannot be deleted; unused ones can.
            blocked = await client.delete(f"{base}/parties/{party['id']}")
            assert blocked.status_code == 409 and blocked.json()["detail"]["references"]["activities"] >= 1
            spare = (await client.post(f"{base}/parties", json={"name": "Түр харилцагч"})).json()
            assert (await client.delete(f"{base}/parties/{spare['id']}")).status_code == 204
            deactivated = (await client.patch(f"{base}/parties/{supplier['id']}", json={"is_active": False})).json()
            assert deactivated["is_active"] is False and deactivated["inactive_since"]

            # Settings: statuses in use cannot be deleted.
            in_use = await client.delete(f"{base}/settings/statuses/{done_status['id']}")
            assert in_use.status_code == 409
            new_status = await client.post(f"{base}/settings/statuses", json={"name": "Цуцалсан", "color": "#ff0000", "category": "cancelled", "sort": 50})
            assert new_status.status_code == 201 and new_status.json()["color"] == "#FF0000"

            # Import: dry run reports row errors; a clean file commits.
            bad = "name,code,tax_id,group\nЗөв ХХК,,111,Харилцагчид\n,,222,\nҮл мэдэх,,333,Байхгүй бүлэг\n"
            preview = (await client.post(f"{base}/parties/import", files={"file": ("p.csv", bad.encode(), "text/csv")})).json()
            assert preview["valid_rows"] == 1 and {error["code"] for error in preview["errors"]} == {"missing_name", "unknown_group"}
            good = "name,tax_id,is_supplier\nИмпорт ХХК,5922364,1\n"
            committed = (await client.post(f"{base}/parties/import", params={"dry_run": False}, files={"file": ("p.csv", good.encode(), "text/csv")})).json()
            assert committed["created"] == 1 and committed["warnings"][0]["code"] == "duplicate_tax_id"
            exported = await client.get(f"{base}/parties/export.csv")
            assert exported.status_code == 200 and "Импорт ХХК" in exported.text

    asyncio.run(run())
