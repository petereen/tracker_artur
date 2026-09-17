from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enterprise_deps import ActorContext
from app.models.models import (
    AdditionalSalary, Employee, EmployeeBankAccount, EmployeeDetails, EmployeePayrollProfile, ERPAccount, ERPDocument, ERPCostCenter, Organization, UserAccount,
    ERPGeneralLedgerEntry, PayrollAdvance, PayrollBankExportProfile, PayrollEmployeeAccumulator,
    PayrollExportArtifact, PayrollPostingProfile, PayrollRun, Payslip, PayslipLineItem,
    PayrollSalaryComponentMaster, PayrollPaymentAllocation, PayrollPaymentBatch, PayrollPaymentReversal, PayrollStatementImport, PayrollStatementLine,
    SalaryComponent, SalaryStructure, SalaryStructureVersion, SHIRateTier, PITBracketTier, TaxReliefTier, StatutoryConfigProfile, SocialInsuranceContributorType, PayrollWorkPolicy, TimeOff, WorkTimeEntry,
    PayslipStatutoryLine,
)
from app.erp.service import validate_posting_gate
from app.services.secret_box import encrypt_secret
from .calculator import (
    CalculationInput, ComponentDefinition, LeaveMonth, PITBracket, ReliefTier as CalcReliefTier, SHIRate,
    StatutoryRules, _SafeFormula, calculate_payslip, money, snapshot_checksum,
)
from .schemas import (
    BankAccountInput, EmployeePayrollInput, PayrollRunInput, PostingProfileInput,
    SalaryComponentMasterInput, SalaryStructureInput, StatutoryProfileInput,
)
from .tax_benefits import approved_tax_adjustments, grouped_benefit_claims, mark_run_benefits_paid, reserve_benefit_claims


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _profile_payload(data: StatutoryProfileInput) -> dict[str, Any]:
    return data.model_dump(mode="json", exclude={"shi_rates", "pit_brackets", "relief_tiers"})


def _validate_date_range(start: date, end: date | None) -> None:
    if end and end < start:
        raise HTTPException(status_code=422, detail={"code": "payroll_invalid_effective_range"})


def _validate_rule_modes(data: StatutoryProfileInput) -> None:
    if sorted(set(data.standard_workweek)) != data.standard_workweek or any(day < 1 or day > 7 for day in data.standard_workweek):
        raise HTTPException(status_code=422, detail={"code": "payroll_invalid_workweek", "path": "standard_workweek", "message": "Weekdays must be unique ISO values from 1 to 7."})
    for index, rule in enumerate(data.shi_rates):
        if rule.upper_bound is not None and rule.upper_bound <= rule.lower_bound:
            raise HTTPException(status_code=422, detail={"code": "payroll_invalid_shi_tier", "path": f"shi_rates[{index}]"})
        if rule.calculation_mode == "formula":
            try:
                _SafeFormula(rule.formula or "")
            except ValueError as exc:
                raise HTTPException(status_code=422, detail={"code": "payroll_invalid_shi_formula", "path": f"shi_rates[{index}].formula", "message": str(exc)}) from exc
    if data.pit_calculation_mode == "formula":
        try:
            _SafeFormula(data.pit_formula or "")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"code": "payroll_invalid_pit_formula", "path": "pit_formula", "message": str(exc)}) from exc
    grouped: dict[tuple[str, str, str, str], list[Any]] = {}
    for rule in data.shi_rates:
        grouped.setdefault((rule.payer, rule.insurance_fund, rule.insured_category, rule.hazard_class), []).append(rule)
    for key, rows in grouped.items():
        modes = {row.calculation_mode for row in rows}
        if "marginal_tiers" in modes:
            ordered = sorted(rows, key=lambda row: row.lower_bound)
            if ordered[0].lower_bound != 0:
                raise HTTPException(status_code=422, detail={"code": "payroll_shi_tier_gap", "path": "shi_rates", "message": f"Marginal SHI tiers for {key} must start at zero."})
            previous: Decimal | None = None
            for row in ordered:
                if previous is not None and row.lower_bound != previous:
                    raise HTTPException(status_code=422, detail={"code": "payroll_shi_tier_gap", "path": "shi_rates", "message": f"Marginal SHI tiers for {key} contain a gap or overlap."})
                previous = row.upper_bound
            if previous is not None:
                raise HTTPException(status_code=422, detail={"code": "payroll_shi_tier_unbounded_required", "path": "shi_rates", "message": f"Marginal SHI tiers for {key} need an open-ended final tier."})
    for index, bracket in enumerate(data.pit_brackets):
        if bracket.upper_bound is not None and bracket.upper_bound <= bracket.lower_bound:
            raise HTTPException(status_code=422, detail={"code": "payroll_invalid_pit_bracket", "path": f"pit_brackets[{index}]"})
    if data.pit_calculation_mode == "marginal_tiers":
        for basis in {bracket.period_basis for bracket in data.pit_brackets}:
            ordered = sorted((bracket for bracket in data.pit_brackets if bracket.period_basis == basis), key=lambda row: row.lower_bound)
            if ordered and ordered[0].lower_bound != 0:
                raise HTTPException(status_code=422, detail={"code": "payroll_pit_tier_gap", "path": "pit_brackets", "message": f"{basis} PIT tiers must start at zero.", "remediation": "Add a zero-based first tier."})
            previous: Decimal | None = None
            for row in ordered:
                if previous is not None and row.lower_bound != previous:
                    raise HTTPException(status_code=422, detail={"code": "payroll_pit_tier_gap", "path": "pit_brackets", "message": f"{basis} PIT tiers contain a gap or overlap.", "remediation": "Make each lower bound equal the prior upper bound."})
                previous = row.upper_bound
            if ordered and previous is not None:
                raise HTTPException(status_code=422, detail={"code": "payroll_pit_tier_unbounded_required", "path": "pit_brackets", "message": f"{basis} PIT tiers need an open-ended final tier.", "remediation": "Leave the final upper bound empty."})


def _validate_persisted_tiers(profile: StatutoryConfigProfile, rates: list[SHIRateTier], brackets: list[PITBracketTier]) -> None:
    """Apply the same gap/overlap checks when calculating or publishing old rows."""
    grouped: dict[tuple[str, str, str, str], list[SHIRateTier]] = {}
    for row in rates:
        if getattr(row, "base_ceiling_policy", "profile") not in {"profile", "none"}:
            raise HTTPException(status_code=422, detail={"code": "payroll_invalid_shi_cap_policy", "path": "shi_rates", "message": "SHI cap policy must be profile or none.", "remediation": "Choose a supported cap policy."})
        if Decimal(str(row.rate)) < 0 or Decimal(str(row.base_floor)) < 0 or Decimal(str(row.fixed_amount)) < 0 or Decimal(str(row.base_tax)) < 0:
            raise HTTPException(status_code=422, detail={"code": "payroll_invalid_shi_rule", "path": "shi_rates", "message": "Rates, floors, and fixed/base amounts cannot be negative.", "remediation": "Correct the rule before calculating or publishing."})
        if row.upper_bound is not None and Decimal(str(row.upper_bound)) <= Decimal(str(row.lower_bound)):
            raise HTTPException(status_code=422, detail={"code": "payroll_invalid_shi_tier", "path": "shi_rates", "message": "Every upper bound must be greater than its lower bound.", "remediation": "Correct the tier bounds."})
        grouped.setdefault((row.payer, row.insurance_fund, row.insured_category, row.hazard_class), []).append(row)
    for key, rows in grouped.items():
        modes = {row.calculation_mode or "flat_percent" for row in rows}
        if "marginal_tiers" not in modes:
            continue
        if modes != {"marginal_tiers"}:
            raise HTTPException(status_code=422, detail={"code": "payroll_mixed_shi_modes", "path": "shi_rates", "message": f"SHI rules for {key} must use one calculation mode.", "remediation": "Split the contributor/fund/hazard combination into a separate rule set."})
        ordered = sorted(rows, key=lambda row: Decimal(str(row.lower_bound)))
        if Decimal(str(ordered[0].lower_bound)) != 0:
            raise HTTPException(status_code=422, detail={"code": "payroll_shi_tier_gap", "path": "shi_rates", "message": f"Marginal SHI tiers for {key} must start at zero.", "remediation": "Add a zero-based first tier."})
        previous: Decimal | None = None
        for row in ordered:
            lower = Decimal(str(row.lower_bound))
            if previous is not None and lower != previous:
                raise HTTPException(status_code=422, detail={"code": "payroll_shi_tier_gap", "path": "shi_rates", "message": f"Marginal SHI tiers for {key} contain a gap or overlap.", "remediation": "Make each lower bound equal the prior upper bound."})
            previous = Decimal(str(row.upper_bound)) if row.upper_bound is not None else None
        if previous is not None:
            raise HTTPException(status_code=422, detail={"code": "payroll_shi_tier_unbounded_required", "path": "shi_rates", "message": f"Marginal SHI tiers for {key} need an open-ended final tier.", "remediation": "Leave the final upper bound empty."})
    if profile.pit_calculation_mode != "marginal_tiers":
        return
    for basis in {row.period_basis for row in brackets}:
        ordered = sorted((row for row in brackets if row.period_basis == basis), key=lambda row: Decimal(str(row.lower_bound)))
        if not ordered:
            continue
        if Decimal(str(ordered[0].lower_bound)) != 0:
            raise HTTPException(status_code=422, detail={"code": "payroll_pit_tier_gap", "path": "pit_brackets", "message": f"{basis} PIT tiers must start at zero.", "remediation": "Add a zero-based first tier."})
        previous: Decimal | None = None
        for row in ordered:
            lower = Decimal(str(row.lower_bound))
            if Decimal(str(row.marginal_rate)) < 0 or Decimal(str(row.base_tax)) < 0:
                raise HTTPException(status_code=422, detail={"code": "payroll_invalid_pit_bracket", "path": "pit_brackets", "message": "PIT rates and base tax cannot be negative.", "remediation": "Correct the bracket before calculating or publishing."})
            if row.upper_bound is not None and Decimal(str(row.upper_bound)) <= lower:
                raise HTTPException(status_code=422, detail={"code": "payroll_invalid_pit_bracket", "path": "pit_brackets", "message": "Every upper bound must be greater than its lower bound.", "remediation": "Correct the bracket bounds."})
            if previous is not None and lower != previous:
                raise HTTPException(status_code=422, detail={"code": "payroll_pit_tier_gap", "path": "pit_brackets", "message": f"{basis} PIT tiers contain a gap or overlap.", "remediation": "Make each lower bound equal the prior upper bound."})
            previous = Decimal(str(row.upper_bound)) if row.upper_bound is not None else None
        if previous is not None:
            raise HTTPException(status_code=422, detail={"code": "payroll_pit_tier_unbounded_required", "path": "pit_brackets", "message": f"{basis} PIT tiers need an open-ended final tier.", "remediation": "Leave the final upper bound empty."})


def component_master_out(row: PayrollSalaryComponentMaster) -> dict[str, Any]:
    return {
        "id": row.id, "code": row.code, "name": row.name, "description": row.description,
        "component_kind": row.component_kind, "formula": row.formula, "amount_mode": row.amount_mode, "percentage_basis": row.percentage_basis, "proration_basis": row.proration_basis,
        "is_taxable": row.is_taxable, "is_shi_subject": row.is_shi_subject,
        "is_non_taxable_allowance": row.is_non_taxable_allowance, "is_leave_average_eligible": row.is_leave_average_eligible,
        "is_flexible_benefit": row.is_flexible_benefit, "max_benefit_amount_yearly": str(row.max_benefit_amount_yearly),
        "pay_against_benefit_claim": row.pay_against_benefit_claim, "only_tax_impact": row.only_tax_impact,
        "payer": row.payer, "account_id": row.account_id, "cost_center_id": row.cost_center_id,
        "metadata_json": row.metadata_json or {}, "status": row.status, "is_active": row.is_active,
        "archived_at": row.archived_at.isoformat() if row.archived_at else None,
    }


async def create_component_master(db: AsyncSession, actor: ActorContext, data: SalaryComponentMasterInput) -> PayrollSalaryComponentMaster:
    duplicate = await db.scalar(select(PayrollSalaryComponentMaster.id).where(PayrollSalaryComponentMaster.organization_id == actor.organization_id, PayrollSalaryComponentMaster.code == data.code))
    if duplicate:
        raise HTTPException(status_code=409, detail={"code": "payroll_component_master_exists"})
    expression = data.formula if data.amount_mode != "percentage" else f"({data.percentage_basis or 'base_salary'}) * ({data.formula})"
    try:
        _SafeFormula(expression)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "payroll_invalid_formula", "path": "formula", "message": str(exc), "remediation": "Correct the formula using the safe formula editor."}) from exc
    values = data.model_dump()
    row = PayrollSalaryComponentMaster(organization_id=actor.organization_id, created_by_account_id=actor.account_id, is_active=True, status="active", **values)
    db.add(row)
    await db.flush()
    return row


async def component_master_usage(db: AsyncSession, actor: ActorContext, component_id: int) -> dict[str, Any]:
    row = await db.scalar(select(PayrollSalaryComponentMaster).where(PayrollSalaryComponentMaster.id == component_id, PayrollSalaryComponentMaster.organization_id == actor.organization_id))
    if not row:
        raise HTTPException(status_code=404, detail="Salary component not found")
    structure_rows = list((await db.execute(select(SalaryComponent.id, SalaryComponent.salary_structure_id).join(SalaryStructure, SalaryStructure.id == SalaryComponent.salary_structure_id).where(SalaryComponent.component_master_id == component_id, SalaryStructure.organization_id == actor.organization_id))).all())
    additional_rows = list((await db.execute(select(AdditionalSalary.id).where(AdditionalSalary.organization_id == actor.organization_id, AdditionalSalary.salary_component_id == component_id))).scalars().all())
    line_rows = list((await db.execute(select(PayslipLineItem.id, PayslipLineItem.payslip_id).where(PayslipLineItem.component_master_id == component_id))).all())
    snapshots: list[int] = []
    for version in (await db.execute(select(SalaryStructureVersion).join(SalaryStructure, SalaryStructure.id == SalaryStructureVersion.salary_structure_id).where(SalaryStructure.organization_id == actor.organization_id, SalaryStructureVersion.salary_structure_id.in_([item[1] for item in structure_rows] or [-1])))).scalars().all():
        if any(isinstance(item, dict) and item.get("component_master_id") == component_id for item in (version.component_snapshot or [])):
            snapshots.append(version.id)
    references = {
        "salary_structure": {"count": len(structure_rows), "ids": sorted({int(item[1]) for item in structure_rows})},
        "salary_structure_version": {"count": len(snapshots), "ids": sorted(snapshots)},
        "additional_salary": {"count": len(additional_rows), "ids": [int(item) for item in additional_rows]},
        "payslip_line_item": {"count": len(line_rows), "ids": [int(item[0]) for item in line_rows]},
    }
    references.update({"structure_rows": references["salary_structure"], "version_snapshots": references["salary_structure_version"], "historical_payslip_lines": references["payslip_line_item"]})
    return {"component": component_master_out(row), "references": references, "in_use": any(item["count"] for item in references.values())}


async def update_component_master(db: AsyncSession, actor: ActorContext, row: PayrollSalaryComponentMaster, data: SalaryComponentMasterInput) -> PayrollSalaryComponentMaster:
    if row.organization_id != actor.organization_id:
        raise HTTPException(status_code=404, detail="Salary component not found")
    usage = await component_master_usage(db, actor, row.id)
    values = data.model_dump()
    locked = {"code", "component_kind", "formula", "amount_mode", "percentage_basis", "proration_basis", "is_taxable", "is_shi_subject", "is_non_taxable_allowance", "is_leave_average_eligible", "is_flexible_benefit", "max_benefit_amount_yearly", "pay_against_benefit_claim", "only_tax_impact", "payer", "account_id", "cost_center_id"}
    if usage["in_use"]:
        changed = [key for key in locked if values.get(key) != getattr(row, key)]
        if changed:
            raise HTTPException(status_code=409, detail={"code": "payroll_component_financial_fields_locked", "fields": changed, "usage": usage["references"]})
    duplicate = await db.scalar(select(PayrollSalaryComponentMaster.id).where(PayrollSalaryComponentMaster.organization_id == actor.organization_id, PayrollSalaryComponentMaster.code == data.code, PayrollSalaryComponentMaster.id != row.id))
    if duplicate:
        raise HTTPException(status_code=409, detail={"code": "payroll_component_master_exists"})
    expression = data.formula if data.amount_mode != "percentage" else f"({data.percentage_basis or 'base_salary'}) * ({data.formula})"
    try:
        _SafeFormula(expression)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "payroll_invalid_formula", "path": "formula", "message": str(exc), "remediation": "Correct the formula using the safe formula editor."}) from exc
    for key, value in values.items():
        setattr(row, key, value)
    row.status = "active" if row.is_active else "archived"
    return row


async def delete_component_master(db: AsyncSession, actor: ActorContext, row: PayrollSalaryComponentMaster) -> None:
    usage = await component_master_usage(db, actor, row.id)
    if usage["in_use"]:
        raise HTTPException(status_code=409, detail={"code": "payroll_component_in_use", "component_id": row.id, "references": usage["references"], "allowed_actions": ["archive", "clone"]})
    await db.delete(row)


async def archive_component_master(db: AsyncSession, actor: ActorContext, row: PayrollSalaryComponentMaster) -> PayrollSalaryComponentMaster:
    if row.organization_id != actor.organization_id:
        raise HTTPException(status_code=404, detail="Salary component not found")
    row.is_active = False; row.status = "archived"; row.archived_at = datetime.now(timezone.utc)
    return row


async def ensure_profile_active(db: AsyncSession, profile_id: int, tax_point_date: date) -> StatutoryConfigProfile:
    profile = await db.scalar(select(StatutoryConfigProfile).where(StatutoryConfigProfile.id == profile_id))
    if not profile or profile.status not in {"published", "active"} or profile.effective_from > tax_point_date or (profile.effective_to and profile.effective_to < tax_point_date):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": "payroll_statutory_profile_not_active", "profile_id": profile_id})
    return profile


