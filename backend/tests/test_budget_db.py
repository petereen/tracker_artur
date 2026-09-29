"""Budget accounts, budgets and budget-vs-actual analysis against PostgreSQL.

Runs only when BUDGET_TEST_DATABASE_URL points at a throwaway database
(for example ``postgresql+asyncpg://tracker@127.0.0.1:55432/budget_test``).
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal

import pytest

DATABASE_URL = os.environ.get("BUDGET_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="BUDGET_TEST_DATABASE_URL is not set")

if DATABASE_URL:
    os.environ.setdefault("DATABASE_URL", DATABASE_URL)
    os.environ.setdefault("SYNC_DATABASE_URL", DATABASE_URL.replace("+asyncpg", "+psycopg2"))
    os.environ.setdefault("SECRET_KEY", "budget-test-secret-key-0123456789abcdef")


def _tables():
    from app.models import budget as b
    from app.models import crm
    from app.models import models as m

    seeds = [
        m.Organization, m.UserAccount, m.Employee, m.RoleAssignment, m.ERPParty, m.ERPDocument, m.ERPGeneralLedgerEntry, m.ERPSequence,
        m.ERPModuleConfig, m.ERPAccessRole, m.ERPCapability, m.ERPAccountRole, m.ERPTeamRole, m.TeamMember, m.ERPAccount, m.Project,
        m.AuditLog, m.DomainEvent, crm.ERPPartyGroup,
        b.BudgetAccountGroup, b.BudgetAccount, b.BudgetAccountLink, b.Budget, b.BudgetEntry,
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
    from app.models import crm
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
        actors = {}
        for key, role in (("admin", "admin"), ("manager", "manager"), ("member", "member")):
            employee = m.Employee(organization_id=org.id, name=f"{key.title()} ажилтан")
            db.add(employee)
            await db.flush()
            account = m.UserAccount(organization_id=org.id, employee_id=employee.id, email=f"{key}@budget.test", password_hash="x")
            db.add(account)
            await db.flush()
            db.add(m.RoleAssignment(account_id=account.id, role=role))
            actors[key] = ActorContext(account_id=account.id, organization_id=org.id, employee_id=employee.id, email=account.email, locale="mn", roles=frozenset({role}))
        ledger = {}
        for code, name, classification in (("4000", "Борлуулалтын орлого", "income"), ("5100", "Цалингийн зардал", "expense"),
                                           ("6010", "Зар сурталчилгаа", "expense"), ("6020", "Сошиал сурталчилгаа", "expense"),
                                           ("6900", "Бусад зардал", "expense"), ("1000", "Касс", "asset")):
            row = m.ERPAccount(organization_id=org.id, code=code, name=name, account_type=classification, classification=classification)
            db.add(row)
            await db.flush()
            ledger[code] = row.id
        project = m.Project(organization_id=org.id, code="MKT", name="Маркетингийн кампанит ажил")
        group = crm.ERPPartyGroup(organization_id=org.id, code="RETAIL", name="Жижиглэн")
        db.add_all([project, group])
        await db.flush()
        party = m.ERPParty(organization_id=org.id, party_type="customer", code="10001", name="Харилцагч ХХК", group_id=group.id)
        db.add(party)
        await db.flush()
        await db.commit()
        ids = {"org": org.id, "ledger": ledger, "project": project.id, "party_group": group.id, "party": party.id}

    current = {"actor": actors["admin"]}
    api = FastAPI()
    api.include_router(erp.router, prefix="/v1/erp")

    async def override_db():
        async with sessions() as session:
            yield session

    api.dependency_overrides[get_db] = override_db
    api.dependency_overrides[get_actor] = lambda: current["actor"]
    async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:
        yield client, current, actors, ids, sessions
    await engine.dispose()


async def _post_journal(sessions, ids, posting_date: date, lines: list[tuple[str, str, str]], *, project: bool = False, party: bool = False) -> None:
    """Post a balanced journal straight to the ledger (debit/credit per account code)."""
    from app.models import models as m

    async with sessions() as db:
        document = m.ERPDocument(organization_id=ids["org"], document_type="journal_entry", number=f"JE-{posting_date.isoformat()}-{len(lines)}-{project}",
                                 status="submitted", posting_date=posting_date, project_id=ids["project"] if project else None,
                                 party_id=ids["party"] if party else None)
        db.add(document)
        await db.flush()
        for code, debit, credit in lines:
            db.add(m.ERPGeneralLedgerEntry(organization_id=ids["org"], document_id=document.id, account_id=ids["ledger"][code], posting_date=posting_date,
                                           debit=Decimal(debit), credit=Decimal(credit), memo=f"{code} test"))
        await db.commit()


def test_budget_accounts_budgets_and_analysis():
    async def run():
        async with _api() as (client, current, actors, ids, sessions):
            base = "/v1/erp/budget"
            ledger = ids["ledger"]

            caps = (await client.get(f"{base}/capabilities")).json()
            assert caps["budgets"]["approve"] and caps["settings"]["edit"] and caps["module_enabled"] is False

            # A plain member has no budget access at all.
            current["actor"] = actors["member"]
            assert (await client.get(f"{base}/lookups")).status_code == 403
            assert (await client.get(f"{base}/budgets")).status_code == 403
            current["actor"] = actors["admin"]

            lookups = (await client.get(f"{base}/lookups")).json()
            groups = {row["code"]: row for row in lookups["groups"]}
            assert {"INCOME", "COGS", "EXPENSE"} <= set(groups)

            # ③ Budget accounts: generate one per ledger account, or group several (60101/60102 → Маркетинг).
            generated = (await client.post(f"{base}/accounts/generate", json={"erp_account_ids": [ledger["4000"], ledger["5100"]]})).json()
            assert generated["created"] == 2
            by_code = {row["code"]: row for row in generated["accounts"]}
            assert by_code["4000"]["kind"] == "income" and by_code["4000"]["group_id"] == groups["INCOME"]["id"]
            assert by_code["5100"]["kind"] == "expense"
            marketing = await client.post(f"{base}/accounts", json={"code": "MKT", "name": "Маркетингийн зардал", "kind": "expense",
                                                                    "group_id": groups["EXPENSE"]["id"], "erp_account_ids": [ledger["6010"], ledger["6020"]]})
            assert marketing.status_code == 201, marketing.text
            marketing = marketing.json()
            assert {row["code"] for row in marketing["erp_accounts"]} == {"6010", "6020"}
            taken = await client.post(f"{base}/accounts", json={"code": "DUP", "name": "Давхар", "kind": "expense", "erp_account_ids": [ledger["6010"]]})
            assert taken.status_code == 409 and taken.json()["detail"]["code"] == "budget_account_link_taken"
            assert (await client.post(f"{base}/accounts", json={"code": "MKT", "name": "x"})).json()["detail"]["code"] == "budget_code_taken"
            income_id, salary_id, marketing_id = by_code["4000"]["id"], by_code["5100"]["id"], marketing["id"]

            # ④ Budget: 2026 monthly, base scenario.
            created = await client.post(f"{base}/budgets", json={"name": "2026 оны үндсэн төсөв", "purpose": "Жилийн зорилт", "scenario": "base",
                                                                 "period_type": "month", "start_date": "2026-01-01", "end_date": "2026-12-31"})
            assert created.status_code == 201, created.text
            budget = created.json()
            assert budget["number"] == "BUD-0001" and len(budget["columns"]) == 12 and budget["status"] == "draft"
            months = [column["start"] for column in budget["columns"]]
            rows = [
                {"budget_account_id": income_id, "party_group_id": ids["party_group"], "amounts": {month: "100" for month in months}},
                {"budget_account_id": salary_id, "amounts": {month: "-30" for month in months}},
                {"budget_account_id": marketing_id, "project_id": ids["project"], "amounts": {months[0]: "-10", months[1]: "-15", months[2]: "-15"}},
            ]

            # Income +, costs − (d161 🚨2) and optimistic locking.
            wrong = [*rows[:1], {"budget_account_id": salary_id, "amounts": {months[0]: "30"}}]
            response = await client.put(f"{base}/budgets/{budget['id']}/lines", json={"version": budget["version"], "rows": wrong})
            assert response.status_code == 422 and response.json()["detail"]["code"] == "budget_sign_mismatch"
            assert response.json()["detail"]["violations"][0]["account_code"] == "5100"
            response = await client.put(f"{base}/budgets/{budget['id']}/lines", json={"version": budget["version"] + 5, "rows": rows})
            assert response.status_code == 409 and response.json()["detail"]["code"] == "budget_version_conflict"
            response = await client.put(f"{base}/budgets/{budget['id']}/lines", json={"version": budget["version"], "rows": [rows[1], rows[1]]})
            assert response.json()["detail"]["code"] == "budget_duplicate_row"
            response = await client.put(f"{base}/budgets/{budget['id']}/lines", json={"version": budget["version"], "rows": rows})
            assert response.status_code == 200, response.text
            budget = response.json()
            assert budget["totals"]["income"] == "1200.00" and budget["totals"]["expense"] == "-400.00" and budget["totals"]["profit"] == "800.00"
            assert len(budget["rows"]) == 3 and budget["rows"][0]["total"] == "1200.00"

            # Period cannot change once amounts are keyed to it.
            locked = await client.patch(f"{base}/budgets/{budget['id']}", json={"version": budget["version"], "period_type": "quarter"})
            assert locked.status_code == 409 and locked.json()["detail"]["code"] == "budget_period_locked"

            # ⑤ Actuals from the ledger (credit − debit).
            await _post_journal(sessions, ids, date(2026, 1, 20), [("1000", "300", "0"), ("4000", "0", "300")], party=True)
            await _post_journal(sessions, ids, date(2026, 5, 10), [("1000", "350", "0"), ("4000", "0", "350")], party=True)
            await _post_journal(sessions, ids, date(2026, 3, 31), [("5100", "160", "0"), ("1000", "0", "160")])
            await _post_journal(sessions, ids, date(2026, 2, 14), [("6010", "30", "0"), ("6020", "25", "0"), ("1000", "0", "55")], project=True)
            await _post_journal(sessions, ids, date(2026, 4, 1), [("6900", "7", "0"), ("1000", "0", "7")])
            await _post_journal(sessions, ids, date(2026, 9, 1), [("1000", "999", "0"), ("4000", "0", "999")])  # after as-of

            params = {"budget_id": budget["id"], "as_of": "2026-06-30"}
            analysis = (await client.get(f"{base}/analysis", params=params)).json()
            rows_by_account = {row["key"]["account"]: row for row in analysis["rows"]}
            income = rows_by_account[income_id]
            assert (income["budgeted"], income["expected"], income["actual"], income["performance_pct"], income["status"]) == ("1200.00", "600.00", "650.00", "108.3", "favorable")
            salary = rows_by_account[salary_id]
            assert (salary["expected"], salary["actual"], salary["status"]) == ("-180.00", "-160.00", "favorable")
            spend = rows_by_account[marketing_id]
            assert (spend["expected"], spend["actual"], spend["performance_pct"], spend["status"]) == ("-40.00", "-55.00", "137.5", "unfavorable")
            assert analysis["totals"]["profit"]["actual"] == "435.00" and analysis["totals"]["income"]["actual"] == "650.00"
            assert analysis["window"]["as_of"] == "2026-06-30"
            assert [row["code"] for row in analysis["unmapped"]] == ["6900"] and analysis["unmapped"][0]["actual"] == "-7.00"

            # Pivot: account × month, and per project / customer group.
            pivot = (await client.get(f"{base}/analysis", params={**params, "group_by": "account,month"})).json()
            january = next(row for row in pivot["rows"] if row["key"] == {"account": income_id, "month": "2026-01-01"})
            assert (january["budgeted"], january["actual"], january["labels"]["month"]) == ("100.00", "300.00", "2026.01")
            by_project = {row["key"]["project"]: row for row in (await client.get(f"{base}/analysis", params={**params, "group_by": "project"})).json()["rows"]}
            assert by_project[ids["project"]]["actual"] == "-55.00" and by_project[ids["project"]]["budgeted"] == "-40.00"
            by_group = {row["key"]["party_group"]: row for row in (await client.get(f"{base}/analysis", params={**params, "group_by": "party_group"})).json()["rows"]}
            assert by_group[ids["party_group"]]["actual"] == "650.00"
            filtered = (await client.get(f"{base}/analysis", params={**params, "project_id": ids["project"]})).json()
            assert [row["key"]["account"] for row in filtered["rows"]] == [marketing_id]
            assert (await client.get(f"{base}/analysis", params={**params, "group_by": "month,year"})).status_code == 422

            # Drill down to the source transactions (d161 “Drill down”).
            drill = (await client.get(f"{base}/analysis/transactions", params={**params, "budget_account_id": marketing_id})).json()
            assert drill["total_count"] == 2 and drill["total_amount"] == "-55.00"
            assert {item["account_code"] for item in drill["items"]} == {"6010", "6020"} and drill["items"][0]["project_name"] == "Маркетингийн кампанит ажил"
            january_drill = (await client.get(f"{base}/analysis/transactions", params={**params, "budget_account_id": income_id,
                                                                                         "period_start": "2026-01-01", "period_end": "2026-01-31"})).json()
            assert january_drill["total_amount"] == "300.00"
            exported = await client.get(f"{base}/analysis/export", params=params)
            assert exported.status_code == 200 and exported.content[:2] == b"PK"

            # A manager may plan (bridge) but not approve; approval locks the grid.
            current["actor"] = actors["manager"]
            assert (await client.get(f"{base}/budgets/{budget['id']}")).status_code == 200
            assert (await client.post(f"{base}/budgets/{budget['id']}/approve", json={})).status_code == 403
            current["actor"] = actors["admin"]
            approved = (await client.post(f"{base}/budgets/{budget['id']}/approve", json={"version": budget["version"]})).json()
            assert approved["status"] == "approved" and approved["approved_by"] == "Admin ажилтан"
            response = await client.put(f"{base}/budgets/{budget['id']}/lines", json={"version": approved["version"], "rows": rows})
            assert response.status_code == 409 and response.json()["detail"]["code"] == "budget_not_draft"
            primary = (await client.post(f"{base}/budgets/{budget['id']}/primary", json={"is_primary": True})).json()
            assert primary["is_primary"] is True
            default_analysis = (await client.get(f"{base}/analysis", params={"as_of": "2026-06-30"})).json()
            assert default_analysis["budget"]["id"] == budget["id"]

            # Used accounts cannot be deleted or change kind.
            assert (await client.delete(f"{base}/accounts/{marketing_id}")).json()["detail"]["code"] == "budget_account_in_use"
            assert (await client.patch(f"{base}/accounts/{marketing_id}", json={"kind": "income"})).json()["detail"]["code"] == "budget_account_kind_locked"

            # Scenario copy: next year, optimistic +10%.
            copy = await client.post(f"{base}/budgets/{budget['id']}/copy", json={"name": "2027 өөдрөг", "scenario": "optimistic", "shift_years": 1, "adjust_pct": "10"})
            assert copy.status_code == 201, copy.text
            copy = copy.json()
            assert (copy["start_date"], copy["status"], copy["copied_from_id"]) == ("2027-01-01", "draft", budget["id"])
            assert copy["totals"]["income"] == "1320.00" and copy["totals"]["expense"] == "-440.00"
            assert copy["rows"][0]["party_group_id"] == ids["party_group"]

            # Excel round trip into the copy (import replaces the draft grid).
            workbook = await client.get(f"{base}/budgets/{budget['id']}/export")
            assert workbook.status_code == 200 and workbook.content[:2] == b"PK"
            from app.budget.excel import build_budget_workbook
            content = build_budget_workbook(title="x", columns=[{"start": date(2027, 1, 1), "label": "2027.01"}], rows=[
                {"account_code": "4000", "account_name": "", "project_code": None, "party_group_code": "RETAIL", "note": "импорт",
                 "amounts": {date(2027, 1, 1): Decimal("500")}},
                {"account_code": "MKT", "account_name": "", "project_code": "MKT", "party_group_code": None, "note": None,
                 "amounts": {date(2027, 1, 1): Decimal("-20")}},
            ])
            imported = await client.post(f"{base}/budgets/{copy['id']}/import", files={"file": ("budget.xlsx", content, "application/octet-stream")})
            assert imported.status_code == 200, imported.text
            assert imported.json()["imported_rows"] == 2 and imported.json()["budget"]["totals"]["profit"] == "480.00"
            bad = build_budget_workbook(title="x", columns=[{"start": date(2027, 1, 1), "label": "2027.01"}], rows=[
                {"account_code": "NOPE", "account_name": "", "project_code": None, "party_group_code": None, "note": None, "amounts": {date(2027, 1, 1): Decimal("1")}},
            ])
            rejected = await client.post(f"{base}/budgets/{copy['id']}/import", files={"file": ("bad.xlsx", bad, "application/octet-stream")})
            assert rejected.status_code == 422 and rejected.json()["detail"]["errors"][0]["row"] == 4

            # Lifecycle: reopen clears primary; approved budgets cannot be deleted; archive / restore.
            assert (await client.delete(f"{base}/budgets/{budget['id']}")).status_code == 409
            reopened = (await client.post(f"{base}/budgets/{budget['id']}/reopen", json={})).json()
            assert reopened["status"] == "draft" and reopened["is_primary"] is False
            archived = (await client.post(f"{base}/budgets/{copy['id']}/archive", json={})).json()
            assert archived["status"] == "archived"
            listed = (await client.get(f"{base}/budgets")).json()["items"]
            assert [row["id"] for row in listed] == [budget["id"]]
            assert (await client.post(f"{base}/budgets/{copy['id']}/restore", json={})).json()["status"] == "draft"
            assert (await client.delete(f"{base}/budgets/{copy['id']}")).status_code == 204

    asyncio.run(run())
