from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enterprise_deps import ActorContext
from app.models.models import (
    Employee, EmployeeBankAccount, EmployeePayrollProfile, ERPAccount, ERPDocument, ERPCostCenter, UserAccount,
    ERPGeneralLedgerEntry, PayrollAdvance, PayrollBankExportProfile, PayrollEmployeeAccumulator,
    PayrollExportArtifact, PayrollPostingProfile, PayrollRun, Payslip, PayslipLineItem,
    SalaryComponent, SalaryStructure, SalaryStructureVersion, SHIRateTier, PITBracketTier, TaxReliefTier, StatutoryConfigProfile, WorkTimeEntry,
)
from app.services.secret_box import encrypt_secret
from .calculator import (
    CalculationInput, ComponentDefinition, LeaveMonth, PITBracket, ReliefTier as CalcReliefTier, SHIRate,
    StatutoryRules, _SafeFormula, calculate_payslip, money, snapshot_checksum,
)
from .schemas import (
    BankAccountInput, EmployeePayrollInput, PayrollRunInput, PostingProfileInput,
    SalaryStructureInput, StatutoryProfileInput,
)
from .tax_benefits import approved_tax_adjustments, grouped_benefit_claims, mark_run_benefits_paid, reserve_benefit_claims


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _profile_payload(data: StatutoryProfileInput) -> dict[str, Any]:
    return data.model_dump(mode="json", exclude={"shi_rates", "pit_brackets", "relief_tiers"})


def _validate_date_range(start: date, end: date | None) -> None:
    if end and end < start:
        raise HTTPException(status_code=422, detail={"code": "payroll_invalid_effective_range"})


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


async def load_rules(db: AsyncSession, profile: StatutoryConfigProfile, *, insured_category: str = "employee", hazard_class: str = "standard") -> StatutoryRules:
    shi_rows = (await db.execute(select(SHIRateTier).where(SHIRateTier.profile_id == profile.id, SHIRateTier.insured_category == insured_category, SHIRateTier.hazard_class == hazard_class).order_by(SHIRateTier.position, SHIRateTier.id))).scalars().all()
    pit_candidates = (await db.execute(select(PITBracketTier).where(PITBracketTier.profile_id == profile.id).order_by(PITBracketTier.position, PITBracketTier.id))).scalars().all()
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
        shi_rates=tuple(SHIRate(payer=row.payer, insurance_fund=row.insurance_fund, rate=Decimal(str(row.rate)), base_floor=Decimal(str(row.base_floor)), exemption_code=row.exemption_code) for row in shi_rows),
        pit_brackets=tuple(PITBracket(lower_bound=Decimal(str(row.lower_bound)), upper_bound=Decimal(str(row.upper_bound)) if row.upper_bound is not None else None, marginal_rate=Decimal(str(row.marginal_rate)), base_tax=Decimal(str(row.base_tax)), period_basis=row.period_basis) for row in pit_rows),
        relief_tiers=tuple(CalcReliefTier(eligibility_code=row.eligibility_code, lower_bound=Decimal(str(row.lower_bound)), upper_bound=Decimal(str(row.upper_bound)) if row.upper_bound is not None else None, fixed_amount=Decimal(str(row.fixed_amount)), amount_basis=row.amount_basis, formula=row.formula) for row in relief_rows),
        pit_withholding_method=profile.pit_withholding_method,
        rounding_quantum=Decimal(str((profile.rounding_policy or {}).get("quantum", "0.01"))),
        leave_policy=profile.leave_policy or {"lookback_months": 12, "missing_history_fallback": "error"},
    )