async def resolve_profile(db: AsyncSession, organization_id: int, tax_point_date: date) -> StatutoryConfigProfile:
    profile = await db.scalar(select(StatutoryConfigProfile).where(
        StatutoryConfigProfile.organization_id == organization_id,
        StatutoryConfigProfile.status.in_(("published", "active")),
        StatutoryConfigProfile.effective_from <= tax_point_date,
        (StatutoryConfigProfile.effective_to.is_(None) | (StatutoryConfigProfile.effective_to >= tax_point_date)),
    ).order_by(StatutoryConfigProfile.effective_from.desc(), StatutoryConfigProfile.version.desc()).limit(1))
    if not profile:
        raise HTTPException(status_code=409, detail={"code": "payroll_no_active_statutory_profile", "tax_point_date": tax_point_date.isoformat()})
    return profile


async def preflight_run(db: AsyncSession, actor: ActorContext, data: PayrollRunInput) -> dict[str, Any]:
    """Validate a run without persisting a draft or mutating payroll inputs."""
    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    def issue(code: str, message: str, *, severity: str = "blocker", entity_ids: list[int] | None = None, remediation_url: str | None = None, metadata: dict[str, Any] | None = None) -> None:
        payload = {"code": code, "severity": severity, "message": message, "affected_entities": entity_ids or [], "entity_ids": entity_ids or [], "metadata": metadata or {}}
        if remediation_url:
            payload["remediation_url"] = remediation_url
        (blockers if severity == "blocker" else warnings).append(payload)

    if data.period_end < data.period_start:
        issue("payroll_invalid_period", "Period end must be on or after period start.")
        return {"can_create": False, "employee_ids": [], "employee_count": 0, "blockers": blockers, "warnings": warnings}

    try:
        profile = await (ensure_profile_active(db, data.statutory_profile_id, data.tax_point_date) if data.statutory_profile_id else resolve_profile(db, actor.organization_id, data.tax_point_date))
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
        issue(str(detail.get("code", "payroll_statutory_profile_missing")), "No published statutory profile is effective for this tax point.", remediation_url="/erp/payroll/setup?tab=structures")
        profile = None

    employee_ids = list(dict.fromkeys(data.employee_ids))
    if not employee_ids:
        query = select(Employee.id).where(Employee.organization_id == actor.organization_id, Employee.is_active.is_(True))
        work_branch = data.employee_filter.get("work_branch")
        department_id = data.employee_filter.get("department_id")
        if work_branch:
            query = query.where(Employee.work_branch == str(work_branch))
        if department_id:
            query = query.join(EmployeeDetails, EmployeeDetails.employee_id == Employee.id).where(EmployeeDetails.organization_id == actor.organization_id, EmployeeDetails.department_id == int(department_id))
        employee_ids = list((await db.execute(query.order_by(Employee.id))).scalars().all())
    if not employee_ids:
        issue("payroll_no_employees", "No active employees match this run scope.", remediation_url="/erp/payroll/runs/new")

    profiles = {}
    if employee_ids:
        rows = (await db.execute(select(EmployeePayrollProfile).where(
            EmployeePayrollProfile.organization_id == actor.organization_id,
            EmployeePayrollProfile.employee_id.in_(employee_ids),
            EmployeePayrollProfile.effective_from <= data.tax_point_date,
            (EmployeePayrollProfile.effective_to.is_(None) | (EmployeePayrollProfile.effective_to >= data.tax_point_date)),
        ).order_by(EmployeePayrollProfile.effective_from.desc()))).scalars().all()
        for row in rows:
            profiles.setdefault(row.employee_id, row)
    missing_profiles = sorted(set(employee_ids) - set(profiles))
    if missing_profiles:
        issue("payroll_employee_profile_missing", "Employees need an effective payroll profile.", entity_ids=missing_profiles, remediation_url="/erp/payroll/setup?tab=employees")

    structure_ids = {row.salary_structure_id for row in profiles.values()}
    structures = list((await db.execute(select(SalaryStructure).where(SalaryStructure.organization_id == actor.organization_id, SalaryStructure.id.in_(structure_ids or {-1})))).scalars().all())
    structure_by_id = {row.id: row for row in structures}
    missing_structures = sorted({row.salary_structure_id for row in profiles.values() if row.salary_structure_id not in structure_by_id or row.status not in {"published", "active"}})
    if missing_structures:
        affected = [employee_id for employee_id, row in profiles.items() if row.salary_structure_id in missing_structures]
        issue("payroll_salary_structure_missing", "Employees need an effective published salary structure.", entity_ids=affected, remediation_url="/erp/payroll/setup?tab=structures", metadata={"salary_structure_ids": missing_structures})
    if structure_by_id:
        component_rows = (await db.execute(select(SalaryComponent).where(SalaryComponent.salary_structure_id.in_(structure_by_id)))).scalars().all()
        unmapped_structures = sorted({row.salary_structure_id for row in component_rows if row.account_id is None})
        if unmapped_structures:
            issue("payroll_component_gl_mapping_missing", "Every active salary component must map to a GL account before a run can be created.", remediation_url="/erp/payroll/setup?tab=accounting", metadata={"salary_structure_ids": unmapped_structures})

        bank_ids = set()
    if employee_ids:
        bank_ids = set((await db.execute(select(EmployeeBankAccount.employee_id).where(
            EmployeeBankAccount.employee_id.in_(employee_ids), EmployeeBankAccount.is_primary.is_(True),
            EmployeeBankAccount.valid_from <= data.tax_point_date,
            (EmployeeBankAccount.valid_to.is_(None) | (EmployeeBankAccount.valid_to >= data.tax_point_date)),
        ))).scalars().all())
    bank_required = [employee_id for employee_id, profile_row in profiles.items() if profile_row.payment_method == "bank" and employee_id not in bank_ids]
    if bank_required:
        issue("payroll_bank_account_missing", "Bank-paid employees need a valid primary bank account.", entity_ids=sorted(bank_required), remediation_url="/erp/payroll/setup?tab=employees")

    if employee_ids:
        pending_leave = list((await db.execute(select(TimeOff.id).where(
            TimeOff.employee_id.in_(employee_ids), TimeOff.starts_on <= data.period_end, TimeOff.ends_on >= data.period_start, TimeOff.status.notin_(("approved", "rejected", "cancelled")),
        ))).scalars().all())
        if pending_leave:
            issue("payroll_unapproved_leave", "Leave requests overlapping the run must be approved or rejected.", entity_ids=[int(item) for item in pending_leave], remediation_url="/hr/leave")
        pending_extra = list((await db.execute(select(AdditionalSalary.id).where(
            AdditionalSalary.organization_id == actor.organization_id, AdditionalSalary.employee_id.in_(employee_ids), AdditionalSalary.payroll_date >= data.period_start, AdditionalSalary.payroll_date <= data.period_end, AdditionalSalary.status == "draft",
        ))).scalars().all())
        if pending_extra:
            issue("payroll_unapproved_additional_salary", "Additional Salary inputs must be submitted before calculation.", entity_ids=[int(item) for item in pending_extra], remediation_url="/erp/payroll/setup?tab=compensation")
        pending_time = list((await db.execute(select(WorkTimeEntry.id).where(
            WorkTimeEntry.employee_id.in_(employee_ids), WorkTimeEntry.entry_type == "work", WorkTimeEntry.started_at >= datetime.combine(data.period_start, datetime.min.time()), WorkTimeEntry.started_at <= datetime.combine(data.period_end, datetime.max.time()), WorkTimeEntry.approval_status != "approved",
        ))).scalars().all())
        if pending_time:
            severity = "blocker" if data.validate_attendance else "warning"
            issue("payroll_missing_or_unapproved_scans", "Work-time entries are not fully approved for this period.", severity=severity, entity_ids=[int(item) for item in pending_time], remediation_url="/hr/attendance")
        entries = list((await db.execute(select(WorkTimeEntry).where(WorkTimeEntry.employee_id.in_(employee_ids), WorkTimeEntry.started_at <= datetime.combine(data.period_end, datetime.max.time()), WorkTimeEntry.ended_at.is_not(None), WorkTimeEntry.ended_at >= datetime.combine(data.period_start, datetime.min.time())))).scalars().all())
        overlap_ids: list[int] = []
        by_employee: dict[int, list[WorkTimeEntry]] = {}
        for entry in entries:
            by_employee.setdefault(entry.employee_id, []).append(entry)
        for employee_entries in by_employee.values():
            employee_entries.sort(key=lambda item: item.started_at)
            for previous, current in zip(employee_entries, employee_entries[1:]):
                if previous.ended_at and current.started_at < previous.ended_at:
                    overlap_ids.extend([previous.id, current.id])
        if overlap_ids:
            issue("payroll_worktime_overlap", "Overlapping WorkTime entries must be resolved before calculation.", entity_ids=sorted(set(overlap_ids)), remediation_url="/hr/attendance")

    posting = await db.scalar(select(PayrollPostingProfile).where(PayrollPostingProfile.organization_id == actor.organization_id, PayrollPostingProfile.code == "default", PayrollPostingProfile.is_active.is_(True)))
    required_roles = {"salary_expense", "net_pay_payable", "pit_payable", "employee_shi_payable", "employer_shi_payable"}
    mapped_roles = set((posting.account_roles if posting else {}).keys())
    missing_roles = sorted(required_roles - mapped_roles)
    if missing_roles:
        issue("payroll_gl_mapping_incomplete", "Default payroll posting profile is missing required account mappings.", remediation_url="/erp/payroll/setup?tab=accounting", metadata={"missing_roles": missing_roles})
    if profile and profile.is_example:
        issue("payroll_example_profile", "The statutory profile is an example configuration and requires acknowledgement at calculation.", severity="warning", remediation_url="/erp/payroll/setup?tab=structures")

    return {"can_create": not blockers, "employee_ids": employee_ids, "employee_count": len(employee_ids), "blockers": blockers, "warnings": warnings, "evaluated_at": datetime.now(timezone.utc).isoformat()}


async def load_rules(db: AsyncSession, profile: StatutoryConfigProfile, *, insured_category: str = "employee", hazard_class: str = "standard", effective_date: date | None = None) -> StatutoryRules:
    tax_point = effective_date or profile.effective_from
    contributor_master_exists = await db.scalar(select(SocialInsuranceContributorType.id).where(SocialInsuranceContributorType.organization_id == profile.organization_id).limit(1))
    if contributor_master_exists:
        contributor = await db.scalar(select(SocialInsuranceContributorType.id).where(SocialInsuranceContributorType.organization_id == profile.organization_id, SocialInsuranceContributorType.code == insured_category, SocialInsuranceContributorType.status == "active", SocialInsuranceContributorType.effective_from <= tax_point, (SocialInsuranceContributorType.effective_to.is_(None) | (SocialInsuranceContributorType.effective_to >= tax_point))).limit(1))
        if not contributor:
            raise HTTPException(status_code=422, detail={"code": "payroll_contributor_type_invalid", "path": "insured_category", "message": f"Contributor code {insured_category!r} is not active for the statutory profile effective date.", "remediation": "Publish the contributor type or correct the employee payroll profile."})
    shi_rows = (await db.execute(select(SHIRateTier).where(SHIRateTier.profile_id == profile.id, SHIRateTier.insured_category == insured_category, SHIRateTier.hazard_class == hazard_class).order_by(SHIRateTier.position, SHIRateTier.id))).scalars().all()
    if not shi_rows:
        raise HTTPException(status_code=422, detail={"code": "payroll_missing_contributor_rules", "path": "shi_rates", "message": f"No SHI rules match contributor category {insured_category!r} and hazard class {hazard_class!r}.", "remediation": "Add an effective SHI rule for this contributor/hazard combination or correct the employee profile."})
    all_brackets = list((await db.execute(select(PITBracketTier).where(PITBracketTier.profile_id == profile.id).order_by(PITBracketTier.position, PITBracketTier.id))).scalars().all())
    _validate_persisted_tiers(profile, list(shi_rows), all_brackets)
    pit_candidates = all_brackets
    # A profile may retain annual, monthly, and period brackets for audit or
    # alternate withholding methods. Never mix bases in one calculation.
    preferred_basis = "annual" if profile.pit_withholding_method == "ytd_cumulative" else "monthly"
    available_bases = {row.period_basis for row in pit_candidates}
    selected_basis = preferred_basis if preferred_basis in available_bases else ("monthly" if "monthly" in available_bases else next(iter(available_bases), preferred_basis))
    pit_rows = [row for row in pit_candidates if row.period_basis == selected_basis]
    relief_candidates = (await db.execute(select(TaxReliefTier).where(TaxReliefTier.profile_id == profile.id).order_by(TaxReliefTier.position, TaxReliefTier.id))).scalars().all()
    relief_basis = "annual" if profile.pit_withholding_method == "ytd_cumulative" else "monthly"
    available_relief_bases = {row.amount_basis for row in relief_candidates}
    selected_relief_basis = relief_basis if relief_basis in available_relief_bases else ("monthly" if "monthly" in available_relief_bases else next(iter(available_relief_bases), relief_basis))
    relief_rows = [row for row in relief_candidates if row.amount_basis == selected_relief_basis]
    return StatutoryRules(
        minimum_wage=Decimal(str(profile.minimum_wage)), shi_ceiling_multiplier=Decimal(str(profile.shi_ceiling_multiplier)),
        shi_rates=tuple(SHIRate(payer=row.payer, insurance_fund=row.insurance_fund, rate=Decimal(str(row.rate)), base_floor=Decimal(str(row.base_floor)), lower_bound=Decimal(str(row.lower_bound)), upper_bound=Decimal(str(row.upper_bound)) if row.upper_bound is not None else None, calculation_mode=row.calculation_mode, fixed_amount=Decimal(str(row.fixed_amount)), base_tax=Decimal(str(row.base_tax)), base_ceiling_policy=getattr(row, "base_ceiling_policy", "profile"), formula=row.formula, exemption_code=row.exemption_code) for row in shi_rows),
        pit_brackets=tuple(PITBracket(lower_bound=Decimal(str(row.lower_bound)), upper_bound=Decimal(str(row.upper_bound)) if row.upper_bound is not None else None, marginal_rate=Decimal(str(row.marginal_rate)), base_tax=Decimal(str(row.base_tax)), period_basis=row.period_basis, formula=getattr(row, "formula", None)) for row in pit_rows),
        relief_tiers=tuple(CalcReliefTier(eligibility_code=row.eligibility_code, lower_bound=Decimal(str(row.lower_bound)), upper_bound=Decimal(str(row.upper_bound)) if row.upper_bound is not None else None, fixed_amount=Decimal(str(row.fixed_amount)), amount_basis=row.amount_basis, formula=row.formula) for row in relief_rows),
        pit_withholding_method=profile.pit_withholding_method,
        pit_calculation_mode=profile.pit_calculation_mode,
        pit_formula=profile.pit_formula,
        rounding_quantum=Decimal(str((profile.rounding_policy or {}).get("quantum", "0.01"))),
        leave_policy=profile.leave_policy or {"lookback_months": 12, "missing_history_fallback": "error"},
    )


async def resolve_work_policy(db: AsyncSession, organization_id: int, employee_id: int, tax_point: date, *, job_title: str | None = None) -> PayrollWorkPolicy | None:
    """Resolve employee → job title → organization policy at the tax point."""
    candidates = [("employee", str(employee_id)), ("job_title", job_title), ("organization", "*")]
    for scope_type, scope_key in candidates:
        if not scope_key:
            continue
        policy = await db.scalar(select(PayrollWorkPolicy).where(
            PayrollWorkPolicy.organization_id == organization_id,
            PayrollWorkPolicy.scope_type == scope_type,
            PayrollWorkPolicy.scope_key == scope_key,
            PayrollWorkPolicy.status.in_(("active", "published")),
            PayrollWorkPolicy.effective_from <= tax_point,
            (PayrollWorkPolicy.effective_to.is_(None) | (PayrollWorkPolicy.effective_to >= tax_point)),
        ).order_by(PayrollWorkPolicy.effective_from.desc(), PayrollWorkPolicy.id.desc()).limit(1))
        if policy:
            return policy
    return None


def profile_out(profile: StatutoryConfigProfile, *, rates: list[SHIRateTier] | None = None, brackets: list[PITBracketTier] | None = None, reliefs: list[TaxReliefTier] | None = None) -> dict[str, Any]:
    return {
        "id": profile.id, "organization_id": profile.organization_id, "code": profile.code, "jurisdiction": profile.jurisdiction,
        "version": profile.version, "status": profile.status, "effective_from": profile.effective_from.isoformat(), "effective_to": profile.effective_to.isoformat() if profile.effective_to else None,
        "tax_point_basis": profile.tax_point_basis, "currency": profile.currency, "minimum_wage": str(profile.minimum_wage), "shi_ceiling_multiplier": str(profile.shi_ceiling_multiplier),
        "pit_withholding_method": profile.pit_withholding_method, "pit_calculation_mode": profile.pit_calculation_mode, "pit_formula": profile.pit_formula, "standard_daily_hours": str(profile.standard_daily_hours), "standard_weekly_hours": str(profile.standard_weekly_hours), "standard_workweek": profile.standard_workweek, "rounding_policy": profile.rounding_policy, "leave_policy": profile.leave_policy,
        "source_references": profile.source_references, "is_example": profile.is_example, "checksum": profile.checksum,
        "shi_rates": [{"payer": row.payer, "insurance_fund": row.insurance_fund, "insured_category": row.insured_category, "hazard_class": row.hazard_class, "rate": str(row.rate), "base_floor": str(row.base_floor), "lower_bound": str(row.lower_bound), "upper_bound": str(row.upper_bound) if row.upper_bound is not None else None, "calculation_mode": row.calculation_mode, "fixed_amount": str(row.fixed_amount), "base_tax": str(row.base_tax), "base_ceiling_policy": getattr(row, "base_ceiling_policy", "profile"), "formula": row.formula, "exemption_code": row.exemption_code} for row in (rates or [])],
        "pit_brackets": [{"period_basis": row.period_basis, "lower_bound": str(row.lower_bound), "upper_bound": str(row.upper_bound) if row.upper_bound is not None else None, "marginal_rate": str(row.marginal_rate), "base_tax": str(row.base_tax), "formula": getattr(row, "formula", None)} for row in (brackets or [])],
        "relief_tiers": [{"eligibility_code": row.eligibility_code, "lower_bound": str(row.lower_bound), "upper_bound": str(row.upper_bound) if row.upper_bound is not None else None, "fixed_amount": str(row.fixed_amount), "amount_basis": row.amount_basis, "formula": row.formula} for row in (reliefs or [])],
    }


