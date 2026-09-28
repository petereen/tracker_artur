"""Advance ↔ remaining payment reconciliation against a disposable PostgreSQL database.

Runs only with PAYROLL_TEST_DATABASE_URL (see test_payroll_monthly_workflow_db).
Covers the company-side payout on the dashboard (advance = Суутгалын дүн,
final = the rest of the gross) and the advance projection of a mid-month raise.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from tests.test_payroll_monthly_workflow_db import _ok, _payroll_api, _row, pytestmark  # noqa: F401


async def _daily_allowance_on_advance(sessions, employee_id: int) -> None:
    from sqlalchemy import update

    from app.models import models as m

    async with sessions() as db:
        await db.execute(update(m.MonthlyPayrollProfile).where(m.MonthlyPayrollProfile.employee_id == employee_id).values(
            allowance_basis="FIXED", allowance_payout="ADVANCE", meal_allowance=Decimal("5000"), commute_allowance=Decimal("3000"),
        ))
        await db.commit()


def test_dashboard_advance_and_final_add_up_to_gross(monkeypatch):
    asyncio.run(_dashboard_scenario(monkeypatch))


async def _dashboard_scenario(monkeypatch):
    async with _payroll_api(monkeypatch) as (client, ids, sessions, _organization_id):
        await _daily_allowance_on_advance(sessions, ids["oyun"])
        month = await _ok(await client.post("/m/months", json={"year": 2026, "month": 8}), 201)
        advance = await _ok(await client.post(f"/m/months/{month['id']}/runs", json={"run_type": "advance", "pay_date": "2026-08-10"}), 201)
        projection = _row(await _ok(await client.get(f"/m/runs/{advance['id']}")), ids["oyun"])["result"]["projection"]
        # 40% × 1,500,000 + 21 days × 8,000 meal/commute = 768,000 cash.
        assert (projection["advance"], projection["employee_shi"], projection["pit"], projection["total_deductions"]) == ("768000", "191820", "131618", "1091438")
        await _ok(await client.post(f"/m/runs/{advance['id']}/approve"))

        dashboard = await _ok(await client.get("/m/dashboard", params={"month": "2026-08"}))
        # The advance costs the company its Суутгалын дүн, not only the cash.
        assert {key: dashboard["advance"][key] for key in ("planned", "cash", "employee_shi", "pit")} == {"planned": "1091438", "cash": "768000", "employee_shi": "191820", "pit": "131618"}
        assert dashboard["pipeline"][0]["company_total"] == "1091438" and dashboard["pipeline"][0]["total"] == "768000"

        final = await _ok(await client.post(f"/m/months/{month['id']}/runs", json={"run_type": "final", "pay_date": "2026-08-25"}), 201)
        row = await _ok(await client.put(f"/m/runs/{final['id']}/rows/{ids['oyun']}", json={"worked_normal_hours": "168", "worked_days": "21", "reason": "Сарын цаг"}))
        assert (row["result"]["gross"], row["result"]["net_pay"]) == ("1668000", "576562")
        final_run = await _ok(await client.get(f"/m/runs/{final['id']}"))
        gross = sum(Decimal(item["result"].get("gross", "0")) for item in final_run["rows"])

        dashboard = await _ok(await client.get("/m/dashboard", params={"month": "2026-08"}))
        # Advance + remaining payment = олговол зохих: НДШ/ХХОАТ already went out with the advance.
        assert Decimal(dashboard["advance"]["planned"]) + Decimal(dashboard["final"]["company_total"]) == gross
        assert dashboard["alerts"]["withholding_changed"] == 0
        upcoming = {item["run_type"]: item["amount"] for item in dashboard["upcoming"]}
        assert upcoming["final"] == dashboard["final"]["company_total"]

        # Fewer hours in the final: НДШ/ХХОАТ drop, the final settles the difference and it is flagged.
        await _ok(await client.put(f"/m/runs/{final['id']}/rows/{ids['oyun']}", json={"worked_normal_hours": "160", "worked_days": "20", "reason": "Нэг өдөр тасалсан"}))
        final_run = await _ok(await client.get(f"/m/runs/{final['id']}"))
        gross = sum(Decimal(item["result"].get("gross", "0")) for item in final_run["rows"])
        dashboard = await _ok(await client.get("/m/dashboard", params={"month": "2026-08"}))
        assert Decimal(dashboard["advance"]["planned"]) + Decimal(dashboard["final"]["company_total"]) == gross
        assert dashboard["alerts"]["withholding_changed"] == 1


def test_advance_projection_prices_a_mid_month_raise_like_the_final(monkeypatch):
    asyncio.run(_raise_scenario(monkeypatch))


async def _raise_scenario(monkeypatch):
    async with _payroll_api(monkeypatch) as (client, ids, sessions, organization_id):
        from sqlalchemy import select

        from app.models import models as m

        await _daily_allowance_on_advance(sessions, ids["oyun"])
        async with sessions() as db:
            profile = await db.scalar(select(m.MonthlyPayrollProfile).where(m.MonthlyPayrollProfile.employee_id == ids["oyun"]))
            history = await db.scalar(select(m.MonthlyPayrollSalaryHistory).where(m.MonthlyPayrollSalaryHistory.profile_id == profile.id))
            history.valid_to = date(2026, 8, 16)
            db.add(m.MonthlyPayrollSalaryHistory(profile_id=profile.id, monthly_salary=Decimal("2000000"), valid_from=date(2026, 8, 17)))
            # A full month of confirmed 8-hour weekdays.
            zone = timezone(timedelta(hours=8))
            for day in range(1, 32):
                worked = date(2026, 8, day)
                if worked.weekday() < 5:
                    db.add(m.AttendanceLog(organization_id=organization_id, employee_id=ids["oyun"], attendance_date=worked, status="present", worked_minutes=480, confirmed_at=datetime(2026, 8, day, 18, tzinfo=zone)))
            await db.commit()
        month = await _ok(await client.post("/m/months", json={"year": 2026, "month": 8}), 201)
        advance = await _ok(await client.post(f"/m/months/{month['id']}/runs", json={"run_type": "advance", "pay_date": "2026-08-10"}), 201)
        projection = _row(await _ok(await client.get(f"/m/runs/{advance['id']}")), ids["oyun"])["result"]["projection"]
        await _ok(await client.post(f"/m/runs/{advance['id']}/approve"))
        final = await _ok(await client.post(f"/m/months/{month['id']}/runs", json={"run_type": "final", "pay_date": "2026-08-25"}), 201)
        result = _row(await _ok(await client.get(f"/m/runs/{final['id']}")), ids["oyun"])["result"]
        # 1,500,000 × 80/168 + 2,000,000 × 88/168: hours after the cut-off earn the new salary.
        assert result["base_pay"] == "1761905"
        for key in ("base_pay", "gross", "employee_shi", "pit", "total_deductions", "net_pay"):
            assert projection[key] == result[key], key