def profile_out(profile: StatutoryConfigProfile, *, rates: list[SHIRateTier] | None = None, brackets: list[PITBracketTier] | None = None, reliefs: list[TaxReliefTier] | None = None) -> dict[str, Any]:
    return {
        "id": profile.id, "organization_id": profile.organization_id, "code": profile.code, "jurisdiction": profile.jurisdiction,
        "version": profile.version, "status": profile.status, "effective_from": profile.effective_from.isoformat(), "effective_to": profile.effective_to.isoformat() if profile.effective_to else None,
        "tax_point_basis": profile.tax_point_basis, "currency": profile.currency, "minimum_wage": str(profile.minimum_wage), "shi_ceiling_multiplier": str(profile.shi_ceiling_multiplier),
        "pit_withholding_method": profile.pit_withholding_method, "rounding_policy": profile.rounding_policy, "leave_policy": profile.leave_policy,
        "source_references": profile.source_references, "is_example": profile.is_example, "checksum": profile.checksum,
        "shi_rates": [{"payer": row.payer, "insurance_fund": row.insurance_fund, "insured_category": row.insured_category, "hazard_class": row.hazard_class, "rate": str(row.rate), "base_floor": str(row.base_floor), "exemption_code": row.exemption_code} for row in (rates or [])],
        "pit_brackets": [{"period_basis": row.period_basis, "lower_bound": str(row.lower_bound), "upper_bound": str(row.upper_bound) if row.upper_bound is not None else None, "marginal_rate": str(row.marginal_rate), "base_tax": str(row.base_tax)} for row in (brackets or [])],
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
    db.add_all([SHIRateTier(profile_id=profile.id, **row.model_dump()) for row in data.shi_rates])
    db.add_all([PITBracketTier(profile_id=profile.id, **row.model_dump()) for row in data.pit_brackets])
    db.add_all([TaxReliefTier(profile_id=profile.id, **row.model_dump()) for row in data.relief_tiers])
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
    db.add_all([SHIRateTier(profile_id=profile.id, **row.model_dump()) for row in data.shi_rates])
    db.add_all([PITBracketTier(profile_id=profile.id, **row.model_dump()) for row in data.pit_brackets])
    db.add_all([TaxReliefTier(profile_id=profile.id, **row.model_dump()) for row in data.relief_tiers])
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


async def publish_profile(db: AsyncSession, actor: ActorContext, profile: StatutoryConfigProfile, acknowledge_example: bool) -> None:
    if profile.organization_id != actor.organization_id:
        raise HTTPException(status_code=404, detail="Profile not found")
    if profile.status in {"published", "active"}:
        raise HTTPException(status_code=409, detail={"code": "payroll_profile_already_published"})
    if profile.is_example and not acknowledge_example:
        raise HTTPException(status_code=409, detail={"code": "payroll_example_profile_requires_acknowledgement"})
    rates = (await db.execute(select(SHIRateTier).where(SHIRateTier.profile_id == profile.id))).scalars().all()
    brackets = (await db.execute(select(PITBracketTier).where(PITBracketTier.profile_id == profile.id).order_by(PITBracketTier.position))).scalars().all()
    reliefs = (await db.execute(select(TaxReliefTier).where(TaxReliefTier.profile_id == profile.id).order_by(TaxReliefTier.position))).scalars().all()
    if not rates or not brackets:
        raise HTTPException(status_code=422, detail={"code": "payroll_profile_rules_incomplete"})
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
    ))).scalars().all()
    if any(row.effective_from <= (profile.effective_to or date.max) and (row.effective_to is None or row.effective_to >= profile.effective_from) for row in others):
        raise HTTPException(status_code=409, detail={"code": "payroll_profile_effective_overlap"})
    # Recompute the digest from the complete published rule set.  This turns
    # the seeded zero checksum into a real snapshot checksum only after an
    # administrator has explicitly reviewed and published the example.
    profile.checksum = _hash({"profile": {"code": profile.code, "version": profile.version, "effective_from": profile.effective_from, "effective_to": profile.effective_to, "currency": profile.currency, "minimum_wage": profile.minimum_wage, "shi_ceiling_multiplier": profile.shi_ceiling_multiplier, "pit_withholding_method": profile.pit_withholding_method, "rounding_policy": profile.rounding_policy, "leave_policy": profile.leave_policy, "source_references": profile.source_references}, "shi_rates": [{"payer": row.payer, "insurance_fund": row.insurance_fund, "insured_category": row.insured_category, "hazard_class": row.hazard_class, "rate": row.rate, "base_floor": row.base_floor, "exemption_code": row.exemption_code} for row in rates], "pit_brackets": [{"period_basis": row.period_basis, "lower_bound": row.lower_bound, "upper_bound": row.upper_bound, "marginal_rate": row.marginal_rate, "base_tax": row.base_tax} for row in brackets], "relief_tiers": [{"eligibility_code": row.eligibility_code, "lower_bound": row.lower_bound, "upper_bound": row.upper_bound, "fixed_amount": row.fixed_amount, "amount_basis": row.amount_basis, "formula": row.formula} for row in reliefs]})
    profile.status = "published"; profile.approved_by_account_id = actor.account_id; profile.approved_at = datetime.now(timezone.utc)


async def create_salary_structure(db: AsyncSession, actor: ActorContext, data: SalaryStructureInput) -> SalaryStructure:
    _validate_date_range(data.effective_from, data.effective_to)
    if data.currency.upper() != "MNT":
        raise HTTPException(status_code=422, detail={"code": "payroll_currency_not_supported", "currency": data.currency})
    codes = [item.code for item in data.components]
    if len(codes) != len(set(codes)): raise HTTPException(status_code=422, detail={"code": "payroll_duplicate_component"})
    if any(item.pay_against_benefit_claim and (not item.is_flexible_benefit or item.component_kind != "earning") for item in data.components):
        raise HTTPException(status_code=422, detail={"code": "payroll_invalid_flexible_benefit_component"})
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
    structure = SalaryStructure(organization_id=actor.organization_id, code=data.code, name=data.name, effective_from=data.effective_from, effective_to=data.effective_to, currency=data.currency.upper(), checksum=_hash(data.model_dump(mode="json")), created_by_account_id=actor.account_id)
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