async def create_statutory_profile(db: AsyncSession, actor: ActorContext, data: StatutoryProfileInput) -> StatutoryConfigProfile:
    _validate_date_range(data.effective_from, data.effective_to)
    if data.currency.upper() != "MNT":
        raise HTTPException(status_code=422, detail={"code": "payroll_currency_not_supported", "currency": data.currency})
    try:
        quantum = Decimal(str(data.rounding_policy.get("quantum", "0.01")))
    except Exception as exc:
        raise HTTPException(status_code=422, detail={"code": "payroll_invalid_rounding_quantum"}) from exc
    if quantum <= 0:
        raise HTTPException(status_code=422, detail={"code": "payroll_invalid_rounding_quantum"})
    _validate_rule_modes(data)
    for bracket in data.pit_brackets:
        if bracket.upper_bound is not None and bracket.upper_bound <= bracket.lower_bound:
            raise HTTPException(status_code=422, detail={"code": "payroll_invalid_pit_bracket"})
    for basis in {bracket.period_basis for bracket in data.pit_brackets}:
        ordered_brackets = sorted((bracket for bracket in data.pit_brackets if bracket.period_basis == basis), key=lambda bracket: bracket.lower_bound)
        previous_upper: Decimal | None = None
        for index, bracket in enumerate(ordered_brackets):
            if previous_upper is None and index > 0:
                raise HTTPException(status_code=422, detail={"code": "payroll_bracket_after_unbounded_tier", "period_basis": basis})
            if previous_upper is not None and bracket.lower_bound < previous_upper:
                raise HTTPException(status_code=422, detail={"code": "payroll_overlapping_pit_bracket", "period_basis": basis})
            previous_upper = bracket.upper_bound
    for relief in data.relief_tiers:
        if relief.upper_bound is not None and relief.upper_bound <= relief.lower_bound:
            raise HTTPException(status_code=422, detail={"code": "payroll_invalid_relief_tier"})
        if relief.formula:
            try:
                _SafeFormula(relief.formula)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail={"code": "payroll_invalid_relief_formula", "message": str(exc)}) from exc
    payload = _profile_payload(data)
    payload["currency"] = data.currency.upper()
    profile = StatutoryConfigProfile(organization_id=actor.organization_id, **payload, checksum=_hash(data.model_dump(mode="json")), created_by_account_id=actor.account_id)
    db.add(profile); await db.flush()
    db.add_all([SHIRateTier(profile_id=profile.id, **{**row.model_dump(), "position": row.position if row.position else index}) for index, row in enumerate(data.shi_rates)])
    db.add_all([PITBracketTier(profile_id=profile.id, **{**row.model_dump(), "position": row.position if row.position else index}) for index, row in enumerate(data.pit_brackets)])
    db.add_all([TaxReliefTier(profile_id=profile.id, **{**row.model_dump(), "position": row.position if row.position else index}) for index, row in enumerate(data.relief_tiers)])
    return profile


async def update_statutory_profile(db: AsyncSession, actor: ActorContext, profile: StatutoryConfigProfile, data: StatutoryProfileInput) -> StatutoryConfigProfile:
    if profile.organization_id != actor.organization_id:
        raise HTTPException(status_code=404, detail="Profile not found")
    if profile.status in {"published", "active"}:
        raise HTTPException(status_code=409, detail={"code": "payroll_profile_immutable"})
    # Keep draft editing on the same validation path as profile creation.
    _validate_date_range(data.effective_from, data.effective_to)
    if data.currency.upper() != "MNT":
        raise HTTPException(status_code=422, detail={"code": "payroll_currency_not_supported", "currency": data.currency})
    try:
        quantum = Decimal(str(data.rounding_policy.get("quantum", "0.01")))
    except Exception as exc:
        raise HTTPException(status_code=422, detail={"code": "payroll_invalid_rounding_quantum"}) from exc
    if quantum <= 0:
        raise HTTPException(status_code=422, detail={"code": "payroll_invalid_rounding_quantum"})
    _validate_rule_modes(data)
    for bracket in data.pit_brackets:
        if bracket.upper_bound is not None and bracket.upper_bound <= bracket.lower_bound:
            raise HTTPException(status_code=422, detail={"code": "payroll_invalid_pit_bracket"})
    for relief in data.relief_tiers:
        if relief.upper_bound is not None and relief.upper_bound <= relief.lower_bound:
            raise HTTPException(status_code=422, detail={"code": "payroll_invalid_relief_tier"})
        if relief.formula:
            try:
                _SafeFormula(relief.formula)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail={"code": "payroll_invalid_relief_formula", "message": str(exc)}) from exc
    for basis in {bracket.period_basis for bracket in data.pit_brackets}:
        ordered = sorted((bracket for bracket in data.pit_brackets if bracket.period_basis == basis), key=lambda row: row.lower_bound)
        previous_upper: Decimal | None = None
        for index, bracket in enumerate(ordered):
            if previous_upper is None and index > 0:
                raise HTTPException(status_code=422, detail={"code": "payroll_bracket_after_unbounded_tier", "period_basis": basis})
            if previous_upper is not None and bracket.lower_bound < previous_upper:
                raise HTTPException(status_code=422, detail={"code": "payroll_overlapping_pit_bracket", "period_basis": basis})
            previous_upper = bracket.upper_bound
    for key, value in _profile_payload(data).items():
        setattr(profile, key, value)
    profile.currency = data.currency.upper()
    profile.checksum = _hash(data.model_dump(mode="json"))
    await db.execute(delete(SHIRateTier).where(SHIRateTier.profile_id == profile.id))
    await db.execute(delete(PITBracketTier).where(PITBracketTier.profile_id == profile.id))
    await db.execute(delete(TaxReliefTier).where(TaxReliefTier.profile_id == profile.id))
    db.add_all([SHIRateTier(profile_id=profile.id, **{**row.model_dump(), "position": row.position if row.position else index}) for index, row in enumerate(data.shi_rates)])
    db.add_all([PITBracketTier(profile_id=profile.id, **{**row.model_dump(), "position": row.position if row.position else index}) for index, row in enumerate(data.pit_brackets)])
    db.add_all([TaxReliefTier(profile_id=profile.id, **{**row.model_dump(), "position": row.position if row.position else index}) for index, row in enumerate(data.relief_tiers)])
    await db.flush()
    return profile


async def delete_statutory_profile(db: AsyncSession, actor: ActorContext, profile: StatutoryConfigProfile) -> None:
    if profile.organization_id != actor.organization_id:
        raise HTTPException(status_code=404, detail="Profile not found")
    if profile.status in {"published", "active"}:
        raise HTTPException(status_code=409, detail={"code": "payroll_profile_immutable"})
    referenced_run = await db.scalar(select(PayrollRun.id).where(PayrollRun.statutory_profile_id == profile.id).limit(1))
    if referenced_run:
        raise HTTPException(status_code=409, detail={"code": "payroll_profile_referenced_by_run"})
    await db.delete(profile)
    await db.flush()


async def bump_statutory_profile(db: AsyncSession, actor: ActorContext, profile: StatutoryConfigProfile, effective_from: date) -> StatutoryConfigProfile:
    if profile.organization_id != actor.organization_id:
        raise HTTPException(status_code=404, detail="Profile not found")
    rates = (await db.execute(select(SHIRateTier).where(SHIRateTier.profile_id == profile.id).order_by(SHIRateTier.position, SHIRateTier.id))).scalars().all()
    brackets = (await db.execute(select(PITBracketTier).where(PITBracketTier.profile_id == profile.id).order_by(PITBracketTier.position, PITBracketTier.id))).scalars().all()
    reliefs = (await db.execute(select(TaxReliefTier).where(TaxReliefTier.profile_id == profile.id).order_by(TaxReliefTier.position, TaxReliefTier.id))).scalars().all()
    next_version = (await db.scalar(select(func.max(StatutoryConfigProfile.version)).where(StatutoryConfigProfile.organization_id == actor.organization_id, StatutoryConfigProfile.code == profile.code)) or profile.version) + 1
    data = StatutoryProfileInput.model_validate({
        "code": profile.code, "version": next_version, "effective_from": effective_from,
        "effective_to": profile.effective_to, "tax_point_basis": profile.tax_point_basis, "currency": profile.currency,
        "minimum_wage": profile.minimum_wage, "shi_ceiling_multiplier": profile.shi_ceiling_multiplier,
        "pit_withholding_method": profile.pit_withholding_method, "pit_calculation_mode": profile.pit_calculation_mode, "pit_formula": profile.pit_formula, "standard_daily_hours": profile.standard_daily_hours, "standard_weekly_hours": profile.standard_weekly_hours, "standard_workweek": profile.standard_workweek, "rounding_policy": profile.rounding_policy,
        "leave_policy": profile.leave_policy, "source_references": profile.source_references, "is_example": profile.is_example,
        "shi_rates": [{"payer": row.payer, "insurance_fund": row.insurance_fund, "insured_category": row.insured_category, "hazard_class": row.hazard_class, "rate": row.rate, "base_floor": row.base_floor, "lower_bound": row.lower_bound, "upper_bound": row.upper_bound, "calculation_mode": row.calculation_mode, "fixed_amount": row.fixed_amount, "base_tax": row.base_tax, "base_ceiling_policy": getattr(row, "base_ceiling_policy", "profile"), "formula": row.formula, "exemption_code": row.exemption_code} for row in rates],
        "pit_brackets": [{"lower_bound": row.lower_bound, "upper_bound": row.upper_bound, "marginal_rate": row.marginal_rate, "base_tax": row.base_tax, "period_basis": row.period_basis, "formula": getattr(row, "formula", None)} for row in brackets],
        "relief_tiers": [{"eligibility_code": row.eligibility_code, "lower_bound": row.lower_bound, "upper_bound": row.upper_bound, "fixed_amount": row.fixed_amount, "amount_basis": row.amount_basis, "formula": row.formula} for row in reliefs],
    })
    successor = await create_statutory_profile(db, actor, data)
    profile.superseded_on = effective_from
    profile.superseded_by_id = successor.id
    await db.flush()
    return successor


async def publish_profile(db: AsyncSession, actor: ActorContext, profile: StatutoryConfigProfile, acknowledge_example: bool) -> None:
    if profile.organization_id != actor.organization_id:
        raise HTTPException(status_code=404, detail="Profile not found")
    if profile.status in {"published", "active"}:
        raise HTTPException(status_code=409, detail={"code": "payroll_profile_already_published"})
    if profile.is_example and not acknowledge_example:
        raise HTTPException(status_code=409, detail={"code": "payroll_example_profile_requires_acknowledgement"})
    if not profile.source_references:
        raise HTTPException(status_code=422, detail={"code": "payroll_source_reference_required", "path": "source_references", "message": "Published statutory profiles must cite an authoritative source.", "remediation": "Add the current Legalinfo law/resolution reference and obtain accountant approval."})
    rates = (await db.execute(select(SHIRateTier).where(SHIRateTier.profile_id == profile.id))).scalars().all()
    brackets = (await db.execute(select(PITBracketTier).where(PITBracketTier.profile_id == profile.id).order_by(PITBracketTier.position))).scalars().all()
    reliefs = (await db.execute(select(TaxReliefTier).where(TaxReliefTier.profile_id == profile.id).order_by(TaxReliefTier.position))).scalars().all()
    if not rates or (profile.pit_calculation_mode != "formula" and not brackets):
        raise HTTPException(status_code=422, detail={"code": "payroll_profile_rules_incomplete"})
    _validate_persisted_tiers(profile, list(rates), list(brackets))
    if any(row.calculation_mode == "formula" and not row.formula for row in rates):
        raise HTTPException(status_code=422, detail={"code": "payroll_invalid_shi_formula", "message": "Every formula-mode SHI rule needs a formula."})
    if any(row.calculation_mode == "formula" for row in rates):
        try:
            for row in rates:
                if row.formula:
                    _SafeFormula(row.formula)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"code": "payroll_invalid_shi_formula", "message": str(exc)}) from exc
    if profile.pit_calculation_mode == "formula":
        try:
            _SafeFormula(profile.pit_formula or "")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"code": "payroll_invalid_pit_formula", "path": "pit_formula", "message": str(exc)}) from exc
    for basis in {bracket.period_basis for bracket in brackets}:
        ordered = sorted((bracket for bracket in brackets if bracket.period_basis == basis), key=lambda bracket: Decimal(str(bracket.lower_bound)))
        previous_upper: Decimal | None = None
        for index, bracket in enumerate(ordered):
            if previous_upper is None and index > 0:
                raise HTTPException(status_code=422, detail={"code": "payroll_bracket_after_unbounded_tier", "period_basis": basis})
            if previous_upper is not None and Decimal(str(bracket.lower_bound)) < previous_upper:
                raise HTTPException(status_code=422, detail={"code": "payroll_overlapping_pit_bracket", "period_basis": basis})
            previous_upper = Decimal(str(bracket.upper_bound)) if bracket.upper_bound is not None else None
    try:
        for relief in reliefs:
            if relief.formula:
                _SafeFormula(relief.formula)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "payroll_invalid_relief_formula", "message": str(exc)}) from exc
    others = (await db.execute(select(StatutoryConfigProfile).where(
        StatutoryConfigProfile.organization_id == actor.organization_id,
        StatutoryConfigProfile.id != profile.id,
        StatutoryConfigProfile.status.in_(("published", "active")),
        (StatutoryConfigProfile.superseded_on.is_(None) | (StatutoryConfigProfile.superseded_on > profile.effective_from)),
    ))).scalars().all()
    if any(row.effective_from <= (profile.effective_to or date.max) and (row.effective_to is None or row.effective_to >= profile.effective_from) for row in others):
        raise HTTPException(status_code=409, detail={"code": "payroll_profile_effective_overlap"})
    # Recompute the digest from the complete published rule set.  This turns
    # the seeded zero checksum into a real snapshot checksum only after an
    # administrator has explicitly reviewed and published the example.
    profile.checksum = _hash({"profile": {"code": profile.code, "version": profile.version, "effective_from": profile.effective_from, "effective_to": profile.effective_to, "currency": profile.currency, "minimum_wage": profile.minimum_wage, "shi_ceiling_multiplier": profile.shi_ceiling_multiplier, "pit_withholding_method": profile.pit_withholding_method, "pit_calculation_mode": profile.pit_calculation_mode, "pit_formula": profile.pit_formula, "standard_daily_hours": profile.standard_daily_hours, "standard_weekly_hours": profile.standard_weekly_hours, "standard_workweek": profile.standard_workweek, "rounding_policy": profile.rounding_policy, "leave_policy": profile.leave_policy, "source_references": profile.source_references}, "shi_rates": [{"payer": row.payer, "insurance_fund": row.insurance_fund, "insured_category": row.insured_category, "hazard_class": row.hazard_class, "rate": row.rate, "base_floor": row.base_floor, "lower_bound": row.lower_bound, "upper_bound": row.upper_bound, "calculation_mode": row.calculation_mode, "fixed_amount": row.fixed_amount, "base_tax": row.base_tax, "base_ceiling_policy": getattr(row, "base_ceiling_policy", "profile"), "formula": row.formula, "exemption_code": row.exemption_code} for row in rates], "pit_brackets": [{"period_basis": row.period_basis, "lower_bound": row.lower_bound, "upper_bound": row.upper_bound, "marginal_rate": row.marginal_rate, "base_tax": row.base_tax, "formula": getattr(row, "formula", None)} for row in brackets], "relief_tiers": [{"eligibility_code": row.eligibility_code, "lower_bound": row.lower_bound, "upper_bound": row.upper_bound, "fixed_amount": row.fixed_amount, "amount_basis": row.amount_basis, "formula": row.formula} for row in reliefs]})
    profile.status = "published"; profile.approved_by_account_id = actor.account_id; profile.approved_at = datetime.now(timezone.utc)


