"""Chart of accounts API («Данс код», d047) against PostgreSQL.

Runs only when CHART_TEST_DATABASE_URL points at a throwaway database
(for example ``postgresql+asyncpg://tracker@127.0.0.1:55432/chart_test``).
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

import pytest

DATABASE_URL = os.environ.get("CHART_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="CHART_TEST_DATABASE_URL is not set")

if DATABASE_URL:
    os.environ.setdefault("DATABASE_URL", DATABASE_URL)
    os.environ.setdefault("SYNC_DATABASE_URL", DATABASE_URL.replace("+asyncpg", "+psycopg2"))
    os.environ.setdefault("SECRET_KEY", "chart-test-secret-key-0123456789abcdef")


def _tables():
    from app.models import models as m

    # Usage and delete protection scan every table that references an account.
    referencing = {table for table in m.Base.metadata.tables.values()
                   if any(foreign_key.column.table.name == "erp_accounts" for column in table.columns for foreign_key in column.foreign_keys)}
    seeds = {model.__table__ for model in (m.Organization, m.UserAccount, m.Employee, m.RoleAssignment, m.ERPAccessRole, m.ERPCapability, m.ERPAccountRole,
                                          m.ERPTeamRole, m.TeamMember, m.PayrollPostingProfile, m.AuditLog, m.DomainEvent, m.ERPDeletedSeedAccount)}
    tables = referencing | seeds
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
        employee = m.Employee(organization_id=org.id, name="Нягтлан")
        db.add(employee)
        await db.flush()
        account = m.UserAccount(organization_id=org.id, employee_id=employee.id, email="admin@chart.test", password_hash="x")
        db.add(account)
        await db.flush()
        actor = ActorContext(account_id=account.id, organization_id=org.id, employee_id=employee.id, email=account.email, locale="mn", roles=frozenset({"admin"}))
        await db.commit()
        org_id = org.id

    api = FastAPI()
    api.include_router(erp.router, prefix="/v1/erp")

    async def override_db():
        async with sessions() as session:
            yield session

    api.dependency_overrides[get_db] = override_db
    api.dependency_overrides[get_actor] = lambda: actor
    async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:
        yield client, sessions, org_id
    await engine.dispose()


def test_chart_of_accounts_flows_keep_posting_and_payroll_consistent():
    async def scenario():
        from app.erp.service import bootstrap_organization, default_account

        async with _api() as (client, sessions, org_id):
            async with sessions() as db:
                await bootstrap_organization(db, org_id)
                await db.commit()
            accounts = {row["code"]: row for row in (await client.get("/v1/erp/accounting/accounts")).json()}
            assert accounts["1000"]["name"] == "Касс дахь мөнгө" and accounts["1000"]["account_type"] == "cash"
            assert accounts["5100"]["purpose"] == "salary_expense"

            # Renaming the cash account must not stop payments finding it (old bug: account_type became "asset").
            cash = accounts["1000"]
            response = await client.put(f"/v1/erp/accounting/accounts/{cash['id']}", json={**cash, "name": "Касс — төв салбар"})
            assert response.status_code == 200 and response.json()["account_type"] == "cash"
            async with sessions() as db:
                assert (await default_account(db, org_id, "cash")).id == cash["id"]

            # Bank details are kept on a bank account; a purpose/classification mismatch is refused.
            bank = await client.post("/v1/erp/accounting/accounts", json={"code": "1020", "name": "Харилцах данс — Хаан банк", "classification": "asset", "purpose": "bank",
                                                                          "bank_name": "Хаан банк", "bank_account_number": "5012345678", "bank_iban": "mn 12 0005"})
            assert bank.status_code == 201 and bank.json()["bank_iban"] == "MN120005" and bank.json()["account_type"] == "cash"
            wrong = await client.post("/v1/erp/accounting/accounts", json={"code": "1030", "name": "Буруу", "classification": "expense", "purpose": "bank"})
            assert wrong.status_code == 422 and wrong.json()["detail"]["code"] == "erp_account_classification_invalid"

            # Summary accounts: same classification only, and no cycles.
            top = (await client.post("/v1/erp/accounting/accounts", json={"code": "6", "name": "Бусад зардал", "classification": "expense", "purpose": "general", "is_group": True})).json()
            sub = (await client.post("/v1/erp/accounting/accounts", json={"code": "60", "name": "Маркетинг", "classification": "expense", "purpose": "general", "is_group": True, "parent_id": top["id"]})).json()
            cycle = await client.put(f"/v1/erp/accounting/accounts/{top['id']}", json={**top, "parent_id": sub["id"]})
            assert cycle.status_code == 422 and cycle.json()["detail"]["code"] == "erp_account_parent_cycle"
            mismatch = await client.post("/v1/erp/accounting/accounts", json={"code": "1090", "name": "Хөрөнгө", "classification": "asset", "purpose": "general", "parent_id": top["id"]})
            assert mismatch.status_code == 422 and mismatch.json()["detail"]["code"] == "erp_account_parent_classification_mismatch"

            # Payroll settings accept only the right class of account and then show up in usage.
            advance = accounts["2350"]
            settings = (await client.get("/v1/erp/payroll/monthly/settings")).json()
            refused = await client.put("/v1/erp/payroll/monthly/settings", json={**settings, "salary_expense_account_id": cash["id"]})
            assert refused.status_code == 422 and "Зардал" in refused.json()["detail"]
            saved = await client.put("/v1/erp/payroll/monthly/settings", json={**settings, "salary_expense_account_id": accounts["5100"]["id"], "advance_clearing_account_id": advance["id"]})
            assert saved.status_code == 200, saved.text
            # The advance may also be settled through the salary expense account; other classes are refused.
            as_expense = await client.put("/v1/erp/payroll/monthly/settings", json={**settings, "advance_clearing_account_id": accounts["5100"]["id"]})
            assert as_expense.status_code == 200, as_expense.text
            as_income = await client.put("/v1/erp/payroll/monthly/settings", json={**settings, "advance_clearing_account_id": accounts["4000"]["id"]})
            assert as_income.status_code == 422
            await client.put("/v1/erp/payroll/monthly/settings", json={**settings, "salary_expense_account_id": accounts["5100"]["id"], "advance_clearing_account_id": advance["id"]})
            usage = {row["account_id"]: row for row in (await client.get("/v1/erp/accounting/accounts/usage")).json()}
            assert usage[accounts["5100"]["id"]]["modules"] == {"payroll": 1}
            assert usage[top["id"]]["modules"] == {"children": 1}

            # A used account keeps its posting identity: code change refused, rename fine, delete archives.
            salary = accounts["5100"]
            locked = await client.put(f"/v1/erp/accounting/accounts/{salary['id']}", json={**salary, "code": "5101"})
            assert locked.status_code == 409 and locked.json()["detail"]["fields"] == ["code"]
            renamed = await client.put(f"/v1/erp/accounting/accounts/{salary['id']}", json={**salary, "name": "Үндсэн цалингийн зардал"})
            assert renamed.status_code == 200
            assert (await client.delete(f"/v1/erp/accounting/accounts/{salary['id']}")).json()["outcome"] == "archived"
            assert (await client.delete(f"/v1/erp/accounting/accounts/{bank.json()['id']}")).json()["outcome"] == "deleted"

            catalog = (await client.get("/v1/erp/accounting/accounts/catalog")).json()
            assert {"key": "bank", "label": "Харилцах данс (банк)", "classifications": ["asset"], "module": "cash", "has_bank_details": True} in catalog["purposes"]

    asyncio.run(scenario())