async def delete_salary_structure(db: AsyncSession, actor: ActorContext, structure: SalaryStructure) -> None:
    if structure.organization_id != actor.organization_id:
        raise HTTPException(status_code=404, detail="Salary structure not found")
    if structure.status in {"published", "active"}:
        raise HTTPException(status_code=409, detail={"code": "payroll_salary_structure_immutable"})
    referenced_profile = await db.scalar(select(EmployeePayrollProfile.id).where(EmployeePayrollProfile.salary_structure_id == structure.id).limit(1))
    if referenced_profile:
        raise HTTPException(status_code=409, detail={"code": "payroll_salary_structure_referenced_by_employee"})
    await db.delete(structure)
    await db.flush()


async def create_employee_profile(db: AsyncSession, actor: ActorContext, employee_id: int, data: EmployeePayrollInput) -> EmployeePayrollProfile:
    employee = await db.get(Employee, employee_id)
    if not employee: raise HTTPException(status_code=404, detail="Employee not found")
    linked_org = await db.scalar(select(UserAccount.organization_id).where(UserAccount.employee_id == employee_id, UserAccount.status.in_(("active", "invited"))))
    # Employee rows predate tenant-aware ERP accounts.  Payroll setup is
    # therefore allowed only through the employee's organization-scoped
    # account; an unlinked legacy employee cannot be guessed or reassigned
    # across tenants.
    if linked_org != actor.organization_id:
        raise HTTPException(status_code=404, detail="Employee not found")
    structure = await db.scalar(select(SalaryStructure).where(SalaryStructure.id == data.salary_structure_id, SalaryStructure.organization_id == actor.organization_id, SalaryStructure.effective_from <= data.effective_from, (SalaryStructure.effective_to.is_(None) | (SalaryStructure.effective_to >= data.effective_from))))
    if not structure or structure.status not in {"published", "active"}: raise HTTPException(status_code=404, detail="Published salary structure not found")
    existing_profiles = (await db.execute(select(EmployeePayrollProfile).where(EmployeePayrollProfile.organization_id == actor.organization_id, EmployeePayrollProfile.employee_id == employee_id))).scalars().all()
    if any(row.effective_from <= (data.effective_to or date.max) and (row.effective_to is None or row.effective_to >= data.effective_from) for row in existing_profiles):
        raise HTTPException(status_code=409, detail={"code": "payroll_employee_profile_effective_overlap"})
    values = data.model_dump(exclude={"employee_id", "salary_structure_id", "taxpayer_number", "social_insurance_number"})
    profile = EmployeePayrollProfile(organization_id=actor.organization_id, employee_id=employee_id, salary_structure_id=structure.id, **values)
    if data.taxpayer_number: profile.taxpayer_number_ciphertext = encrypt_secret(data.taxpayer_number)
    if data.social_insurance_number: profile.social_insurance_number_ciphertext = encrypt_secret(data.social_insurance_number)
    db.add(profile); await db.flush(); return profile


async def create_bank_account(db: AsyncSession, actor: ActorContext, employee_id: int, data: BankAccountInput) -> EmployeeBankAccount:
    _validate_date_range(data.valid_from, data.valid_to)
    profile = await db.scalar(select(EmployeePayrollProfile).where(EmployeePayrollProfile.employee_id == employee_id, EmployeePayrollProfile.organization_id == actor.organization_id, EmployeePayrollProfile.effective_from <= data.valid_from, (EmployeePayrollProfile.effective_to.is_(None) | (EmployeePayrollProfile.effective_to >= data.valid_from))).order_by(EmployeePayrollProfile.effective_from.desc()).limit(1))
    if not profile: raise HTTPException(status_code=404, detail="Employee payroll profile not found")
    if data.is_primary:
        accounts = (await db.execute(select(EmployeeBankAccount).where(EmployeeBankAccount.employee_payroll_profile_id == profile.id))).scalars().all()
        for account in accounts: account.is_primary = False
    normalized_account = "".join(data.account_number.split())
    if len(normalized_account) < 4:
        raise HTTPException(status_code=422, detail={"code": "payroll_invalid_bank_account"})
    fingerprint = hashlib.sha256(normalized_account.encode()).hexdigest()
    account = EmployeeBankAccount(employee_payroll_profile_id=profile.id, bank_code=data.bank_code, account_number_ciphertext=encrypt_secret(normalized_account), account_fingerprint=fingerprint, account_last4=normalized_account[-4:], account_holder_ciphertext=encrypt_secret(data.account_holder.strip()) if data.account_holder else None, is_primary=data.is_primary, valid_from=data.valid_from, valid_to=data.valid_to)
    db.add(account); await db.flush(); return account


