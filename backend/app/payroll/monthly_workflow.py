"""Organization-scoped API for the run-based monthly payroll design."""

from __future__ import annotations

import calendar
import base64
import io
import json
import statistics
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.enterprise_deps import ActorContext, get_actor
from app.erp.service import require_capability
from app.models.models import (
    AttendanceLog, Department, Employee, EmployeeBankAccount, EmployeeDetails, HolidayRecord, MonthlyPayrollArchive, MonthlyPayrollCalendarDay, MonthlyPayrollCompanySettings,
    MonthlyPayrollMonth, MonthlyPayrollProfile, MonthlyPayrollRowAudit,
    MonthlyPayrollRuleSet, MonthlyPayrollRun, MonthlyPayrollRunRow, ERPAccount,
    MonthlyPayrollSalaryHistory, Schedule, TimeOff, WorkTimeEntry,
)
from app.services.enterprise_events import record_change
from app.services.secret_box import decrypt_secret, encrypt_secret
from .inputs import payment_days
from .monthly_engine import (
    AdvanceBasis, CalendarDayType, PayrollProfile, PayrollRunType, PayrollRules, apply_computed_overrides,
    SalarySegment, amount, calculate_monthly_run, classify_work_hours, default_2026_rules, month_calendar,
)


router = APIRouter()
BLOCKING_ROW_WARNINGS = {"negative_final_pay", "profile_missing", "salary_history_missing_or_incomplete", "row_flagged", "advance_changed", "advance_not_calculated"}


class MonthInput(BaseModel):
    year: int = Field(ge=2000, le=2100)
    month: int = Field(ge=1, le=12)


class RunInput(BaseModel):
    run_type: Literal["advance", "final"]
    pay_date: date
    cutoff_date: date | None = None
    department_id: int | None = None
    employee_ids: list[int] | None = Field(default=None, min_length=1, max_length=500)
    note: str | None = Field(default=None, max_length=2000)


class RowInput(BaseModel):
    worked_normal_hours: Decimal | None = Field(default=None, ge=0)
    worked_to_date_hours: Decimal = Field(default=Decimal("0"), ge=0)
    elapsed_planned_days: int = Field(default=0, ge=0)
    overtime_hours: dict[str, Decimal] = Field(default_factory=dict)
    leave_pay: Decimal = Field(default=Decimal("0"), ge=0)
    bonus: Decimal = Field(default=Decimal("0"), ge=0)
    other_deductions: list[dict[str, Any]] = Field(default_factory=list)
    fixed_advance: Decimal | None = Field(default=None, gt=0)
    advance_percent: Decimal | None = Field(default=None, gt=0, le=100)
    advance_basis: Literal["FIXED", "PERCENT", "WORKED-TO-DATE"] | None = None
    reason: str | None = Field(default=None, max_length=1000)