async def create_salary_structure(db: AsyncSession, actor: ActorContext, data: SalaryStructureInput) -> SalaryStructure:
    _validate_date_range(data.effective_from, data.effective_to)
    if data.currency.upper() != "MNT":
        raise HTTPException(status_code=422, detail={"code": "payroll_currency_not_supported", "currency": data.currency})
    codes = [item.code for item in data.components]
    if len(codes) != len(set(codes)): raise HTTPException(status_code=422, detail={"code": "payroll_duplicate_component"})
    if any(item.pay_against_benefit_claim and (not item.is_flexible_benefit or item.component_kind != "earning") for item in data.components):
        raise HTTPException(status_code=422, detail={"code": "payroll_invalid_flexible_benefit_component"})
    master_ids = {item.component_master_id for item in data.components if item.component_master_id is not None}
    if master_ids:
        known_master_ids = set((await db.execute(select(PayrollSalaryComponentMaster.id).where(PayrollSalaryComponentMaster.organization_id == actor.organization_id, PayrollSalaryComponentMaster.status == "active", PayrollSalaryComponentMaster.id.in_(master_ids)))).scalars().all())
        if known_master_ids != master_ids:
            raise HTTPException(status_code=422, detail={"code": "payroll_component_master_invalid", "component_master_ids": sorted(master_ids - known_master_ids)})
    account_ids = {item.account_id for item in data.components if item.account_id is not None}
    if account_ids:
        known_accounts = set((await db.execute(select(ERPAccount.id).where(ERPAccount.organization_id == actor.organization_id, ERPAccount.is_active.is_(True), ERPAccount.id.in_(account_ids)))).scalars().all())
        if known_accounts != account_ids:
            raise HTTPException(status_code=422, detail={"code": "payroll_component_account_invalid", "account_ids": sorted(account_ids - known_accounts)})
    cost_center_ids = {item.cost_center_id for item in data.components if item.cost_center_id is not None}
    if cost_center_ids:
        known_cost_centers = set((await db.execute(select(ERPCostCenter.id).where(ERPCostCenter.organization_id == actor.organization_id, ERPCostCenter.is_active.is_(True), ERPCostCenter.id.in_(cost_center_ids)))).scalars().all())
        if known_cost_centers != cost_center_ids:
            raise HTTPException(status_code=422, detail={"code": "payroll_component_cost_center_invalid", "cost_center_ids": sorted(cost_center_ids - known_cost_centers)})
    try:
        for item in data.components: _SafeFormula(item.formula)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "payroll_invalid_formula", "message": str(exc)}) from exc
    latest_version = await db.scalar(select(func.max(SalaryStructure.version)).where(SalaryStructure.organization_id == actor.organization_id, SalaryStructure.code == data.code)) or 0
    structure = SalaryStructure(organization_id=actor.organization_id, code=data.code, name=data.name, version=int(latest_version) + 1, effective_from=data.effective_from, effective_to=data.effective_to, currency=data.currency.upper(), checksum=_hash(data.model_dump(mode="json")), created_by_account_id=actor.account_id)
    db.add(structure); await db.flush()
    db.add_all([SalaryComponent(salary_structure_id=structure.id, **item.model_dump()) for item in data.components])
    db.add(SalaryStructureVersion(
        salary_structure_id=structure.id,
        version=structure.version,
        status=structure.status,
        effective_from=structure.effective_from,
        effective_to=structure.effective_to,
        component_snapshot=[item.model_dump(mode="json") for item in data.components],
        checksum=structure.checksum,
    ))
    return structure


async def update_salary_structure(db: AsyncSession, actor: ActorContext, structure: SalaryStructure, data: SalaryStructureInput) -> SalaryStructure:
    if structure.organization_id != actor.organization_id:
        raise HTTPException(status_code=404, detail="Salary structure not found")
    if structure.status in {"published", "active"}:
        raise HTTPException(status_code=409, detail={"code": "payroll_salary_structure_immutable"})
    _validate_date_range(data.effective_from, data.effective_to)
    if data.currency.upper() != "MNT":
        raise HTTPException(status_code=422, detail={"code": "payroll_currency_not_supported", "currency": data.currency})
    codes = [item.code for item in data.components]
    if len(codes) != len(set(codes)):
        raise HTTPException(status_code=422, detail={"code": "payroll_duplicate_component"})
    if any(item.pay_against_benefit_claim and (not item.is_flexible_benefit or item.component_kind != "earning") for item in data.components):
        raise HTTPException(status_code=422, detail={"code": "payroll_invalid_flexible_benefit_component"})
    master_ids = {item.component_master_id for item in data.components if item.component_master_id is not None}
    if master_ids:
        known_master_ids = set((await db.execute(select(PayrollSalaryComponentMaster.id).where(PayrollSalaryComponentMaster.organization_id == actor.organization_id, PayrollSalaryComponentMaster.status == "active", PayrollSalaryComponentMaster.id.in_(master_ids)))).scalars().all())
        if known_master_ids != master_ids:
            raise HTTPException(status_code=422, detail={"code": "payroll_component_master_invalid", "component_master_ids": sorted(master_ids - known_master_ids)})
    try:
        for item in data.components:
            _SafeFormula(item.formula)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "payroll_invalid_formula", "message": str(exc)}) from exc
    structure.code = data.code
    structure.name = data.name
    structure.effective_from = data.effective_from
    structure.effective_to = data.effective_to
    structure.currency = data.currency.upper()
    structure.checksum = _hash(data.model_dump(mode="json"))
    await db.execute(delete(SalaryComponent).where(SalaryComponent.salary_structure_id == structure.id))
    db.add_all([SalaryComponent(salary_structure_id=structure.id, **item.model_dump()) for item in data.components])
    version_snapshot = await db.scalar(select(SalaryStructureVersion).where(SalaryStructureVersion.salary_structure_id == structure.id, SalaryStructureVersion.version == structure.version))
    if version_snapshot:
        version_snapshot.effective_from = structure.effective_from
        version_snapshot.effective_to = structure.effective_to
        version_snapshot.component_snapshot = [item.model_dump(mode="json") for item in data.components]
        version_snapshot.checksum = structure.checksum
    await db.flush()
    return structure


async def bump_salary_structure(db: AsyncSession, actor: ActorContext, structure: SalaryStructure, effective_from: date, data: SalaryStructureInput | None = None) -> SalaryStructure:
    if structure.organization_id != actor.organization_id:
        raise HTTPException(status_code=404, detail="Salary structure not found")
    components = (await db.execute(select(SalaryComponent).where(SalaryComponent.salary_structure_id == structure.id).order_by(SalaryComponent.position, SalaryComponent.id))).scalars().all()
    payload = data or SalaryStructureInput.model_validate({
        "code": structure.code, "name": structure.name, "effective_from": effective_from, "effective_to": structure.effective_to,
        "currency": structure.currency,
        "components": [{"component_master_id": row.component_master_id, "code": row.code, "name": row.name, "component_kind": row.component_kind, "formula": row.formula, "amount_mode": row.amount_mode, "percentage_basis": row.percentage_basis, "proration_basis": row.proration_basis, "is_taxable": row.is_taxable, "is_shi_subject": row.is_shi_subject, "is_non_taxable_allowance": row.is_non_taxable_allowance, "is_leave_average_eligible": row.is_leave_average_eligible, "is_flexible_benefit": row.is_flexible_benefit, "max_benefit_amount_yearly": row.max_benefit_amount_yearly, "pay_against_benefit_claim": row.pay_against_benefit_claim, "only_tax_impact": row.only_tax_impact, "payer": row.payer, "position": row.position, "account_id": row.account_id, "cost_center_id": row.cost_center_id, "metadata_json": row.metadata_json} for row in components],
    })
    successor = await create_salary_structure(db, actor, payload)
    successor.source_structure_id = structure.id
    structure.superseded_on = effective_from
    structure.superseded_by_id = successor.id
    await db.flush()
    return successor


async def delete_salary_structure(db: AsyncSession, actor: ActorContext, structure: SalaryStructure) -> None:
    if structure.organization_id != actor.organization_id:
        raise HTTPException(status_code=404, detail="Salary structure not found")
    if structure.status in {"published", "active"}:
        raise HTTPException(status_code=409, detail={"code": "payroll_salary_structure_immutable"})
    referenced_profile = await db.scalar(select(EmployeePayrollProfile.id).where(EmployeePayrollProfile.salary_structure_id == structure.id).limit(1))
    if referenced_profile:
        raise HTTPException(status_code=409, detail={"code": "payroll_salary_structure_referenced_by_employee"})
    referenced_payslip = await db.scalar(select(Payslip.id).where(Payslip.organization_id == actor.organization_id, Payslip.employee_profile_snapshot["salary_structure_id"].as_integer() == structure.id).limit(1))
    if referenced_payslip:
        raise HTTPException(status_code=409, detail={"code": "payroll_salary_structure_referenced_by_payslip", "payslip_id": referenced_payslip})
    await db.delete(structure)
    await db.flush()


async def create_employee_profile(db: AsyncSession, actor: ActorContext, employee_id: int, data: EmployeePayrollInput) -> EmployeePayrollProfile:
    employee = await db.get(Employee, employee_id)
    if not employee: raise HTTPException(status_code=404, detail="Employee not found")
    if employee.organization_id != actor.organization_id:
        raise HTTPException(status_code=404, detail="Employee not found")
    structure = await db.scalar(select(SalaryStructure).where(SalaryStructure.id == data.salary_structure_id, SalaryStructure.organization_id == actor.organization_id, SalaryStructure.effective_from <= data.effective_from, (SalaryStructure.effective_to.is_(None) | (SalaryStructure.effective_to >= data.effective_from))))
    if not structure or structure.status not in {"published", "active"}: raise HTTPException(status_code=404, detail="Published salary structure not found")
    existing_profiles = (await db.execute(select(EmployeePayrollProfile).where(EmployeePayrollProfile.organization_id == actor.organization_id, EmployeePayrollProfile.employee_id == employee_id))).scalars().all()
    overlaps = [row for row in existing_profiles if row.effective_from <= (data.effective_to or date.max) and (row.effective_to is None or row.effective_to >= data.effective_from)]
    for prior in overlaps:
        if prior.effective_from == data.effective_from:
            raise HTTPException(status_code=409, detail={"code": "payroll_employee_profile_effective_overlap"})
        prior.effective_to = data.effective_from - timedelta(days=1)
    values = data.model_dump(exclude={"employee_id", "salary_structure_id", "taxpayer_number", "social_insurance_number"})
    profile = EmployeePayrollProfile(organization_id=actor.organization_id, employee_id=employee_id, salary_structure_id=structure.id, **values)
    if data.taxpayer_number: profile.taxpayer_number_ciphertext = encrypt_secret(data.taxpayer_number)
    if data.social_insurance_number: profile.social_insurance_number_ciphertext = encrypt_secret(data.social_insurance_number)
    db.add(profile); await db.flush(); return profile


async def create_bank_account(db: AsyncSession, actor: ActorContext, employee_id: int, data: BankAccountInput) -> EmployeeBankAccount:
    _validate_date_range(data.valid_from, data.valid_to)
    profile = await db.scalar(select(EmployeePayrollProfile).where(EmployeePayrollProfile.employee_id == employee_id, EmployeePayrollProfile.organization_id == actor.organization_id, EmployeePayrollProfile.effective_from <= data.valid_from, (EmployeePayrollProfile.effective_to.is_(None) | (EmployeePayrollProfile.effective_to >= data.valid_from))).order_by(EmployeePayrollProfile.effective_from.desc()).limit(1))
    employee = await db.scalar(select(Employee).where(Employee.id == employee_id, Employee.organization_id == actor.organization_id))
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    if data.is_primary:
        accounts = (await db.execute(select(EmployeeBankAccount).where(EmployeeBankAccount.employee_id == employee_id))).scalars().all()
        for account in accounts: account.is_primary = False
    normalized_account = "".join(data.account_number.split())
    if len(normalized_account) < 4:
        raise HTTPException(status_code=422, detail={"code": "payroll_invalid_bank_account"})
    fingerprint = hashlib.sha256(normalized_account.encode()).hexdigest()
    account = EmployeeBankAccount(employee_payroll_profile_id=profile.id if profile else None, employee_id=employee_id, bank_code=data.bank_code, account_number_ciphertext=encrypt_secret(normalized_account), account_fingerprint=fingerprint, account_last4=normalized_account[-4:], account_holder_ciphertext=encrypt_secret(data.account_holder.strip()) if data.account_holder else None, is_primary=data.is_primary, valid_from=data.valid_from, valid_to=data.valid_to)
    db.add(account); await db.flush(); return account


async def create_run(db: AsyncSession, actor: ActorContext, data: PayrollRunInput) -> PayrollRun:
    organization = await db.get(Organization, actor.organization_id)
    if organization and (organization.settings or {}).get("unified_payroll_v2") is False:
        raise HTTPException(status_code=409, detail={"code": "unified_payroll_v2_disabled"})
    preflight = await preflight_run(db, actor, data)
    if preflight["blockers"]:
        raise HTTPException(status_code=409, detail={"code": "payroll_preflight_blocked", **preflight})
    if data.period_end < data.period_start: raise HTTPException(status_code=422, detail={"code": "payroll_invalid_period"})
    profile = await ensure_profile_active(db, data.statutory_profile_id, data.tax_point_date) if data.statutory_profile_id else await resolve_profile(db, actor.organization_id, data.tax_point_date)
    if profile.organization_id != actor.organization_id:
        raise HTTPException(status_code=404, detail="Statutory profile not found")
    employee_ids = list(preflight["employee_ids"])
    if not employee_ids: raise HTTPException(status_code=422, detail={"code": "payroll_no_employees"})
    valid_employee_ids = set((await db.execute(select(EmployeePayrollProfile.employee_id).where(
        EmployeePayrollProfile.organization_id == actor.organization_id,
        EmployeePayrollProfile.employee_id.in_(employee_ids),
        EmployeePayrollProfile.effective_from <= data.tax_point_date,
        (EmployeePayrollProfile.effective_to.is_(None) | (EmployeePayrollProfile.effective_to >= data.tax_point_date)),
    ))).scalars().all())
    missing_employee_ids = sorted(set(employee_ids) - valid_employee_ids)
    if missing_employee_ids:
        raise HTTPException(status_code=422, detail={"code": "payroll_employee_profile_missing", "employee_ids": missing_employee_ids})
    variable_employee_ids = {row.employee_id for row in data.variable_inputs}
    if variable_employee_ids - set(employee_ids):
        raise HTTPException(status_code=422, detail={"code": "payroll_variable_input_employee_not_in_run", "employee_ids": sorted(variable_employee_ids - set(employee_ids))})
    for employee_key, override in data.input_overrides.items():
        if override and not str(override.get("reason") or "").strip():
            raise HTTPException(status_code=422, detail={"code": "payroll_manual_override_reason_required", "path": f"input_overrides.{employee_key}.reason", "message": "Manual payroll overrides must include an explanation.", "remediation": "Add reason to the override; it will be frozen in the run snapshot."})
    frozen_shi_rates = (await db.execute(select(SHIRateTier).where(SHIRateTier.profile_id == profile.id).order_by(SHIRateTier.position, SHIRateTier.id))).scalars().all()
    frozen_pit_brackets = (await db.execute(select(PITBracketTier).where(PITBracketTier.profile_id == profile.id).order_by(PITBracketTier.position, PITBracketTier.id))).scalars().all()
    frozen_reliefs = (await db.execute(select(TaxReliefTier).where(TaxReliefTier.profile_id == profile.id).order_by(TaxReliefTier.position, TaxReliefTier.id))).scalars().all()
    frozen_work_policies = (await db.execute(select(PayrollWorkPolicy).where(PayrollWorkPolicy.organization_id == actor.organization_id, PayrollWorkPolicy.status.in_(("active", "published")), PayrollWorkPolicy.effective_from <= data.tax_point_date, (PayrollWorkPolicy.effective_to.is_(None) | (PayrollWorkPolicy.effective_to >= data.tax_point_date))).order_by(PayrollWorkPolicy.scope_type, PayrollWorkPolicy.scope_key, PayrollWorkPolicy.effective_from.desc()))).scalars().all()
    period_end_exclusive = datetime.combine(data.period_end, datetime.max.time())
    approved_entries = list((await db.execute(select(WorkTimeEntry).where(WorkTimeEntry.employee_id.in_(employee_ids), WorkTimeEntry.entry_type == "work", WorkTimeEntry.approval_status == "approved", WorkTimeEntry.started_at >= datetime.combine(data.period_start, datetime.min.time()), WorkTimeEntry.started_at <= period_end_exclusive))).scalars().all())
    approved_time_ids = [entry.id for entry in approved_entries]
    approved_time_snapshot = [{"id": entry.id, "employee_id": entry.employee_id, "local_work_date": entry.local_work_date.isoformat() if entry.local_work_date else None, "started_at": entry.started_at.isoformat(), "ended_at": entry.ended_at.isoformat() if entry.ended_at else None, "approval_status": entry.approval_status, "hours": str(Decimal(str((entry.ended_at - entry.started_at).total_seconds())) / Decimal("3600")) if entry.ended_at else "0"} for entry in approved_entries]
    snapshot = {"employee_ids": employee_ids, "employee_filter": data.employee_filter, "overrides": data.input_overrides, "attendance_policy": data.attendance_policy, "validate_attendance": data.validate_attendance, "posting_date": (data.posting_date or data.tax_point_date).isoformat(), "cost_center_id": data.cost_center_id, "variable_inputs": [row.model_dump(mode="json") for row in data.variable_inputs], "approved_time_entry_ids": approved_time_ids, "approved_time_entries": approved_time_snapshot, "preflight": preflight, "calendar": {"period_start": data.period_start.isoformat(), "period_end": data.period_end.isoformat(), "timezone": "Asia/Ulaanbaatar"}}
    config_snapshot = {"profile_id": profile.id, "profile_version": profile.version, "profile_checksum": profile.checksum, "source_references": profile.source_references, "is_example": profile.is_example, "currency": profile.currency, "pit_withholding_method": profile.pit_withholding_method, "pit_calculation_mode": profile.pit_calculation_mode, "pit_formula": profile.pit_formula, "standard_daily_hours": str(profile.standard_daily_hours), "standard_weekly_hours": str(profile.standard_weekly_hours), "standard_workweek": profile.standard_workweek, "rounding_policy": profile.rounding_policy, "minimum_wage": str(profile.minimum_wage), "shi_ceiling_multiplier": str(profile.shi_ceiling_multiplier), "leave_policy": profile.leave_policy, "work_policies": [{"id": row.id, "scope_type": row.scope_type, "scope_key": row.scope_key, "code": row.code, "daily_hours": str(row.daily_hours), "weekly_hours": str(row.weekly_hours), "workweek": row.workweek, "overtime_rules": row.overtime_rules, "stacking_policy": row.stacking_policy} for row in frozen_work_policies], "shi_rates": [{"payer": row.payer, "insurance_fund": row.insurance_fund, "insured_category": row.insured_category, "hazard_class": row.hazard_class, "rate": str(row.rate), "base_floor": str(row.base_floor), "lower_bound": str(row.lower_bound), "upper_bound": str(row.upper_bound) if row.upper_bound is not None else None, "calculation_mode": row.calculation_mode, "fixed_amount": str(row.fixed_amount), "base_tax": str(row.base_tax), "base_ceiling_policy": getattr(row, "base_ceiling_policy", "profile"), "formula": row.formula, "exemption_code": row.exemption_code} for row in frozen_shi_rates], "pit_brackets": [{"period_basis": row.period_basis, "lower_bound": str(row.lower_bound), "upper_bound": str(row.upper_bound) if row.upper_bound is not None else None, "marginal_rate": str(row.marginal_rate), "base_tax": str(row.base_tax), "formula": getattr(row, "formula", None)} for row in frozen_pit_brackets], "relief_tiers": [{"eligibility_code": row.eligibility_code, "lower_bound": str(row.lower_bound), "upper_bound": str(row.upper_bound) if row.upper_bound is not None else None, "fixed_amount": str(row.fixed_amount), "amount_basis": row.amount_basis, "formula": row.formula} for row in frozen_reliefs]}
    run = PayrollRun(organization_id=actor.organization_id, run_number=f"PR-{data.period_end:%Y%m}-{datetime.now(timezone.utc).strftime('%H%M%S%f')[:9]}", run_type=data.run_type, period_start=data.period_start, period_end=data.period_end, settlement_key=data.period_end.strftime("%Y-%m"), tax_point_date=data.tax_point_date, posting_date=data.posting_date or data.tax_point_date, workflow_version="unified_v2", document_status="draft", cost_center_id=data.cost_center_id, statutory_profile_id=profile.id, input_snapshot=snapshot, config_snapshot=config_snapshot, snapshot_checksum=_hash({"input": snapshot, "config": config_snapshot}), created_by_account_id=actor.account_id)
    db.add(run); await db.flush(); return run