async def create_run(db: AsyncSession, actor: ActorContext, data: PayrollRunInput) -> PayrollRun:
    if data.period_end < data.period_start: raise HTTPException(status_code=422, detail={"code": "payroll_invalid_period"})
    profile = await ensure_profile_active(db, data.statutory_profile_id, data.tax_point_date) if data.statutory_profile_id else await resolve_profile(db, actor.organization_id, data.tax_point_date)
    if profile.organization_id != actor.organization_id:
        raise HTTPException(status_code=404, detail="Statutory profile not found")
    employee_ids = data.employee_ids
    if not employee_ids:
        employee_ids = list((await db.execute(select(EmployeePayrollProfile.employee_id).where(EmployeePayrollProfile.organization_id == actor.organization_id, EmployeePayrollProfile.effective_from <= data.tax_point_date, (EmployeePayrollProfile.effective_to.is_(None) | (EmployeePayrollProfile.effective_to >= data.tax_point_date))))).scalars().all())
    employee_ids = list(dict.fromkeys(employee_ids))
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
    frozen_shi_rates = (await db.execute(select(SHIRateTier).where(SHIRateTier.profile_id == profile.id).order_by(SHIRateTier.position, SHIRateTier.id))).scalars().all()
    frozen_pit_brackets = (await db.execute(select(PITBracketTier).where(PITBracketTier.profile_id == profile.id).order_by(PITBracketTier.position, PITBracketTier.id))).scalars().all()
    frozen_reliefs = (await db.execute(select(TaxReliefTier).where(TaxReliefTier.profile_id == profile.id).order_by(TaxReliefTier.position, TaxReliefTier.id))).scalars().all()
    period_end_exclusive = datetime.combine(data.period_end, datetime.max.time())
    approved_entries = list((await db.execute(select(WorkTimeEntry).where(WorkTimeEntry.employee_id.in_(employee_ids), WorkTimeEntry.approval_status == "approved", WorkTimeEntry.started_at >= datetime.combine(data.period_start, datetime.min.time()), WorkTimeEntry.started_at <= period_end_exclusive))).scalars().all())
    approved_time_ids = [entry.id for entry in approved_entries]
    approved_time_snapshot = [{"id": entry.id, "employee_id": entry.employee_id, "local_work_date": entry.local_work_date.isoformat() if entry.local_work_date else None, "started_at": entry.started_at.isoformat(), "ended_at": entry.ended_at.isoformat() if entry.ended_at else None, "approval_status": entry.approval_status, "hours": str(Decimal(str((entry.ended_at - entry.started_at).total_seconds())) / Decimal("3600")) if entry.ended_at else "0"} for entry in approved_entries]
    snapshot = {"employee_ids": employee_ids, "overrides": data.input_overrides, "approved_time_entry_ids": approved_time_ids, "approved_time_entries": approved_time_snapshot, "calendar": {"period_start": data.period_start.isoformat(), "period_end": data.period_end.isoformat(), "timezone": "Asia/Ulaanbaatar"}}
    config_snapshot = {"profile_id": profile.id, "profile_version": profile.version, "profile_checksum": profile.checksum, "source_references": profile.source_references, "is_example": profile.is_example, "currency": profile.currency, "pit_withholding_method": profile.pit_withholding_method, "rounding_policy": profile.rounding_policy, "minimum_wage": str(profile.minimum_wage), "shi_ceiling_multiplier": str(profile.shi_ceiling_multiplier), "leave_policy": profile.leave_policy, "shi_rates": [{"payer": row.payer, "insurance_fund": row.insurance_fund, "insured_category": row.insured_category, "hazard_class": row.hazard_class, "rate": str(row.rate), "base_floor": str(row.base_floor), "exemption_code": row.exemption_code} for row in frozen_shi_rates], "pit_brackets": [{"period_basis": row.period_basis, "lower_bound": str(row.lower_bound), "upper_bound": str(row.upper_bound) if row.upper_bound is not None else None, "marginal_rate": str(row.marginal_rate), "base_tax": str(row.base_tax)} for row in frozen_pit_brackets], "relief_tiers": [{"eligibility_code": row.eligibility_code, "lower_bound": str(row.lower_bound), "upper_bound": str(row.upper_bound) if row.upper_bound is not None else None, "fixed_amount": str(row.fixed_amount), "amount_basis": row.amount_basis, "formula": row.formula} for row in frozen_reliefs]}
    run = PayrollRun(organization_id=actor.organization_id, run_number=f"PR-{data.period_end:%Y%m}-{datetime.now(timezone.utc).strftime('%H%M%S%f')[:9]}", run_type=data.run_type, period_start=data.period_start, period_end=data.period_end, settlement_key=data.period_end.strftime("%Y-%m"), tax_point_date=data.tax_point_date, statutory_profile_id=profile.id, input_snapshot=snapshot, config_snapshot=config_snapshot, snapshot_checksum=_hash({"input": snapshot, "config": config_snapshot}), created_by_account_id=actor.account_id)
    db.add(run); await db.flush(); return run