class UnlockInput(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


class FlagInput(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


class ComputedOverrideInput(BaseModel):
    field: Literal["gross", "employee_shi", "employer_shi", "pit", "advance", "other_deductions"]
    value: Decimal = Field(ge=0, le=Decimal("999999999999999"))
    reason: str = Field(min_length=1, max_length=1000)


class ComputedOverrideRevertInput(BaseModel):
    field: Literal["gross", "employee_shi", "employer_shi", "pit", "advance", "other_deductions"]
    reason: str = Field(min_length=1, max_length=1000)


class CalendarDayInput(BaseModel):
    day_type: Literal["working", "weekly_rest", "public_holiday"]
    holiday_name: str | None = Field(default=None, max_length=240)


class CompanyMonthlySettingsInput(BaseModel):
    legal_company_name: str | None = Field(default=None, max_length=240)
    daily_norm_hours: Decimal = Field(gt=0, le=24)
    employer_injury_rate: Decimal = Field(ge=Decimal("0.005"), le=Decimal("0.025"))
    weekday_overtime_multiplier: Decimal = Field(ge=Decimal("1.5"), le=Decimal("10"))
    rest_day_overtime_multiplier: Decimal = Field(ge=Decimal("1.5"), le=Decimal("10"))
    public_holiday_overtime_multiplier: Decimal = Field(ge=Decimal("2"), le=Decimal("10"))
    default_advance_basis: Literal["FIXED", "PERCENT", "WORKED-TO-DATE"]
    default_advance_percent: Decimal = Field(gt=0, le=100)
    deduction_types: list[str] = Field(min_length=1, max_length=32)
    salary_expense_account_id: int | None = Field(default=None, gt=0)
    employer_shi_account_id: int | None = Field(default=None, gt=0)
    advance_clearing_account_id: int | None = Field(default=None, gt=0)


class MonthlyRuleSetInput(BaseModel):
    valid_from: date
    valid_to: date | None = None
    minimum_wage: Decimal = Field(gt=0, le=Decimal("999999999"))
    shi_cap_multiplier: Decimal = Field(gt=0, le=Decimal("100"))
    employee_rates: dict[str, Decimal]
    employer_rates: dict[str, Decimal]
    pit_brackets: list[dict[str, Any]] = Field(min_length=1, max_length=20)
    relief_tiers: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    overtime_multipliers: dict[str, Decimal]
    source_references: list[str] = Field(min_length=1, max_length=20)


async def _closing_stats(db: AsyncSession, month: MonthlyPayrollMonth, organization_id: int) -> dict[str, Any]:
    runs = (await db.execute(select(MonthlyPayrollRun).where(
        MonthlyPayrollRun.month_id == month.id, MonthlyPayrollRun.organization_id == organization_id,
    ).order_by(MonthlyPayrollRun.pay_date, MonthlyPayrollRun.run_type))).scalars().all()
    run_rows: dict[int, list[MonthlyPayrollRunRow]] = {}
    for run in runs:
        run_rows[run.id] = (await db.execute(select(MonthlyPayrollRunRow).where(MonthlyPayrollRunRow.run_id == run.id))).scalars().all()
    final_run = next((run for run in runs if run.run_type == "final"), None)
    final_rows = run_rows.get(final_run.id, []) if final_run else []
    fields = ("gross", "employee_shi", "employer_shi", "pit", "relief", "advance", "other_deductions", "net_pay")
    totals = {key: sum((Decimal(str((row.result or {}).get(key, 0))) for row in final_rows), Decimal("0")) for key in fields}
    gross_values = [Decimal(str((row.result or {}).get("gross", 0))) for row in final_rows]
    net_values = [Decimal(str((row.result or {}).get("net_pay", 0))) for row in final_rows]
    advance_rows = [(run, row) for run in runs if run.run_type == "advance" for row in run_rows.get(run.id, [])]
    overtime_hours: dict[str, Decimal] = {}
    overtime_amounts: dict[str, Decimal] = {}
    deduction_totals: dict[str, Decimal] = {}
    departments: dict[str, dict[str, Any]] = {}
    extra_workers, manual_rows, cap_hits, warned_rows = set(), 0, 0, 0
    cap = Decimal(str(month.rule_snapshot.get("minimum_wage", 0))) * Decimal(str(month.rule_snapshot.get("shi_cap_multiplier", 10)))
    for row in final_rows:
        identity, inputs, result = row.identity_snapshot or {}, row.inputs or {}, row.result or {}
        department = identity.get("department") or "Бусад"
        group = departments.setdefault(department, {key: Decimal("0") for key in ("headcount", "gross", "employee_shi", "pit", "employer_shi", "net_pay")})
        group["headcount"] += 1
        for key in ("gross", "employee_shi", "pit", "employer_shi", "net_pay"):
            group[key] += Decimal(str(result.get(key, 0)))
        if any(Decimal(str(value)) > 0 for value in (inputs.get("overtime_hours") or {}).values()):
            extra_workers.add(row.employee_id)
        if row.warnings:
            warned_rows += 1
        if Decimal(str(result.get("shi_base", 0))) >= cap and cap > 0:
            cap_hits += 1
        for kind, hours in (inputs.get("overtime_hours") or {}).items():
            overtime_hours[kind] = overtime_hours.get(kind, Decimal("0")) + Decimal(str(hours))
        for kind, value in (result.get("overtime_by_bucket") or {}).items():
            overtime_amounts[kind] = overtime_amounts.get(kind, Decimal("0")) + Decimal(str(value))
        for line in inputs.get("other_deductions", []):
            label = line.get("type") or "Төрөлгүй"
            deduction_totals[label] = deduction_totals.get(label, Decimal("0")) + Decimal(str(line.get("amount", 0)))
    # Count accountant-edited rows from the immutable field audit records.
    audit_rows = (await db.execute(select(MonthlyPayrollRowAudit.row_id).where(
        MonthlyPayrollRowAudit.organization_id == organization_id,
        MonthlyPayrollRowAudit.run_id.in_([run.id for run in runs] or [-1]),
    ))).scalars().all()
    manual_rows = len(set(audit_rows))
    advance_total = sum((Decimal(str((row.result or {}).get("advance", 0))) for _, row in advance_rows), Decimal("0"))
    return _json_value({
        "headcount": {"on_register": len(final_rows), "paid": len([row for row in final_rows if any(run.status == "paid" for run in runs if run.run_type == "final")]), "with_extra_work": len(extra_workers), "manually_edited": manual_rows},
        "totals": {**totals, "advance_total": advance_total, "company_cost": totals["gross"] + totals["employer_shi"], "account_a": totals["gross"], "account_b": totals["employer_shi"]},
        "averages": {"average_gross": sum(gross_values, Decimal("0")) / len(gross_values) if gross_values else 0, "median_gross": statistics.median(gross_values) if gross_values else 0, "average_take_home": sum(net_values, Decimal("0")) / len(net_values) if net_values else 0, "highest_gross": max(gross_values) if gross_values else 0, "lowest_gross": min(gross_values) if gross_values else 0},
        "overtime": {"hours": overtime_hours, "amounts": overtime_amounts, "workers": len(extra_workers)},
        "other_deductions_by_type": deduction_totals,
        "by_department": departments,
        "quality": {"manual_rows": manual_rows, "shi_cap_hits": cap_hits, "rows_with_warnings": warned_rows, "workers_without_advance": sum("advance_not_calculated" in (row.warnings or []) for row in final_rows)},
        "run_statuses": {str(run.id): run.status for run in runs},
    })


async def _month_close_issues(db: AsyncSession, actor: ActorContext, month: MonthlyPayrollMonth, runs: list[MonthlyPayrollRun]) -> list[str]:
    issues: list[str] = []
    finals = [run for run in runs if run.run_type == "final"]
    if len(finals) != 1:
        issues.append("final_run_required")
    if any(run.status not in {"approved", "paid", "closed"} for run in runs):
        issues.append("all_runs_must_be_approved")
    all_rows: dict[int, list[MonthlyPayrollRunRow]] = {}
    for run in runs:
        rows = list((await db.execute(select(MonthlyPayrollRunRow).where(
            MonthlyPayrollRunRow.run_id == run.id,
            MonthlyPayrollRunRow.organization_id == actor.organization_id,
        ))).scalars().all())
        all_rows[run.id] = rows
        if any(row.status != "approved" for row in rows):
            issues.append("all_rows_must_be_approved")
    if not finals:
        return sorted(set(issues))
    final_rows = all_rows.get(finals[0].id, [])
    for row in final_rows:
        result = row.result or {}
        if not row.profile_snapshot.get("complete", True):
            issues.append("profile_incomplete")
        if Decimal(str(result.get("net_pay", 0))) < 0:
            issues.append("negative_final_pay")
        if Decimal(str(result.get("total_deductions", 0))) + Decimal(str(result.get("net_pay", 0))) != Decimal(str(result.get("gross", 0))):
            issues.append("row_payroll_equation_mismatch")
    final_advance = sum((Decimal(str((row.result or {}).get("advance", 0))) for row in final_rows), Decimal("0"))
    approved_advance = sum((Decimal(str((row.result or {}).get("advance", 0))) for run in runs if run.run_type == "advance" and run.status in {"approved", "paid", "closed"} for row in all_rows.get(run.id, [])), Decimal("0"))
    if final_advance != approved_advance:
        issues.append("advance_reconciliation_mismatch")
    return sorted(set(issues))


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _rules(snapshot: dict[str, Any]) -> PayrollRules:
    return PayrollRules(
        minimum_wage=amount(snapshot["minimum_wage"]),
        shi_cap_multiplier=amount(snapshot.get("shi_cap_multiplier", 10)),
        employee_shi_rates={key: amount(value) for key, value in snapshot["employee_rates"].items()},
        employer_shi_rates={key: amount(value) for key, value in snapshot["employer_rates"].items()},
        pit_brackets=tuple((amount(row["lower"]), amount(row["upper"]) if row.get("upper") is not None else None, amount(row["rate"]), amount(row.get("base_tax", 0))) for row in snapshot["pit_brackets"]),
        relief_tiers=tuple((amount(row["lower"]), amount(row["upper"]) if row.get("upper") is not None else None, amount(row["amount"])) for row in snapshot["relief_tiers"]),
        overtime_multipliers={key: amount(value) for key, value in snapshot["overtime_multipliers"].items()},
    )


def _rule_snapshot(row: MonthlyPayrollRuleSet) -> dict[str, Any]:
    return _json_value({
        "id": row.id, "version": row.version, "valid_from": row.valid_from,
        "minimum_wage": row.minimum_wage, "shi_cap_multiplier": row.shi_cap_multiplier,
        "employee_rates": row.employee_rates, "employer_rates": row.employer_rates,
        "pit_brackets": row.pit_brackets, "relief_tiers": row.relief_tiers,
        "overtime_multipliers": row.overtime_multipliers, "source_references": row.source_references,
    })


def _rule_validation_issues(data: MonthlyRuleSetInput) -> list[str]:
    issues: list[str] = []
    if data.valid_to is not None and data.valid_to < data.valid_from:
        issues.append("valid_to_before_valid_from")
    if any(not source.strip() for source in data.source_references):
        issues.append("source_reference_required")
    if not data.employee_rates or not data.employer_rates:
        issues.append("shi_rates_required")
    if any(rate < 0 or rate > 1 for rate in (*data.employee_rates.values(), *data.employer_rates.values())):
        issues.append("shi_rate_out_of_range")
    required_overtime = {"weekday", "rest_day", "public_holiday"}
    if set(data.overtime_multipliers) != required_overtime or any(value <= 0 or value > 10 for value in data.overtime_multipliers.values()):
        issues.append("overtime_buckets_invalid")
    for field_name, brackets, has_rate in (("pit", data.pit_brackets, True), ("relief", data.relief_tiers, False)):
        previous_upper: Decimal | None = None
        for index, bracket in enumerate(brackets):
            try:
                lower = amount(bracket["lower"])
                upper = amount(bracket["upper"]) if bracket.get("upper") is not None else None
                value = amount(bracket["rate"] if has_rate else bracket["amount"])
                if lower < 0 or (upper is not None and upper <= lower) or value < 0:
                    raise ValueError
                if has_rate and (value > 1 or amount(bracket.get("base_tax", 0)) < 0):
                    raise ValueError
                if index == 0 and lower != 0:
                    issues.append(f"{field_name}_must_start_at_zero")
                if index and (previous_upper is None or lower != previous_upper):
                    issues.append(f"{field_name}_tiers_must_be_contiguous")
                if index < len(brackets) - 1 and upper is None:
                    issues.append(f"{field_name}_only_last_tier_can_be_open_ended")
                previous_upper = upper
            except (KeyError, TypeError, ValueError):
                issues.append(f"{field_name}_tier_{index + 1}_invalid")
    if data.pit_brackets and data.pit_brackets[-1].get("upper") is not None:
        issues.append("pit_last_tier_must_be_open_ended")
    return sorted(set(issues))


def _rule_input_from_row(row: MonthlyPayrollRuleSet) -> dict[str, Any]:
    return {
        "id": row.id, "version": row.version, "status": row.status,
        "valid_from": row.valid_from.isoformat(), "valid_to": row.valid_to.isoformat() if row.valid_to else None,
        "minimum_wage": str(row.minimum_wage), "shi_cap_multiplier": str(row.shi_cap_multiplier),
        "employee_rates": row.employee_rates, "employer_rates": row.employer_rates,
        "pit_brackets": row.pit_brackets, "relief_tiers": row.relief_tiers,
        "overtime_multipliers": row.overtime_multipliers, "source_references": row.source_references,
        "validation_issues": row.validation_issues if hasattr(row, "validation_issues") else [],
    }


def _rule_input_default() -> dict[str, Any]:
    rules = default_2026_rules()
    return {
        "valid_from": date(2026, 1, 1), "valid_to": None,
        "minimum_wage": rules.minimum_wage, "shi_cap_multiplier": rules.shi_cap_multiplier,
        "employee_rates": rules.employee_shi_rates, "employer_rates": rules.employer_shi_rates,
        "pit_brackets": [{"lower": lower, "upper": upper, "rate": rate, "base_tax": base} for lower, upper, rate, base in rules.pit_brackets],
        "relief_tiers": [{"lower": lower, "upper": upper, "amount": value} for lower, upper, value in rules.relief_tiers],
        "overtime_multipliers": rules.overtime_multipliers,
        "source_references": [
            "https://legalinfo.mn/mn/detail?lawId=14410",
            "https://legalinfo.mn/mn/detail?lawId=16760148379551",
        ],
    }


@router.get("/rule-sets")
async def list_monthly_rule_sets(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "payroll", "view")
    rows = (await db.execute(select(MonthlyPayrollRuleSet).where(
        MonthlyPayrollRuleSet.organization_id == actor.organization_id,
    ).order_by(MonthlyPayrollRuleSet.valid_from.desc(), MonthlyPayrollRuleSet.version.desc()))).scalars().all()
    return [_rule_input_from_row(row) for row in rows]


@router.get("/rule-sets/template")
async def get_monthly_rule_template(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "payroll", "view")
    return _json_value(_rule_input_default())


@router.post("/rule-sets", status_code=status.HTTP_201_CREATED)
async def create_monthly_rule_draft(data: MonthlyRuleSetInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "payroll", "administer")
    values = data.model_dump()
    if not values["pit_brackets"]:
        values["pit_brackets"] = _rule_input_default()["pit_brackets"]
    current_version = await db.scalar(select(MonthlyPayrollRuleSet.version).where(
        MonthlyPayrollRuleSet.organization_id == actor.organization_id,
    ).order_by(MonthlyPayrollRuleSet.version.desc()).limit(1)) or 0
    row = MonthlyPayrollRuleSet(
        organization_id=actor.organization_id, version=current_version + 1, status="draft",
        valid_from=data.valid_from, valid_to=data.valid_to, minimum_wage=data.minimum_wage,
        shi_cap_multiplier=data.shi_cap_multiplier,
        employee_rates=_json_value(data.employee_rates), employer_rates=_json_value(data.employer_rates),
        pit_brackets=_json_value(data.pit_brackets), relief_tiers=_json_value(data.relief_tiers),
        overtime_multipliers=_json_value(data.overtime_multipliers),
        source_references=[source.strip() for source in data.source_references],
    )
    db.add(row)
    await db.flush()
    await record_change(db, actor=actor, topic="payroll", aggregate_type="monthly_payroll_rule_set", aggregate_id=row.id, operation="drafted", after=_rule_input_from_row(row))
    await db.commit()
    await db.refresh(row)
    return _rule_input_from_row(row)


@router.put("/rule-sets/{rule_id}")
async def update_monthly_rule_draft(rule_id: int, data: MonthlyRuleSetInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "payroll", "administer")
    row = await db.scalar(select(MonthlyPayrollRuleSet).where(
        MonthlyPayrollRuleSet.id == rule_id,
        MonthlyPayrollRuleSet.organization_id == actor.organization_id,
    ).with_for_update())
    if row is None:
        raise HTTPException(status_code=404, detail="Дүрмийн хувилбар олдсонгүй.")
    if row.status not in {"draft", "validated"}:
        raise HTTPException(status_code=409, detail="Нийтэлсэн дүрмийг засах боломжгүй. Шинэ хувилбар ноороглоно уу.")
    before = _rule_input_from_row(row)
    row.status = "draft"
    row.valid_from, row.valid_to = data.valid_from, data.valid_to
    row.minimum_wage, row.shi_cap_multiplier = data.minimum_wage, data.shi_cap_multiplier
    row.employee_rates, row.employer_rates = _json_value(data.employee_rates), _json_value(data.employer_rates)
    row.pit_brackets, row.relief_tiers = _json_value(data.pit_brackets), _json_value(data.relief_tiers)
    row.overtime_multipliers = _json_value(data.overtime_multipliers)
    row.source_references = [source.strip() for source in data.source_references]
    await record_change(db, actor=actor, topic="payroll", aggregate_type="monthly_payroll_rule_set", aggregate_id=row.id, operation="draft_updated", before=before, after=_rule_input_from_row(row))
    await db.commit()
    await db.refresh(row)
    return _rule_input_from_row(row)


@router.post("/rule-sets/{rule_id}/validate")
async def validate_monthly_rule_draft(rule_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "payroll", "administer")
    row = await db.scalar(select(MonthlyPayrollRuleSet).where(
        MonthlyPayrollRuleSet.id == rule_id, MonthlyPayrollRuleSet.organization_id == actor.organization_id,
    ).with_for_update())
    if row is None:
        raise HTTPException(status_code=404, detail="Дүрмийн хувилбар олдсонгүй.")
    if row.status not in {"draft", "validated"}:
        raise HTTPException(status_code=409, detail="Зөвхөн ноорог дүрмийг шалгана.")
    payload = MonthlyRuleSetInput(
        valid_from=row.valid_from, valid_to=row.valid_to, minimum_wage=row.minimum_wage,
        shi_cap_multiplier=row.shi_cap_multiplier, employee_rates=row.employee_rates,
        employer_rates=row.employer_rates, pit_brackets=row.pit_brackets, relief_tiers=row.relief_tiers,
        overtime_multipliers=row.overtime_multipliers, source_references=row.source_references,
    )
    issues = _rule_validation_issues(payload)
    if not issues:
        overlaps = (await db.execute(select(MonthlyPayrollRuleSet).where(
            MonthlyPayrollRuleSet.organization_id == actor.organization_id,
            MonthlyPayrollRuleSet.status == "published", MonthlyPayrollRuleSet.id != row.id,
        ))).scalars().all()
        for current in overlaps:
            candidate_end = payload.valid_to or date.max
            current_end = current.valid_to or date.max
            if payload.valid_from <= current_end and current.valid_from <= candidate_end:
                # A later-dated version supersedes the earlier rule's open
                # tail when published. A rule cannot be inserted before or
                # at the start of an already published successor.
                if current.valid_from >= payload.valid_from:
                    issues.append(f"published_effective_period_overlaps_version_{current.version}")
    before = row.status
    row.status = "validated" if not issues else "draft"
    await record_change(db, actor=actor, topic="payroll", aggregate_type="monthly_payroll_rule_set", aggregate_id=row.id, operation="validated", before={"status": before}, after={"status": row.status, "issues": issues})
    await db.commit()
    await db.refresh(row)
    return {**_rule_input_from_row(row), "validation_issues": issues}


@router.post("/rule-sets/{rule_id}/publish")
async def publish_monthly_rule_draft(rule_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "payroll", "administer")
    row = await db.scalar(select(MonthlyPayrollRuleSet).where(
        MonthlyPayrollRuleSet.id == rule_id, MonthlyPayrollRuleSet.organization_id == actor.organization_id,
    ).with_for_update())
    if row is None:
        raise HTTPException(status_code=404, detail="Дүрмийн хувилбар олдсонгүй.")
    if row.status != "validated":
        raise HTTPException(status_code=409, detail="Нийтлэхийн өмнө дүрмийг шалгана уу.")
    before = _rule_input_from_row(row)
    published = (await db.execute(select(MonthlyPayrollRuleSet).where(
        MonthlyPayrollRuleSet.organization_id == actor.organization_id,
        MonthlyPayrollRuleSet.status == "published", MonthlyPayrollRuleSet.id != row.id,
    ).with_for_update())).scalars().all()
    for previous in published:
        previous_end = previous.valid_to or date.max
        if previous.valid_from < row.valid_from <= previous_end:
            old_valid_to = previous.valid_to
            previous.valid_to = row.valid_from - timedelta(days=1)
            await record_change(
                db, actor=actor, topic="payroll", aggregate_type="monthly_payroll_rule_set",
                aggregate_id=previous.id, operation="effective_period_superseded",
                before={"valid_to": old_valid_to.isoformat() if old_valid_to else None},
                after={"valid_to": previous.valid_to.isoformat(), "successor_version": row.version},
            )
    row.status = "published"
    await record_change(db, actor=actor, topic="payroll", aggregate_type="monthly_payroll_rule_set", aggregate_id=row.id, operation="published", before=before, after=_rule_input_from_row(row))
    await db.commit()
    await db.refresh(row)
    return _rule_input_from_row(row)


@router.get("/settings")
async def get_monthly_settings(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "payroll", "view")
    row = await db.scalar(select(MonthlyPayrollCompanySettings).where(MonthlyPayrollCompanySettings.organization_id == actor.organization_id))
    if row is None:
        return {"legal_company_name": None, "daily_norm_hours": "8", "employer_injury_rate": "0.005", "weekday_overtime_multiplier": "1.5", "rest_day_overtime_multiplier": "1.5", "public_holiday_overtime_multiplier": "2", "default_advance_basis": "FIXED", "default_advance_percent": "40", "deduction_types": ["Торгууль / сахилгын шийтгэл", "Хохирол / ажилтнаас авах авлага", "Бусад"], "salary_expense_account_id": None, "employer_shi_account_id": None, "advance_clearing_account_id": None}
    fields = ("legal_company_name", "daily_norm_hours", "employer_injury_rate", "weekday_overtime_multiplier", "rest_day_overtime_multiplier", "public_holiday_overtime_multiplier", "default_advance_basis", "default_advance_percent", "deduction_types", "salary_expense_account_id", "employer_shi_account_id", "advance_clearing_account_id")
    account_fields = {"salary_expense_account_id", "employer_shi_account_id", "advance_clearing_account_id"}
    return {key: str(getattr(row, key)) if key not in {"deduction_types", "legal_company_name", *account_fields} and getattr(row, key) is not None else getattr(row, key) for key in fields}


@router.put("/settings")
async def save_monthly_settings(data: CompanyMonthlySettingsInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "payroll", "administer")
    row = await db.scalar(select(MonthlyPayrollCompanySettings).where(MonthlyPayrollCompanySettings.organization_id == actor.organization_id).with_for_update())
    if row is None:
        row = MonthlyPayrollCompanySettings(organization_id=actor.organization_id)
        db.add(row)
    account_ids = {value for value in (data.salary_expense_account_id, data.employer_shi_account_id, data.advance_clearing_account_id) if value is not None}
    if account_ids:
        valid_ids = set((await db.execute(select(ERPAccount.id).where(ERPAccount.organization_id == actor.organization_id, ERPAccount.id.in_(account_ids), ERPAccount.is_active.is_(True), ERPAccount.is_group.is_(False)))).scalars().all())
        if valid_ids != account_ids:
            raise HTTPException(status_code=422, detail="Сонгосон данс танай байгууллагын идэвхтэй данс биш байна.")
    before = {key: getattr(row, key) for key in ("legal_company_name", "daily_norm_hours", "employer_injury_rate", "weekday_overtime_multiplier", "rest_day_overtime_multiplier", "public_holiday_overtime_multiplier", "default_advance_basis", "default_advance_percent", "deduction_types", "salary_expense_account_id", "employer_shi_account_id", "advance_clearing_account_id")}
    for key, value in data.model_dump().items():
        setattr(row, key, _json_value(value))
    await db.flush()
    await record_change(db, actor=actor, topic="payroll", aggregate_type="monthly_payroll_company_settings", aggregate_id=row.id, operation="updated", before=_json_value(before), after=_json_value({key: getattr(row, key) for key in before}))
    await db.commit()
    return await get_monthly_settings(db, actor)


@router.get("/calendar/{year}/{month_num}")
async def get_monthly_calendar(year: int, month_num: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "payroll", "view")
    if month_num < 1 or month_num > 12:
        raise HTTPException(status_code=422, detail="Сарыг 1-12 хооронд сонгоно уу.")
    first, last = date(year, month_num, 1), date(year, month_num, calendar.monthrange(year, month_num)[1])
    rows = (await db.execute(select(MonthlyPayrollCalendarDay).where(
        MonthlyPayrollCalendarDay.organization_id == actor.organization_id,
        MonthlyPayrollCalendarDay.calendar_date.between(first, last),
    ))).scalars().all()
    overrides = {row.calendar_date: row.day_type for row in rows}
    days = month_calendar(year, month_num, overrides=overrides)
    names = {row.calendar_date: row.holiday_name for row in rows}
    return [{"date": day.isoformat(), "day_type": day_type.value, "holiday_name": names.get(day)} for day, day_type in days.items()]


@router.put("/calendar/{calendar_date}")
async def set_monthly_calendar_day(calendar_date: date, data: CalendarDayInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "payroll", "administer")
    month = await db.scalar(select(MonthlyPayrollMonth).where(
        MonthlyPayrollMonth.organization_id == actor.organization_id,
        MonthlyPayrollMonth.year == calendar_date.year, MonthlyPayrollMonth.month == calendar_date.month,
    ))
    if month:
        raise HTTPException(status_code=409, detail="Сарын хуанли бодолтод хадгалагдсан тул өөрчлөх боломжгүй.")
    row = await db.scalar(select(MonthlyPayrollCalendarDay).where(
        MonthlyPayrollCalendarDay.organization_id == actor.organization_id,
        MonthlyPayrollCalendarDay.calendar_date == calendar_date,
    ).with_for_update())
    if row is None:
        row = MonthlyPayrollCalendarDay(organization_id=actor.organization_id, calendar_date=calendar_date, day_type=data.day_type, holiday_name=data.holiday_name, updated_by_account_id=actor.account_id)
        db.add(row)
    else:
        row.day_type = data.day_type
        row.holiday_name = data.holiday_name
        row.updated_by_account_id = actor.account_id
    await db.commit()
    return {"date": calendar_date.isoformat(), "day_type": data.day_type, "holiday_name": data.holiday_name}


def _month_out(month: MonthlyPayrollMonth, runs: list[MonthlyPayrollRun]) -> dict[str, Any]:
    return {
        "id": month.id, "year": month.year, "month": month.month, "status": month.status,
        "rule_set_id": month.rule_set_id, "rule_snapshot": month.rule_snapshot,
        "calendar_snapshot": month.calendar_snapshot,
        "runs": [_run_out(run) for run in runs],
    }


def _run_out(run: MonthlyPayrollRun) -> dict[str, Any]:
    return {
        "id": run.id, "month_id": run.month_id, "run_type": run.run_type,
        "pay_date": run.pay_date.isoformat(), "cutoff_date": run.cutoff_date.isoformat() if run.cutoff_date else None,
        "department_id": run.department_id, "status": run.status, "note": run.note,
        "advance_snapshot": run.advance_snapshot or {},
        "approved_at": run.approved_at.isoformat() if run.approved_at else None,
        "paid_at": run.paid_at.isoformat() if run.paid_at else None,
        "approved_by_account_id": run.approved_by_account_id,
        "paid_by_account_id": run.paid_by_account_id,
        "created_by_account_id": run.created_by_account_id,
    }


def _row_out(row: MonthlyPayrollRunRow, *, include_payout_snapshot: bool = False) -> dict[str, Any]:
    result = {
        "id": row.id, "employee_id": row.employee_id, "status": row.status,
        "identity": row.identity_snapshot or {}, "profile": row.profile_snapshot or {},
        "inputs": row.inputs or {}, "result": row.result or {}, "warnings": row.warnings or [],
        "approved_at": row.approved_at.isoformat() if row.approved_at else None,
        "approved_by_account_id": row.approved_by_account_id,
    }
    if include_payout_snapshot:
        result["payout_snapshot_ciphertext"] = row.payout_snapshot_ciphertext
    return result


async def _month(db: AsyncSession, actor: ActorContext, month_id: int, *, lock: bool = False) -> MonthlyPayrollMonth:
    query = select(MonthlyPayrollMonth).where(
        MonthlyPayrollMonth.id == month_id,
        MonthlyPayrollMonth.organization_id == actor.organization_id,
    )
    if lock:
        query = query.with_for_update()
    row = await db.scalar(query)
    if row is None:
        raise HTTPException(status_code=404, detail="Payroll month not found")
    return row


async def _run(db: AsyncSession, actor: ActorContext, run_id: int, *, lock: bool = False) -> MonthlyPayrollRun:
    query = select(MonthlyPayrollRun).where(
        MonthlyPayrollRun.id == run_id,
        MonthlyPayrollRun.organization_id == actor.organization_id,
    )
    if lock:
        query = query.with_for_update()
    row = await db.scalar(query)
    if row is None:
        raise HTTPException(status_code=404, detail="Payroll run not found")
    return row


async def _profiles_for_month(db: AsyncSession, actor: ActorContext, month: MonthlyPayrollMonth, department_id: int | None):
    first = date(month.year, month.month, 1)
    last = date(month.year, month.month, calendar.monthrange(month.year, month.month)[1])
    query = select(Employee, EmployeeDetails, MonthlyPayrollProfile).outerjoin(
        MonthlyPayrollProfile,
        (MonthlyPayrollProfile.employee_id == Employee.id) & (MonthlyPayrollProfile.organization_id == actor.organization_id),
    ).outerjoin(
        EmployeeDetails,
        (EmployeeDetails.employee_id == Employee.id) & (EmployeeDetails.organization_id == actor.organization_id),
    ).where(
        Employee.organization_id == actor.organization_id,
        Employee.deleted_at.is_(None),
        or_(Employee.is_active.is_(True), EmployeeDetails.end_date.is_not(None)),
    )
    if department_id is not None:
        query = query.where(EmployeeDetails.department_id == department_id)
    workers = (await db.execute(query.order_by(Employee.name))).all()
    output = []
    for employee, details, profile in workers:
        # Include recently departed and not-yet-configured workers whenever
        # their employment overlapped this earning month. They must appear as
        # actionable payroll validation rows rather than disappear silently.
        if details and ((details.start_date and details.start_date > last) or (details.end_date and details.end_date < first)):
            continue
        if profile is None:
            output.append((employee, details, None, None, []))
            continue
        history = (await db.execute(select(MonthlyPayrollSalaryHistory).where(
            MonthlyPayrollSalaryHistory.profile_id == profile.id,
            MonthlyPayrollSalaryHistory.valid_from <= last,
        ).order_by(MonthlyPayrollSalaryHistory.valid_from, MonthlyPayrollSalaryHistory.id))).scalars().all()
        active_history = [item for item in history if item.valid_from <= last]
        current_salary = active_history[-1] if active_history else None
        segments = []
        for item in active_history:
            segment_start = max(first, item.valid_from)
            later = [entry.valid_from for entry in active_history if entry.valid_from > item.valid_from]
            segment_end = min(last, (min(later) - date.resolution) if later else last)
            if segment_end < first or segment_start > last:
                continue
            segments.append({"monthly_salary": str(item.monthly_salary), "valid_from": segment_start.isoformat(), "valid_to": segment_end.isoformat()})
        covered_from = min((date.fromisoformat(item["valid_from"]) for item in segments), default=None)
        output.append((employee, details, profile, current_salary if covered_from is None or covered_from <= first else None, segments))
    return output


async def _attendance_inputs(db: AsyncSession, organization_id: int, employee_id: int, month: MonthlyPayrollMonth, cutoff: date | None, daily_norm_hours: Decimal, overrides: dict[date, str]) -> dict[str, Any]:
    first = date(month.year, month.month, 1)
    last = date(month.year, month.month, calendar.monthrange(month.year, month.month)[1])
    end = min(last, cutoff) if cutoff else last
    logs = (await db.execute(select(AttendanceLog).where(
        AttendanceLog.organization_id == organization_id, AttendanceLog.employee_id == employee_id,
        AttendanceLog.attendance_date >= first, AttendanceLog.attendance_date <= end,
        AttendanceLog.confirmed_at.is_not(None),
    ).order_by(AttendanceLog.attendance_date))).scalars().all()
    from zoneinfo import ZoneInfo
    local_zone = ZoneInfo("Asia/Ulaanbaatar")
    log_by_day = {log.attendance_date: log for log in logs}
    holiday_days = set((await db.execute(select(HolidayRecord.holiday_date).where(
        HolidayRecord.organization_id == organization_id, HolidayRecord.is_active.is_(True),
        HolidayRecord.holiday_date >= first, HolidayRecord.holiday_date <= end,
    ))).scalars().all())
    calendar_overrides = dict(overrides)
    for holiday_day in holiday_days:
        calendar_overrides.setdefault(holiday_day, CalendarDayType.PUBLIC_HOLIDAY.value)
    calendar_days = month_calendar(month.year, month.month, overrides=calendar_overrides)
    leave_rows = (await db.execute(select(TimeOff).where(
        TimeOff.organization_id == organization_id, TimeOff.employee_id == employee_id,
        TimeOff.status == "approved", TimeOff.starts_on <= end, TimeOff.ends_on >= first,
    ))).scalars().all()
    approved_leave = [{"id": row.id, "start": row.starts_on, "end": row.ends_on, "type": row.time_off_type, "minutes": row.partial_day_minutes} for row in leave_rows]
    work_rows = (await db.execute(select(WorkTimeEntry).join(Employee, Employee.id == WorkTimeEntry.employee_id).where(
        Employee.organization_id == organization_id, WorkTimeEntry.employee_id == employee_id,
        WorkTimeEntry.entry_type == "work", WorkTimeEntry.approval_status == "approved",
        WorkTimeEntry.ended_at.is_not(None),
        WorkTimeEntry.started_at >= datetime.combine(first, datetime.min.time(), local_zone),
        WorkTimeEntry.started_at < datetime.combine(end + timedelta(days=1), datetime.min.time(), local_zone),
    ))).scalars().all()
    approved_work: dict[date, Decimal] = {}
    for entry in work_rows:
        day = entry.local_work_date or entry.started_at.astimezone(local_zone).date()
        if first <= day <= end:
            minutes = Decimal(str(max(0, (entry.ended_at - entry.started_at).total_seconds() / 60)))
            approved_work[day] = approved_work.get(day, Decimal("0")) + minutes
    details = await db.scalar(select(EmployeeDetails).where(EmployeeDetails.organization_id == organization_id, EmployeeDetails.employee_id == employee_id))
    schedule = await db.scalar(select(Schedule).where(Schedule.employee_id == employee_id))
    weekdays = tuple(dict.fromkeys(max(0, min(6, int(day) - 1)) for day in (schedule.weekdays if schedule and schedule.weekdays else [1, 2, 3, 4, 5]))) or (0, 1, 2, 3, 4)
    normalized = payment_days(
        first, end, employment_start=details.start_date if details else None,
        employment_end=details.end_date if details else None, holidays=holiday_days,
        attendance={day: {"id": row.id, "status": row.status, "minutes": row.worked_minutes} for day, row in log_by_day.items()},
        leaves=approved_leave, approved_work=approved_work, validate_attendance=True,
        workweek=weekdays, hours_per_day=float(daily_norm_hours),
    )
    leave_fraction = {date.fromisoformat(item["date"]): Decimal(item["fraction"]) for item in normalized["days"]}
    normal_hours = Decimal("0")
    overtime = {"weekday": Decimal("0"), "rest_day": Decimal("0"), "public_holiday": Decimal("0")}
    lines = []
    day_minutes: dict[date, Decimal] = {}
    day_sources: dict[date, str] = {}
    for day, log in log_by_day.items():
        if log.status not in {"present", "remote", "late"} or log.worked_minutes <= 0:
            continue
        day_minutes[day] = Decimal(log.worked_minutes)
        day_sources[day] = log.source
    for day, minutes in approved_work.items():
        if day not in day_minutes:
            day_minutes[day] = minutes
            day_sources[day] = "approved_worktime"
    lines = []
    for work_day, minutes in sorted(day_minutes.items()):
        total_hours = minutes / Decimal(60) * leave_fraction.get(work_day, Decimal("1"))
        normal, buckets = classify_work_hours(calendar_days[work_day], total_hours, daily_norm_hours)
        normal_hours += normal
        for key, value in buckets.items():
            overtime[key] += value
        lines.append({"date": work_day.isoformat(), "day_type": calendar_days[work_day].value, "hours": str(total_hours), "normal_hours": str(normal), "overtime_hours": {key: str(value) for key, value in buckets.items() if value > 0}, "source": day_sources[work_day]})
    planned_days_to_cutoff = sum(day <= end and day_type is CalendarDayType.WORKING for day, day_type in calendar_days.items())
    return {"worked_normal_hours": str(normal_hours), "worked_to_date_hours": str(normal_hours), "elapsed_planned_days": planned_days_to_cutoff, "overtime_hours": {key: str(value) for key, value in overtime.items()}, "day_lines": lines, "missing_dates": normalized["missing_dates"], "approved_leave_days": normalized["days"], "time_source": "confirmed_hr_attendance_or_approved_worktime" if lines else "manual"}


async def _approved_advances(db: AsyncSession, run: MonthlyPayrollRun, employee_id: int, *, through_date: date | None = None) -> tuple[list[str], list[str]]:
    runs = (await db.execute(select(MonthlyPayrollRun).where(
        MonthlyPayrollRun.month_id == run.month_id,
        MonthlyPayrollRun.organization_id == run.organization_id,
        MonthlyPayrollRun.run_type == "advance",
        MonthlyPayrollRun.status.in_(("approved", "paid", "closed")),
        MonthlyPayrollRun.pay_date <= (through_date or run.pay_date),
    ))).scalars().all()
    values, ids = [], []
    for advance_run in runs:
        row = await db.scalar(select(MonthlyPayrollRunRow).where(
            MonthlyPayrollRunRow.run_id == advance_run.id,
            MonthlyPayrollRunRow.employee_id == employee_id,
        ))
        if row and row.result:
            values.append(str(row.result.get("advance", "0")))
            ids.append(str(advance_run.id))
    return values, ids


async def _calculate_row(db: AsyncSession, month: MonthlyPayrollMonth, run: MonthlyPayrollRun, row: MonthlyPayrollRunRow) -> dict[str, Any]:
    profile_data = row.profile_snapshot
    inputs = dict(row.inputs or {})
    if not profile_data.get("complete", True):
        row.result = {
            "run_type": run.run_type, "gross": "0", "advance": "0",
            "employee_shi": "0", "employer_shi": "0", "pit": "0",
            "net_pay": "0", "total_deductions": "0",
        }
        row.warnings = profile_data.get("validation_issues") or ["profile_incomplete"]
        return row.result
    profile = PayrollProfile(
        base_salary=amount(profile_data["base_salary"]), salary_type=profile_data["salary_type"],
        meal_allowance=amount(profile_data.get("meal_allowance", 0)), commute_allowance=amount(profile_data.get("commute_allowance", 0)),
        payment_frequency=profile_data["payment_frequency"], pay_days=tuple(profile_data["pay_days"]),
        advance_basis=AdvanceBasis(profile_data["advance_basis"]), advance_amount=amount(profile_data.get("advance_amount", 0)),
        advance_percent=amount(profile_data.get("advance_percent", 40)), daily_norm_hours=amount(profile_data.get("daily_norm_hours", 8)),
        insured_type=profile_data.get("insured_type", "01001"), tax_relief_eligible=bool(profile_data.get("tax_relief_eligible", False)),
    )
    if run.run_type == "advance":
        basis = AdvanceBasis(inputs.get("advance_basis", profile.advance_basis.value))
        adjustments = {**asdict(profile), "advance_basis": basis}
        advance_days = list(profile.pay_days[:-1])
        slot = next((index for index, day in enumerate(advance_days) if min(day, calendar.monthrange(month.year, month.month)[1]) == run.pay_date.day), None)
        slot_values = profile_data.get("advance_values") or []
        slot_value = amount(slot_values[slot]) if slot is not None and slot < len(slot_values) and slot_values[slot] not in (None, "") else None
        if slot_value is not None and basis is AdvanceBasis.FIXED:
            adjustments["advance_amount"] = slot_value
        elif slot_value is not None and basis is AdvanceBasis.PERCENT:
            adjustments["advance_percent"] = slot_value
        if inputs.get("fixed_advance") is not None:
            adjustments["advance_amount"] = amount(inputs["fixed_advance"])
        if inputs.get("advance_percent") is not None:
            adjustments["advance_percent"] = amount(inputs["advance_percent"])
        profile = PayrollProfile(**adjustments)
    rule_snapshot = month.rule_snapshot
    rules = _rules(rule_snapshot)
    calendar_snapshot = month.calendar_snapshot
    year, month_num = month.year, month.month
    overrides = {date.fromisoformat(key): value for key, value in calendar_snapshot.items()}
    days = month_calendar(year, month_num, overrides=overrides)
    planned_days = sum(value is CalendarDayType.WORKING for value in days.values())
    planned_hours = sum((amount(profile.daily_norm_hours) for value in days.values() if value is CalendarDayType.WORKING), Decimal("0"))
    segments_raw = profile_data.get("salary_segments") or []
    segment_objects = []
    if segments_raw:
        raw_segments = []
        total_segment_days = 0
        for segment in segments_raw:
            start, end = date.fromisoformat(segment["valid_from"]), date.fromisoformat(segment["valid_to"])
            segment_days = sum(start <= day <= end and day_type is CalendarDayType.WORKING for day, day_type in days.items())
            if segment_days:
                raw_segments.append((segment, segment_days))
                total_segment_days += segment_days
        day_lines = inputs.get("day_lines") or []
        normal_by_segment = [Decimal("0") for _ in raw_segments]
        overtime_by_segment = [{key: Decimal("0") for key in (inputs.get("overtime_hours") or {})} for _ in raw_segments]
        for line in day_lines:
            line_day = date.fromisoformat(line["date"])
            index = next((i for i, (segment, _) in enumerate(raw_segments) if date.fromisoformat(segment["valid_from"]) <= line_day <= date.fromisoformat(segment["valid_to"])), None)
            if index is None:
                continue
            normal_by_segment[index] += amount(line.get("normal_hours", 0))
            for bucket, hours in (line.get("overtime_hours") or {}).items():
                overtime_by_segment[index][bucket] = overtime_by_segment[index].get(bucket, Decimal("0")) + amount(hours)
        has_segment_lines = any(value > 0 for value in normal_by_segment) or any(any(value > 0 for value in group.values()) for group in overtime_by_segment)
        for index, (segment, segment_days) in enumerate(raw_segments):
            fraction = Decimal(segment_days) / Decimal(max(1, total_segment_days))
            # When an accountant edits aggregate hours, retain the date-based
            # allocation if it still reconciles; otherwise scale the source
            # lines proportionally and fall back to planned-day weights.
            worked_hours = normal_by_segment[index]
            overtime_values = overtime_by_segment[index]
            if has_segment_lines:
                normal_total = sum(normal_by_segment, Decimal("0"))
                if normal_total > 0:
                    worked_hours = amount(inputs.get("worked_normal_hours", 0)) * normal_by_segment[index] / normal_total
                else:
                    worked_hours = amount(inputs.get("worked_normal_hours", 0)) * fraction
                for bucket, total in (inputs.get("overtime_hours") or {}).items():
                    source_total = sum((group.get(bucket, Decimal("0")) for group in overtime_by_segment), Decimal("0"))
                    overtime_values[bucket] = amount(total) * overtime_by_segment[index].get(bucket, Decimal("0")) / source_total if source_total > 0 else amount(total) * fraction
            else:
                worked_hours = amount(inputs.get("worked_normal_hours", 0)) * fraction
                overtime_values = {key: amount(value) * fraction for key, value in (inputs.get("overtime_hours") or {}).items()}
            segment_objects.append(SalarySegment(
                amount(segment["monthly_salary"]), segment_days,
                worked_hours, overtime_values,
            ))
    advance_snapshot = (run.advance_snapshot or {}).get(str(row.employee_id), {}) if run.run_type == "final" else {}
    approved_advances = advance_snapshot.get("amounts", [])
    advance_ids = advance_snapshot.get("run_ids", [])
    prior_advances, _ = await _approved_advances(db, run, row.employee_id) if run.run_type == "advance" else ([], [])
    deductions = inputs.get("other_deductions", [])
    for hours in (inputs.get("overtime_hours") or {}).values():
        if amount(hours) < 0:
            raise HTTPException(status_code=422, detail={"code": "payroll_hours_nonnegative", "message": "Илүү цаг сөрөг байж болохгүй."})
    for line in deductions:
        if amount(line.get("amount", 0)) <= 0:
            raise HTTPException(status_code=422, detail={"code": "payroll_deduction_positive", "message": "Бусад суутгалын дүн 0-ээс их байх ёстой."})
    result = calculate_monthly_run(
        run.run_type, profile, rules=rules, planned_days=planned_days, planned_hours=planned_hours,
        worked_normal_hours=inputs.get("worked_normal_hours", 0),
        overtime_hours=inputs.get("overtime_hours", {}), leave_pay=inputs.get("leave_pay", 0),
        bonus=inputs.get("bonus", 0), approved_advances=approved_advances,
        prior_approved_advances=prior_advances,
        other_deductions=[item["amount"] for item in deductions],
        advance_pay_day=run.pay_date.day if run.run_type == "advance" else None,
        worked_to_date_hours=inputs.get("worked_to_date_hours", 0),
        elapsed_planned_days=int(inputs.get("elapsed_planned_days", 0)), salary_segments=segment_objects or None,
    )
    result_data = _json_value(asdict(result))
    result_data["advance_run_ids"] = advance_ids
    warnings = []
    computed_overrides = inputs.get("_computed_overrides") or {}
    if computed_overrides:
        result_data = apply_computed_overrides(
            result_data, computed_overrides, rules=rules,
            tax_relief_eligible=profile.tax_relief_eligible,
        )
        warnings.append("computed_cell_overridden")
    if run.run_type == "final":
        due_advances = list(profile.pay_days[:-1]) if profile.payment_frequency != "MONTHLY" else []
        month_end = date(year, month_num, calendar.monthrange(year, month_num)[1])
        current_rows = (await db.execute(select(MonthlyPayrollRun.id, MonthlyPayrollRun.pay_date, MonthlyPayrollRunRow.result).join(
            MonthlyPayrollRunRow, MonthlyPayrollRunRow.run_id == MonthlyPayrollRun.id,
        ).where(
            MonthlyPayrollRun.month_id == run.month_id,
            MonthlyPayrollRun.organization_id == run.organization_id,
            MonthlyPayrollRunRow.organization_id == run.organization_id,
            MonthlyPayrollRunRow.employee_id == row.employee_id,
            MonthlyPayrollRun.run_type == "advance",
            MonthlyPayrollRun.status.in_(("approved", "paid", "closed")),
            MonthlyPayrollRun.pay_date <= month_end,
        ).order_by(MonthlyPayrollRun.pay_date, MonthlyPayrollRun.id))).all()
        current_ids = [str(item.id) for item in current_rows]
        current_amounts = [str((item.result or {}).get("advance", "0")) for item in current_rows]
        if current_ids != advance_ids or current_amounts != approved_advances:
            warnings.append("advance_changed")
        scheduled_dates = {date(year, month_num, min(day, calendar.monthrange(year, month_num)[1])) for day in due_advances}
        approved_dates = {item.pay_date for item in current_rows if item.pay_date in scheduled_dates}
        if scheduled_dates - approved_dates:
            warnings.append("advance_not_calculated")
    if result.net_pay < 0:
        warnings.append("negative_final_pay")
    if run.run_type == "advance":
        estimated = calculate_monthly_run(
            PayrollRunType.FINAL, profile, rules=rules, planned_days=planned_days, planned_hours=planned_hours,
            worked_normal_hours=planned_hours, salary_segments=segment_objects or None,
        )
        if result.advance > estimated.net_pay:
            warnings.append("advance_above_estimated_net")
    if sum((amount(value) for value in inputs.get("overtime_hours", {}).values()), Decimal("0")) > 0:
        warnings.append("overtime_work")
    if profile.base_salary < rules.minimum_wage:
        warnings.append("base_below_minimum_wage")
    if amount(inputs.get("worked_normal_hours", 0)) + sum((amount(value) for value in inputs.get("overtime_hours", {}).values()), Decimal("0")) > planned_hours:
        warnings.append("worked_hours_above_planned")
    if run.run_type == "final" and profile.salary_type == "PRORATION" and amount(inputs.get("worked_normal_hours", 0)) == 0:
        warnings.append("zero_worked_hours")
    if run.run_type == "advance" and profile.advance_basis is AdvanceBasis.WORKED_TO_DATE and not inputs.get("day_lines"):
        warnings.append("worked_to_date_without_time")
    if any(not line.get("type") or not line.get("note") for line in deductions):
        warnings.append("deduction_details_missing")
    row.result = result_data
    row.warnings = warnings
    return result_data


@router.post("/months", status_code=status.HTTP_201_CREATED)
async def create_month(data: MonthInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "payroll", "create")
    existing = await db.scalar(select(MonthlyPayrollMonth).where(
        MonthlyPayrollMonth.organization_id == actor.organization_id,
        MonthlyPayrollMonth.year == data.year, MonthlyPayrollMonth.month == data.month,
    ))
    if existing:
        return _month_out(existing, [])
    effective = date(data.year, data.month, 1)
    rule = await db.scalar(select(MonthlyPayrollRuleSet).where(
        MonthlyPayrollRuleSet.organization_id == actor.organization_id,
        MonthlyPayrollRuleSet.status == "published", MonthlyPayrollRuleSet.valid_from <= effective,
        (MonthlyPayrollRuleSet.valid_to.is_(None) | (MonthlyPayrollRuleSet.valid_to >= effective)),
    ).order_by(MonthlyPayrollRuleSet.version.desc()).limit(1))
    if not rule:
        raise HTTPException(status_code=409, detail="Тухайн сард хүчинтэй нийтэлсэн цалингийн дүрэм алга.")
    last = date(data.year, data.month, calendar.monthrange(data.year, data.month)[1])
    overrides_rows = (await db.execute(select(MonthlyPayrollCalendarDay).where(
        MonthlyPayrollCalendarDay.organization_id == actor.organization_id,
        MonthlyPayrollCalendarDay.calendar_date >= effective,
        MonthlyPayrollCalendarDay.calendar_date <= last,
    ))).scalars().all()
    overrides = {row.calendar_date: row.day_type for row in overrides_rows}
    built = month_calendar(data.year, data.month, overrides=overrides)
    rule_snapshot = _rule_snapshot(rule)
    settings = await db.scalar(select(MonthlyPayrollCompanySettings).where(MonthlyPayrollCompanySettings.organization_id == actor.organization_id))
    if settings:
        employer_rates = dict(rule_snapshot.get("employer_rates", {}))
        employer_rates["injury"] = str(settings.employer_injury_rate)
        rule_snapshot["employer_rates"] = employer_rates
        rule_snapshot["overtime_multipliers"] = {
            "weekday": str(settings.weekday_overtime_multiplier),
            "rest_day": str(settings.rest_day_overtime_multiplier),
            "public_holiday": str(settings.public_holiday_overtime_multiplier),
        }
    month_row = MonthlyPayrollMonth(
        organization_id=actor.organization_id, year=data.year, month=data.month,
        rule_set_id=rule.id, rule_snapshot=rule_snapshot,
        calendar_snapshot={day.isoformat(): day_type.value for day, day_type in built.items()},
        created_by_account_id=actor.account_id,
    )
    db.add(month_row)
    await db.commit()
    await db.refresh(month_row)
    return _month_out(month_row, [])


@router.get("/months")
async def list_months(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "payroll", "view")
    months = (await db.execute(select(MonthlyPayrollMonth).where(
        MonthlyPayrollMonth.organization_id == actor.organization_id,
    ).order_by(MonthlyPayrollMonth.year.desc(), MonthlyPayrollMonth.month.desc()))).scalars().all()
    result = []
    for month in months:
        runs = (await db.execute(select(MonthlyPayrollRun).where(MonthlyPayrollRun.month_id == month.id).order_by(MonthlyPayrollRun.pay_date, MonthlyPayrollRun.run_type))).scalars().all()
        result.append(_month_out(month, runs))
    return result


@router.get("/months/{month_id}")
async def get_month(month_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "payroll", "view")
    month = await _month(db, actor, month_id)
    runs = (await db.execute(select(MonthlyPayrollRun).where(
        MonthlyPayrollRun.month_id == month.id, MonthlyPayrollRun.organization_id == actor.organization_id,
    ).order_by(MonthlyPayrollRun.pay_date, MonthlyPayrollRun.run_type))).scalars().all()
    return _month_out(month, runs)


@router.get("/months/{month_id}/advance-dates")
async def get_advance_dates(month_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "payroll", "view")
    month = await _month(db, actor, month_id)
    last = date(month.year, month.month, calendar.monthrange(month.year, month.month)[1])
    workers = await _profiles_for_month(db, actor, month, None)
    days = sorted({min(int(day), last.day) for _, _, profile, _, _ in workers if profile is not None for day in (profile.pay_days or [])[:-1] if int(day) > 0})
    return [{"day": day, "date": date(month.year, month.month, day).isoformat()} for day in days]


@router.post("/months/{month_id}/runs", status_code=status.HTTP_201_CREATED)
async def create_run(month_id: int, data: RunInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "payroll", "create")
    month = await _month(db, actor, month_id, lock=True)
    if month.status != "open":
        raise HTTPException(status_code=409, detail="Хаагдсан сарын бодолт өөрчлөх боломжгүй.")
    first, last = date(month.year, month.month, 1), date(month.year, month.month, calendar.monthrange(month.year, month.month)[1])
    if not first <= data.pay_date <= last:
        raise HTTPException(status_code=422, detail="Төлбөрийн өдөр сонгосон сард багтах ёстой.")
    if data.cutoff_date and data.cutoff_date > data.pay_date:
        raise HTTPException(status_code=422, detail="Таслах өдөр төлбөрийн өдрөөс хойш байж болохгүй.")
    if data.run_type == "final" and data.employee_ids:
        raise HTTPException(status_code=422, detail="Сүүл цалингийн бодолт бүх eligible ажилтныг хамарна.")
    if data.run_type == "final":
        prior_final = await db.scalar(select(MonthlyPayrollRun.id).where(
            MonthlyPayrollRun.month_id == month.id, MonthlyPayrollRun.run_type == "final",
        ))
        if prior_final:
            raise HTTPException(status_code=409, detail="Сард зөвхөн нэг сүүл цалингийн бодолт үүсгэж болно.")
    else:
        duplicate = await db.scalar(select(MonthlyPayrollRun.id).where(
            MonthlyPayrollRun.month_id == month.id, MonthlyPayrollRun.run_type == "advance",
            MonthlyPayrollRun.pay_date == data.pay_date,
        ))
        if duplicate:
            raise HTTPException(status_code=409, detail="Энэ төлбөрийн өдөр урьдчилгааны бодолт байна.")
    workers = await _profiles_for_month(db, actor, month, data.department_id)
    eligible = []
    for employee, details, profile, history, segments in workers:
        # One final register covers every worker in the earning month;
        # individual payment dates stay on the HR profiles.
        if data.run_type == "advance":
            if profile is None:
                continue
            if data.employee_ids is not None:
                if employee.id not in data.employee_ids:
                    continue
            else:
                days = profile.pay_days or []
                expected_day = next((day for day in days[:-1] if min(day, last.day) == data.pay_date.day), None)
                if expected_day is None:
                    continue
        department_id = details.department_id if details else None
        department_name = await db.scalar(select(Department.name).where(Department.id == department_id, Department.organization_id == actor.organization_id)) if department_id else None
        final_pay_date = None
        if data.run_type == "final" and profile is not None and profile.pay_days:
            final_pay_date = date(month.year, month.month, min(profile.pay_days[-1], last.day))
        payout_date = final_pay_date or data.pay_date
        identity = {"employee_id": employee.id, "name": employee.name, "rd": (employee.metadata_json or {}).get("rd"), "job_title": details.job_title if details else employee.job_title, "department_id": department_id, "department": department_name or "Бусад", "pay_date": payout_date.isoformat()}
        if profile is None:
            profile_data = {"complete": False, "validation_issues": ["profile_missing"], "base_salary": "0", "salary_segments": [], "salary_type": "PRORATION", "meal_allowance": "0", "commute_allowance": "0", "payment_frequency": "MONTHLY", "pay_days": [25], "advance_basis": "FIXED", "advance_amount": "0", "advance_percent": "40", "advance_values": [], "daily_norm_hours": "8", "insured_type": "01001", "tax_relief_eligible": True}
        else:
            days = profile.pay_days or []
            issues = ["salary_history_missing_or_incomplete"] if history is None else []
            profile_data = {"complete": not issues, "validation_issues": issues, "base_salary": str(history.monthly_salary if history else 0), "salary_segments": segments, "salary_type": profile.salary_type, "meal_allowance": str(profile.meal_allowance), "commute_allowance": str(profile.commute_allowance), "payment_frequency": profile.payment_frequency, "pay_days": days, "advance_basis": profile.advance_basis, "advance_amount": str(profile.advance_amount), "advance_percent": str(profile.advance_percent), "advance_values": profile.advance_values or [], "daily_norm_hours": str(profile.daily_norm_hours), "insured_type": profile.insured_type, "tax_relief_eligible": profile.tax_relief_eligible}
        eligible.append((employee, identity, profile_data))
    eligible_ids = {employee.id for employee, _, _ in eligible}
    if data.employee_ids and eligible_ids != set(data.employee_ids):
        raise HTTPException(status_code=422, detail={"code": "monthly_payroll_advance_worker_invalid", "employee_ids": sorted(set(data.employee_ids) - eligible_ids), "message": "Нэг удаагийн урьдчилгаанд цалингийн профайлтай ажилтныг сонгоно уу."})
    if not eligible:
        raise HTTPException(status_code=422, detail="Төлбөрийн өдөрт тохирох идэвхтэй ажилтан, цалингийн профайл олдсонгүй.")
    run = MonthlyPayrollRun(
        organization_id=actor.organization_id, month_id=month.id, run_type=data.run_type,
        pay_date=data.pay_date, cutoff_date=data.cutoff_date or (data.pay_date - timedelta(days=1) if data.run_type == "advance" else None),
        department_id=data.department_id, note=data.note, created_by_account_id=actor.account_id,
    )
    db.add(run)
    await db.flush()
    if data.run_type == "final":
        advance_runs = (await db.execute(select(MonthlyPayrollRun).where(
            MonthlyPayrollRun.month_id == month.id, MonthlyPayrollRun.run_type == "advance",
            MonthlyPayrollRun.status.in_(("approved", "paid", "closed")), MonthlyPayrollRun.pay_date <= last,
        ).order_by(MonthlyPayrollRun.pay_date))).scalars().all()
        snapshot: dict[str, dict[str, list[str]]] = {}
        for advance_run in advance_runs:
            advance_rows = (await db.execute(select(MonthlyPayrollRunRow).where(MonthlyPayrollRunRow.run_id == advance_run.id))).scalars().all()
            for advance_row in advance_rows:
                item = snapshot.setdefault(str(advance_row.employee_id), {"amounts": [], "run_ids": []})
                item["amounts"].append(str(advance_row.result.get("advance", "0")))
                item["run_ids"].append(str(advance_run.id))
        run.advance_snapshot = snapshot
    calendar_overrides = {date.fromisoformat(key): value for key, value in month.calendar_snapshot.items()}
    new_rows = []
    for employee, identity, profile_data in eligible:
        payout_date = date.fromisoformat(identity["pay_date"])
        attendance = await _attendance_inputs(
            db, actor.organization_id, employee.id, month,
            run.cutoff_date if run.run_type == "advance" else None,
            amount(profile_data["daily_norm_hours"]), calendar_overrides,
        )
        payout = await db.scalar(select(EmployeeBankAccount).where(
            EmployeeBankAccount.employee_id == employee.id,
            EmployeeBankAccount.is_primary.is_(True), EmployeeBankAccount.valid_from <= payout_date,
            (EmployeeBankAccount.valid_to.is_(None) | (EmployeeBankAccount.valid_to >= payout_date)),
        ).order_by(EmployeeBankAccount.valid_from.desc(), EmployeeBankAccount.id.desc()).limit(1))
        payout_snapshot = None
        if payout:
            payout_snapshot = encrypt_secret(json.dumps({
                "bank_code": payout.bank_code,
                "account_number": decrypt_secret(payout.account_number_ciphertext),
                "account_holder": decrypt_secret(payout.account_holder_ciphertext) if payout.account_holder_ciphertext else employee.name,
            }, ensure_ascii=False))
        attendance["_source_snapshot"] = {key: attendance.get(key) for key in ("worked_normal_hours", "worked_to_date_hours", "elapsed_planned_days", "overtime_hours", "day_lines", "missing_dates", "approved_leave_days", "time_source")}
        row = MonthlyPayrollRunRow(
            organization_id=actor.organization_id, run_id=run.id, employee_id=employee.id,
            identity_snapshot=identity, profile_snapshot=profile_data,
            payout_snapshot_ciphertext=payout_snapshot,
            inputs={**attendance, "leave_pay": "0", "bonus": "0", "other_deductions": [], **({"one_off_advance": True} if run.run_type == "advance" and data.employee_ids is not None else {})},
        )
        db.add(row)
        new_rows.append(row)
    await db.flush()
    for row in new_rows:
        await _calculate_row(db, month, run, row)
    await db.commit()
    await db.refresh(run)
    return _run_out(run)


@router.get("/runs/{run_id}")
async def get_run(run_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "payroll", "view_salary")
    run = await _run(db, actor, run_id)
    rows = (await db.execute(select(MonthlyPayrollRunRow).where(
        MonthlyPayrollRunRow.run_id == run.id, MonthlyPayrollRunRow.organization_id == actor.organization_id,
    ).order_by(MonthlyPayrollRunRow.id))).scalars().all()
    audits = (await db.execute(select(MonthlyPayrollRowAudit).where(
        MonthlyPayrollRowAudit.organization_id == actor.organization_id,
        MonthlyPayrollRowAudit.run_id == run.id,
    ).order_by(MonthlyPayrollRowAudit.id))).scalars().all()
    by_row: dict[int, list[dict[str, Any]]] = {}
    for audit in audits:
        by_row.setdefault(audit.row_id, []).append({"field": audit.field_name, "old": audit.old_value, "new": audit.new_value, "reason": audit.reason, "account_id": audit.account_id, "at": audit.created_at.isoformat()})
    return {**_run_out(run), "rows": [{**_row_out(row), "audit": by_row.get(row.id, [])} for row in rows]}


@router.put("/runs/{run_id}/rows/{employee_id}")
async def update_row(run_id: int, employee_id: int, data: RowInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "payroll", "create")
    run = await _run(db, actor, run_id, lock=True)
    if run.status != "draft":
        raise HTTPException(status_code=409, detail="Баталсан бодолтын мөр засах боломжгүй.")
    row = await db.scalar(select(MonthlyPayrollRunRow).where(
        MonthlyPayrollRunRow.run_id == run.id, MonthlyPayrollRunRow.employee_id == employee_id,
        MonthlyPayrollRunRow.organization_id == actor.organization_id,
    ).with_for_update())
    if not row:
        raise HTTPException(status_code=404, detail="Бодолтын ажилтан олдсонгүй.")
    if row.status != "draft":
        raise HTTPException(status_code=409, detail="Баталсан мөрийг засах боломжгүй.")
    changes = data.model_dump(exclude_unset=True, exclude={"reason"})
    before = dict(row.inputs or {})
    after = {**before, **_json_value(changes)}
    if data.fixed_advance is not None:
        after["fixed_advance"] = str(data.fixed_advance)
    if data.advance_percent is not None:
        after["advance_percent"] = str(data.advance_percent)
    row.inputs = after
    db.add(MonthlyPayrollRowAudit(organization_id=actor.organization_id, run_id=run.id, row_id=row.id, account_id=actor.account_id, field_name="inputs", old_value=before, new_value=after, reason=data.reason))
    month = await _month(db, actor, run.month_id)
    try:
        await _calculate_row(db, month, run, row)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "payroll_row_invalid", "message": str(exc)}) from exc
    await db.commit()
    await db.refresh(row)
    return _row_out(row)