async def calculate_run(db: AsyncSession, actor: ActorContext, run: PayrollRun) -> list[Payslip]:
    if run.organization_id != actor.organization_id: raise HTTPException(status_code=404, detail="Run not found")
    if run.status != "draft": raise HTTPException(status_code=409, detail={"code": "payroll_run_immutable", "status": run.status})
    profile = await ensure_profile_active(db, run.statutory_profile_id, run.tax_point_date)
    await db.execute(delete(Payslip).where(Payslip.payroll_run_id == run.id))
    employee_ids = list((run.input_snapshot or {}).get("employee_ids") or [])
    overrides = (run.input_snapshot or {}).get("overrides") or {}
    result_rows: list[Payslip] = []
    for employee_id in employee_ids:
        # Serialise all calculations for an employee.  This is the lock that
        # makes monthly SHI-cap and YTD consumption deterministic when two
        # off-cycle runs are calculated concurrently.
        employee_profile = await db.scalar(select(EmployeePayrollProfile).where(EmployeePayrollProfile.organization_id == actor.organization_id, EmployeePayrollProfile.employee_id == employee_id, EmployeePayrollProfile.effective_from <= run.period_end, (EmployeePayrollProfile.effective_to.is_(None) | (EmployeePayrollProfile.effective_to >= run.period_start))).order_by(EmployeePayrollProfile.effective_from.desc()).limit(1).with_for_update())
        if not employee_profile: raise HTTPException(status_code=422, detail={"code": "payroll_employee_profile_missing", "employee_id": employee_id})
        employee_row = await db.scalar(select(Employee).where(Employee.id == employee_id, Employee.organization_id == actor.organization_id))
        frozen_policies = (run.config_snapshot or {}).get("work_policies") or []
        work_policy = None
        if frozen_policies:
            policy_keys = [("employee", str(employee_id)), ("job_title", employee_row.job_title if employee_row else None), ("organization", "*")]
            for scope_type, scope_key in policy_keys:
                candidate = next((item for item in frozen_policies if item.get("scope_type") == scope_type and item.get("scope_key") == scope_key), None)
                if candidate:
                    work_policy = SimpleNamespace(**candidate)
                    break
        if work_policy is None:
            work_policy = await resolve_work_policy(db, actor.organization_id, employee_id, run.tax_point_date, job_title=employee_row.job_title if employee_row else None)
        structure = await db.get(SalaryStructure, employee_profile.salary_structure_id)
        rules = await load_rules(db, profile, insured_category=employee_profile.insured_category, hazard_class=employee_profile.hazard_class, effective_date=run.tax_point_date)
        components = (await db.execute(select(SalaryComponent).where(SalaryComponent.salary_structure_id == structure.id).order_by(SalaryComponent.position, SalaryComponent.id))).scalars().all()
        prior = await db.execute(select(func.coalesce(func.sum(Payslip.gross), 0), func.coalesce(func.sum(Payslip.taxable_income), 0), func.coalesce(func.sum(Payslip.pit), 0)).join(PayrollRun, PayrollRun.id == Payslip.payroll_run_id).where(Payslip.organization_id == actor.organization_id, Payslip.employee_id == employee_id, PayrollRun.tax_point_date >= date(run.tax_point_date.year, 1, 1), PayrollRun.tax_point_date < date(run.tax_point_date.year + 1, 1, 1), PayrollRun.status.in_(("posted", "paid")), PayrollRun.tax_point_date <= run.tax_point_date, PayrollRun.run_type != "advance", PayrollRun.id != run.id))
        prior_gross, prior_taxable, prior_pit = prior.one()
        # Keep compatibility with a migrated ledger that has accumulator
        # rows but no retained payslip rows (for example, a legacy import).
        if not any((prior_gross, prior_taxable, prior_pit)):
            legacy_prior = await db.execute(select(func.coalesce(func.sum(PayrollEmployeeAccumulator.gross_delta), 0), func.coalesce(func.sum(PayrollEmployeeAccumulator.taxable_delta), 0), func.coalesce(func.sum(PayrollEmployeeAccumulator.pit_withheld_delta), 0)).where(PayrollEmployeeAccumulator.organization_id == actor.organization_id, PayrollEmployeeAccumulator.employee_id == employee_id, PayrollEmployeeAccumulator.tax_year == run.tax_point_date.year))
            prior_gross, prior_taxable, prior_pit = legacy_prior.one()
        prior_relief = await db.scalar(select(func.coalesce(func.sum(Payslip.pit_relief), 0)).join(PayrollRun, PayrollRun.id == Payslip.payroll_run_id).where(Payslip.organization_id == actor.organization_id, Payslip.employee_id == employee_id, PayrollRun.tax_point_date >= date(run.tax_point_date.year, 1, 1), PayrollRun.tax_point_date < run.tax_point_date, PayrollRun.status.in_(("posted", "paid")), PayrollRun.run_type != "advance")) or 0
        prior_month_base = await db.scalar(select(func.coalesce(func.sum(Payslip.shi_base), 0)).join(PayrollRun, PayrollRun.id == Payslip.payroll_run_id).where(Payslip.organization_id == actor.organization_id, Payslip.employee_id == employee_id, PayrollRun.settlement_key == run.settlement_key, PayrollRun.status.in_(("posted", "paid")), PayrollRun.tax_point_date <= run.tax_point_date, PayrollRun.id != run.id)) or 0
        override = overrides.get(str(employee_id), {}) or {}
        # Advances are created when an advance run is posted.  A final (or
        # single) run consumes only the still-unapplied balance.  Keeping the
        # lookup here, before calling the pure calculator, makes the advance
        # input part of the frozen payslip snapshot and prevents tax from
        # being recomputed or withheld a second time.
        advance_rows = (await db.execute(select(PayrollAdvance).where(
            PayrollAdvance.organization_id == actor.organization_id,
            PayrollAdvance.employee_id == employee_id,
            PayrollAdvance.settlement_key == run.settlement_key,
            PayrollAdvance.status.in_(("approved", "partially_applied")),
            PayrollAdvance.amount > PayrollAdvance.applied_amount,
        ).order_by(PayrollAdvance.id))).scalars().all()
        unapplied_advance = sum((max(Decimal("0"), Decimal(str(row.amount)) - Decimal(str(row.applied_amount or 0))) for row in advance_rows), Decimal("0"))
        if "current_advance" in override:
            current_advance = Decimal(str(override.get("current_advance", 0)))
        else:
            current_advance = unapplied_advance if run.run_type in {"final", "single"} else Decimal("0")
        context = override.get("context") or {}
        frozen_time_entries = (run.input_snapshot or {}).get("approved_time_entries") or []
        if frozen_time_entries:
            approved_dates = {date.fromisoformat(str(entry["local_work_date"])) if entry.get("local_work_date") else datetime.fromisoformat(str(entry["started_at"])).date() for entry in frozen_time_entries if int(entry.get("employee_id", -1)) == employee_id}
            approved_hours = sum((Decimal(str(entry.get("hours", 0))) for entry in frozen_time_entries if int(entry.get("employee_id", -1)) == employee_id), Decimal("0"))
        else:
            # Compatibility for runs created before full time-entry snapshots
            # were introduced; new runs always use the frozen branch above.
            approved_entries = (await db.execute(select(WorkTimeEntry).where(WorkTimeEntry.id.in_((run.input_snapshot or {}).get("approved_time_entry_ids") or []), WorkTimeEntry.employee_id == employee_id, WorkTimeEntry.entry_type == "work", WorkTimeEntry.approval_status == "approved"))).scalars().all()
            approved_dates = {entry.local_work_date or entry.started_at.date() for entry in approved_entries}
            approved_hours = sum((Decimal(str((entry.ended_at - entry.started_at).total_seconds())) / Decimal("3600") for entry in approved_entries if entry.ended_at is not None), Decimal("0"))
        workweek = set((work_policy.workweek if work_policy else (run.config_snapshot or {}).get("standard_workweek") or [1, 2, 3, 4, 5]))
        scheduled_workdays = sum(1 for offset in range((run.period_end - run.period_start).days + 1) if (run.period_start + timedelta(days=offset)).isoweekday() in workweek)
        unpaid_leave_days = Decimal(str(override.get("unpaid_leave_days", 0)))
        default_payable_workdays = Decimal(str(len(approved_dates))) if approved_dates else max(Decimal("0"), Decimal(str(scheduled_workdays)) - unpaid_leave_days)
        payable_workdays = Decimal(str(override.get("payable_workdays", default_payable_workdays)))
        scheduled_workdays_value = Decimal(str(override.get("scheduled_workdays", scheduled_workdays)))
        payable_hours = Decimal(str(override.get("payable_hours", approved_hours)))
        daily_hours = Decimal(str(work_policy.daily_hours if work_policy else profile.standard_daily_hours))
        scheduled_hours = Decimal(str(override.get("scheduled_hours", approved_hours if approved_hours > 0 else scheduled_workdays_value * daily_hours)))
        overtime_hours = max(Decimal("0"), payable_hours - scheduled_hours)
        weekday_overtime = rest_day_overtime = public_holiday_overtime = night_overtime = Decimal("0")
        public_holidays = set((run.input_snapshot or {}).get("attendance_policy", {}).get("public_holidays") or [])
        if frozen_time_entries:
            for entry in frozen_time_entries:
                if int(entry.get("employee_id", -1)) != employee_id:
                    continue
                hours = Decimal(str(entry.get("hours", 0)))
                work_date = date.fromisoformat(str(entry["local_work_date"])) if entry.get("local_work_date") else datetime.fromisoformat(str(entry["started_at"])).date()
                started = datetime.fromisoformat(str(entry["started_at"]))
                if work_date.isoformat() in public_holidays:
                    public_holiday_overtime += hours
                elif work_date.isoweekday() in workweek:
                    weekday_overtime += hours
                else:
                    rest_day_overtime += hours
                if started.hour >= 22 or started.hour < 6:
                    night_overtime += hours
        overtime_context = {"overtime_hours": overtime_hours, "weekday_overtime_hours": min(overtime_hours, weekday_overtime), "rest_day_overtime_hours": min(overtime_hours, rest_day_overtime), "public_holiday_overtime_hours": min(overtime_hours, public_holiday_overtime), "night_overtime_hours": min(overtime_hours, night_overtime)}
        leave_month_payload = override.get("leave_months")
        if leave_month_payload is None:
            lookback_months = int((rules.leave_policy or {}).get("lookback_months", 12))
            month_number = run.tax_point_date.year * 12 + run.tax_point_date.month - 1 - max(lookback_months, 1)
            history_start = date(month_number // 12, month_number % 12 + 1, 1)
            history_rows = (await db.execute(select(Payslip).join(PayrollRun, PayrollRun.id == Payslip.payroll_run_id).where(Payslip.organization_id == actor.organization_id, Payslip.employee_id == employee_id, PayrollRun.tax_point_date >= history_start, PayrollRun.tax_point_date < run.tax_point_date, PayrollRun.status.in_(("approved", "posted", "paid"))).order_by(PayrollRun.tax_point_date))).scalars().all()
            leave_month_payload = []
            for history_row in history_rows:
                history_lines = (await db.execute(select(PayslipLineItem).where(PayslipLineItem.payslip_id == history_row.id))).scalars().all()
                eligible_earnings = sum((Decimal(str(item.amount)) for item in history_lines if item.component_kind == "earning" and item.payer == "employee" and (item.trace or {}).get("leave_average_eligible", True)), Decimal("0"))
                history_input = history_row.input_snapshot or {}
                history_override = history_input.get("override") or {}
                history_units = history_input.get("resolved_units") or {}
                leave_month_payload.append({"earnings": str(eligible_earnings), "worked_days": str(history_override.get("payable_workdays", history_units.get("payable_workdays", 0))), "eligible": True})
        leave_months = tuple(LeaveMonth(Decimal(str(item.get("earnings", 0))), Decimal(str(item.get("worked_days", 0))), bool(item.get("eligible", True))) for item in (leave_month_payload or []) if isinstance(item, dict))
        tax_adjustments = await approved_tax_adjustments(db, organization_id=actor.organization_id, employee_id=employee_id, tax_year=run.tax_point_date.year)
        prior_traces = list((await db.execute(select(Payslip.calculation_trace).join(PayrollRun, PayrollRun.id == Payslip.payroll_run_id).where(Payslip.organization_id == actor.organization_id, Payslip.employee_id == employee_id, PayrollRun.tax_point_date >= date(run.tax_point_date.year, 1, 1), PayrollRun.tax_point_date < run.tax_point_date, PayrollRun.status.in_(("posted", "paid")), PayrollRun.tax_point_date <= run.tax_point_date, PayrollRun.run_type != "advance", PayrollRun.id != run.id))).scalars().all())
        prior_declared_deduction = sum((Decimal(str(((trace or {}).get("pit") or {}).get("declared_deduction", 0))) for trace in prior_traces), Decimal("0"))
        prior_declared_credit = sum((Decimal(str(((trace or {}).get("pit") or {}).get("declared_credit", 0))) for trace in prior_traces), Decimal("0"))
        declared_deduction = max(Decimal("0"), Decimal(str(tax_adjustments["deduction"])) - prior_declared_deduction)
        declared_credit = Decimal(str(tax_adjustments["credit"])) if rules.pit_withholding_method == "ytd_cumulative" else max(Decimal("0"), Decimal(str(tax_adjustments["credit"])) - prior_declared_credit)
        benefit_claims = await reserve_benefit_claims(db, run=run, employee_id=employee_id)
        grouped_claims = grouped_benefit_claims(benefit_claims)
        benefit_context = {f"benefit_claim_amount_{item['component_id']}": item["amount"] for item in grouped_claims}
        base_defs = [ComponentDefinition(code=row.code, label=row.name, component_kind=row.component_kind, formula=row.formula, amount_mode=row.amount_mode, percentage_basis=row.percentage_basis, proration_basis=row.proration_basis, taxable=row.is_taxable, shi_subject=row.is_shi_subject, non_taxable_allowance=row.is_non_taxable_allowance, leave_average_eligible=row.is_leave_average_eligible, only_tax_impact=row.only_tax_impact, payer=row.payer, position=row.position) for row in components if not (row.is_flexible_benefit and row.pay_against_benefit_claim)]
        benefit_defs = [ComponentDefinition(code=f"benefit_claim_{item['component_id']}", label=item["component_name"], component_kind="earning", formula=f"benefit_claim_amount_{item['component_id']}", taxable=item["taxable"], shi_subject=item["shi_subject"], non_taxable_allowance=item["non_taxable_allowance"], leave_average_eligible=False, only_tax_impact=item["only_tax_impact"], payer="employee", position=len(components) + index) for index, item in enumerate(grouped_claims)]
        employee_variable_inputs = [item for item in ((run.input_snapshot or {}).get("variable_inputs") or []) if int(item.get("employee_id", -1)) == employee_id]
        variable_defs = [ComponentDefinition(code=f"variable_{index}_{item['code']}", label=item["label"], component_kind=item["component_kind"], formula=str(item["amount"]), taxable=bool(item.get("taxable", True)), shi_subject=bool(item.get("shi_subject", True)), non_taxable_allowance=not bool(item.get("taxable", True)), leave_average_eligible=False, payer="employee", position=len(components) + len(benefit_defs) + index) for index, item in enumerate(employee_variable_inputs)]
        overtime_defs: list[ComponentDefinition] = []
        overtime_rules = (work_policy.overtime_rules if work_policy else {}) or {}
        premium_candidates = [("weekday_overtime_hours", "weekday", "Weekday overtime"), ("rest_day_overtime_hours", "rest_day", "Rest-day overtime"), ("public_holiday_overtime_hours", "public_holiday", "Public-holiday overtime"), ("night_overtime_hours", "night", "Night overtime")]
        if (work_policy.stacking_policy if work_policy else "exclusive") == "exclusive":
            available = []
            for hours_code, rule_code, label in premium_candidates:
                raw_multiplier = overtime_rules.get(rule_code)
                if raw_multiplier in (None, "", 0, "0"):
                    continue
                try:
                    multiplier_value = Decimal(str(raw_multiplier))
                except Exception as exc:
                    raise HTTPException(status_code=422, detail={"code": "payroll_invalid_overtime_multiplier", "path": f"work_policy.overtime_rules.{rule_code}"}) from exc
                if multiplier_value < 0:
                    raise HTTPException(status_code=422, detail={"code": "payroll_invalid_overtime_multiplier", "path": f"work_policy.overtime_rules.{rule_code}"})
                if Decimal(str(overtime_context.get(hours_code, 0))) > 0:
                    available.append((hours_code, rule_code, label, multiplier_value))
            premium_candidates = [(hours_code, rule_code, label) for hours_code, rule_code, label, _ in sorted(available, key=lambda item: item[3], reverse=True)[:1]]
        for index, (hours_code, rule_code, label) in enumerate(premium_candidates):
            multiplier = overtime_rules.get(rule_code)
            if multiplier in (None, "", 0, "0"):
                continue
            try:
                multiplier_decimal = Decimal(str(multiplier))
            except Exception as exc:
                raise HTTPException(status_code=422, detail={"code": "payroll_invalid_overtime_multiplier", "path": f"work_policy.overtime_rules.{rule_code}"}) from exc
            if multiplier_decimal < 0:
                raise HTTPException(status_code=422, detail={"code": "payroll_invalid_overtime_multiplier", "path": f"work_policy.overtime_rules.{rule_code}"})
            overtime_defs.append(ComponentDefinition(code=f"overtime_{rule_code}", label=label, component_kind="earning", formula=f"if_else(scheduled_hours > 0, {hours_code} * base_salary / scheduled_hours * {multiplier_decimal}, 0)", taxable=True, shi_subject=True, leave_average_eligible=False, payer="employee", position=len(components) + len(benefit_defs) + len(variable_defs) + index))
        defs = tuple(base_defs + benefit_defs + variable_defs + overtime_defs)
        calc = calculate_payslip(CalculationInput(base_salary=Decimal(str(override.get("base_salary", employee_profile.base_salary))), payable_workdays=payable_workdays, scheduled_workdays=scheduled_workdays_value, payable_calendar_days=Decimal(str(override.get("payable_calendar_days", (run.period_end - run.period_start).days + 1))), scheduled_calendar_days=Decimal(str(override.get("scheduled_calendar_days", (run.period_end - run.period_start).days + 1))), payable_hours=payable_hours, scheduled_hours=scheduled_hours, context={**context, **overtime_context, **benefit_context}, components=defs, prior_ytd_gross=Decimal(str(prior_gross or 0)), prior_ytd_taxable=Decimal(str(prior_taxable or 0)), prior_ytd_pit=Decimal(str(prior_pit or 0)), prior_ytd_relief=Decimal(str(prior_relief or 0)), prior_month_shi_base=Decimal(str(prior_month_base or 0)), current_advance=current_advance if run.run_type != "advance" else Decimal("0"), other_tax_deductible=Decimal(str(override.get("other_tax_deductible", 0))) + declared_deduction, other_tax_credit=declared_credit, other_deductions=Decimal(str(override.get("other_deductions", 0))), relief_eligibilities=frozenset(employee_profile.tax_relief_eligibility or []), leave_months=leave_months, leave_days=Decimal(str(override.get("leave_days", 0))), exemption_codes=frozenset((employee_profile.exemption_flags or {}).get("shi", [])), withhold_statutory=run.run_type != "advance"))
        profile_snapshot = {"employee_id": employee_id, "base_salary": str(employee_profile.base_salary), "salary_structure_id": structure.id, "salary_structure_version": structure.version, "salary_structure_checksum": structure.checksum, "components": [{"code": row.code, "name": row.name, "component_kind": row.component_kind, "formula": row.formula, "amount_mode": row.amount_mode, "percentage_basis": row.percentage_basis, "proration_basis": row.proration_basis, "is_taxable": row.is_taxable, "is_shi_subject": row.is_shi_subject, "is_non_taxable_allowance": row.is_non_taxable_allowance, "is_leave_average_eligible": row.is_leave_average_eligible, "is_flexible_benefit": row.is_flexible_benefit, "max_benefit_amount_yearly": str(row.max_benefit_amount_yearly), "pay_against_benefit_claim": row.pay_against_benefit_claim, "only_tax_impact": row.only_tax_impact, "payer": row.payer, "position": row.position, "account_id": row.account_id, "cost_center_id": row.cost_center_id} for row in components], "insured_category": employee_profile.insured_category, "hazard_class": employee_profile.hazard_class, "residency_status": employee_profile.residency_status, "tax_relief_eligibility": employee_profile.tax_relief_eligibility, "exemption_flags": employee_profile.exemption_flags, "insured_code": employee_profile.insured_category}
        input_snapshot = {"override": override, "variable_inputs": employee_variable_inputs, "profile_id": employee_profile.id, "advance_ids": [row.id for row in advance_rows], "unapplied_advance": str(unapplied_advance), "current_advance": str(current_advance), "tax_adjustments": {**tax_adjustments, "deduction": str(tax_adjustments["deduction"]), "credit": str(tax_adjustments["credit"]), "applied_deduction": str(declared_deduction), "applied_credit": str(declared_credit)}, "benefit_claims": benefit_claims, "work_policy": {"id": work_policy.id, "code": work_policy.code, "daily_hours": str(work_policy.daily_hours), "weekly_hours": str(work_policy.weekly_hours), "workweek": work_policy.workweek, "overtime_rules": work_policy.overtime_rules, "stacking_policy": work_policy.stacking_policy} if work_policy else {"daily_hours": str(profile.standard_daily_hours), "weekly_hours": str(profile.standard_weekly_hours), "workweek": sorted(workweek)}, "resolved_units": {"payable_workdays": str(payable_workdays), "scheduled_workdays": str(scheduled_workdays_value), "payable_calendar_days": str(Decimal(str(override.get("payable_calendar_days", (run.period_end - run.period_start).days + 1)))), "scheduled_calendar_days": str(Decimal(str(override.get("scheduled_calendar_days", (run.period_end - run.period_start).days + 1)))), "payable_hours": str(payable_hours), "scheduled_hours": str(scheduled_hours), "overtime_hours": str(overtime_hours)}}
        payslip = Payslip(payroll_run_id=run.id, organization_id=actor.organization_id, employee_id=employee_id, document_status="draft", employee_profile_snapshot=profile_snapshot, input_snapshot=input_snapshot, calculation_trace=calc.trace, ytd_snapshot={key: str(value) for key, value in calc.ytd.items()}, gross=calc.gross, taxable_income=calc.taxable_income, shi_subject_gross=calc.shi_subject_gross, shi_base=calc.shi_base, employee_shi=calc.employee_shi, employer_shi=calc.employer_shi, pit=calc.pit, pit_relief=calc.relief, advance_offset=calc.advance_offset, net_pay=calc.net_pay, snapshot_checksum=snapshot_checksum({"profile": profile_snapshot, "input": input_snapshot, "result": calc.trace, "gross": str(calc.gross), "taxable_income": str(calc.taxable_income), "net": str(calc.net_pay)}))
        db.add(payslip); await db.flush()
        component_by_code = {row.code: row for row in components}
        component_by_code.update({f"benefit_claim_{item['component_id']}": next((row for row in components if row.id == item["component_id"]), None) for item in grouped_claims})
        db.add_all([PayslipLineItem(payslip_id=payslip.id, component_code=line["code"], component_master_id=getattr(component_by_code.get(line["code"]), "component_master_id", None), label=line["label"], component_kind=line["component_kind"], amount=line["amount"], taxable=line["taxable"], shi_subject=line["shi_subject"], payer=line["payer"], formula_snapshot=line["formula"], trace={"position": line["position"], "leave_average_eligible": line.get("leave_average_eligible", False)}, account_id=getattr(component_by_code.get(line["code"]), "account_id", None), cost_center_id=getattr(component_by_code.get(line["code"]), "cost_center_id", None), position=line["position"]) for line in calc.lines])
        statutory_rules = (calc.trace.get("shi") or {}).get("rules") or []
        db.add_all([PayslipStatutoryLine(payslip_id=payslip.id, contributor_code=employee_profile.insured_category, payer=item.get("payer", "employee"), insurance_fund=item.get("insurance_fund", "unknown"), hazard_class=employee_profile.hazard_class, calculation_mode=item.get("calculation_mode", "flat_percent"), base=Decimal(str(item.get("base", 0))), lower_bound=Decimal(str(item.get("lower_bound", 0))), upper_bound=Decimal(str(item["upper_bound"])) if item.get("upper_bound") is not None else None, rate=Decimal(str(item.get("rate", 0))), amount=Decimal(str(item.get("amount", 0))), formula_snapshot=item.get("formula"), trace=item, position=index) for index, item in enumerate(statutory_rules)])
        result_rows.append(payslip)
    run.total_gross = sum((row.gross for row in result_rows), Decimal("0")); run.total_employee_shi = sum((row.employee_shi for row in result_rows), Decimal("0")); run.total_employer_shi = sum((row.employer_shi for row in result_rows), Decimal("0")); run.total_pit = sum((row.pit for row in result_rows), Decimal("0")); run.total_net = sum((row.net_pay for row in result_rows), Decimal("0")); run.status = "calculated"; run.reconciliation_snapshot = {}; run.approval_workflow = {}; run.salary_slips_created = True if run.workflow_version == "frappe_v1" else run.salary_slips_created; run.document_status = "draft" if run.workflow_version == "frappe_v1" else run.document_status
    run.snapshot_checksum = _hash({"input": run.input_snapshot, "config": run.config_snapshot, "payslips": [row.snapshot_checksum for row in result_rows]})
    return result_rows


async def reconcile_run(db: AsyncSession, actor: ActorContext, run: PayrollRun) -> dict[str, Any]:
    """Build a reproducible payroll register variance and exception report."""
    if run.organization_id != actor.organization_id:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status not in {"calculated", "in_review", "approved", "posted", "paid"}:
        raise HTTPException(status_code=409, detail={"code": "payroll_run_requires_calculation"})
    slips = list((await db.execute(select(Payslip).where(Payslip.payroll_run_id == run.id).order_by(Payslip.employee_id))).scalars().all())
    prior_run = await db.scalar(select(PayrollRun).where(
        PayrollRun.organization_id == actor.organization_id,
        PayrollRun.id != run.id,
        PayrollRun.period_end < run.period_start,
        PayrollRun.run_type == run.run_type,
        PayrollRun.status.in_(("calculated", "in_review", "approved", "posted", "paid")),
    ).order_by(PayrollRun.period_end.desc(), PayrollRun.id.desc()).limit(1))
    prior_slips = list((await db.execute(select(Payslip).where(Payslip.payroll_run_id == prior_run.id))).scalars().all()) if prior_run else []
    prior_by_employee = {row.employee_id: row for row in prior_slips}
    resolved = set((run.reconciliation_snapshot or {}).get("resolved_issue_keys") or [])
    issues: list[dict[str, Any]] = []

    def add_issue(code: str, severity: str, message: str, employee_id: int | None = None) -> None:
        key = f"{code}:{employee_id or 'run'}"
        issues.append({"key": key, "code": code, "severity": severity, "employee_id": employee_id, "message": message, "resolved": key in resolved})

    employee_ids = [row.employee_id for row in slips]
    profiles = list((await db.execute(select(EmployeePayrollProfile).where(
        EmployeePayrollProfile.organization_id == actor.organization_id,
        EmployeePayrollProfile.employee_id.in_(employee_ids),
        EmployeePayrollProfile.effective_from <= run.tax_point_date,
        (EmployeePayrollProfile.effective_to.is_(None) | (EmployeePayrollProfile.effective_to >= run.tax_point_date)),
    ))).scalars().all()) if employee_ids else []
    profile_by_employee = {row.employee_id: row for row in profiles}
    bank_profile_ids = [row.id for row in profiles if row.payment_method == "bank"]
    bank_accounts = list((await db.execute(select(EmployeeBankAccount).where(
        EmployeeBankAccount.employee_id.in_(employee_ids),
        EmployeeBankAccount.is_primary.is_(True),
        EmployeeBankAccount.valid_from <= run.tax_point_date,
        (EmployeeBankAccount.valid_to.is_(None) | (EmployeeBankAccount.valid_to >= run.tax_point_date)),
    ))).scalars().all()) if bank_profile_ids else []
    bank_ready_employee_ids = {row.employee_id for row in bank_accounts}
    for slip in slips:
        if Decimal(str(slip.net_pay)) < 0:
            add_issue("negative_net_pay", "error", "Net pay is negative and must be corrected before approval.", slip.employee_id)
        profile = profile_by_employee.get(slip.employee_id)
        if profile and profile.payment_method == "bank" and slip.employee_id not in bank_ready_employee_ids:
            add_issue("missing_bank_details", "error", "The employee has no active primary bank account.", slip.employee_id)
        units = (slip.input_snapshot or {}).get("resolved_units") or {}
        payable_hours = Decimal(str(units.get("payable_hours", 0)))
        scheduled_hours = Decimal(str(units.get("scheduled_hours", 0)))
        prorated = any(item.get("proration_basis") in {"hours", "working_days"} for item in ((slip.employee_profile_snapshot or {}).get("components") or []))
        if prorated and not Decimal(str(units.get("payable_workdays", 0))) and not payable_hours:
            add_issue("missing_approved_time", "error", "No approved time or payable-day override was frozen for a prorated employee.", slip.employee_id)
        if scheduled_hours > 0 and payable_hours > scheduled_hours * Decimal("1.25"):
            add_issue("overtime_spike", "warning", "Approved hours exceed scheduled hours by more than 25%.", slip.employee_id)
        prior = prior_by_employee.get(slip.employee_id)
        if prior and Decimal(str(prior.gross)) and abs(Decimal(str(slip.gross)) - Decimal(str(prior.gross))) / abs(Decimal(str(prior.gross))) > Decimal("0.25"):
            add_issue("gross_variance", "warning", "Gross pay changed by more than 25% from the prior comparable cycle.", slip.employee_id)

    pending_time = list((await db.execute(select(WorkTimeEntry).where(
        WorkTimeEntry.employee_id.in_(employee_ids),
        WorkTimeEntry.entry_type == "work",
        WorkTimeEntry.approval_status != "approved",
        WorkTimeEntry.started_at >= datetime.combine(run.period_start, datetime.min.time()),
        WorkTimeEntry.started_at <= datetime.combine(run.period_end, datetime.max.time()),
    ))).scalars().all()) if employee_ids else []
    for employee_id in sorted({row.employee_id for row in pending_time if row.employee_id is not None}):
        add_issue("unapproved_time_entry", "error", "One or more time entries in this period are not approved.", employee_id)

    frozen_by_employee: dict[int, list[dict[str, Any]]] = {}
    for entry in (run.input_snapshot or {}).get("approved_time_entries") or []:
        frozen_by_employee.setdefault(int(entry.get("employee_id", -1)), []).append(entry)
    for employee_id, entries in frozen_by_employee.items():
        ordered = sorted((entry for entry in entries if entry.get("ended_at")), key=lambda item: item["started_at"])
        if any(datetime.fromisoformat(ordered[index]["started_at"]) < datetime.fromisoformat(ordered[index - 1]["ended_at"]) for index in range(1, len(ordered))):
            add_issue("overlapping_time_entries", "error", "Approved time entries overlap in the frozen input snapshot.", employee_id)

    def variance(current: Any, previous: Any) -> dict[str, str | None]:
        current_value, previous_value = Decimal(str(current or 0)), Decimal(str(previous or 0))
        delta = current_value - previous_value
        percent = (delta / abs(previous_value) * Decimal("100")) if previous_value else None
        return {"current": str(current_value), "previous": str(previous_value), "delta": str(delta), "percent": str(percent.quantize(Decimal("0.01"))) if percent is not None else None}

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "prior_run": {"id": prior_run.id, "run_number": prior_run.run_number, "period_end": prior_run.period_end.isoformat()} if prior_run else None,
        "register": {"employee_count": len(slips), "gross": str(run.total_gross), "employee_shi": str(run.total_employee_shi), "employer_shi": str(run.total_employer_shi), "pit": str(run.total_pit), "net": str(run.total_net)},
        "variances": {
            "gross": variance(run.total_gross, prior_run.total_gross if prior_run else 0),
            "employee_shi": variance(run.total_employee_shi, prior_run.total_employee_shi if prior_run else 0),
            "pit": variance(run.total_pit, prior_run.total_pit if prior_run else 0),
            "net": variance(run.total_net, prior_run.total_net if prior_run else 0),
        },
        "issues": issues,
        "unresolved_errors": sum(1 for item in issues if item["severity"] == "error" and not item["resolved"]),
        "unresolved_warnings": sum(1 for item in issues if item["severity"] == "warning" and not item["resolved"]),
        "resolved_issue_keys": sorted(resolved),
        "resolution_notes": (run.reconciliation_snapshot or {}).get("resolution_notes") or [],
    }
    run.reconciliation_snapshot = report
    return report