async def calculate_run(db: AsyncSession, actor: ActorContext, run: PayrollRun) -> list[Payslip]:
    if run.organization_id != actor.organization_id: raise HTTPException(status_code=404, detail="Run not found")
    if run.status not in {"draft", "calculated", "in_review"}: raise HTTPException(status_code=409, detail={"code": "payroll_run_immutable", "status": run.status})
    profile = await ensure_profile_active(db, run.statutory_profile_id, run.tax_point_date)
    await db.execute(delete(Payslip).where(Payslip.payroll_run_id == run.id))
    employee_ids = list((run.input_snapshot or {}).get("employee_ids") or [])
    overrides = (run.input_snapshot or {}).get("overrides") or {}
    result_rows: list[Payslip] = []
    for employee_id in employee_ids:
        # Serialise all calculations for an employee.  This is the lock that
        # makes monthly SHI-cap and YTD consumption deterministic when two
        # off-cycle runs are calculated concurrently.
        employee_profile = await db.scalar(select(EmployeePayrollProfile).where(EmployeePayrollProfile.organization_id == actor.organization_id, EmployeePayrollProfile.employee_id == employee_id, EmployeePayrollProfile.effective_from <= run.tax_point_date, (EmployeePayrollProfile.effective_to.is_(None) | (EmployeePayrollProfile.effective_to >= run.tax_point_date))).order_by(EmployeePayrollProfile.effective_from.desc()).limit(1).with_for_update())
        if not employee_profile: raise HTTPException(status_code=422, detail={"code": "payroll_employee_profile_missing", "employee_id": employee_id})
        structure = await db.get(SalaryStructure, employee_profile.salary_structure_id)
        rules = await load_rules(db, profile, insured_category=employee_profile.insured_category, hazard_class=employee_profile.hazard_class)
        components = (await db.execute(select(SalaryComponent).where(SalaryComponent.salary_structure_id == structure.id).order_by(SalaryComponent.position, SalaryComponent.id))).scalars().all()
        prior = await db.execute(select(func.coalesce(func.sum(Payslip.gross), 0), func.coalesce(func.sum(Payslip.taxable_income), 0), func.coalesce(func.sum(Payslip.pit), 0)).join(PayrollRun, PayrollRun.id == Payslip.payroll_run_id).where(Payslip.organization_id == actor.organization_id, Payslip.employee_id == employee_id, PayrollRun.tax_point_date >= date(run.tax_point_date.year, 1, 1), PayrollRun.tax_point_date < date(run.tax_point_date.year + 1, 1, 1), PayrollRun.status.in_(("calculated", "in_review", "approved", "posted", "paid")), PayrollRun.run_type != "advance", PayrollRun.id != run.id))
        prior_gross, prior_taxable, prior_pit = prior.one()
        # Keep compatibility with a migrated ledger that has accumulator
        # rows but no retained payslip rows (for example, a legacy import).
        if not any((prior_gross, prior_taxable, prior_pit)):
            legacy_prior = await db.execute(select(func.coalesce(func.sum(PayrollEmployeeAccumulator.gross_delta), 0), func.coalesce(func.sum(PayrollEmployeeAccumulator.taxable_delta), 0), func.coalesce(func.sum(PayrollEmployeeAccumulator.pit_withheld_delta), 0)).where(PayrollEmployeeAccumulator.organization_id == actor.organization_id, PayrollEmployeeAccumulator.employee_id == employee_id, PayrollEmployeeAccumulator.tax_year == run.tax_point_date.year))
            prior_gross, prior_taxable, prior_pit = legacy_prior.one()
        prior_relief = await db.scalar(select(func.coalesce(func.sum(Payslip.pit_relief), 0)).join(PayrollRun, PayrollRun.id == Payslip.payroll_run_id).where(Payslip.organization_id == actor.organization_id, Payslip.employee_id == employee_id, PayrollRun.tax_point_date >= date(run.tax_point_date.year, 1, 1), PayrollRun.tax_point_date < run.tax_point_date, PayrollRun.status.in_(("calculated", "in_review", "approved", "posted", "paid")), PayrollRun.run_type != "advance")) or 0
        prior_month_base = await db.scalar(select(func.coalesce(func.sum(Payslip.shi_base), 0)).join(PayrollRun, PayrollRun.id == Payslip.payroll_run_id).where(Payslip.organization_id == actor.organization_id, Payslip.employee_id == employee_id, PayrollRun.settlement_key == run.settlement_key, PayrollRun.status.in_(("calculated", "in_review", "approved", "posted", "paid")), PayrollRun.id != run.id)) or 0
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
            approved_entries = (await db.execute(select(WorkTimeEntry).where(WorkTimeEntry.id.in_((run.input_snapshot or {}).get("approved_time_entry_ids") or []), WorkTimeEntry.employee_id == employee_id, WorkTimeEntry.approval_status == "approved"))).scalars().all()
            approved_dates = {entry.local_work_date or entry.started_at.date() for entry in approved_entries}
            approved_hours = sum((Decimal(str((entry.ended_at - entry.started_at).total_seconds())) / Decimal("3600") for entry in approved_entries if entry.ended_at is not None), Decimal("0"))
        scheduled_workdays = sum(1 for offset in range((run.period_end - run.period_start).days + 1) if (run.period_start + timedelta(days=offset)).weekday() < 5)
        payable_workdays = Decimal(str(override.get("payable_workdays", len(approved_dates))))
        scheduled_workdays_value = Decimal(str(override.get("scheduled_workdays", scheduled_workdays)))
        payable_hours = Decimal(str(override.get("payable_hours", approved_hours)))
        scheduled_hours = Decimal(str(override.get("scheduled_hours", approved_hours if approved_hours > 0 else scheduled_workdays_value * Decimal("8"))))
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
        prior_traces = list((await db.execute(select(Payslip.calculation_trace).join(PayrollRun, PayrollRun.id == Payslip.payroll_run_id).where(Payslip.organization_id == actor.organization_id, Payslip.employee_id == employee_id, PayrollRun.tax_point_date >= date(run.tax_point_date.year, 1, 1), PayrollRun.tax_point_date < run.tax_point_date, PayrollRun.status.in_(("calculated", "in_review", "approved", "posted", "paid")), PayrollRun.run_type != "advance", PayrollRun.id != run.id))).scalars().all())
        prior_declared_deduction = sum((Decimal(str(((trace or {}).get("pit") or {}).get("declared_deduction", 0))) for trace in prior_traces), Decimal("0"))
        prior_declared_credit = sum((Decimal(str(((trace or {}).get("pit") or {}).get("declared_credit", 0))) for trace in prior_traces), Decimal("0"))
        declared_deduction = max(Decimal("0"), Decimal(str(tax_adjustments["deduction"])) - prior_declared_deduction)
        declared_credit = Decimal(str(tax_adjustments["credit"])) if rules.pit_withholding_method == "ytd_cumulative" else max(Decimal("0"), Decimal(str(tax_adjustments["credit"])) - prior_declared_credit)
        benefit_claims = await reserve_benefit_claims(db, run=run, employee_id=employee_id)
        grouped_claims = grouped_benefit_claims(benefit_claims)
        benefit_context = {f"benefit_claim_amount_{item['component_id']}": item["amount"] for item in grouped_claims}
        base_defs = [ComponentDefinition(code=row.code, label=row.name, component_kind=row.component_kind, formula=row.formula, proration_basis=row.proration_basis, taxable=row.is_taxable, shi_subject=row.is_shi_subject, non_taxable_allowance=row.is_non_taxable_allowance, leave_average_eligible=row.is_leave_average_eligible, only_tax_impact=row.only_tax_impact, payer=row.payer, position=row.position) for row in components if not (row.is_flexible_benefit and row.pay_against_benefit_claim)]
        benefit_defs = [ComponentDefinition(code=f"benefit_claim_{item['component_id']}", label=item["component_name"], component_kind="earning", formula=f"benefit_claim_amount_{item['component_id']}", taxable=item["taxable"], shi_subject=item["shi_subject"], non_taxable_allowance=item["non_taxable_allowance"], leave_average_eligible=False, only_tax_impact=item["only_tax_impact"], payer="employee", position=len(components) + index) for index, item in enumerate(grouped_claims)]
        defs = tuple(base_defs + benefit_defs)
        calc = calculate_payslip(CalculationInput(base_salary=Decimal(str(override.get("base_salary", employee_profile.base_salary))), payable_workdays=payable_workdays, scheduled_workdays=scheduled_workdays_value, payable_calendar_days=Decimal(str(override.get("payable_calendar_days", (run.period_end - run.period_start).days + 1))), scheduled_calendar_days=Decimal(str(override.get("scheduled_calendar_days", (run.period_end - run.period_start).days + 1))), payable_hours=payable_hours, scheduled_hours=scheduled_hours, context={**context, **benefit_context}, components=defs, prior_ytd_gross=Decimal(str(prior_gross or 0)), prior_ytd_taxable=Decimal(str(prior_taxable or 0)), prior_ytd_pit=Decimal(str(prior_pit or 0)), prior_ytd_relief=Decimal(str(prior_relief or 0)), prior_month_shi_base=Decimal(str(prior_month_base or 0)), current_advance=current_advance if run.run_type != "advance" else Decimal("0"), other_tax_deductible=Decimal(str(override.get("other_tax_deductible", 0))) + declared_deduction, other_tax_credit=declared_credit, other_deductions=Decimal(str(override.get("other_deductions", 0))), relief_eligibilities=frozenset(employee_profile.tax_relief_eligibility or []), leave_months=leave_months, leave_days=Decimal(str(override.get("leave_days", 0))), exemption_codes=frozenset((employee_profile.exemption_flags or {}).get("shi", [])), withhold_statutory=run.run_type != "advance"))
        profile_snapshot = {"employee_id": employee_id, "base_salary": str(employee_profile.base_salary), "salary_structure_id": structure.id, "salary_structure_version": structure.version, "salary_structure_checksum": structure.checksum, "components": [{"code": row.code, "name": row.name, "component_kind": row.component_kind, "formula": row.formula, "proration_basis": row.proration_basis, "is_taxable": row.is_taxable, "is_shi_subject": row.is_shi_subject, "is_non_taxable_allowance": row.is_non_taxable_allowance, "is_leave_average_eligible": row.is_leave_average_eligible, "is_flexible_benefit": row.is_flexible_benefit, "max_benefit_amount_yearly": str(row.max_benefit_amount_yearly), "pay_against_benefit_claim": row.pay_against_benefit_claim, "only_tax_impact": row.only_tax_impact, "payer": row.payer, "position": row.position, "account_id": row.account_id, "cost_center_id": row.cost_center_id} for row in components], "insured_category": employee_profile.insured_category, "hazard_class": employee_profile.hazard_class, "residency_status": employee_profile.residency_status, "tax_relief_eligibility": employee_profile.tax_relief_eligibility, "exemption_flags": employee_profile.exemption_flags, "insured_code": employee_profile.insured_category}
        input_snapshot = {"override": override, "profile_id": employee_profile.id, "advance_ids": [row.id for row in advance_rows], "unapplied_advance": str(unapplied_advance), "current_advance": str(current_advance), "tax_adjustments": {**tax_adjustments, "deduction": str(tax_adjustments["deduction"]), "credit": str(tax_adjustments["credit"]), "applied_deduction": str(declared_deduction), "applied_credit": str(declared_credit)}, "benefit_claims": benefit_claims, "resolved_units": {"payable_workdays": str(payable_workdays), "scheduled_workdays": str(scheduled_workdays_value), "payable_calendar_days": str(Decimal(str(override.get("payable_calendar_days", (run.period_end - run.period_start).days + 1)))), "scheduled_calendar_days": str(Decimal(str(override.get("scheduled_calendar_days", (run.period_end - run.period_start).days + 1)))), "payable_hours": str(payable_hours), "scheduled_hours": str(scheduled_hours)}}
        payslip = Payslip(payroll_run_id=run.id, organization_id=actor.organization_id, employee_id=employee_id, employee_profile_snapshot=profile_snapshot, input_snapshot=input_snapshot, calculation_trace=calc.trace, ytd_snapshot={key: str(value) for key, value in calc.ytd.items()}, gross=calc.gross, taxable_income=calc.taxable_income, shi_subject_gross=calc.shi_subject_gross, shi_base=calc.shi_base, employee_shi=calc.employee_shi, employer_shi=calc.employer_shi, pit=calc.pit, pit_relief=calc.relief, advance_offset=calc.advance_offset, net_pay=calc.net_pay, snapshot_checksum=snapshot_checksum({"profile": profile_snapshot, "input": input_snapshot, "result": calc.trace, "gross": str(calc.gross), "taxable_income": str(calc.taxable_income), "net": str(calc.net_pay)}))
        db.add(payslip); await db.flush()
        component_by_code = {row.code: row for row in components}
        component_by_code.update({f"benefit_claim_{item['component_id']}": next((row for row in components if row.id == item["component_id"]), None) for item in grouped_claims})
        db.add_all([PayslipLineItem(payslip_id=payslip.id, component_code=line["code"], label=line["label"], component_kind=line["component_kind"], amount=line["amount"], taxable=line["taxable"], shi_subject=line["shi_subject"], payer=line["payer"], formula_snapshot=line["formula"], trace={"position": line["position"], "leave_average_eligible": line.get("leave_average_eligible", False)}, account_id=getattr(component_by_code.get(line["code"]), "account_id", None), cost_center_id=getattr(component_by_code.get(line["code"]), "cost_center_id", None)) for line in calc.lines])
        result_rows.append(payslip)
    run.total_gross = sum((row.gross for row in result_rows), Decimal("0")); run.total_employee_shi = sum((row.employee_shi for row in result_rows), Decimal("0")); run.total_employer_shi = sum((row.employer_shi for row in result_rows), Decimal("0")); run.total_pit = sum((row.pit for row in result_rows), Decimal("0")); run.total_net = sum((row.net_pay for row in result_rows), Decimal("0")); run.status = "calculated"
    run.snapshot_checksum = _hash({"input": run.input_snapshot, "config": run.config_snapshot, "payslips": [row.snapshot_checksum for row in result_rows]})
    return result_rows