@router.post("/runs/{run_id}/rows/{employee_id}/revert-overrides")
async def revert_row_overrides(run_id: int, employee_id: int, data: UnlockInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "payroll", "create")
    run = await _run(db, actor, run_id, lock=True)
    if run.status != "draft":
        raise HTTPException(status_code=409, detail="Зөвхөн ноорог бодолтын оролтыг буцаах боломжтой.")
    row = await db.scalar(select(MonthlyPayrollRunRow).where(MonthlyPayrollRunRow.run_id == run.id, MonthlyPayrollRunRow.employee_id == employee_id, MonthlyPayrollRunRow.organization_id == actor.organization_id).with_for_update())
    if row is None or row.status != "draft":
        raise HTTPException(status_code=404 if row is None else 409, detail="Ноорог ажилтны мөр олдсонгүй.")
    before = dict(row.inputs or {})
    source = dict(before.get("_source_snapshot") or {})
    after = {**before, **source, "leave_pay": "0", "bonus": "0", "other_deductions": []}
    for key in ("fixed_advance", "advance_percent", "advance_basis", "other_deduction_amount", "other_deduction_type", "other_deduction_note"):
        after.pop(key, None)
    row.inputs = after
    month = await _month(db, actor, run.month_id)
    await _calculate_row(db, month, run, row)
    db.add(MonthlyPayrollRowAudit(organization_id=actor.organization_id, run_id=run.id, row_id=row.id, account_id=actor.account_id, field_name="overrides_reverted", old_value=before, new_value=after, reason=data.reason.strip()))
    await db.commit()
    await db.refresh(row)
    return _row_out(row)