async def post_run(db: AsyncSession, actor: ActorContext, run: PayrollRun) -> ERPDocument:
    if run.erp_document_id and run.status in {"posted", "payment_prepared", "partially_settled", "settled", "paid"}:
        existing = await db.get(ERPDocument, run.erp_document_id)
        if existing:
            return existing
    # Legacy runs retain the reconciliation/approval gates.  Frappe-style
    # entries submit calculated salary slips directly, then settle them with a
    # separate Bank Entry document.
    if run.workflow_version == "frappe_v1":
        if run.status != "calculated":
            raise HTTPException(status_code=409, detail={"code": "payroll_salary_slips_not_ready"})
    elif run.status != "approved":
        raise HTTPException(status_code=409, detail={"code": "payroll_run_requires_approval"})
    posting = await db.scalar(select(PayrollPostingProfile).where(PayrollPostingProfile.organization_id == actor.organization_id, PayrollPostingProfile.code == "default", PayrollPostingProfile.is_active.is_(True)))
    if not posting: raise HTTPException(status_code=422, detail={"code": "payroll_posting_profile_missing"})
    source_run = await db.scalar(select(PayrollRun).where(PayrollRun.id == run.reversal_of_run_id, PayrollRun.organization_id == actor.organization_id)) if run.reversal_of_run_id else None
    is_advance = run.run_type == "advance" or (source_run is not None and source_run.run_type == "advance")
    roles = posting.account_roles or {}
    # An advance is a clearing balance until the final settlement.  It has no
    # salary expense or statutory liability of its own, but must have a
    # dedicated clearing account and bank role so the payout is traceable.
    required = {"advance_clearing", "bank"} if is_advance else {"salary_expense", "employer_shi_expense", "employee_shi_payable", "employer_shi_payable", "pit_payable", "net_pay_payable"}
    if not required.issubset(roles): raise HTTPException(status_code=422, detail={"code": "payroll_posting_accounts_incomplete", "missing": sorted(required - set(roles))})
    accounts = (await db.execute(select(ERPAccount).where(ERPAccount.organization_id == actor.organization_id, ERPAccount.is_active.is_(True), ERPAccount.is_group.is_(False), ERPAccount.currency == "MNT", ERPAccount.id.in_(list(roles.values()))))).scalars().all()
    if len(accounts) != len(set(roles.values())): raise HTTPException(status_code=422, detail={"code": "payroll_posting_account_invalid"})
    expected_purposes = {
        "salary_expense": "salary_expense", "employer_shi_expense": "employer_shi_expense",
        "employee_shi_payable": "employee_shi_payable", "employer_shi_payable": "employer_shi_payable",
        "pit_payable": "pit_payable", "net_pay_payable": "net_pay_payable", "advance_clearing": "advance_clearing", "bank": "bank",
    }
    account_by_id = {row.id: row for row in accounts}
    for role, purpose in expected_purposes.items():
        if role in roles and account_by_id[roles[role]].purpose not in {purpose, "general"}:
            raise HTTPException(status_code=422, detail={"code": "payroll_posting_account_purpose_invalid", "role": role, "account_id": roles[role], "expected": purpose})
    frozen_accounting = (run.config_snapshot or {}).get("accounting_snapshot")
    if frozen_accounting:
        if frozen_accounting.get("posting_profile_id") != posting.id or frozen_accounting.get("account_roles") != roles:
            raise HTTPException(status_code=409, detail={"code": "payroll_accounting_snapshot_mismatch"})
    else:
        run.config_snapshot = {**(run.config_snapshot or {}), "accounting_snapshot": {"posting_profile_id": posting.id, "account_roles": dict(roles), "posting_date": (run.posting_date or run.tax_point_date).isoformat(), "currency": "MNT", "cost_center_id": run.cost_center_id}}
    await mark_run_benefits_paid(db, run.id)
    posting_date = run.posting_date or run.tax_point_date or run.period_end
    document = ERPDocument(organization_id=actor.organization_id, document_type="payroll_run", number=run.run_number, status="submitted", currency="MNT", posting_date=posting_date, net_total=run.total_net if is_advance else run.total_gross, tax_total=Decimal("0") if is_advance else run.total_employee_shi + run.total_pit + run.total_employer_shi, grand_total=run.total_net if is_advance else run.total_gross + run.total_employer_shi, outstanding_amount=Decimal("0") if is_advance else run.total_net, payload={"payroll_run_id": run.id, "run_type": run.run_type, "cost_center_id": run.cost_center_id}, custom={})
    db.add(document); await db.flush()
    payslips = (await db.execute(select(Payslip).where(Payslip.payroll_run_id == run.id))).scalars().all()
    total_advance = sum((Decimal(str(row.advance_offset or 0)) for row in payslips), Decimal("0"))
    total_other_deductions = sum((Decimal(str(row.gross or 0)) - Decimal(str(row.employee_shi or 0)) - Decimal(str(row.pit or 0)) - Decimal(str(row.net_pay or 0)) - Decimal(str(row.advance_offset or 0)) for row in payslips), Decimal("0"))
    line_items = (await db.execute(select(PayslipLineItem).where(PayslipLineItem.payslip_id.in_([row.id for row in payslips]), PayslipLineItem.component_kind == "earning", PayslipLineItem.payer == "employee"))).scalars().all()
    cost_center_ids = {item.cost_center_id for item in line_items if item.cost_center_id is not None}
    if cost_center_ids:
        active_cost_centers = set((await db.execute(select(ERPCostCenter.id).where(ERPCostCenter.organization_id == actor.organization_id, ERPCostCenter.is_active.is_(True), ERPCostCenter.id.in_(cost_center_ids)))).scalars().all())
        if active_cost_centers != cost_center_ids:
            raise HTTPException(status_code=422, detail={"code": "payroll_component_cost_center_invalid", "cost_center_ids": sorted(cost_center_ids - active_cost_centers)})
    component_account_ids = {item.account_id for item in line_items if item.account_id}
    if component_account_ids - {row.id for row in accounts}:
        extra_accounts = (await db.execute(select(ERPAccount).where(ERPAccount.organization_id == actor.organization_id, ERPAccount.is_active.is_(True), ERPAccount.is_group.is_(False), ERPAccount.currency == "MNT", ERPAccount.id.in_(list(component_account_ids))))).scalars().all()
        accounts.extend(extra_accounts)
    active_account_ids = {row.id for row in accounts}
    salary_split: dict[tuple[int, int | None], Decimal] = {}
    if not is_advance:
        for item in line_items:
            account_id = item.account_id or roles["salary_expense"]
            if item.account_id and item.account_id not in active_account_ids:
                raise HTTPException(status_code=422, detail={"code": "payroll_component_account_invalid", "account_id": item.account_id})
            key = (account_id, item.cost_center_id or run.cost_center_id)
            salary_split[key] = salary_split.get(key, Decimal("0")) + Decimal(str(item.amount))
        if not salary_split:
            salary_split[(roles["salary_expense"], None)] = Decimal(str(run.total_gross))
    lines: list[tuple[int, Decimal, Decimal, str, int | None]] = []

    def entry(account_id: int, amount: Decimal, memo: str, *, debit_nature: bool, cost_center_id: int | None = None) -> None:
        amount = Decimal(str(amount or 0))
        if not amount:
            return
        debit, credit = (amount, Decimal("0")) if debit_nature and amount > 0 else (Decimal("0"), -amount) if debit_nature else (Decimal("0"), amount) if amount > 0 else (-amount, Decimal("0"))
        lines.append((account_id, debit, credit, memo, cost_center_id))

    if is_advance:
        # The advance run records and pays the employee's cash entitlement
        # through clearing.  It deliberately has no SHI/PIT or salary-expense
        # posting; the final run posts the full month's gross.
        entry(roles["advance_clearing"], run.total_net, "Employee advance clearing", debit_nature=True)
        entry(roles["bank"], run.total_net, "Advance bank payment", debit_nature=False)
    else:
        for (account_id, cost_center_id), amount in salary_split.items():
            entry(account_id, amount, "Payroll gross salary expense", debit_nature=True, cost_center_id=cost_center_id)
        entry(roles["employer_shi_expense"], run.total_employer_shi, "Employer SHI expense", debit_nature=True, cost_center_id=run.cost_center_id)
        fund_totals: dict[str, Decimal] = {}
        for payslip in payslips:
            for fund, amount in ((payslip.calculation_trace or {}).get("shi", {}).get("by_fund", {}) or {}).items():
                fund_totals[fund] = fund_totals.get(fund, Decimal("0")) + Decimal(str(amount))
        employee_funds = {fund: amount for fund, amount in fund_totals.items() if fund.startswith("employee:")}
        employer_funds = {fund: amount for fund, amount in fund_totals.items() if fund.startswith("employer:")}
        if employee_funds:
            for fund, amount in employee_funds.items():
                entry(roles["employee_shi_payable"], amount, f"Employee SHI payable ({fund.split(':', 1)[1]})", debit_nature=False)
        else:
            entry(roles["employee_shi_payable"], run.total_employee_shi, "Employee SHI payable", debit_nature=False)
        if employer_funds:
            for fund, amount in employer_funds.items():
                entry(roles["employer_shi_payable"], amount, f"Employer SHI payable ({fund.split(':', 1)[1]})", debit_nature=False)
        else:
            entry(roles["employer_shi_payable"], run.total_employer_shi, "Employer SHI payable", debit_nature=False)
        entry(roles["pit_payable"], run.total_pit, "PIT payable", debit_nature=False)
        entry(roles["net_pay_payable"], run.total_net + total_advance, "Net salary payable", debit_nature=False)
        if total_other_deductions:
            if "other_deductions_payable" not in roles: raise HTTPException(status_code=422, detail={"code": "payroll_other_deduction_account_missing"})
            entry(roles["other_deductions_payable"], total_other_deductions, "Other employee deductions payable", debit_nature=False)
        if total_advance:
            if "advance_clearing" not in roles: raise HTTPException(status_code=422, detail={"code": "payroll_advance_clearing_account_missing"})
            entry(roles["net_pay_payable"], total_advance, "Advance offset against net salary payable", debit_nature=True)
            entry(roles["advance_clearing"], total_advance, "Employee advance clearing", debit_nature=False)
    await validate_posting_gate(db, actor.organization_id, posting_date, lines, currency="MNT")
    db.add_all([ERPGeneralLedgerEntry(organization_id=actor.organization_id, document_id=document.id, account_id=account_id, cost_center_id=cost_center_id, posting_date=posting_date, debit=debit, credit=credit, memo=memo) for account_id, debit, credit, memo, cost_center_id in lines])
    for payslip in payslips:
        if source_run is not None and source_run.run_type == "advance" and Decimal(str(payslip.net_pay or 0)) < 0:
            source_advances = (await db.execute(select(PayrollAdvance).where(
                PayrollAdvance.organization_id == actor.organization_id,
                PayrollAdvance.payroll_run_id == source_run.id,
                PayrollAdvance.employee_id == payslip.employee_id,
                PayrollAdvance.status.in_(("approved", "partially_applied")),
            ).with_for_update())).scalars().all()
            for source_advance in source_advances:
                source_advance.status = "reversed"
        if is_advance and Decimal(str(payslip.net_pay or 0)) > 0:
            # A posted advance is an auditable source for the final run's
            # automatic offset.  The amount is net of any explicitly
            # configured non-statutory deduction on the advance run.
            db.add(PayrollAdvance(
                organization_id=actor.organization_id,
                employee_id=payslip.employee_id,
                payroll_run_id=run.id,
                settlement_key=run.settlement_key,
                amount=payslip.net_pay,
                applied_amount=Decimal("0"),
                status="approved",
            ))
        if not is_advance:
            # Mark only advances that actually contributed to this payslip as
            # applied.  Rows are locked so two concurrent final/off-cycle
            # posts cannot consume the same money.
            remaining = max(Decimal("0"), Decimal(str(payslip.advance_offset or 0)))
            if remaining:
                advance_rows = (await db.execute(select(PayrollAdvance).where(
                    PayrollAdvance.organization_id == actor.organization_id,
                    PayrollAdvance.employee_id == payslip.employee_id,
                    PayrollAdvance.settlement_key == run.settlement_key,
                    PayrollAdvance.status.in_(("approved", "partially_applied")),
                    PayrollAdvance.amount > PayrollAdvance.applied_amount,
                ).order_by(PayrollAdvance.id).with_for_update())).scalars().all()
                for advance in advance_rows:
                    available = max(Decimal("0"), Decimal(str(advance.amount)) - Decimal(str(advance.applied_amount or 0)))
                    applied = min(remaining, available)
                    if not applied:
                        continue
                    advance.applied_amount = Decimal(str(advance.applied_amount or 0)) + applied
                    advance.status = "applied" if advance.applied_amount >= advance.amount else "partially_applied"
                    remaining -= applied
                    if remaining <= 0:
                        break
        # Advance runs do not contribute to the month’s statutory accumulator;
        # the final run consumes the advance offset.
        if is_advance:
            continue
        # Lock the employee's effective payroll profile before assigning the
        # append-only YTD sequence so concurrent off-cycle runs serialize.
        await db.scalar(select(EmployeePayrollProfile.id).where(EmployeePayrollProfile.organization_id == actor.organization_id, EmployeePayrollProfile.employee_id == payslip.employee_id, EmployeePayrollProfile.effective_from <= run.tax_point_date, (EmployeePayrollProfile.effective_to.is_(None) | (EmployeePayrollProfile.effective_to >= run.tax_point_date))).with_for_update())
        last_sequence = await db.scalar(select(func.coalesce(func.max(PayrollEmployeeAccumulator.sequence_no), 0)).where(PayrollEmployeeAccumulator.organization_id == actor.organization_id, PayrollEmployeeAccumulator.employee_id == payslip.employee_id, PayrollEmployeeAccumulator.tax_year == run.tax_point_date.year)) or 0
        db.add(PayrollEmployeeAccumulator(organization_id=actor.organization_id, employee_id=payslip.employee_id, payroll_run_id=run.id, tax_year=run.tax_point_date.year, sequence_no=int(last_sequence) + 1, gross_delta=payslip.gross, taxable_delta=payslip.taxable_income, shi_base_delta=payslip.shi_base, pit_withheld_delta=payslip.pit))
    run.erp_document_id = document.id; run.posting_profile_id = posting.id; run.status = "posted"; run.posted_at = datetime.now(timezone.utc)
    if run.workflow_version == "frappe_v1":
        run.document_status = "submitted"
        run.salary_slips_submitted = True
        run.payment_status = "unpaid"
    run.snapshot_checksum = _hash({"input": run.input_snapshot, "config": run.config_snapshot, "payslips": [row.snapshot_checksum for row in payslips]})
    return document