async def post_run(db: AsyncSession, actor: ActorContext, run: PayrollRun) -> ERPDocument:
    if run.status != "approved": raise HTTPException(status_code=409, detail={"code": "payroll_run_requires_approval"})
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
    accounts = (await db.execute(select(ERPAccount).where(ERPAccount.organization_id == actor.organization_id, ERPAccount.is_active.is_(True), ERPAccount.id.in_(list(roles.values()))))).scalars().all()
    if len(accounts) != len(set(roles.values())): raise HTTPException(status_code=422, detail={"code": "payroll_posting_account_invalid"})
    run.config_snapshot = {**(run.config_snapshot or {}), "posting_profile_id": posting.id, "bank_debit_account": roles.get("bank")}
    await mark_run_benefits_paid(db, run.id)
    document = ERPDocument(organization_id=actor.organization_id, document_type="payroll_run", number=run.run_number, status="submitted", currency="MNT", posting_date=run.period_end, net_total=run.total_net if is_advance else run.total_gross, tax_total=Decimal("0") if is_advance else run.total_employee_shi + run.total_pit + run.total_employer_shi, grand_total=run.total_net if is_advance else run.total_gross + run.total_employer_shi, outstanding_amount=Decimal("0") if is_advance else run.total_net, payload={"payroll_run_id": run.id, "run_type": run.run_type}, custom={})
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
        extra_accounts = (await db.execute(select(ERPAccount).where(ERPAccount.organization_id == actor.organization_id, ERPAccount.is_active.is_(True), ERPAccount.id.in_(list(component_account_ids))))).scalars().all()
        accounts.extend(extra_accounts)
    active_account_ids = {row.id for row in accounts}
    salary_split: dict[tuple[int, int | None], Decimal] = {}
    if not is_advance:
        for item in line_items:
            account_id = item.account_id or roles["salary_expense"]
            if item.account_id and item.account_id not in active_account_ids:
                raise HTTPException(status_code=422, detail={"code": "payroll_component_account_invalid", "account_id": item.account_id})
            key = (account_id, item.cost_center_id)
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
        entry(roles["employer_shi_expense"], run.total_employer_shi, "Employer SHI expense", debit_nature=True)
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
    debit, credit = sum((row[1] for row in lines), Decimal("0")), sum((row[2] for row in lines), Decimal("0"))
    if debit != credit: raise HTTPException(status_code=422, detail={"code": "payroll_unbalanced_journal", "debit": str(debit), "credit": str(credit)})
    db.add_all([ERPGeneralLedgerEntry(organization_id=actor.organization_id, document_id=document.id, account_id=account_id, cost_center_id=cost_center_id, posting_date=run.period_end, debit=debit, credit=credit, memo=memo) for account_id, debit, credit, memo, cost_center_id in lines])
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
    run.snapshot_checksum = _hash({"input": run.input_snapshot, "config": run.config_snapshot, "payslips": [row.snapshot_checksum for row in payslips]})
    return document