@router.post("/runs/{run_id}/rows/{employee_id}/computed-overrides")
async def override_computed_cell(run_id: int, employee_id: int, data: ComputedOverrideInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "payroll", "create")
    run = await _run(db, actor, run_id, lock=True)
    if run.status != "draft":
        raise HTTPException(status_code=409, detail="Зөвхөн ноорог бодолтын тооцсон дүнг засна.")
    row = await db.scalar(select(MonthlyPayrollRunRow).where(MonthlyPayrollRunRow.run_id == run.id, MonthlyPayrollRunRow.employee_id == employee_id, MonthlyPayrollRunRow.organization_id == actor.organization_id).with_for_update())
    if row is None or row.status != "draft":
        raise HTTPException(status_code=404 if row is None else 409, detail="Ноорог ажилтны мөр олдсонгүй.")
    if not row.profile_snapshot.get("complete", True):
        raise HTTPException(status_code=409, detail={"code": "monthly_payroll_profile_incomplete", "employee_id": employee_id})
    before_result, before_inputs = dict(row.result or {}), dict(row.inputs or {})
    overrides = dict(before_inputs.get("_computed_overrides") or {})
    overrides[data.field] = str(data.value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    row.inputs = {**before_inputs, "_computed_overrides": overrides}
    month = await _month(db, actor, run.month_id)
    await _calculate_row(db, month, run, row)
    db.add(MonthlyPayrollRowAudit(organization_id=actor.organization_id, run_id=run.id, row_id=row.id, account_id=actor.account_id, field_name=f"computed:{data.field}", old_value=before_result.get(data.field), new_value=row.result.get(data.field), reason=data.reason.strip()))
    await db.commit()
    await db.refresh(row)
    return _row_out(row)


@router.post("/runs/{run_id}/rows/{employee_id}/computed-overrides/revert")
async def revert_computed_cell_override(run_id: int, employee_id: int, data: ComputedOverrideRevertInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "payroll", "create")
    run = await _run(db, actor, run_id, lock=True)
    if run.status != "draft":
        raise HTTPException(status_code=409, detail="Зөвхөн ноорог бодолтын тооцсон дүнг буцаана.")
    row = await db.scalar(select(MonthlyPayrollRunRow).where(MonthlyPayrollRunRow.run_id == run.id, MonthlyPayrollRunRow.employee_id == employee_id, MonthlyPayrollRunRow.organization_id == actor.organization_id).with_for_update())
    if row is None or row.status != "draft":
        raise HTTPException(status_code=404 if row is None else 409, detail="Ноорог ажилтны мөр олдсонгүй.")
    before_result, inputs = dict(row.result or {}), dict(row.inputs or {})
    overrides = dict(inputs.get("_computed_overrides") or {})
    if data.field not in overrides:
        raise HTTPException(status_code=409, detail="Энэ дүнд засвар бүртгэгдээгүй байна.")
    overrides.pop(data.field)
    if overrides:
        inputs["_computed_overrides"] = overrides
    else:
        inputs.pop("_computed_overrides", None)
    row.inputs = inputs
    month = await _month(db, actor, run.month_id)
    await _calculate_row(db, month, run, row)
    db.add(MonthlyPayrollRowAudit(organization_id=actor.organization_id, run_id=run.id, row_id=row.id, account_id=actor.account_id, field_name=f"computed:{data.field}:revert", old_value=before_result.get(data.field), new_value=row.result.get(data.field), reason=data.reason.strip()))
    await db.commit()
    await db.refresh(row)
    return _row_out(row)


@router.post("/runs/{run_id}/rows/{employee_id}/flag")
async def flag_row(run_id: int, employee_id: int, data: FlagInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "payroll", "create")
    run = await _run(db, actor, run_id, lock=True)
    if run.status != "draft":
        raise HTTPException(status_code=409, detail="Зөвхөн ноорог бодолтын мөрийг тэмдэглэнэ.")
    row = await db.scalar(select(MonthlyPayrollRunRow).where(
        MonthlyPayrollRunRow.run_id == run.id,
        MonthlyPayrollRunRow.employee_id == employee_id,
        MonthlyPayrollRunRow.organization_id == actor.organization_id,
    ).with_for_update())
    if not row:
        raise HTTPException(status_code=404, detail="Бодолтын ажилтан олдсонгүй.")
    if row.status not in {"draft", "flagged"}:
        raise HTTPException(status_code=409, detail="Баталсан мөрийг тэмдэглэх боломжгүй.")
    before = {"status": row.status, "flag_reason": (row.inputs or {}).get("flag_reason")}
    row.status = "flagged"
    row.inputs = {**(row.inputs or {}), "flag_reason": data.reason.strip()}
    row.warnings = list(dict.fromkeys([*(row.warnings or []), "row_flagged"]))
    db.add(MonthlyPayrollRowAudit(organization_id=actor.organization_id, run_id=run.id, row_id=row.id, account_id=actor.account_id, field_name="status", old_value=before, new_value={"status": "flagged", "flag_reason": data.reason.strip()}, reason=data.reason.strip()))
    await db.commit()
    return _row_out(row)


@router.post("/runs/{run_id}/rows/{employee_id}/unflag")
async def unflag_row(run_id: int, employee_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "payroll", "create")
    run = await _run(db, actor, run_id, lock=True)
    if run.status != "draft":
        raise HTTPException(status_code=409, detail="Зөвхөн ноорог бодолтын мөрийн тэмдэглэгээг арилгана.")
    row = await db.scalar(select(MonthlyPayrollRunRow).where(
        MonthlyPayrollRunRow.run_id == run.id,
        MonthlyPayrollRunRow.employee_id == employee_id,
        MonthlyPayrollRunRow.organization_id == actor.organization_id,
    ).with_for_update())
    if not row:
        raise HTTPException(status_code=404, detail="Бодолтын ажилтан олдсонгүй.")
    if row.status != "flagged":
        raise HTTPException(status_code=409, detail="Мөр тэмдэглэгдээгүй байна.")
    inputs = dict(row.inputs or {})
    reason = inputs.pop("flag_reason", None)
    row.inputs = inputs
    row.status = "draft"
    row.warnings = [warning for warning in (row.warnings or []) if warning != "row_flagged"]
    db.add(MonthlyPayrollRowAudit(organization_id=actor.organization_id, run_id=run.id, row_id=row.id, account_id=actor.account_id, field_name="status", old_value={"status": "flagged", "flag_reason": reason}, new_value={"status": "draft"}, reason="Тэмдэглэгээ арилгав"))
    await db.commit()
    return _row_out(row)


@router.post("/runs/{run_id}/refresh-time")
async def refresh_run_time(run_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "payroll", "calculate")
    run = await _run(db, actor, run_id, lock=True)
    if run.status != "draft":
        raise HTTPException(status_code=409, detail="Ноорог бодолтын цагийн мэдээллийг шинэчилнэ.")
    month = await _month(db, actor, run.month_id)
    rows = (await db.execute(select(MonthlyPayrollRunRow).where(
        MonthlyPayrollRunRow.run_id == run.id,
        MonthlyPayrollRunRow.organization_id == actor.organization_id,
    ).with_for_update())).scalars().all()
    changed = 0
    calendar_overrides = {date.fromisoformat(key): value for key, value in month.calendar_snapshot.items()}
    canonical_keys = ("worked_normal_hours", "worked_to_date_hours", "elapsed_planned_days", "overtime_hours", "day_lines", "missing_dates", "approved_leave_days", "time_source")
    for row in rows:
        if row.status != "draft" or not row.profile_snapshot.get("complete", True):
            continue
        fresh = await _attendance_inputs(db, actor.organization_id, row.employee_id, month, run.cutoff_date if run.run_type == "advance" else None, amount(row.profile_snapshot.get("daily_norm_hours", 8)), calendar_overrides)
        inputs = dict(row.inputs or {})
        source = dict(inputs.get("_source_snapshot") or {})
        before = dict(inputs)
        new_source = {key: fresh.get(key) for key in canonical_keys}
        for key in canonical_keys:
            if inputs.get(key) == source.get(key):
                inputs[key] = fresh.get(key)
        inputs["_source_snapshot"] = new_source
        if inputs != before:
            row.inputs = inputs
            await _calculate_row(db, month, run, row)
            db.add(MonthlyPayrollRowAudit(organization_id=actor.organization_id, run_id=run.id, row_id=row.id, account_id=actor.account_id, field_name="time_inputs", old_value=source, new_value=new_source, reason="HR цаг, чөлөө, календарийн мэдээллийг шинэчлэв"))
            changed += 1
    await db.commit()
    return {"run_id": run.id, "updated_rows": changed, "rows": [_row_out(row) for row in rows]}


@router.post("/runs/{run_id}/sync-workers")
async def sync_run_workers(run_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "payroll", "create")
    run = await _run(db, actor, run_id, lock=True)
    if run.status != "draft":
        raise HTTPException(status_code=409, detail="Зөвхөн ноорог бодолтын ажилтны жагсаалтыг шинэчилнэ.")
    month = await _month(db, actor, run.month_id, lock=True)
    if month.status != "open":
        raise HTTPException(status_code=409, detail="Хаагдсан сарын бодолтыг шинэчлэх боломжгүй.")
    existing_ids = set((await db.execute(select(MonthlyPayrollRunRow.employee_id).where(MonthlyPayrollRunRow.run_id == run.id))).scalars().all())
    last = date(month.year, month.month, calendar.monthrange(month.year, month.month)[1])
    workers = await _profiles_for_month(db, actor, month, run.department_id)
    calendar_overrides = {date.fromisoformat(key): value for key, value in month.calendar_snapshot.items()}
    added = []
    for employee, details, profile, history, segments in workers:
        if employee.id in existing_ids:
            continue
        if run.run_type == "advance" and (profile is None or not any(min(day, last.day) == run.pay_date.day for day in (profile.pay_days or [])[:-1])):
            continue
        department_id = details.department_id if details else None
        department_name = await db.scalar(select(Department.name).where(Department.id == department_id, Department.organization_id == actor.organization_id)) if department_id else None
        payout_date = date(month.year, month.month, min(profile.pay_days[-1], last.day)) if run.run_type == "final" and profile and profile.pay_days else run.pay_date
        identity = {"employee_id": employee.id, "name": employee.name, "rd": (employee.metadata_json or {}).get("rd"), "job_title": details.job_title if details else employee.job_title, "department_id": department_id, "department": department_name or "Бусад", "pay_date": payout_date.isoformat()}
        if profile is None:
            profile_data = {"complete": False, "validation_issues": ["profile_missing"], "base_salary": "0", "salary_segments": [], "salary_type": "PRORATION", "meal_allowance": "0", "commute_allowance": "0", "payment_frequency": "MONTHLY", "pay_days": [25], "advance_basis": "FIXED", "advance_amount": "0", "advance_percent": "40", "advance_values": [], "daily_norm_hours": "8", "insured_type": "01001", "tax_relief_eligible": True}
        else:
            issues = ["salary_history_missing_or_incomplete"] if history is None else []
            profile_data = {"complete": not issues, "validation_issues": issues, "base_salary": str(history.monthly_salary if history else 0), "salary_segments": segments, "salary_type": profile.salary_type, "meal_allowance": str(profile.meal_allowance), "commute_allowance": str(profile.commute_allowance), "payment_frequency": profile.payment_frequency, "pay_days": profile.pay_days or [], "advance_basis": profile.advance_basis, "advance_amount": str(profile.advance_amount), "advance_percent": str(profile.advance_percent), "advance_values": profile.advance_values or [], "daily_norm_hours": str(profile.daily_norm_hours), "insured_type": profile.insured_type, "tax_relief_eligible": profile.tax_relief_eligible}
        attendance = await _attendance_inputs(db, actor.organization_id, employee.id, month, run.cutoff_date if run.run_type == "advance" else None, amount(profile_data["daily_norm_hours"]), calendar_overrides)
        attendance["_source_snapshot"] = {key: attendance.get(key) for key in ("worked_normal_hours", "worked_to_date_hours", "elapsed_planned_days", "overtime_hours", "day_lines", "missing_dates", "approved_leave_days", "time_source")}
        payout = await db.scalar(select(EmployeeBankAccount).where(EmployeeBankAccount.employee_id == employee.id, EmployeeBankAccount.is_primary.is_(True), EmployeeBankAccount.valid_from <= payout_date, (EmployeeBankAccount.valid_to.is_(None) | (EmployeeBankAccount.valid_to >= payout_date))).order_by(EmployeeBankAccount.valid_from.desc(), EmployeeBankAccount.id.desc()).limit(1))
        payout_snapshot = encrypt_secret(json.dumps({"bank_code": payout.bank_code, "account_number": decrypt_secret(payout.account_number_ciphertext), "account_holder": decrypt_secret(payout.account_holder_ciphertext) if payout.account_holder_ciphertext else employee.name}, ensure_ascii=False)) if payout else None
        row = MonthlyPayrollRunRow(organization_id=actor.organization_id, run_id=run.id, employee_id=employee.id, identity_snapshot=identity, profile_snapshot=profile_data, payout_snapshot_ciphertext=payout_snapshot, inputs={**attendance, "leave_pay": "0", "bonus": "0", "other_deductions": []})
        db.add(row)
        await db.flush()
        await _calculate_row(db, month, run, row)
        db.add(MonthlyPayrollRowAudit(organization_id=actor.organization_id, run_id=run.id, row_id=row.id, account_id=actor.account_id, field_name="worker_sync", old_value=None, new_value={"employee_id": employee.id, "pay_date": payout_date.isoformat()}, reason="Ажилтны жагсаалтыг HR бүртгэлээс шинэчлэв"))
        added.append(row)
    await db.commit()
    return {"run_id": run.id, "added_workers": len(added), "run": await get_run(run.id, db, actor)}


@router.get("/runs/{run_id}/import-template")
async def payroll_input_template(run_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "payroll", "export")
    await _run(db, actor, run_id)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Оролтын засвар"
    sheet.append(["employee_id", "worked_normal_hours", "worked_to_date_hours", "overtime_weekday", "overtime_rest_day", "overtime_public_holiday", "leave_pay", "bonus", "deduction_type", "deduction_amount", "deduction_note", "reason"])
    sheet.append(["Ажилтны ID", "Ердийн цаг", "Урьдчилгааны цаг", "Ажлын өдрийн илүү цаг", "Амралтын өдрийн илүү цаг", "Баярын өдрийн илүү цаг", "Амралтын олговор", "Урамшуулал", "Суутгалын төрөл", "Суутгалын дүн", "Суутгалын тайлбар", "Засварын шалтгаан"])
    stream = io.BytesIO()
    workbook.save(stream)
    return Response(content=stream.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f'attachment; filename="monthly-payroll-{run_id}-input-template.xlsx"'})


