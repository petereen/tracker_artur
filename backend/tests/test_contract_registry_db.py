"""Contract registry metadata (Dayansoft d028) against PostgreSQL.

Runs only when CONTRACT_TEST_DATABASE_URL points at a throwaway database
(for example ``postgresql+asyncpg://tracker@127.0.0.1:55432/contract_test``).
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import date, timedelta

import pytest

DATABASE_URL = os.environ.get("CONTRACT_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="CONTRACT_TEST_DATABASE_URL is not set")

if DATABASE_URL:
    os.environ.setdefault("DATABASE_URL", DATABASE_URL)
    os.environ.setdefault("SYNC_DATABASE_URL", DATABASE_URL.replace("+asyncpg", "+psycopg2"))
    os.environ.setdefault("SECRET_KEY", "contract-test-secret-key-0123456789abcdef")

BODY = {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Гэрээний нөхцөл"}]}]}


def _tables():
    from app.models import contracts as c
    from app.models import crm
    from app.models import models as m

    seeds = [
        m.Organization, m.UserAccount, m.Employee, m.RoleAssignment, m.ERPParty, m.ERPUnitOfMeasure, m.Project, m.Task,
        m.AuditLog, m.DomainEvent, crm.ERPPaymentTerm, crm.ERPPartyGroup,
        c.ContractGroup, c.ContractDocument, c.ContractRevision, c.ContractReview, c.ContractComment, c.ContractFile,
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
    from app.models import crm
    from app.models import models as m
    from app.routers import contracts

    engine = create_async_engine(DATABASE_URL)
    tables = _tables()
    async with engine.begin() as connection:
        await connection.execute(text("DROP TABLE IF EXISTS " + ", ".join(f'"{table.name}"' for table in tables) + " CASCADE"))
        await connection.run_sync(lambda sync: m.Base.metadata.create_all(sync, tables=tables))
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async with sessions() as db:
        org, other_org = m.Organization(name="Оюунс"), m.Organization(name="Өөр")
        db.add_all([org, other_org])
        await db.flush()
        actors = {}
        for key, role in (("admin", "admin"), ("author", "member"), ("outsider", "member")):
            employee = m.Employee(organization_id=org.id, name=f"{key.title()} ажилтан")
            db.add(employee)
            await db.flush()
            account = m.UserAccount(organization_id=org.id, employee_id=employee.id, email=f"{key}@contract.test", password_hash="x")
            db.add(account)
            await db.flush()
            db.add(m.RoleAssignment(account_id=account.id, role=role))
            actors[key] = ActorContext(account_id=account.id, organization_id=org.id, employee_id=employee.id, email=account.email, locale="mn", roles=frozenset({role}))
        head = m.ERPParty(organization_id=org.id, party_type="customer", code="10001", name="Толгой групп ХХК")
        foreign = m.ERPParty(organization_id=other_org.id, party_type="customer", code="90001", name="Гадны ХХК")
        db.add_all([head, foreign])
        await db.flush()
        term = crm.ERPPaymentTerm(organization_id=org.id, code="NET30", name="30 хоногт", days=30)
        unit = m.ERPUnitOfMeasure(organization_id=org.id, code="HR", name="Цаг", symbol="ц")
        db.add_all([term, unit])
        await db.flush()
        party = m.ERPParty(organization_id=org.id, party_type="customer", code="10002", name="Салбар Харилцагч ХХК", parent_party_id=head.id, payment_term_id=term.id)
        db.add(party)
        await db.flush()
        await db.commit()
        ids = {"org": org.id, "head": head.id, "party": party.id, "foreign": foreign.id, "term": term.id, "unit": unit.id}

    current = {"actor": actors["author"]}
    api = FastAPI()
    api.include_router(contracts.router, prefix="/v1")

    async def override_db():
        async with sessions() as session:
            yield session

    api.dependency_overrides[get_db] = override_db
    api.dependency_overrides[get_actor] = lambda: current["actor"]
    async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:
        yield client, current, actors, ids
    await engine.dispose()


def _draft(**extra):
    return {"title": "Үйлчилгээний гэрээ", "document_type": "contract", "body_json": BODY, "effective_end_on": (date.today() + timedelta(days=90)).isoformat(), **extra}


def test_contract_registry_metadata_codes_groups_and_filters():
    async def run():
        async with _api() as (client, current, actors, ids):
            options = (await client.get("/v1/contracts/registry-options")).json()
            assert options["next_code"] == "CT-0001" and options["can_manage_groups"] is False
            assert options["units"][0]["code"] == "HR" and options["payment_terms"][0]["code"] == "NET30"

            # Groups: only admin / legal counsel manage them; hierarchical without cycles.
            assert (await client.post("/v1/contracts/groups", json={"code": "SALES", "name": "Борлуулалтын гэрээ"})).status_code == 403
            current["actor"] = actors["admin"]
            sales = (await client.post("/v1/contracts/groups", json={"code": "SALES", "name": "Борлуулалтын гэрээ"})).json()
            service = (await client.post("/v1/contracts/groups", json={"code": "SVC", "name": "Үйлчилгээний гэрээ", "parent_id": sales["id"]})).json()
            assert (await client.post("/v1/contracts/groups", json={"code": "sales", "name": "Давхар"})).status_code == 409
            cycle = await client.patch(f"/v1/contracts/groups/{sales['id']}", json={"parent_id": service["id"]})
            assert cycle.status_code == 422 and cycle.json()["detail"]["code"] == "contract_group_cycle"
            current["actor"] = actors["author"]

            parties = (await client.get("/v1/contracts/party-options", params={"q": "Салбар"})).json()
            assert [row["code"] for row in parties] == ["10002"]
            assert parties[0]["head_party"]["name"] == "Толгой групп ХХК" and parties[0]["payment_term_id"] == ids["term"]

            created = await client.post("/v1/contracts", json=_draft(
                contract_number="ГД-15/2026", group_id=service["id"], party_id=ids["party"], signed_on="2026-09-01",
                quantity="120", unit_id=ids["unit"], unit_price="50000", amount="6000000", currency="mnt", penalty_pct="0.5",
                payment_term_id=ids["term"], note="Сар бүр тооцоо нийлнэ",
                links=[{"kind": "shared", "label": "Скан", "url": "https://drive.example/scan.pdf"}, {"kind": "path", "url": "\\\\srv\\contracts\\015.pdf"}],
                custom_fields=[{"label": "Хариуцагч хуульч", "value": "Б. Сараа"}],
            ))
            assert created.status_code == 201, created.text
            first = created.json()
            assert first["code"] == "CT-0001" and first["contract_number"] == "ГД-15/2026"
            assert first["party"]["name"] == "Салбар Харилцагч ХХК" and first["head_party"]["code"] == "10001"
            assert first["group"]["code"] == "SVC" and first["unit"]["symbol"] == "ц" and first["payment_term"]["code"] == "NET30"
            assert first["amount"] == 6000000 and first["currency"] == "MNT" and first["penalty_pct"] == 0.5
            assert first["links"][1]["kind"] == "path" and first["custom_fields"] == [{"label": "Хариуцагч хуульч", "value": "Б. Сараа"}]
            assert first["is_active"] is True and first["overdue_days"] == 0 and first["file_count"] == 0

            # Manual codes are accepted and the next contract continues their numbering.
            manual = (await client.post("/v1/contracts", json=_draft(code="ГЭ-2026/015"))).json()
            assert manual["code"] == "ГЭ-2026/015"
            auto = (await client.post("/v1/contracts", json=_draft(effective_end_on=(date.today() - timedelta(days=3)).isoformat(), effective_start_on="2026-01-01"))).json()
            assert auto["code"] == "ГЭ-2026/016" and auto["overdue_days"] == 3
            taken = await client.post("/v1/contracts", json=_draft(code="ГЭ-2026/016"))
            assert taken.status_code == 409 and taken.json()["detail"]["code"] == "contract_code_taken"

            # Validation: unsafe links and cross-organization references are rejected.
            assert (await client.post("/v1/contracts", json=_draft(links=[{"kind": "online", "url": "javascript:alert(1)"}]))).status_code == 422
            foreign = await client.post("/v1/contracts", json=_draft(party_id=ids["foreign"]))
            assert foreign.status_code == 422 and foreign.json()["detail"]["code"] == "contract_party_not_found"

            # Filters: party, group (includes sub-groups), search by counterparty name / code.
            listing = (await client.get("/v1/contracts", params={"party_id": ids["party"]})).json()
            assert [item["code"] for item in listing["items"]] == ["CT-0001"]
            assert [item["code"] for item in (await client.get("/v1/contracts", params={"group_id": sales["id"]})).json()["items"]] == ["CT-0001"]
            assert [item["code"] for item in (await client.get("/v1/contracts", params={"search": "Салбар"})).json()["items"]] == ["CT-0001"]
            assert [item["code"] for item in (await client.get("/v1/contracts", params={"search": "2026/015"})).json()["items"]] == ["ГЭ-2026/015"]
            period = (await client.get("/v1/contracts", params={"date_from": date.today().isoformat()})).json()
            assert "ГЭ-2026/016" not in [item["code"] for item in period["items"]]

            # Draft edits: registry fields change, a cleared code keeps the current one.
            detail = (await client.get(f"/v1/contracts/{first['public_id']}")).json()
            patched = await client.patch(f"/v1/contracts/{first['public_id']}", json={"code": "", "amount": "6500000", "penalty_pct": None}, headers={"If-Match": str(detail["version"])})
            assert patched.status_code == 200, patched.text
            assert patched.json()["code"] == "CT-0001" and patched.json()["amount"] == 6500000 and patched.json()["penalty_pct"] is None
            assert patched.json()["party"]["code"] == "10002"

            # Registry patch works outside the draft lock and deactivates instead of deleting.
            deactivated = await client.patch(f"/v1/contracts/{auto['public_id']}/registry", json={"is_active": False, "contract_number": "ГД-16"})
            assert deactivated.status_code == 200 and deactivated.json()["is_active"] is False and deactivated.json()["overdue_days"] == 0
            inactive = (await client.get("/v1/contracts", params={"active": "false"})).json()
            assert [item["code"] for item in inactive["items"]] == ["ГЭ-2026/016"]
            current["actor"] = actors["outsider"]
            assert (await client.patch(f"/v1/contracts/{auto['public_id']}/registry", json={"is_active": True})).status_code == 404

            # A group in use cannot be deleted; an unused inactive one cannot be newly selected.
            current["actor"] = actors["admin"]
            assert (await client.delete(f"/v1/contracts/groups/{service['id']}")).status_code == 409
            spare = (await client.post("/v1/contracts/groups", json={"code": "OLD", "name": "Хуучин"})).json()
            await client.patch(f"/v1/contracts/groups/{spare['id']}", json={"is_active": False})
            inactive_group = await client.post("/v1/contracts", json=_draft(group_id=spare["id"]))
            assert inactive_group.status_code == 422 and inactive_group.json()["detail"]["code"] == "contract_group_inactive"
            assert (await client.delete(f"/v1/contracts/groups/{spare['id']}")).status_code == 204
            options = (await client.get("/v1/contracts/registry-options")).json()
            assert options["can_manage_groups"] is True
            assert {row["code"]: row["contract_count"] for row in options["groups"]} == {"SALES": 0, "SVC": 1}

    asyncio.run(run())