def canonical_payout_rows(run: PayrollRun, payslips: list[Payslip], accounts: dict[int, EmployeeBankAccount], employees: dict[int, Employee]) -> list[dict[str, Any]]:
    rows = []
    for index, payslip in enumerate(payslips, start=1):
        employee = employees[payslip.employee_id]; account = accounts[payslip.employee_id]
        rows.append({"batch_reference": run.run_number, "sequence": index, "execution_date": run.period_end.isoformat(), "debit_account": (run.config_snapshot or {}).get("bank_debit_account"), "employee_id": employee.id, "employee_reference": str(employee.id), "recipient_name": employee.name, "bank_code": account.bank_code, "bic": account.bank_code, "account_number_ciphertext": account.account_number_ciphertext, "amount": str(payslip.net_pay), "currency": (run.config_snapshot or {}).get("currency", "MNT"), "purpose": f"Salary {run.settlement_key}", "reference": f"{run.run_number}-{employee.id}"})
    return rows


async def reverse_run(db: AsyncSession, actor: ActorContext, run: PayrollRun) -> PayrollRun:
    """Create a negative, linked replacement journal without mutating a post."""
    if run.organization_id != actor.organization_id:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status not in {"posted", "paid"}:
        raise HTTPException(status_code=409, detail={"code": "payroll_run_requires_posted_for_reversal"})
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
        status="approved",
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
        db.add_all([PayslipLineItem(payslip_id=reversal_slip.id, component_code=line.component_code, label=line.label, component_kind=line.component_kind, amount=neg(line.amount), taxable=line.taxable, shi_subject=line.shi_subject, payer=line.payer, formula_snapshot=line.formula_snapshot, trace={**(line.trace or {}), "reversal_of_line_id": line.id}, account_id=line.account_id, cost_center_id=line.cost_center_id, position=line.position) for line in source_lines])
    reversal.snapshot_checksum = _hash({"source": run.snapshot_checksum, "run_id": reversal.id, "payslips": [slip.snapshot_checksum for slip in (await db.execute(select(Payslip).where(Payslip.payroll_run_id == reversal.id))).scalars().all()]})
    return reversal


async def create_replacement_run(db: AsyncSession, actor: ActorContext, source: PayrollRun, data: PayrollRunInput) -> PayrollRun:
    if source.organization_id != actor.organization_id:
        raise HTTPException(status_code=404, detail="Run not found")
    if source.status not in {"posted", "paid"}:
        raise HTTPException(status_code=409, detail={"code": "payroll_run_requires_posted_for_replacement"})
    run = await create_run(db, actor, data)
    run.replacement_of_run_id = source.id
    run.input_snapshot = {**(run.input_snapshot or {}), "replacement_of_run_id": source.id}
    run.snapshot_checksum = _hash(run.input_snapshot)
    return run