@router.post("/runs/{run_id}/import-xlsx")
async def import_payroll_inputs(run_id: int, file: UploadFile = File(...), db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "payroll", "create")
    run = await _run(db, actor, run_id, lock=True)
    if run.status != "draft":
        raise HTTPException(status_code=409, detail="Зөвхөн ноорог бодолтод Excel оролт оруулна.")
    payload = await file.read(5 * 1024 * 1024 + 1)
    if len(payload) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Excel файл 5 MB-аас бага байх ёстой.")
    try:
        workbook = load_workbook(io.BytesIO(payload), read_only=True, data_only=True)
        sheet = workbook.active
        values = list(sheet.iter_rows(values_only=True))
        headers = [str(value or "").strip() for value in values[0]] if values else []
        records = [dict(zip(headers, row)) for row in values[2:] if any(value not in (None, "") for value in row)]
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Excel загварыг уншиж чадсангүй.") from exc
    required = {"employee_id", "reason"}
    if not required.issubset(headers) or len(headers) != len(set(headers)):
        raise HTTPException(status_code=422, detail="Ажилтны ID, шалтгаан баганатай цалингийн загвар ашиглана уу.")
    employee_ids = []
    for index, record in enumerate(records, start=3):
        try:
            employee_ids.append(int(record.get("employee_id")))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=f"{index}-р мөрийн ажилтны ID буруу байна.") from exc
    if len(employee_ids) != len(set(employee_ids)):
        raise HTTPException(status_code=422, detail="Нэг ажилтныг файлд давхар оруулсан байна.")
    rows = (await db.execute(select(MonthlyPayrollRunRow).where(MonthlyPayrollRunRow.run_id == run.id, MonthlyPayrollRunRow.employee_id.in_(employee_ids or [-1]), MonthlyPayrollRunRow.organization_id == actor.organization_id).with_for_update())).scalars().all()
    by_employee = {row.employee_id: row for row in rows}
    if set(employee_ids) != set(by_employee):
        raise HTTPException(status_code=422, detail={"code": "monthly_payroll_import_employee_not_in_run", "employee_ids": sorted(set(employee_ids) - set(by_employee))})
    month = await _month(db, actor, run.month_id)
    changed = 0
    for record, employee_id in zip(records, employee_ids):
        row = by_employee[employee_id]
        if row.status != "draft":
            raise HTTPException(status_code=409, detail={"code": "monthly_payroll_import_row_locked", "employee_id": employee_id})
        def text_value(key: str, default: str = "0") -> str:
            value = record.get(key)
            return default if value in (None, "") else str(value).strip()
        overtime = {key: text_value(f"overtime_{key}") for key in ("weekday", "rest_day", "public_holiday")}
        deduction_amount = text_value("deduction_amount")
        try:
            deductions = [{"type": text_value("deduction_type", "Бусад"), "amount": deduction_amount, "note": text_value("deduction_note", "")} ] if amount(deduction_amount) > 0 else []
            input_data = RowInput.model_validate({"worked_normal_hours": text_value("worked_normal_hours") if run.run_type == "final" else None, "worked_to_date_hours": text_value("worked_to_date_hours"), "overtime_hours": overtime, "leave_pay": text_value("leave_pay"), "bonus": text_value("bonus"), "other_deductions": deductions, "reason": text_value("reason", "").strip()})
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail={"code": "monthly_payroll_import_value_invalid", "employee_id": employee_id}) from exc
        if not input_data.reason:
            raise HTTPException(status_code=422, detail={"code": "monthly_payroll_import_reason_required", "employee_id": employee_id})
        before = dict(row.inputs or {})
        row.inputs = {**before, **_json_value(input_data.model_dump(exclude_unset=True, exclude={"reason"}))}
        await _calculate_row(db, month, run, row)
        db.add(MonthlyPayrollRowAudit(organization_id=actor.organization_id, run_id=run.id, row_id=row.id, account_id=actor.account_id, field_name="excel_import", old_value=before, new_value=row.inputs, reason=input_data.reason))
        changed += 1
    await db.commit()
    return {"run_id": run.id, "updated_rows": changed}