async def posting_preview(db: AsyncSession, actor: ActorContext, run: PayrollRun) -> dict[str, Any]:
    if run.organization_id != actor.organization_id:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status not in {"calculated", "in_review", "approved", "posted", "payment_prepared", "partially_settled", "settled", "payslips_released"}:
        raise HTTPException(status_code=409, detail={"code": "payroll_run_requires_calculation"})
    posting = await db.scalar(select(PayrollPostingProfile).where(PayrollPostingProfile.organization_id == actor.organization_id, PayrollPostingProfile.code == "default", PayrollPostingProfile.is_active.is_(True)))
    if not posting:
        raise HTTPException(status_code=422, detail={"code": "payroll_posting_profile_missing"})
    roles = posting.account_roles or {}
    required = {"salary_expense", "employer_shi_expense", "employee_shi_payable", "employer_shi_payable", "pit_payable", "net_pay_payable"}
    missing = sorted(required - set(roles))
    if missing:
        raise HTTPException(status_code=422, detail={"code": "payroll_posting_accounts_incomplete", "missing": missing})
    slips = list((await db.execute(select(Payslip).where(Payslip.payroll_run_id == run.id))).scalars().all())
    total_other = sum((Decimal(str(row.gross or 0)) - Decimal(str(row.employee_shi or 0)) - Decimal(str(row.pit or 0)) - Decimal(str(row.net_pay or 0)) - Decimal(str(row.advance_offset or 0)) for row in slips), Decimal("0"))
    lines = [
        {"role": "salary_expense", "account_id": roles["salary_expense"], "debit": str(run.total_gross), "credit": "0", "memo": "Salary expense"},
        {"role": "employer_shi_expense", "account_id": roles["employer_shi_expense"], "debit": str(run.total_employer_shi), "credit": "0", "memo": "Employer SHI expense"},
        {"role": "employee_shi_payable", "account_id": roles["employee_shi_payable"], "debit": "0", "credit": str(run.total_employee_shi), "memo": "Employee SHI payable"},
        {"role": "employer_shi_payable", "account_id": roles["employer_shi_payable"], "debit": "0", "credit": str(run.total_employer_shi), "memo": "Employer SHI payable"},
        {"role": "pit_payable", "account_id": roles["pit_payable"], "debit": "0", "credit": str(run.total_pit), "memo": "PIT payable"},
        {"role": "net_pay_payable", "account_id": roles["net_pay_payable"], "debit": "0", "credit": str(run.total_net), "memo": "Net salary payable"},
    ]
    if total_other and "other_deductions_payable" in roles:
        lines.append({"role": "other_deductions_payable", "account_id": roles["other_deductions_payable"], "debit": "0", "credit": str(total_other), "memo": "Other deductions payable"})
    debit = sum((Decimal(item["debit"]) for item in lines), Decimal("0")); credit = sum((Decimal(item["credit"]) for item in lines), Decimal("0"))
    return {"run_id": run.id, "currency": "MNT", "lines": lines, "total_debit": str(debit), "total_credit": str(credit), "balanced": debit == credit, "posting_profile_id": posting.id}


def canonical_payout_rows(run: PayrollRun, payslips: list[Payslip], accounts: dict[int, EmployeeBankAccount], employees: dict[int, Employee]) -> list[dict[str, Any]]:
    rows = []
    for index, payslip in enumerate(payslips, start=1):
        employee = employees[payslip.employee_id]; account = accounts[payslip.employee_id]
        rows.append({"batch_reference": run.run_number, "sequence": index, "execution_date": run.period_end.isoformat(), "debit_account": (run.config_snapshot or {}).get("bank_debit_account"), "employee_id": employee.id, "employee_reference": str(employee.id), "recipient_name": employee.name, "bank_code": account.bank_code, "bic": account.bank_code, "account_number_ciphertext": account.account_number_ciphertext, "amount": str(payslip.net_pay), "currency": (run.config_snapshot or {}).get("currency", "MNT"), "purpose": f"Salary {run.settlement_key}", "reference": f"{run.run_number}-{employee.id}"})
    return rows


