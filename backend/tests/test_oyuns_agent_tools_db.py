"""OYUNS company-data tools against PostgreSQL: scoping and ID-free output.

Runs only when SHARE_TEST_DATABASE_URL points at a throwaway database
(for example ``postgresql+asyncpg://tracker@127.0.0.1:55432/share_test``).
"""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone

import pytest

DATABASE_URL = os.environ.get("SHARE_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="SHARE_TEST_DATABASE_URL is not set")

if DATABASE_URL:
    os.environ.setdefault("DATABASE_URL", DATABASE_URL)
    os.environ.setdefault("SYNC_DATABASE_URL", DATABASE_URL.replace("+asyncpg", "+psycopg2"))
    os.environ.setdefault("SECRET_KEY", "agent-tools-test-secret-key-0123456789")


def _tables():
    from app.models import contracts as c
    from app.models import models as m

    seeds = [
        m.Organization, m.UserAccount, m.Employee, m.RoleAssignment, m.Department, m.EmployeeDetails,
        m.Task, m.TaskAssignee, m.TaskReviewer, m.Project, m.PlanIdea, m.TimeOff, m.LeaveBalance,
        m.WorkReport, m.WorkReportRevision, m.WorkTimeEntry, m.Team, m.TeamMember,
        c.ContractDocument, c.ContractRevision, c.ContractReview,
        m.MonthlyPayrollRuleSet, m.MonthlyPayrollMonth, m.MonthlyPayrollRun, m.MonthlyPayrollRunRow,
        m.AssistantToolAudit, m.AttendanceLog, m.HolidayRecord, m.ERPModuleConfig,
        m.ERPCapability, m.ERPAccessRole, m.ERPAccountRole, m.ERPTeamRole, m.Schedule,
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
async def _world():
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.enterprise_deps import build_actor_context
    from app.models import contracts as c
    from app.models import models as m

    engine = create_async_engine(DATABASE_URL)
    tables = _tables()
    async with engine.begin() as connection:
        await connection.execute(text("DROP TABLE IF EXISTS " + ", ".join(f'"{table.name}"' for table in tables) + " CASCADE"))
        await connection.run_sync(lambda sync: m.Base.metadata.create_all(sync, tables=tables))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(timezone.utc)
    today = now.date()
    async with sessions() as db:
        org = m.Organization(name="Оюунс", timezone="UTC")
        db.add(org)
        await db.flush()
        boss = m.Employee(organization_id=org.id, name="Болд Админ", timezone="UTC")
        worker = m.Employee(organization_id=org.id, name="Сараа Ажилтан", timezone="UTC")
        db.add_all([boss, worker])
        await db.flush()
        admin_account = m.UserAccount(organization_id=org.id, employee_id=boss.id, email="admin@example.test", password_hash="x")
        member_account = m.UserAccount(organization_id=org.id, employee_id=worker.id, email="member@example.test", password_hash="x")
        db.add_all([admin_account, member_account])
        await db.flush()
        for employee, body in ((boss, "Стратеги боловсруулсан"), (worker, "Борлуулалтын уулзалт хийсэн")):
            report = m.WorkReport(employee_id=employee.id, report_type="daily", period_date=today, status="submitted", title="Өдрийн тайлан")
            db.add(report)
            await db.flush()
            db.add(m.WorkReportRevision(report_id=report.id, text=body, status="draft"))
        worker_report = m.WorkReport(employee_id=worker.id, report_type="daily", period_date=today - timedelta(days=1), status="awaiting", title="Өдрийн тайлан")
        db.add(worker_report)
        await db.flush()
        db.add_all([
            m.WorkTimeEntry(report_id=worker_report.id, employee_id=worker.id, local_work_date=today, timezone="UTC", entry_type="work", mode="remote", started_at=now - timedelta(hours=2)),
            m.WorkTimeEntry(report_id=worker_report.id, employee_id=boss.id, local_work_date=today, timezone="UTC", entry_type="work", mode="in_person", started_at=now - timedelta(hours=5), ended_at=now - timedelta(hours=1)),
        ])
        db.add(c.ContractDocument(organization_id=org.id, author_account_id=admin_account.id, author_employee_id=boss.id, title="Түрээсийн гэрээ", document_type="contract", status="APPROVED", effective_end_on=today + timedelta(days=20)))
        db.add_all([
            m.PlanIdea(organization_id=org.id, submitted_by_account_id=admin_account.id, submitted_by_employee_id=boss.id, plan_month=today.replace(day=1), title="Шинэ бүтээгдэхүүн"),
            m.PlanIdea(organization_id=org.id, submitted_by_account_id=member_account.id, submitted_by_employee_id=worker.id, plan_month=today.replace(day=1), title="Сургалт"),
        ])
        db.add_all([
            m.TimeOff(organization_id=org.id, employee_id=boss.id, time_off_type="annual", starts_on=today, ends_on=today, status="approved"),
            m.TimeOff(organization_id=org.id, employee_id=worker.id, time_off_type="sick", starts_on=today, ends_on=today, status="pending"),
        ])
        rules = m.MonthlyPayrollRuleSet(organization_id=org.id, valid_from=date(2020, 1, 1), minimum_wage=660000, employee_rates={}, employer_rates={}, pit_brackets=[], relief_tiers=[], overtime_multipliers={})
        db.add(rules)
        await db.flush()
        month = m.MonthlyPayrollMonth(organization_id=org.id, year=today.year, month=today.month, rule_set_id=rules.id)
        db.add(month)
        await db.flush()
        run = m.MonthlyPayrollRun(organization_id=org.id, month_id=month.id, run_type="final", pay_date=today, status="approved")
        db.add(run)
        await db.flush()
        db.add_all([
            m.MonthlyPayrollRunRow(organization_id=org.id, run_id=run.id, employee_id=boss.id, result={"gross": "3000000", "pit": "270000", "total_deductions": "600000", "net_pay": "2400000"}),
            m.MonthlyPayrollRunRow(organization_id=org.id, run_id=run.id, employee_id=worker.id, result={"gross": "2000000", "pit": "180000", "total_deductions": "400000", "net_pay": "1600000"}),
        ])
        await db.commit()
        actors = {
            "admin": build_actor_context(account_id=admin_account.id, organization_id=org.id, employee_id=boss.id, email="admin@example.test", locale="mn", roles=frozenset({"admin"})),
            "member": build_actor_context(account_id=member_account.id, organization_id=org.id, employee_id=worker.id, email="member@example.test", locale="mn", roles=frozenset({"member"})),
            "hr": build_actor_context(account_id=member_account.id, organization_id=org.id, employee_id=worker.id, email="member@example.test", locale="mn", roles=frozenset({"hr"})),
        }
    try:
        yield sessions, actors
    finally:
        await engine.dispose()


async def _call(sessions, actor, tool: str, arguments: dict) -> dict:
    from app.services.mcp import adapters

    async with sessions() as db:
        result = await adapters.execute(db, actor, tool_name=tool, arguments=arguments, channel="web", request_id="test")
        await db.commit()
    return result


def _assert_no_ids(value, path="data"):
    if isinstance(value, dict):
        for key, item in value.items():
            assert key != "id" and not key.endswith("_id") and not key.endswith("_ids"), f"{path}.{key} leaks an ID"
            _assert_no_ids(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_no_ids(item, f"{path}[{index}]")


def _names(result: dict, key: str = "employee") -> set[str]:
    return {item.get(key) for item in result["data"].get("items", [])}


def test_reports_are_scoped_and_include_text():
    async def scenario():
        async with _world() as (sessions, actors):
            member = await _call(sessions, actors["member"], "oyuns_reports_search", {"report_types": ["daily"]})
            assert _names(member) == {"Сараа Ажилтан"}
            assert any("Борлуулалтын уулзалт" in (item.get("text") or "") for item in member["data"]["items"])
            admin = await _call(sessions, actors["admin"], "oyuns_reports_search", {"report_types": ["daily"], "status": "submitted"})
            assert _names(admin) == {"Болд Админ", "Сараа Ажилтан"}
            missing = await _call(sessions, actors["admin"], "oyuns_reports_search", {"report_types": ["daily"], "status": "missing"})
            assert missing["data"]["total"] == 1
            _assert_no_ids(admin["data"])
    asyncio.run(scenario())


def test_worktime_status_and_team_scope():
    async def scenario():
        async with _world() as (sessions, actors):
            own = await _call(sessions, actors["member"], "oyuns_worktime_get", {"view": "status_now", "scope": "self"})
            assert own["data"]["items"][0]["state"] == "working" and own["data"]["items"][0]["mode"] == "remote"
            member_team = await _call(sessions, actors["member"], "oyuns_worktime_get", {"view": "totals", "scope": "team"})
            assert _names(member_team) <= {"Сараа Ажилтан"}
            admin_team = await _call(sessions, actors["admin"], "oyuns_worktime_get", {"view": "status_now", "scope": "team"})
            assert _names(admin_team) == {"Сараа Ажилтан"}
            assert admin_team["data"]["not_clocked_in"] == ["Болд Админ"]
            totals = await _call(sessions, actors["admin"], "oyuns_worktime_get", {"view": "totals", "scope": "team"})
            boss = next(item for item in totals["data"]["items"] if item["employee"] == "Болд Админ")
            assert boss["worked_hours"] == 4.0
            _assert_no_ids(totals["data"])
    asyncio.run(scenario())


def test_contracts_follow_author_reviewer_rule():
    async def scenario():
        async with _world() as (sessions, actors):
            assert (await _call(sessions, actors["member"], "oyuns_contracts_search", {}))["status"] == "empty"
            admin = await _call(sessions, actors["admin"], "oyuns_contracts_search", {"expiring_within_days": 30})
            assert admin["data"]["items"][0]["title"] == "Түрээсийн гэрээ"
            assert admin["data"]["items"][0]["days_until_end"] == 20
    asyncio.run(scenario())


def test_plan_ideas_and_leave_are_scoped():
    async def scenario():
        async with _world() as (sessions, actors):
            ideas = await _call(sessions, actors["member"], "oyuns_projects_search", {"entity": "ideas"})
            assert {item["title"] for item in ideas["data"]["items"]} == {"Сургалт"}
            leave = await _call(sessions, actors["member"], "oyuns_hr_get", {"resource": "leave_requests"})
            assert {item["employee_name"] for item in leave["data"]["items"]} == {"Сараа Ажилтан"}
            all_leave = await _call(sessions, actors["hr"], "oyuns_hr_get", {"resource": "leave_requests"})
            assert {item["employee_name"] for item in all_leave["data"]["items"]} == {"Болд Админ", "Сараа Ажилтан"}
            _assert_no_ids(all_leave["data"])
    asyncio.run(scenario())


def test_payroll_totals_require_capability():
    async def scenario():
        async with _world() as (sessions, actors):
            totals = await _call(sessions, actors["admin"], "oyuns_payroll_summary", {"view": "totals"})
            assert totals["data"]["totals"]["net_pay"] == "4000000"
            assert totals["data"]["employee_count"] == 2
            people = await _call(sessions, actors["admin"], "oyuns_payroll_summary", {"view": "per_employee"})
            assert {item["employee"] for item in people["data"]["items"]} == {"Болд Админ", "Сараа Ажилтан"}
            _assert_no_ids(people["data"])
            # HR without an ERP payroll capability is denied by the page's own rule.
            assert (await _call(sessions, actors["hr"], "oyuns_payroll_summary", {"view": "totals"}))["status"] == "denied"
    asyncio.run(scenario())


def test_crm_reports_disabled_module():
    async def scenario():
        async with _world() as (sessions, actors):
            result = await _call(sessions, actors["admin"], "oyuns_crm_search", {"resource": "summary"})
            assert result["status"] == "empty"
            assert "not enabled" in json.dumps(result["data"])
    asyncio.run(scenario())


def test_read_tool_audit_rows_are_written():
    async def scenario():
        from sqlalchemy import func, select

        from app.models import models as m

        async with _world() as (sessions, actors):
            await _call(sessions, actors["admin"], "oyuns_contracts_search", {})
            async with sessions() as db:
                assert await db.scalar(select(func.count()).select_from(m.AssistantToolAudit).where(m.AssistantToolAudit.tool_name == "oyuns_contracts_search")) == 1
    asyncio.run(scenario())


def test_other_hr_resources_answer_without_errors():
    async def scenario():
        async with _world() as (sessions, actors):
            for resource in ("departments", "leave_balances", "attendance"):
                result = await _call(sessions, actors["hr"], "oyuns_hr_get", {"resource": resource})
                assert result["status"] in {"ok", "empty"}, (resource, result)
                _assert_no_ids(result["data"])
            own = await _call(sessions, actors["member"], "oyuns_hr_get", {"resource": "leave_balances"})
            assert own["status"] in {"ok", "empty"}
            worktime_daily = await _call(sessions, actors["admin"], "oyuns_worktime_get", {"view": "daily", "scope": "team"})
            assert worktime_daily["status"] == "ok"
    asyncio.run(scenario())


def test_context_builder_reads_identity_snapshot_and_available_data(monkeypatch):
    async def scenario():
        from app.services.ai_gateway.gateway import AIGateway, GatewayResponse, PreflightGrounding
        from app.services.file_search_service import KnowledgeSearchResult

        async with _world() as (sessions, actors):
            gateway = AIGateway()
            captured = {}

            async def preflight(*_args):
                return PreflightGrounding(KnowledgeSearchResult("empty", ()))

            async def respond(_db, request):
                captured["context"] = request.grounding_context
                captured["runtime"] = request.runtime
                return GatewayResponse(answer="ok", sources=[], route="test", model="test", cache="bypass", web_search_used=False, usage={})

            monkeypatch.setattr(gateway, "_preflight_grounding", preflight)
            monkeypatch.setattr(gateway, "respond", respond)
            async with sessions() as db:
                await gateway.execute_turn(db, actors["member"], [{"role": "user", "content": "миний ажил"}], input_mode="voice", memory=[{"tool": "oyuns_tasks_search", "items": []}])
            context = captured["context"]
            assert context["company"] == {"name": "Оюунс"}
            assert context["current_employee"]["name"] == "Сараа Ажилтан"
            assert context["my_snapshot"]["my_open_tasks"] == 0
            assert context["my_snapshot"]["my_worktime_now"] == "working_remote"
            assert context["input_mode"] == "voice_transcript"
            assert context["PREVIOUS_RESULTS"] == [{"tool": "oyuns_tasks_search", "items": []}]
            assert "work reports (daily/monthly/plans)" in context["AVAILABLE_DATA"]
            assert "monthly payroll summaries" not in context["AVAILABLE_DATA"]
            assert captured["runtime"].primary_model
    asyncio.run(scenario())