@router.post("/runs/{run_id}/rows/{employee_id}/approve")
async def approve_row(run_id: int, employee_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "payroll", "approve")
    run = await _run(db, actor, run_id, lock=True)
    if run.status != "draft":
        raise HTTPException(status_code=409, detail="Ноорог бодолтын мөрийг батална.")
    row = await db.scalar(select(MonthlyPayrollRunRow).where(
        MonthlyPayrollRunRow.run_id == run.id, MonthlyPayrollRunRow.employee_id == employee_id,
        MonthlyPayrollRunRow.organization_id == actor.organization_id,
    ).with_for_update())
    if row is None:
        raise HTTPException(status_code=404, detail="Бодолтын ажилтан олдсонгүй.")
    if row.status != "draft":
        raise HTTPException(status_code=409, detail="Тэмдэглэсэн эсвэл баталсан мөрийг батлах боломжгүй.")
    month = await _month(db, actor, run.month_id)
    try:
        await _calculate_row(db, month, run, row)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "payroll_row_invalid", "message": str(exc)}) from exc
    result = row.result or {}
    blocking = sorted(set(row.warnings or []) & BLOCKING_ROW_WARNINGS)
    if blocking:
        raise HTTPException(status_code=422, detail={"code": "monthly_payroll_row_blocked", "issues": blocking})
    if run.run_type == "advance" and Decimal(result.get("advance", "0")) <= 0:
        raise HTTPException(status_code=422, detail={"code": "advance_positive", "message": "Урьдчилгаа 0-ээс их байх ёстой."})
    if run.run_type == "final" and Decimal(result.get("net_pay", "0")) < 0:
        raise HTTPException(status_code=422, detail={"code": "negative_final_pay", "message": "Сүүл цалин сөрөг байна."})
    row.status = "approved"
    row.approved_by_account_id = actor.account_id
    row.approved_at = datetime.now(timezone.utc)
    await db.commit()
    return _row_out(row)