async def create_payment_batch(db: AsyncSession, actor: ActorContext, run: PayrollRun, data: Any) -> PayrollPaymentBatch:
    """Prepare employee-level payment allocations without clearing the GL."""
    if run.organization_id != actor.organization_id or run.status not in {"posted", "payment_prepared", "partially_settled", "settled"}:
        raise HTTPException(status_code=409, detail={"code": "payroll_run_requires_posting"})
    posting = await db.scalar(select(PayrollPostingProfile).where(
        PayrollPostingProfile.organization_id == actor.organization_id, PayrollPostingProfile.code == "default", PayrollPostingProfile.is_active.is_(True)
    ))
    roles = posting.account_roles if posting else {}
    payment_account_id = data.payment_account_id or roles.get("bank")
    payable_account_id = roles.get("net_pay_payable")
    if not payment_account_id or not payable_account_id:
        raise HTTPException(status_code=422, detail={"code": "payroll_payment_accounts_incomplete"})
    accounts = (await db.execute(select(ERPAccount).where(
        ERPAccount.organization_id == actor.organization_id,
        ERPAccount.id.in_([payment_account_id, payable_account_id]),
        ERPAccount.is_active.is_(True), ERPAccount.is_group.is_(False), ERPAccount.currency == "MNT",
    ))).scalars().all()
    if len(accounts) != 2:
        raise HTTPException(status_code=422, detail={"code": "payroll_payment_account_invalid"})
    await _assert_payment_date(db, actor.organization_id, data.posting_date or run.posting_date or run.tax_point_date)
    slips = {row.id: row for row in (await db.execute(select(Payslip).where(Payslip.payroll_run_id == run.id))).scalars().all()}
    requested = list(data.allocations or [])
    if data.retry_of_batch_id:
        prior = await db.scalar(select(PayrollPaymentBatch).where(PayrollPaymentBatch.id == data.retry_of_batch_id, PayrollPaymentBatch.organization_id == actor.organization_id))
        if not prior:
            raise HTTPException(status_code=404, detail={"code": "payroll_payment_batch_not_found"})
        rejected = (await db.execute(select(PayrollPaymentAllocation).where(
            PayrollPaymentAllocation.payment_batch_id == prior.id, PayrollPaymentAllocation.status == "rejected"
        ))).scalars().all()
        requested = [{"payslip_id": row.payslip_id, "amount": row.amount} for row in rejected]
    if not requested:
        requested = [{"payslip_id": row.id, "amount": row.net_pay} for row in slips.values() if Decimal(str(row.net_pay or 0)) > 0]
    if not requested:
        raise HTTPException(status_code=422, detail={"code": "payroll_no_payment_allocations"})
    seen: set[int] = set()
    allocations: list[tuple[Payslip, Decimal]] = []
    for raw in requested:
        slip_id, amount = int(raw.payslip_id if hasattr(raw, "payslip_id") else raw["payslip_id"]), Decimal(str(raw.amount if hasattr(raw, "amount") else raw["amount"]))
        slip = slips.get(slip_id)
        if not slip or slip.id in seen or amount <= 0 or amount > Decimal(str(slip.net_pay)):
            raise HTTPException(status_code=422, detail={"code": "payroll_payment_allocation_invalid", "payslip_id": slip_id})
        prior_settled = await db.scalar(select(PayrollPaymentAllocation.id).where(
            PayrollPaymentAllocation.payslip_id == slip.id, PayrollPaymentAllocation.status.in_(("settled", "bank_submitted"))
        ))
        if prior_settled and not data.retry_of_batch_id:
            raise HTTPException(status_code=409, detail={"code": "payroll_payment_already_submitted", "payslip_id": slip.id})
        seen.add(slip.id); allocations.append((slip, amount))
    number = f"PAY-{run.run_number}-{datetime.now(timezone.utc).strftime('%H%M%S%f')[:8]}"
    batch = PayrollPaymentBatch(
        organization_id=actor.organization_id, payroll_run_id=run.id, batch_reference=number,
        payment_account_id=payment_account_id, payable_account_id=payable_account_id,
        posting_date=data.posting_date or run.posting_date or run.tax_point_date, currency="MNT",
        status="prepared", retry_of_batch_id=data.retry_of_batch_id, total_amount=sum((amount for _slip, amount in allocations), Decimal("0")),
        created_by_account_id=actor.account_id,
    )
    db.add(batch); await db.flush()
    db.add_all([PayrollPaymentAllocation(
        organization_id=actor.organization_id, payment_batch_id=batch.id, payslip_id=slip.id,
        employee_id=slip.employee_id, amount=amount, status="pending", attempt_number=2 if data.retry_of_batch_id else 1,
    ) for slip, amount in allocations])
    run.payment_status = "payment_prepared"
    if run.status == "posted":
        run.status = "payment_prepared"
    return batch


async def _assert_payment_date(db: AsyncSession, organization_id: int, posting_date: date) -> None:
    await validate_posting_gate(db, organization_id, posting_date, [], currency="MNT")


async def settle_payment_allocation(db: AsyncSession, actor: ActorContext, allocation_id: int, data: Any) -> PayrollPaymentAllocation:
    allocation = await db.scalar(select(PayrollPaymentAllocation).where(
        PayrollPaymentAllocation.id == allocation_id, PayrollPaymentAllocation.organization_id == actor.organization_id
    ).with_for_update())
    if not allocation:
        raise HTTPException(status_code=404, detail={"code": "payroll_payment_allocation_not_found"})
    if allocation.status == "settled":
        return allocation
    if allocation.status not in {"pending", "bank_submitted"}:
        raise HTTPException(status_code=409, detail={"code": "payroll_payment_allocation_not_settleable"})
    batch = await db.scalar(select(PayrollPaymentBatch).where(PayrollPaymentBatch.id == allocation.payment_batch_id, PayrollPaymentBatch.organization_id == actor.organization_id).with_for_update())
    run = await db.scalar(select(PayrollRun).where(PayrollRun.id == batch.payroll_run_id, PayrollRun.organization_id == actor.organization_id).with_for_update())
    reference = str(data.transaction_reference)
    if allocation.transaction_reference == reference and allocation.erp_document_id:
        return allocation
    duplicate = await db.scalar(select(PayrollPaymentAllocation.id).where(
        PayrollPaymentAllocation.organization_id == actor.organization_id,
        PayrollPaymentAllocation.transaction_reference == reference,
        PayrollPaymentAllocation.id != allocation.id,
    ))
    if duplicate:
        raise HTTPException(status_code=409, detail={"code": "payroll_payment_transaction_duplicate", "transaction_reference": reference})
    payment_date = batch.posting_date
    document = ERPDocument(
        organization_id=actor.organization_id, document_type="payroll_payment", number=f"{batch.batch_reference}-{allocation.id}",
        status="submitted", currency=batch.currency, posting_date=payment_date, net_total=allocation.amount,
        grand_total=allocation.amount, outstanding_amount=Decimal("0"),
        payload={"payment_batch_id": batch.id, "payment_allocation_id": allocation.id, "payroll_run_id": run.id, "transaction_reference": reference}, custom={}
    )
    db.add(document); await db.flush()
    await validate_posting_gate(db, actor.organization_id, payment_date, [
        (batch.payable_account_id, Decimal(str(allocation.amount)), Decimal("0"), None, "Net salary payable settlement"),
        (batch.payment_account_id, Decimal("0"), Decimal(str(allocation.amount)), None, "Bank salary settlement"),
    ], currency=batch.currency)
    db.add_all([
        ERPGeneralLedgerEntry(organization_id=actor.organization_id, document_id=document.id, account_id=batch.payable_account_id, posting_date=payment_date, debit=allocation.amount, credit=Decimal("0"), memo=f"Salary payable settlement {run.run_number}"),
        ERPGeneralLedgerEntry(organization_id=actor.organization_id, document_id=document.id, account_id=batch.payment_account_id, posting_date=payment_date, debit=Decimal("0"), credit=allocation.amount, memo=f"Bank salary payment {run.run_number}"),
    ])
    allocation.status = "settled"; allocation.transaction_reference = reference; allocation.settled_at = datetime.now(timezone.utc); allocation.settlement_evidence = data.evidence or {}; allocation.erp_document_id = document.id
    statuses = list((await db.execute(select(PayrollPaymentAllocation.status).where(PayrollPaymentAllocation.payment_batch_id == batch.id))).scalars().all())
    batch.status = "settled" if statuses and all(status == "settled" for status in statuses) else "partially_settled"
    if batch.status == "settled": run.payment_status = "settled"; run.status = "settled"
    else: run.payment_status = "partially_settled"
    return allocation


async def reject_payment_allocation(db: AsyncSession, actor: ActorContext, allocation_id: int, reason: str) -> PayrollPaymentAllocation:
    allocation = await db.scalar(select(PayrollPaymentAllocation).where(
        PayrollPaymentAllocation.id == allocation_id, PayrollPaymentAllocation.organization_id == actor.organization_id
    ).with_for_update())
    if not allocation:
        raise HTTPException(status_code=404, detail={"code": "payroll_payment_allocation_not_found"})
    if allocation.status == "settled":
        raise HTTPException(status_code=409, detail={"code": "payroll_settled_payment_immutable"})
    allocation.status = "rejected"; allocation.rejection_reason = reason; allocation.rejected_at = datetime.now(timezone.utc)
    batch = await db.get(PayrollPaymentBatch, allocation.payment_batch_id)
    if batch:
        batch.status = "partially_settled"
        run = await db.scalar(select(PayrollRun).where(PayrollRun.id == batch.payroll_run_id, PayrollRun.organization_id == actor.organization_id).with_for_update())
        if run:
            run.payment_status = "partially_settled"
            if run.status in {"posted", "payment_prepared"}:
                run.status = "partially_settled"
    return allocation


async def reverse_payment_allocation(db: AsyncSession, actor: ActorContext, allocation_id: int, data: Any) -> PayrollPaymentReversal:
    allocation = await db.scalar(select(PayrollPaymentAllocation).where(PayrollPaymentAllocation.id == allocation_id, PayrollPaymentAllocation.organization_id == actor.organization_id).with_for_update())
    if not allocation:
        raise HTTPException(status_code=404, detail={"code": "payroll_payment_allocation_not_found"})
    existing = await db.scalar(select(PayrollPaymentReversal).where(PayrollPaymentReversal.payment_allocation_id == allocation.id, PayrollPaymentReversal.organization_id == actor.organization_id))
    if existing:
        return existing
    if allocation.status != "settled" or not allocation.erp_document_id:
        raise HTTPException(status_code=409, detail={"code": "payroll_payment_requires_settled_reversal"})
    batch = await db.scalar(select(PayrollPaymentBatch).where(PayrollPaymentBatch.id == allocation.payment_batch_id, PayrollPaymentBatch.organization_id == actor.organization_id).with_for_update())
    run = await db.scalar(select(PayrollRun).where(PayrollRun.id == batch.payroll_run_id, PayrollRun.organization_id == actor.organization_id).with_for_update())
    original = await db.get(ERPDocument, allocation.erp_document_id)
    if not original:
        raise HTTPException(status_code=409, detail={"code": "payroll_payment_document_missing"})
    reversal_doc = ERPDocument(
        organization_id=actor.organization_id, document_type="payroll_payment_reversal", number=f"REV-{original.number}", status="submitted", currency=original.currency,
        posting_date=original.posting_date, net_total=-Decimal(str(original.net_total or allocation.amount)), grand_total=-Decimal(str(original.grand_total or allocation.amount)), outstanding_amount=Decimal("0"),
        payload={"reversal_of_document_id": original.id, "payment_allocation_id": allocation.id, "payroll_run_id": run.id, "transaction_reference": data.transaction_reference}, custom={"reason": data.reason, "evidence": data.evidence or {}},
    )
    db.add(reversal_doc); await db.flush()
    original_lines = list((await db.execute(select(ERPGeneralLedgerEntry).where(ERPGeneralLedgerEntry.document_id == original.id))).scalars().all())
    for line in original_lines:
        db.add(ERPGeneralLedgerEntry(organization_id=actor.organization_id, document_id=reversal_doc.id, account_id=line.account_id, cost_center_id=line.cost_center_id, party_id=line.party_id, posting_date=reversal_doc.posting_date, debit=line.credit, credit=line.debit, memo=f"Reversal of {original.number}", reversal_of_id=line.id))
    record = PayrollPaymentReversal(organization_id=actor.organization_id, payment_allocation_id=allocation.id, original_erp_document_id=original.id, reversal_erp_document_id=reversal_doc.id, reason=data.reason, transaction_reference=data.transaction_reference, evidence=data.evidence or {}, created_by_account_id=actor.account_id)
    db.add(record)
    allocation.status = "reversed"; allocation.reversed_at = datetime.now(timezone.utc); allocation.reversed_by_account_id = actor.account_id
    statuses = list((await db.execute(select(PayrollPaymentAllocation.status).where(PayrollPaymentAllocation.payment_batch_id == batch.id))).scalars().all())
    if statuses and all(status in {"reversed", "rejected"} for status in statuses):
        batch.status = "reversed"; run.payment_status = "reversed"
    await db.flush()
    return record


async def reverse_run(db: AsyncSession, actor: ActorContext, run: PayrollRun) -> PayrollRun:
    """Create a negative, linked replacement journal without mutating a post."""
    if run.organization_id != actor.organization_id:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status not in {"posted", "payment_prepared", "partially_settled", "settled", "payslips_released", "paid"}:
        raise HTTPException(status_code=409, detail={"code": "payroll_run_requires_posted_for_reversal"})
    unsettled_payment = await db.scalar(select(PayrollPaymentAllocation.id).join(PayrollPaymentBatch, PayrollPaymentBatch.id == PayrollPaymentAllocation.payment_batch_id).where(PayrollPaymentBatch.payroll_run_id == run.id, PayrollPaymentAllocation.organization_id == actor.organization_id, PayrollPaymentAllocation.status.in_(("settled", "pending", "bank_submitted"))).limit(1))
    if unsettled_payment:
        raise HTTPException(status_code=409, detail={"code": "payroll_accrual_reversal_requires_payment_reversal"})
    existing = await db.scalar(select(PayrollRun).where(PayrollRun.organization_id == actor.organization_id, PayrollRun.reversal_of_run_id == run.id))
    if existing:
        return existing
    reversal = PayrollRun(
        organization_id=actor.organization_id,
        run_number=f"REV-{run.id}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')[:17]}",
        run_type="reversal",
        period_start=run.period_start,
        period_end=run.period_end,
        settlement_key=run.settlement_key,
        tax_point_date=run.tax_point_date,
        status="approved", workflow_version="unified_v2", document_status="draft",
        reversal_of_run_id=run.id,
        statutory_profile_id=run.statutory_profile_id,
        input_snapshot={"reversal_of_run_id": run.id, "source_snapshot_checksum": run.snapshot_checksum},
        config_snapshot={**(run.config_snapshot or {}), "reversal_of_run_id": run.id},
        engine_version=run.engine_version,
        snapshot_checksum="pending",
        total_gross=-Decimal(str(run.total_gross)),
        total_employee_shi=-Decimal(str(run.total_employee_shi)),
        total_employer_shi=-Decimal(str(run.total_employer_shi)),
        total_pit=-Decimal(str(run.total_pit)),
        total_net=-Decimal(str(run.total_net)),
        created_by_account_id=actor.account_id,
        approved_by_account_id=actor.account_id,
    )
    db.add(reversal)
    await db.flush()
    source_slips = (await db.execute(select(Payslip).where(Payslip.payroll_run_id == run.id).order_by(Payslip.employee_id))).scalars().all()
    for source in source_slips:
        def neg(value: Any) -> Decimal:
            return -Decimal(str(value or 0))
        profile_snapshot = {**(source.employee_profile_snapshot or {}), "reversal_of_payslip_id": source.id}
        input_snapshot = {**(source.input_snapshot or {}), "reversal_of_payslip_id": source.id}
        reversal_slip = Payslip(
            payroll_run_id=reversal.id,
            organization_id=actor.organization_id,
            employee_id=source.employee_id,
            employee_profile_snapshot=profile_snapshot,
            input_snapshot=input_snapshot,
            calculation_trace={"reversal_of_payslip_id": source.id, "source_checksum": source.snapshot_checksum},
            ytd_snapshot=source.ytd_snapshot,
            gross=neg(source.gross),
            taxable_income=neg(source.taxable_income),
            shi_subject_gross=neg(source.shi_subject_gross),
            shi_base=neg(source.shi_base),
            employee_shi=neg(source.employee_shi),
            employer_shi=neg(source.employer_shi),
            pit=neg(source.pit),
            pit_relief=neg(source.pit_relief),
            advance_offset=neg(source.advance_offset),
            net_pay=neg(source.net_pay),
            snapshot_checksum=snapshot_checksum({"reversal_of": source.snapshot_checksum, "employee_id": source.employee_id}),
        )
        db.add(reversal_slip)
        await db.flush()
        source_lines = (await db.execute(select(PayslipLineItem).where(PayslipLineItem.payslip_id == source.id).order_by(PayslipLineItem.position))).scalars().all()
        db.add_all([PayslipLineItem(payslip_id=reversal_slip.id, component_master_id=line.component_master_id, component_code=line.component_code, label=line.label, component_kind=line.component_kind, amount=neg(line.amount), taxable=line.taxable, shi_subject=line.shi_subject, payer=line.payer, formula_snapshot=line.formula_snapshot, trace={**(line.trace or {}), "reversal_of_line_id": line.id}, account_id=line.account_id, cost_center_id=line.cost_center_id, position=line.position) for line in source_lines])
    reversal.snapshot_checksum = _hash({"input": reversal.input_snapshot, "config": reversal.config_snapshot, "payslips": [slip.snapshot_checksum for slip in (await db.execute(select(Payslip).where(Payslip.payroll_run_id == reversal.id))).scalars().all()]})
    run.status = "reversed"; run.payment_status = "reversed"; run.reversed_at = datetime.now(timezone.utc); run.reversed_by_account_id = actor.account_id
    return reversal


async def create_replacement_run(db: AsyncSession, actor: ActorContext, source: PayrollRun, data: PayrollRunInput) -> PayrollRun:
    if source.organization_id != actor.organization_id:
        raise HTTPException(status_code=404, detail="Run not found")
    if source.status not in {"rejected", "posted", "paid", "reversed"}:
        raise HTTPException(status_code=409, detail={"code": "payroll_run_requires_rejected_or_posted_for_replacement"})
    run = await create_run(db, actor, data)
    run.workflow_version = "unified_v2"
    run.replacement_of_run_id = source.id
    run.input_snapshot = {**(run.input_snapshot or {}), "replacement_of_run_id": source.id}
    run.snapshot_checksum = _hash(run.input_snapshot)
    return run
