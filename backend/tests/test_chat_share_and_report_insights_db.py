"""Chat slash-menu sharing and management report exports against PostgreSQL.

Runs only when SHARE_TEST_DATABASE_URL points at a throwaway database
(for example ``postgresql+asyncpg://tracker@127.0.0.1:55432/share_test``).
"""

from __future__ import annotations

import asyncio
import io
import os
import uuid
import zipfile
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone

import pytest

DATABASE_URL = os.environ.get("SHARE_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="SHARE_TEST_DATABASE_URL is not set")

if DATABASE_URL:
    os.environ.setdefault("DATABASE_URL", DATABASE_URL)
    os.environ.setdefault("SYNC_DATABASE_URL", DATABASE_URL.replace("+asyncpg", "+psycopg2"))
    os.environ.setdefault("SECRET_KEY", "share-insights-test-secret-key-0123456789")


def _tables():
    from app.models import contracts as c
    from app.models import models as m

    seeds = [
        m.Organization, m.UserAccount, m.Employee, m.RoleAssignment, m.Department, m.EmployeeDetails,
        m.Task, m.TaskAssignee, m.TaskReviewer, m.Project, m.CompanyPlanItem, m.PlanIdea,
        m.WorkReport, m.WorkReportRevision, m.WorkTimeEntry,
        c.ContractDocument, c.ContractRevision, c.ContractReview,
        m.ChatConversation, m.ChatParticipant, m.ChatMessage, m.ChatMessageReceipt, m.ChatAttachment, m.ChatCall,
        m.ChatMessageReaction, m.ChatMessageStar, m.ChatMessagePin, m.ChatMessageHidden, m.WorkspacePresence,
        m.JobQueue, m.DomainEvent, m.AuditLog,
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
    from app.models import contracts as c
    from app.models import models as m
    from app.routers import chat, report_insights

    engine = create_async_engine(DATABASE_URL)
    tables = _tables()
    async with engine.begin() as connection:
        await connection.execute(text("DROP TABLE IF EXISTS " + ", ".join(f'"{table.name}"' for table in tables) + " CASCADE"))
        await connection.run_sync(lambda sync: m.Base.metadata.create_all(sync, tables=tables))
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    now = datetime.now(timezone.utc)
    async with sessions() as db:
        org = m.Organization(name="Оюунс")
        db.add(org)
        await db.flush()
        sales = m.Department(organization_id=org.id, code="SAL", name="Борлуулалт")
        finance = m.Department(organization_id=org.id, code="FIN", name="Санхүү")
        db.add_all([sales, finance])
        await db.flush()

        actors: dict[str, ActorContext] = {}
        ids: dict[str, int] = {}

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
            actors[key] = ActorContext(account_id=account.id, organization_id=org.id, employee_id=employee.id, email=account.email, locale="mn", roles=frozenset({role}))
            ids[key] = employee.id
            ids[f"{key}_account"] = account.id

        await person("bold", "Болд Менежер", "manager", None)
        await person("saraa", "Сараа", "member", sales)
        await person("dorj", "Дорж", "member", finance)

        t1 = m.Task(organization_id=org.id, title="Борлуулалтын тайлан бэлтгэх", description="Q3 орлогын задаргаа", assignee_id=ids["saraa"], created_by_id=ids["bold"], workflow_status="in_progress", priority=1, deadline_at=now + timedelta(days=2))
        t2 = m.Task(organization_id=org.id, title="Санхүүгийн хяналт", assignee_id=ids["dorj"], workflow_status="to_do")
        t3 = m.Task(organization_id=org.id, title="Дууссан ажил", assignee_id=ids["saraa"], workflow_status="done", completed_at=now)
        db.add_all([t1, t2, t3])
        plan = m.CompanyPlanItem(organization_id=org.id, plan_month=date(2026, 9, 1), title="Шинэ зах зээл нээх", content="Дархан, Эрдэнэт", horizon="mid_term")
        idea_saraa = m.PlanIdea(organization_id=org.id, submitted_by_account_id=ids["saraa_account"], submitted_by_employee_id=ids["saraa"], plan_month=date(2026, 9, 1), title="CRM нэвтрүүлэх")
        idea_dorj = m.PlanIdea(organization_id=org.id, submitted_by_account_id=ids["dorj_account"], submitted_by_employee_id=ids["dorj"], plan_month=date(2026, 9, 1), title="Зардал бууруулах")
        db.add_all([plan, idea_saraa, idea_dorj])
        contract_saraa = c.ContractDocument(organization_id=org.id, author_account_id=ids["saraa_account"], author_employee_id=ids["saraa"], title="Нийлүүлэлтийн гэрээ", document_type="contract", status="DRAFT")
        contract_dorj = c.ContractDocument(organization_id=org.id, author_account_id=ids["dorj_account"], author_employee_id=ids["dorj"], title="Түрээсийн гэрээ", document_type="agreement", status="DRAFT")
        db.add_all([contract_saraa, contract_dorj])
        await db.flush()

        async def report(employee_key: str, report_type: str, period: date, status: str, body: str):
            row = m.WorkReport(employee_id=ids[employee_key], report_type=report_type, period_date=period, status=status, title=f"{report_type} {period}")
            db.add(row)
            await db.flush()
            revision = m.WorkReportRevision(report_id=row.id, text=body, status="approved" if status == "approved" else "draft")
            db.add(revision)
            await db.flush()
            if status == "approved":
                row.approved_revision_id = revision.id
            return row.id

        ids["r_daily"] = await report("saraa", "daily", date(2026, 9, 10), "submitted", "Өнөөдөр 3 гэрээ хаасан, орлого 12 сая₮.")
        ids["r_monthly_saraa"] = await report("saraa", "monthly", date(2026, 9, 1), "approved", "9-р сард борлуулалт 45 сая₮, зардал 30 сая₮.")
        ids["r_monthly_dorj"] = await report("dorj", "monthly", date(2026, 9, 1), "submitted", "Санхүүгийн хаалт хийгдлээ.")
        ids["r_plan"] = await report("saraa", "next_month_plan", date(2026, 10, 1), "approved", "10-р сард 60 сая₮ зорилт.")
        ids["r_old"] = await report("dorj", "monthly", date(2026, 6, 1), "approved", "Хуучин тайлан.")
        db.add(m.WorkTimeEntry(report_id=ids["r_daily"], employee_id=ids["saraa"], started_at=now - timedelta(hours=8), ended_at=now, local_work_date=date(2026, 9, 10), entry_type="work"))

        conversations: dict[str, str] = {}
        for key, (a, b) in {"saraa_dorj": ("saraa", "dorj"), "saraa_bold": ("saraa", "bold")}.items():
            left, right = ids[f"{a}_account"], ids[f"{b}_account"]
            conversation = m.ChatConversation(organization_id=org.id, kind="direct", direct_key=":".join(str(v) for v in sorted((left, right))), created_by_account_id=left)
            db.add(conversation)
            await db.flush()
            db.add_all([m.ChatParticipant(conversation_id=conversation.id, account_id=left), m.ChatParticipant(conversation_id=conversation.id, account_id=right)])
            conversations[key] = str(conversation.public_id)
        ids.update({"t1": t1.id, "t2": t2.id, "t3": t3.id, "plan": plan.id, "idea_saraa": idea_saraa.id, "idea_dorj": idea_dorj.id, "sales": sales.id, "finance": finance.id})
        refs = {"contract_saraa": str(contract_saraa.public_id), "contract_dorj": str(contract_dorj.public_id)}
        await db.commit()

    current = {"actor": actors["saraa"]}

    async def test_db():
        async with sessions() as session:
            yield session

    app = FastAPI()
    app.include_router(chat.router, prefix="/v1/chat")
    app.include_router(report_insights.router, prefix="/v1/report-insights")
    app.dependency_overrides[get_db] = test_db
    app.dependency_overrides[get_actor] = lambda: current["actor"]

    def as_(key: str):
        current["actor"] = actors[key]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, as_, ids, refs, conversations
    await engine.dispose()


def _refs(payload: dict, group: str) -> set[str]:
    return {item["ref"] for block in payload["groups"] if block["key"] == group for item in block["items"]}


async def _ok(response, status: int = 200):
    assert response.status_code == status, response.text
    return response.json()


def test_share_menu_is_role_scoped_and_live_searchable():
    async def run():
        async with _api() as (client, as_, ids, refs, _):
            as_("saraa")
            mine = await _ok(await client.get("/v1/chat/share-items"))
            assert [block["key"] for block in mine["groups"]] == ["tasks", "plans", "contracts", "reports"]
            assert _refs(mine, "tasks") == {str(ids["t1"])}  # own active task only; done task excluded
            assert {str(ids["plan"]), str(ids["idea_saraa"]), str(ids["r_plan"])} <= _refs(mine, "plans")
            assert str(ids["idea_dorj"]) not in _refs(mine, "plans")
            assert _refs(mine, "contracts") == {refs["contract_saraa"]}
            assert _refs(mine, "reports") == {str(ids["r_daily"]), str(ids["r_monthly_saraa"])}

            searched = await _ok(await client.get("/v1/chat/share-items", params={"q": "борлуул"}))
            assert _refs(searched, "tasks") == {str(ids["t1"])}
            assert not _refs(searched, "contracts")

            as_("bold")
            manager = await _ok(await client.get("/v1/chat/share-items"))
            assert _refs(manager, "tasks") == {str(ids["t1"]), str(ids["t2"])}
            assert {str(ids["r_monthly_dorj"]), str(ids["r_monthly_saraa"])} <= _refs(manager, "reports")
            assert str(ids["idea_dorj"]) in _refs(manager, "plans")
            # Contracts stay author/reviewer scoped for non-admin managers.
            assert not _refs(manager, "contracts")

    asyncio.run(run())


def test_shared_card_link_is_reauthorized_for_each_reader():
    async def run():
        async with _api() as (client, as_, ids, refs, conversations):
            as_("saraa")
            nonce = str(uuid.uuid4())
            sent = await _ok(await client.post(f"/v1/chat/conversations/{conversations['saraa_dorj']}/share", json={"kind": "task", "ref": str(ids["t1"]), "client_nonce": nonce}))
            card = sent["action"]["payload"]
            assert sent["action"]["type"] == "shared_item"
            assert card["title"] == "Борлуулалтын тайлан бэлтгэх"
            assert card["can_open"] is True and card["target_url"] == f"/tasks?task={ids['t1']}"
            assert {field["label"] for field in card["fields"]} >= {"Хариуцагч", "Дуусах хугацаа", "Эрэмбэ"}
            assert sent["body"].startswith("✅ Даалгавар: Борлуулалтын тайлан бэлтгэх")
            assert sent["capabilities"]["can_edit"] is False
            again = await _ok(await client.post(f"/v1/chat/conversations/{conversations['saraa_dorj']}/share", json={"kind": "task", "ref": str(ids["t1"]), "client_nonce": nonce}))
            assert again["id"] == sent["id"]

            as_("dorj")
            items = (await _ok(await client.get(f"/v1/chat/conversations/{conversations['saraa_dorj']}/messages")))["items"]
            received = items[-1]["action"]["payload"]
            assert received["title"] == "Борлуулалтын тайлан бэлтгэх"
            assert received["can_open"] is False and "target_url" not in received

            as_("saraa")
            await _ok(await client.post(f"/v1/chat/conversations/{conversations['saraa_bold']}/share", json={"kind": "contract", "ref": refs["contract_saraa"], "client_nonce": str(uuid.uuid4())}))
            await _ok(await client.post(f"/v1/chat/conversations/{conversations['saraa_bold']}/share", json={"kind": "report", "ref": str(ids["r_monthly_saraa"]), "client_nonce": str(uuid.uuid4())}))
            as_("bold")
            items = (await _ok(await client.get(f"/v1/chat/conversations/{conversations['saraa_bold']}/messages")))["items"]
            by_kind = {item["action"]["payload"]["kind"]: item["action"]["payload"] for item in items}
            assert by_kind["report"]["can_open"] is True and by_kind["report"]["target_url"] == f"/reports?report={ids['r_monthly_saraa']}"
            assert "45 сая" in by_kind["report"]["excerpt"]
            # A manager who is not author/reviewer cannot open the contract page.
            assert by_kind["contract"]["can_open"] is False

            as_("saraa")
            denied = await client.post(f"/v1/chat/conversations/{conversations['saraa_dorj']}/share", json={"kind": "task", "ref": str(ids["t2"]), "client_nonce": str(uuid.uuid4())})
            assert denied.status_code == 404
            bad_kind = await client.post(f"/v1/chat/conversations/{conversations['saraa_dorj']}/share", json={"kind": "payroll", "ref": "1", "client_nonce": str(uuid.uuid4())})
            assert bad_kind.status_code == 422

    asyncio.run(run())


def test_report_export_is_management_only_and_organised_by_choice():
    async def run():
        async with _api() as (client, as_, ids, _, _conversations):
            period = {"date_from": "2026-09-05", "date_to": "2026-10-31"}
            as_("saraa")
            assert (await client.get("/v1/report-insights/export", params=period)).status_code == 403
            assert (await client.post("/v1/report-insights/summary", json=period)).status_code == 403

            as_("bold")
            preview = await _ok(await client.get("/v1/report-insights/export/preview", params={**period, "group_by": "department"}))
            # Monthly reports dated on the 1st still count for a period starting mid-month; June is excluded.
            assert preview["report_count"] == 4 and preview["format"] == "zip"
            assert {row["name"]: row["count"] for row in preview["groups"]} == {"Борлуулалт": 3, "Санхүү": 1}

            response = await client.get("/v1/report-insights/export", params={**period, "group_by": "department"})
            assert response.status_code == 200, response.text
            assert response.headers["content-type"] == "application/zip"
            assert response.headers["x-report-count"] == "4"
            names = zipfile.ZipFile(io.BytesIO(response.content)).namelist()
            root = "reports_2026-09-05_2026-10-31"
            assert f"{root}/manifest.csv" in names
            assert f"{root}/Борлуулалт/Сараа/2026-09-10_daily_{ids['r_daily']}.md" in names
            assert f"{root}/Санхүү/Дорж/2026-09_monthly_{ids['r_monthly_dorj']}.md" in names

            by_worker = zipfile.ZipFile(io.BytesIO((await client.get("/v1/report-insights/export", params={**period, "group_by": "worker"})).content)).namelist()
            assert f"{root}/Сараа/2026-10_next_month_plan_{ids['r_plan']}.md" in by_worker

            single = await client.get("/v1/report-insights/export", params={**period, "employee_ids": [ids["dorj"]]})
            assert single.status_code == 200 and single.headers["content-type"].startswith("text/markdown")
            assert "Санхүүгийн хаалт хийгдлээ." in single.content.decode()
            assert "filename*=UTF-8''" in single.headers["content-disposition"]

            empty = await client.get("/v1/report-insights/export", params={"date_from": "2025-01-01", "date_to": "2025-01-31"})
            assert empty.status_code == 404
            backwards = await client.get("/v1/report-insights/export", params={"date_from": "2026-09-30", "date_to": "2026-09-01"})
            assert backwards.status_code == 422

    asyncio.run(run())


def test_summary_grounds_model_in_scope_and_falls_back(monkeypatch):
    from app.services import report_insights_service as insights
    from app.services.ai_gateway import GatewayError

    captured: dict = {}

    async def fake_generate(**kwargs):
        captured.update(kwargs)
        return "## ROI\nӨгөгдөлд үндэслэсэн хариу."

    async def failing_generate(**kwargs):
        raise GatewayError("down", kind="network", retryable=True)

    async def run():
        async with _api() as (client, as_, ids, _, _conversations):
            as_("bold")
            monkeypatch.setattr(insights._gateway, "generate_text", fake_generate)
            result = await _ok(await client.post("/v1/report-insights/summary", json={
                "date_from": "2026-09-01", "date_to": "2026-09-30", "scope": "department", "department_id": ids["sales"],
                "prompt": "ROI болон зардлын талаар юу анхаарах вэ?",
                "history": [{"role": "user", "content": "Өмнөх асуулт"}, {"role": "assistant", "content": "Өмнөх хариу"}],
            }))
            assert result["degraded"] is False and result["answer"].startswith("## ROI")
            assert result["scope_label"] == "Хэлтэс: Борлуулалт" and result["report_count"] == 2
            data_block = captured["input_items"][0]["content"]
            assert "45 сая₮" in data_block and "Санхүүгийн хаалт" not in data_block  # other department excluded
            assert "| Сараа | Борлуулалт |" in data_block
            assert [item["role"] for item in captured["input_items"]] == ["user", "user", "assistant", "user"]
            assert captured["input_items"][-1]["content"] == "ROI болон зардлын талаар юу анхаарах вэ?"

            monkeypatch.setattr(insights._gateway, "generate_text", failing_generate)
            fallback = await _ok(await client.post("/v1/report-insights/summary", json={"date_from": "2026-09-01", "date_to": "2026-09-30", "scope": "employee", "employee_id": ids["dorj"]}))
            assert fallback["degraded"] is True
            assert "## KPI" in fallback["answer"] and "Дорж" in fallback["answer"]

            missing = await client.post("/v1/report-insights/summary", json={"date_from": "2026-09-01", "date_to": "2026-09-30", "scope": "department", "department_id": 99999})
            assert missing.status_code == 404

    asyncio.run(run())