@router.post("/runs/{run_id}/calculate")
async def calculate_run(run_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "payroll", "calculate")
    run = await _run(db, actor, run_id, lock=True)
    if run.status != "draft":
        raise HTTPException(status_code=409, detail="Ноорог төлөвтэй бодолтыг дахин тооцно.")
    month = await _month(db, actor, run.month_id)
    rows = (await db.execute(select(MonthlyPayrollRunRow).where(MonthlyPayrollRunRow.run_id == run.id).with_for_update())).scalars().all()
    try:
        for row in rows:
            await _calculate_row(db, month, run, row)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "payroll_calculation_invalid", "message": str(exc)}) from exc
    await db.commit()
    return await get_run(run.id, db, actor)


@router.get("/runs/{run_id}/export")
async def export_run(run_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "payroll", "export")
    run = await _run(db, actor, run_id)
    if run.status not in {"approved", "paid", "closed"}:
        raise HTTPException(status_code=409, detail="Баталсан бодолтын дараа Excel экспорт нээгдэнэ.")
    month = await _month(db, actor, run.month_id)
    rows = (await db.execute(select(MonthlyPayrollRunRow).where(
        MonthlyPayrollRunRow.run_id == run.id, MonthlyPayrollRunRow.organization_id == actor.organization_id,
    ).order_by(MonthlyPayrollRunRow.identity_snapshot["department_id"].astext, MonthlyPayrollRunRow.identity_snapshot["name"].astext))).scalars().all()
    workbook = Workbook()
    workbook.remove(workbook.active)
    title = f"{run.pay_date.year} оны {run.pay_date.month} сарын {run.pay_date.day}-ны {'урьдчилгаа цалин' if run.run_type == 'advance' else 'сүүл цалин'}"

    def add_sheet(name: str, headers: list[str], data: list[list[Any]], total_columns: list[int] | None = None) -> None:
        sheet = workbook.create_sheet(name)
        sheet.append([title])
        sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=max(1, len(headers)))
        sheet.cell(1, 1).font = Font(bold=True, size=14)
        sheet.append(headers)
        for cell in sheet[2]:
            cell.font = Font(bold=True)
            cell.alignment = Alignment(wrap_text=True, vertical="center")
        for values in data:
            sheet.append(values)
        for row_cells in sheet.iter_rows(min_row=3):
            for cell in row_cells:
                if isinstance(cell.value, (int, float, Decimal)):
                    cell.number_format = "#,##0"
        if data and total_columns:
            sheet.append(["НИЙТ"] + [f"=SUM({sheet.cell(3, index).column_letter}3:{sheet.cell(sheet.max_row, index).column_letter}{sheet.max_row})" if index in total_columns else "" for index in range(2, len(headers) + 1)])
            for cell in sheet[sheet.max_row]:
                cell.font = Font(bold=True)
        sheet.freeze_panes = "A3"
        sheet.sheet_properties.pageSetUpPr.fitToPage = True
        sheet.page_setup.orientation = "landscape"
        sheet.page_setup.fitToWidth = 1
        sheet.page_setup.fitToHeight = 0
        for column in sheet.columns:
            letter = column[0].column_letter
            width = min(34, max(12, max(len(str(cell.value or "")) for cell in column) + 2))
            sheet.column_dimensions[letter].width = width

    def number(value: Any) -> Decimal:
        return Decimal(str(value or 0))

    payment_rows: list[list[Any]] = []
    register_rows: list[list[Any]] = []
    overtime_rows: list[list[Any]] = []
    shi_rows: list[list[Any]] = []
    deduction_rows: list[list[Any]] = []
    summary_totals: dict[str, Decimal] = {key: Decimal("0") for key in ("gross", "employee_shi", "employer_shi", "pit", "advance", "other_deductions", "net_pay")}
    for row in rows:
        identity, profile, result, inputs = row.identity_snapshot or {}, row.profile_snapshot or {}, row.result or {}, row.inputs or {}
        name = identity.get("name", "")
        rd = identity.get("rd") or ""
        amount_key = "advance" if run.run_type == "advance" else "net_pay"
        payout = json.loads(decrypt_secret(row.payout_snapshot_ciphertext)) if row.payout_snapshot_ciphertext else {}
        payment_rows.append([name, rd, payout.get("bank_code", ""), payout.get("account_number", ""), number(result.get(amount_key)), "" if payout else "Банкны мэдээлэл дутуу"])
        if run.run_type == "advance":
            register_rows.append([identity.get("department", "Бусад"), name, rd, number(profile.get("base_salary")), number(result.get("advance"))])
            continue
        columns = ("gross", "employee_shi", "employer_shi", "pit", "advance", "other_deductions", "net_pay")
        for key in columns:
            summary_totals[key] += number(result.get(key))
        register_rows.append([identity.get("department", "Бусад"), name, rd, number(profile.get("base_salary")), number(result.get("gross")), number(result.get("employee_shi")), number(result.get("taxable_income")), number(result.get("pit")), number(result.get("relief")), number(result.get("advance")), number(result.get("other_deductions")), number(result.get("net_pay")), number(result.get("employer_shi"))])
        daily_norm = number(profile.get("daily_norm_hours", 8))
        planned_days = sum(value == CalendarDayType.WORKING.value for value in month.calendar_snapshot.values())
        planned_hours = daily_norm * max(1, planned_days)
        hourly_rate = number(profile.get("base_salary")) / planned_hours if planned_hours else Decimal("0")
        multipliers = month.rule_snapshot.get("overtime_multipliers", {})
        day_lines = inputs.get("day_lines") or []
        line_totals: dict[str, Decimal] = {}
        for day_line in day_lines:
            for bucket, hours in day_line.get("overtime_hours", {}).items():
                line_totals[bucket] = line_totals.get(bucket, Decimal("0")) + number(hours)
        aggregate_hours = {key: number(value) for key, value in (inputs.get("overtime_hours") or {}).items()}
        if day_lines and all(line_totals.get(key, Decimal("0")) == aggregate_hours.get(key, Decimal("0")) for key in set(line_totals) | set(aggregate_hours)):
            for day_line in day_lines:
                for bucket, hours in day_line.get("overtime_hours", {}).items():
                    multiplier = number(multipliers.get(bucket, 1))
                    line_rate = hourly_rate
                    work_date = date.fromisoformat(day_line["date"])
                    for segment in profile.get("salary_segments", []):
                        if date.fromisoformat(segment["valid_from"]) <= work_date <= date.fromisoformat(segment["valid_to"]):
                            segment_days = sum(value == CalendarDayType.WORKING.value and date.fromisoformat(day) >= date.fromisoformat(segment["valid_from"]) and date.fromisoformat(day) <= date.fromisoformat(segment["valid_to"]) for day, value in month.calendar_snapshot.items())
                            if segment_days:
                                line_rate = number(segment["monthly_salary"]) / (daily_norm * segment_days)
                            break
                    overtime_rows.append([name, day_line.get("date"), bucket, number(hours), multiplier, line_rate, (number(hours) * multiplier * line_rate).quantize(Decimal("1"))])
        else:
            for bucket, hours in (inputs.get("overtime_hours") or {}).items():
                multiplier = number(multipliers.get(bucket, 1))
                overtime_rows.append([name, "", bucket, number(hours), multiplier, hourly_rate, number(result.get("overtime_by_bucket", {}).get(bucket, 0))])
        shi_base = number(result.get("shi_base"))
        month_snapshot = month.rule_snapshot
        for payer, rate_map in (("Ажилтан", month_snapshot.get("employee_rates", {})), ("Байгууллага", month_snapshot.get("employer_rates", {}))):
            for fund, rate in rate_map.items():
                shi_rows.append([name, payer, fund, shi_base, number(rate), (shi_base * number(rate)).quantize(Decimal("1"))])
        for line in inputs.get("other_deductions", []):
            deduction_rows.append([name, line.get("type", ""), number(line.get("amount")), line.get("note", "")])

    if run.run_type == "advance":
        add_sheet("Урьдчилгаа", ["Хэлтэс", "Ажилтан", "РД", "Үндсэн цалин", "Урьдчилгаа"], register_rows, [4, 5])
        add_sheet("Төлбөрийн жагсаалт", ["Ажилтан", "РД", "Банк", "Данс", "Дүн", "Төлөв"], payment_rows, [5])
    else:
        add_sheet("Цалингийн хүснэгт", ["Хэлтэс", "Ажилтан", "РД", "Үндсэн цалин", "Олговол зохих", "НДШ", "Татвар ногдох", "ХХОАТ", "ХХОАТ ХӨН", "Урьдчилгаа", "Бусад суутгал", "Сүүл цалин", "БНДШ"], register_rows, list(range(4, 14)))
        summary_data = [["Нийт цалин", summary_totals["gross"]], ["Ажилтны НДШ", summary_totals["employee_shi"]], ["Ажил олгогчийн НДШ", summary_totals["employer_shi"]], ["ХХОАТ", summary_totals["pit"]], ["Урьдчилгаа", summary_totals["advance"]], ["Бусад суутгал", summary_totals["other_deductions"]], ["Сүүл цалин", summary_totals["net_pay"]], ["Account A · Нийт олговол зохих", summary_totals["gross"]], ["Account B · Байгууллагын НДШ", summary_totals["employer_shi"]], ["Нийт компанийн зардал", summary_totals["gross"] + summary_totals["employer_shi"]]]
        add_sheet("Дүн", ["Үзүүлэлт", "Дүн"], summary_data)
        add_sheet("Илүү цаг", ["Ажилтан", "Огноо", "Ангилал", "Цаг", "Үржүүлэгч", "Цагийн үнэлгээ", "Дүн"], overtime_rows, [4, 7])
        add_sheet("НДШ задаргаа", ["Ажилтан", "Төлөгч", "Сан", "Суурь", "Хувь", "Дүн"], shi_rows, [4, 6])
        add_sheet("Төлбөрийн жагсаалт", ["Ажилтан", "РД", "Банк", "Данс", "Сүүл цалин", "Төлөв"], payment_rows, [5])
        add_sheet("Бусад суутгал", ["Ажилтан", "Төрөл", "Дүн", "Тайлбар"], deduction_rows, [3])
    output = io.BytesIO()
    workbook.save(output)
    filename = f"monthly-payroll-{run.pay_date:%Y-%m-%d}.xlsx"
    return Response(content=output.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.post("/runs/{run_id}/refresh-advances")
async def refresh_advances(run_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "payroll", "calculate")
    run = await _run(db, actor, run_id, lock=True)
    if run.run_type != "final" or run.status != "draft":
        raise HTTPException(status_code=409, detail="Зөвхөн ноорог сүүл цалингийн бодолтод урьдчилгаа дахин татна.")
    month = await _month(db, actor, run.month_id)
    rows = (await db.execute(select(MonthlyPayrollRunRow).where(MonthlyPayrollRunRow.run_id == run.id).with_for_update())).scalars().all()
    snapshot: dict[str, dict[str, list[str]]] = {}
    for row in rows:
        approved, run_ids = await _approved_advances(db, run, row.employee_id)
        snapshot[str(row.employee_id)] = {"amounts": approved, "run_ids": run_ids}
    run.advance_snapshot = snapshot
    for row in rows:
        await _calculate_row(db, month, run, row)
    await db.commit()
    return await get_run(run.id, db, actor)


@router.post("/runs/{run_id}/approve")
async def approve_run(run_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "payroll", "approve")
    run = await _run(db, actor, run_id, lock=True)
    if run.status != "draft":
        raise HTTPException(status_code=409, detail="Зөвхөн ноорог бодолтыг батална.")
    month = await _month(db, actor, run.month_id)
    rows = (await db.execute(select(MonthlyPayrollRunRow).where(MonthlyPayrollRunRow.run_id == run.id).with_for_update())).scalars().all()
    try:
        for row in rows:
            if row.status != "draft":
                raise HTTPException(status_code=409, detail={"code": "monthly_payroll_row_flagged", "employee_id": row.employee_id, "message": "Тэмдэглэсэн мөрийг эхлээд шалгаж цэвэрлэнэ үү."})
            await _calculate_row(db, month, run, row)
            result = row.result or {}
            blocking = sorted(set(row.warnings or []) & BLOCKING_ROW_WARNINGS)
            if blocking:
                raise HTTPException(status_code=422, detail={"code": "monthly_payroll_row_blocked", "employee_id": row.employee_id, "issues": blocking})
            if run.run_type == "advance" and Decimal(result.get("advance", "0")) <= 0:
                raise HTTPException(status_code=422, detail={"code": "advance_positive", "message": f"{row.identity_snapshot.get('name')}: урьдчилгаа 0-ээс их байх ёстой."})
            if run.run_type == "final" and Decimal(result.get("net_pay", "0")) < 0:
                raise HTTPException(status_code=422, detail={"code": "negative_final_pay", "message": f"{row.identity_snapshot.get('name')}: сүүл цалин сөрөг байна."})
            row.status = "approved"
            row.approved_by_account_id = actor.account_id
            row.approved_at = datetime.now(timezone.utc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "payroll_approval_invalid", "message": str(exc)}) from exc
    run.status = "approved"
    run.approved_by_account_id = actor.account_id
    run.approved_at = datetime.now(timezone.utc)
    run.advance_snapshot = run.advance_snapshot or {}
    await db.commit()
    return await get_run(run.id, db, actor)


@router.post("/runs/{run_id}/paid")
async def mark_paid(run_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "payroll", "pay")
    run = await _run(db, actor, run_id, lock=True)
    if run.status != "approved":
        raise HTTPException(status_code=409, detail="Зөвхөн баталсан бодолтыг төлсөн гэж тэмдэглэнэ.")
    run.status = "paid"
    run.paid_by_account_id = actor.account_id
    run.paid_at = datetime.now(timezone.utc)
    await db.commit()
    return _run_out(run)


@router.post("/months/{month_id}/close")
async def close_month(month_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "payroll", "approve")
    await require_capability(db, actor, "payroll", "export")
    month = await _month(db, actor, month_id, lock=True)
    runs = (await db.execute(select(MonthlyPayrollRun).where(MonthlyPayrollRun.month_id == month.id).order_by(MonthlyPayrollRun.pay_date, MonthlyPayrollRun.run_type).with_for_update())).scalars().all()
    issues = await _month_close_issues(db, actor, month, runs)
    if issues:
        raise HTTPException(status_code=409, detail={"code": "monthly_payroll_close_blocked", "issues": issues, "message": "Хаалтын шалгалтын алдааг засна уу."})
    closing_stats = await _closing_stats(db, month, actor.organization_id)
    settings = await db.scalar(select(MonthlyPayrollCompanySettings).where(MonthlyPayrollCompanySettings.organization_id == actor.organization_id))
    totals = closing_stats.get("totals", {})
    closing_stats["accounting_summary"] = {
        "salary_expense": {"account_id": settings.salary_expense_account_id if settings else None, "debit": totals.get("gross", "0")},
        "employer_shi_expense": {"account_id": settings.employer_shi_account_id if settings else None, "debit": totals.get("employer_shi", "0")},
        "advance_clearing": {"account_id": settings.advance_clearing_account_id if settings else None, "credit": totals.get("advance_total", "0")},
    }
    snapshots = []
    stored_exports: dict[str, str] = {}
    for run in runs:
        run.status = "closed"
        rows = (await db.execute(select(MonthlyPayrollRunRow).where(MonthlyPayrollRunRow.run_id == run.id).order_by(MonthlyPayrollRunRow.id))).scalars().all()
        snapshots.append({"run": _run_out(run), "rows": [_row_out(row, include_payout_snapshot=True) for row in rows]})
        exported = await export_run(run.id, db, actor)
        stored_exports[str(run.id)] = base64.b64encode(exported.body).decode("ascii")
    audits = (await db.execute(select(MonthlyPayrollRowAudit).where(MonthlyPayrollRowAudit.organization_id == actor.organization_id, MonthlyPayrollRowAudit.run_id.in_([run.id for run in runs])).order_by(MonthlyPayrollRowAudit.id))).scalars().all()
    previous = await db.scalar(select(MonthlyPayrollArchive.version).where(MonthlyPayrollArchive.month_id == month.id).order_by(MonthlyPayrollArchive.version.desc()).limit(1)) or 0
    archive = MonthlyPayrollArchive(
        organization_id=actor.organization_id, month_id=month.id, version=previous + 1,
        closed_by_account_id=actor.account_id,
        snapshot={"month": {"year": month.year, "month": month.month, "rule_snapshot": month.rule_snapshot, "calendar_snapshot": month.calendar_snapshot}, "runs": snapshots, "closing_stats": closing_stats, "accounting_summary": closing_stats["accounting_summary"], "row_audit": [{"row_id": row.row_id, "field": row.field_name, "old": row.old_value, "new": row.new_value, "reason": row.reason, "account_id": row.account_id, "at": row.created_at.isoformat()} for row in audits], "exports_base64": stored_exports},
    )
    db.add(archive)
    month.status = "closed"
    month.closed_by_account_id = actor.account_id
    month.closed_at = datetime.now(timezone.utc)
    await db.commit()
    return {"month_id": month.id, "archive_version": archive.version, "closed_at": month.closed_at.isoformat(), "closing_stats": closing_stats}


@router.get("/months/{month_id}/closing-stats")
async def get_closing_stats(month_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "payroll", "view_salary")
    month = await _month(db, actor, month_id)
    return await _closing_stats(db, month, actor.organization_id)


@router.post("/months/{month_id}/unlock")
async def unlock_month(month_id: int, data: UnlockInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "payroll", "administer")
    month = await _month(db, actor, month_id, lock=True)
    if month.status != "closed":
        raise HTTPException(status_code=409, detail="Зөвхөн хаагдсан сарыг нээнэ.")
    runs = (await db.execute(select(MonthlyPayrollRun).where(MonthlyPayrollRun.month_id == month.id).with_for_update())).scalars().all()
    before = {"status": month.status, "run_statuses": {str(run.id): run.status for run in runs}}
    month.status = "open"
    for run in runs:
        run.status = "draft"
        run.approved_by_account_id = None
        run.approved_at = None
        rows = (await db.execute(select(MonthlyPayrollRunRow).where(MonthlyPayrollRunRow.run_id == run.id).with_for_update())).scalars().all()
        for row in rows:
            row.status = "draft"
            row.approved_by_account_id = None
            row.approved_at = None
    await record_change(db, actor=actor, topic="payroll", aggregate_type="monthly_payroll_month", aggregate_id=month.id, operation="unlocked", before=before, after={"status": month.status, "reason": data.reason.strip()})
    await db.commit()
    return {"month_id": month.id, "status": month.status, "reason": data.reason.strip()}


@router.get("/months/{month_id}/archives")
async def list_archives(month_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "payroll", "view_salary")
    await _month(db, actor, month_id)
    rows = (await db.execute(select(MonthlyPayrollArchive).where(
        MonthlyPayrollArchive.month_id == month_id, MonthlyPayrollArchive.organization_id == actor.organization_id,
    ).order_by(MonthlyPayrollArchive.version.desc()))).scalars().all()
    def public_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in snapshot.items() if key != "exports_base64"}
    return [{"id": row.id, "version": row.version, "closed_at": row.closed_at.isoformat(), "snapshot": public_snapshot(row.snapshot)} for row in rows]


@router.get("/archives/{archive_id}/runs/{run_id}/export")
async def download_archived_run_export(archive_id: int, run_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "payroll", "export")
    archive = await db.scalar(select(MonthlyPayrollArchive).where(
        MonthlyPayrollArchive.id == archive_id,
        MonthlyPayrollArchive.organization_id == actor.organization_id,
    ))
    if not archive:
        raise HTTPException(status_code=404, detail="Payroll archive not found")
    encoded = (archive.snapshot or {}).get("exports_base64", {}).get(str(run_id))
    if not encoded:
        raise HTTPException(status_code=404, detail="Archived export not found")
    payload = base64.b64decode(encoded)
    return Response(content=payload, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f'attachment; filename="monthly-payroll-archive-{archive.version}-{run_id}.xlsx"'})


async def _report_data(db: AsyncSession, actor: ActorContext, report_kind: str, from_month: str, to_month: str, department_id: int | None) -> dict[str, Any]:
    kinds = {"salary-register", "tax-shi", "overtime", "department-cost", "advance-final", "other-deductions"}
    if report_kind not in kinds:
        raise HTTPException(status_code=404, detail="Payroll report not found")
    try:
        start, end = date.fromisoformat(f"{from_month}-01"), date.fromisoformat(f"{to_month}-01")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Сарын мужийг YYYY-MM форматаар оруулна уу.") from exc
    if start > end:
        raise HTTPException(status_code=422, detail="Эхлэх сар төгсөх сараас хойш байж болохгүй.")
    query_start = date(start.year, 1, 1) if report_kind == "tax-shi" else start
    month_key = MonthlyPayrollMonth.year * 100 + MonthlyPayrollMonth.month
    months = (await db.execute(select(MonthlyPayrollMonth).where(
        MonthlyPayrollMonth.organization_id == actor.organization_id,
        month_key >= query_start.year * 100 + query_start.month,
        month_key <= end.year * 100 + end.month,
    ).order_by(MonthlyPayrollMonth.year, MonthlyPayrollMonth.month))).scalars().all()
    source_runs: list[dict[str, Any]] = []
    for month in months:
        if month.status == "closed":
            archive = await db.scalar(select(MonthlyPayrollArchive).where(MonthlyPayrollArchive.month_id == month.id).order_by(MonthlyPayrollArchive.version.desc()).limit(1))
            if archive:
                source_runs.extend({**item["run"], "rows": item["rows"], "month": f"{month.year:04d}-{month.month:02d}"} for item in archive.snapshot.get("runs", []))
                continue
        runs = (await db.execute(select(MonthlyPayrollRun).where(MonthlyPayrollRun.month_id == month.id, MonthlyPayrollRun.organization_id == actor.organization_id))).scalars().all()
        for run in runs:
            rows = (await db.execute(select(MonthlyPayrollRunRow).where(MonthlyPayrollRunRow.run_id == run.id, MonthlyPayrollRunRow.organization_id == actor.organization_id))).scalars().all()
            source_runs.append({**_run_out(run), "rows": [_row_out(row) for row in rows], "month": f"{month.year:04d}-{month.month:02d}"})
    output: list[dict[str, Any]] = []
    for run in source_runs:
        if report_kind == "advance-final" and run["run_type"] == "advance":
            output.append({"month": run["month"], "run_type": run["run_type"], "pay_date": run["pay_date"], "total": sum((Decimal(str(row.get("result", {}).get("advance", 0))) for row in run["rows"]), Decimal("0"))})
            continue
        if run["run_type"] != "final" and report_kind != "advance-final":
            continue
        for row in run["rows"]:
            identity, result, inputs = row.get("identity", {}), row.get("result", {}), row.get("inputs", {})
            if department_id and identity.get("department_id") != department_id:
                continue
            base = {"month": run["month"], "employee_id": row.get("employee_id"), "employee_name": identity.get("name", ""), "department": identity.get("department", "Бусад"), "run_type": run["run_type"], "pay_date": run["pay_date"]}
            if report_kind == "salary-register":
                output.append({**base, **{key: result.get(key, "0") for key in ("gross", "taxable_income", "employee_shi", "employer_shi", "pit", "relief", "advance", "other_deductions", "net_pay")}})
            elif report_kind == "tax-shi":
                output.append({**base, **{key: result.get(key, "0") for key in ("gross", "taxable_income", "employee_shi", "employer_shi", "pit", "relief", "net_pay")}})
            elif report_kind == "overtime":
                for bucket, hours in (inputs.get("overtime_hours") or {}).items():
                    output.append({**base, "bucket": bucket, "hours": hours, "amount": result.get("overtime_by_bucket", {}).get(bucket, "0")})
            elif report_kind == "department-cost":
                output.append({**base, "gross": result.get("gross", "0"), "employee_shi": result.get("employee_shi", "0"), "pit": result.get("pit", "0"), "employer_shi": result.get("employer_shi", "0"), "company_cost": str(Decimal(str(result.get("gross", 0))) + Decimal(str(result.get("employer_shi", 0))))})
            elif report_kind == "advance-final":
                output.append({**base, "run_type": "final", "total": result.get("net_pay", "0")})
            elif report_kind == "other-deductions":
                for line in inputs.get("other_deductions", []):
                    output.append({**base, "type": line.get("type", ""), "amount": line.get("amount", "0"), "note": line.get("note", "")})
    if report_kind == "tax-shi":
        ytd: dict[tuple[int, int], dict[str, Decimal]] = {}
        for row in sorted(output, key=lambda item: (item["month"], item.get("employee_id", 0))):
            key = (int(row.get("employee_id") or 0), int(row["month"][:4]))
            totals = ytd.setdefault(key, {field: Decimal("0") for field in ("gross", "employee_shi", "employer_shi", "pit")})
            for field in totals:
                totals[field] += Decimal(str(row.get(field, 0)))
                row[f"ytd_{field}"] = totals[field]
        output = [row for row in output if row["month"] >= from_month]
    return {"report_kind": report_kind, "from_month": from_month, "to_month": to_month, "rows": _json_value(output)}


@router.get("/reports/{report_kind}")
async def payroll_monthly_report(report_kind: str, from_month: str, to_month: str, department_id: int | None = None, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "payroll", "view_salary")
    return await _report_data(db, actor, report_kind, from_month, to_month, department_id)


@router.get("/reports/{report_kind}/export")
async def export_monthly_report(report_kind: str, from_month: str, to_month: str, department_id: int | None = None, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "payroll", "export")
    report = await _report_data(db, actor, report_kind, from_month, to_month, department_id)
    rows = report["rows"]
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Тайлан"
    sheet.append([f"{report_kind} · {from_month} — {to_month}"])
    keys = list(rows[0]) if rows else ["month", "employee_name"]
    sheet.append(keys)
    for cell in sheet[2]:
        cell.font = Font(bold=True)
    for row in rows:
        sheet.append([json.dumps(row.get(key), ensure_ascii=False) if isinstance(row.get(key), (dict, list)) else row.get(key, "") for key in keys])
    sheet.freeze_panes = "A3"
    output = io.BytesIO()
    workbook.save(output)
    filename = f"payroll-{report_kind}-{from_month}-{to_month}.xlsx"
    return Response(content=output.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


async def _worker_history(db: AsyncSession, actor: ActorContext, employee_id: int) -> list[dict[str, Any]]:
    employee = await db.scalar(select(Employee.id).where(Employee.id == employee_id, Employee.organization_id == actor.organization_id))
    if not employee:
        raise HTTPException(status_code=404, detail="Ажилтан олдсонгүй.")
    months = (await db.execute(select(MonthlyPayrollMonth).where(MonthlyPayrollMonth.organization_id == actor.organization_id, MonthlyPayrollMonth.status == "closed").order_by(MonthlyPayrollMonth.year, MonthlyPayrollMonth.month))).scalars().all()
    history = []
    for month in months:
        archive = await db.scalar(select(MonthlyPayrollArchive).where(MonthlyPayrollArchive.month_id == month.id).order_by(MonthlyPayrollArchive.version.desc()).limit(1))
        if not archive:
            continue
        for archived_run in archive.snapshot.get("runs", []):
            for row in archived_run.get("rows", []):
                if row.get("employee_id") == employee_id:
                    history.append({"month": f"{month.year:04d}-{month.month:02d}", "run_type": archived_run["run"]["run_type"], "pay_date": archived_run["run"]["pay_date"], **row.get("identity", {}), **row.get("result", {})})
    return history


@router.get("/employees/{employee_id}/history")
async def payroll_worker_history(employee_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "payroll", "view_salary")
    return await _worker_history(db, actor, employee_id)


@router.get("/employees/{employee_id}/history/export")
async def export_payroll_worker_history(employee_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "payroll", "export")
    rows = await _worker_history(db, actor, employee_id)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Ажилтны түүх"
    keys = ["month", "run_type", "pay_date", "name", "department", "gross", "employee_shi", "pit", "advance", "other_deductions", "net_pay"]
    sheet.append(["Архивлагдсан цалингийн түүх"])
    sheet.append(keys)
    for cell in sheet[2]:
        cell.font = Font(bold=True)
    for row in rows:
        sheet.append([row.get(key, "") for key in keys])
    output = io.BytesIO()
    workbook.save(output)
    filename = f"payroll-worker-{employee_id}-history.xlsx"
    return Response(content=output.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f'attachment; filename="{filename}"'})
