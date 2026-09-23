from __future__ import annotations

import base64
import binascii
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.enterprise_deps import ActorContext, get_actor
from app.erp.service import require_capability
from app.models.models import (
    AdditionalSalary, Employee, EmployeeBankAccount, EmployeePayrollProfile, EmployeeBenefitApplication, EmployeeBenefitClaim, ERPAccount,
    EmployeeTaxExemptionDeclaration, EmployeeTaxExemptionProof, PayrollBankExportProfile,
    PayrollBankEntry, PayrollExportArtifact, PayrollPeriod, PayrollPostingProfile, PayrollRun, PayrollSalaryComponentMaster, Payslip, PayslipLineItem, PayslipStatutoryLine, IdempotencyRecord,
    PayrollPaymentBatch, PayrollPaymentAllocation, PayrollStatementImport, PayrollStatementLine,
    PayrollTaxExemptionCategory,
    SalaryComponent, SalaryStructure, SalaryStructureVersion, SHIRateTier, PITBracketTier, TaxReliefTier,
    StatutoryConfigProfile, SocialInsuranceContributorType, PayrollWorkPolicy, PayrollFormulaVariable, PayrollReportTemplate, Organization,
)
from app.services.enterprise_events import record_change
from app.services.secret_box import decrypt_secret, encrypt_secret
from app.services.user_notifications import create_notifications
from .exports import nd7_summary, nd7a_summary, nd7b_rows, nd8_rows, render_bank_export, render_protected_payslip, render_report_pdf, tt11_summary
from .schemas import (
    BankAccountInput, BankExportProfileInput, BankTemplateSampleInput, BankExportRequest, CalculateRunInput,
    EmployeePayrollInput, PayrollRunInput, PayrollCycleInputCorrection, SHIRateInput, PITBracketInput, ReliefTierInput, PostingProfileInput,
    PublishProfileInput, SalaryStructureInput, StatutoryProfileInput,
    BenefitApplicationInput, BenefitApplicationReviewInput, BenefitClaimInput,
    PayslipPublicationInput, PayrollApprovalInput, ProtectedPayslipInput, ReconciliationResolutionInput,
    ReviewDecisionInput, TaxDeclarationInput, TaxExemptionCategoryInput, TaxExemptionCategoryUpdateInput, TaxProofInput, PayrollReturnInput,
    AdditionalSalaryInput, BankEntryInput, BulkSalaryStructureAssignmentInput, GetEmployeesInput,
    PayrollCancelInput, PayrollEntryInput, PayrollPeriodInput, SalaryComponentMasterInput,
    SalaryStructureAssignmentInput,
    PaymentBatchInput, PaymentSettlementInput, PaymentRejectInput, StatementImportInput, PayrollPaymentReversalInput, PayrollRunReversalInput, VersionBumpInput,
    ContributorTypeInput, WorkPolicyInput, FormulaValidationInput, FormulaPreviewInput, FormulaVariableInput, StatutorySimulationInput, ReportTemplateInput,
)
from .tax_benefits import approved_tax_adjustments, validate_claim_balance
from .service import (
    calculate_run, canonical_payout_rows, create_bank_account, create_component_master, create_employee_profile,
    create_payment_batch, settle_payment_allocation, reject_payment_allocation, payment_coverage,
    bump_salary_structure, bump_statutory_profile, create_replacement_run, create_run, create_salary_structure, create_statutory_profile,
    delete_component_master, archive_component_master, component_master_out, component_master_usage, delete_salary_structure, delete_statutory_profile, load_rules, post_run, preflight_run, profile_out, publish_profile, reconcile_run, reverse_run,
    posting_preview, reverse_payment_allocation, update_component_master, update_salary_structure, update_statutory_profile, validate_overtime_rules,
)
from .calculator import CalculationInput, ComponentDefinition, _SafeFormula, _relief_for_income, calculate_payslip, compute_progressive_pit, compute_shi, money
from .frappe_service import (
    additional_salary_out, bank_entry_out, cancel_additional_salary,
    create_additional_salary, create_assignment, create_bulk_assignments,
    create_payroll_entry, create_payroll_period, create_salary_slips, get_employees,
    make_bank_entry, period_out, submit_additional_salary, submit_bank_entry,
    submit_salary_slips,
)


router = APIRouter()


async def payroll_capability(db: AsyncSession, actor: ActorContext, action: str) -> None:
    # Manager/team-lead roles do not imply payroll access; a custom payroll
    # capability assignment is the only way they can pass this gate.
    await require_capability(db, actor, "payroll", action)


@router.get("/capabilities")
async def payroll_effective_capabilities(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    """Expose the effective payroll capability set for capability-driven UI."""
    actions = ("view", "view_salary", "create", "administer", "edit_setup", "edit_formula", "calculate", "approve", "review", "approve_payroll_manager", "approve_hr_director", "approve_finance", "post", "pay", "export", "release_slips")
    result: dict[str, bool] = {}
    for action in actions:
        try:
            await payroll_capability(db, actor, action)
            result[action] = True
        except HTTPException as exc:
            if exc.status_code == 403:
                result[action] = False
            else:
                raise
    return {"capabilities": result, "account_id": actor.account_id}


def _contributor_type_out(row: SocialInsuranceContributorType) -> dict[str, Any]:
    return {"id": row.id, "code": row.code, "name": row.name, "description": row.description, "effective_from": row.effective_from.isoformat(), "effective_to": row.effective_to.isoformat() if row.effective_to else None, "source_references": row.source_references or [], "status": row.status}


def _work_policy_out(row: PayrollWorkPolicy) -> dict[str, Any]:
    return {"id": row.id, "code": row.code, "name": row.name, "scope_type": row.scope_type, "scope_key": row.scope_key, "effective_from": row.effective_from.isoformat(), "effective_to": row.effective_to.isoformat() if row.effective_to else None, "daily_hours": str(row.daily_hours), "weekly_hours": str(row.weekly_hours), "workweek": row.workweek or [], "hazard_class": row.hazard_class, "overtime_rules": row.overtime_rules or {}, "stacking_policy": row.stacking_policy, "source_references": row.source_references or [], "status": row.status}


def _report_template_out(row: PayrollReportTemplate) -> dict[str, Any]:
    return {"id": row.id, "kind": row.kind, "version": row.version, "status": row.status, "template": row.template or {}, "required_keys": row.required_keys or [], "source_references": row.source_references or [], "checksum": row.checksum}


@router.get("/statutory-profiles/{profile_id}/contributor-types")
async def list_payroll_contributor_types(profile_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "view")
    profile = await db.scalar(select(StatutoryConfigProfile).where(StatutoryConfigProfile.id == profile_id, StatutoryConfigProfile.organization_id == actor.organization_id))
    if not profile:
        raise HTTPException(status_code=404, detail="Statutory profile not found")
    rows = (await db.execute(select(SocialInsuranceContributorType).where(SocialInsuranceContributorType.organization_id == actor.organization_id, SocialInsuranceContributorType.effective_from <= profile.effective_from, (SocialInsuranceContributorType.effective_to.is_(None) | (SocialInsuranceContributorType.effective_to >= profile.effective_from))).order_by(SocialInsuranceContributorType.code))).scalars().all()
    return [_contributor_type_out(row) for row in rows]


@router.post("/statutory-profiles/{profile_id}/contributor-types", status_code=status.HTTP_201_CREATED)
async def create_payroll_contributor_type(profile_id: int, data: ContributorTypeInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "edit_setup")
    profile = await db.scalar(select(StatutoryConfigProfile).where(StatutoryConfigProfile.id == profile_id, StatutoryConfigProfile.organization_id == actor.organization_id))
    if not profile:
        raise HTTPException(status_code=404, detail="Statutory profile not found")
    if data.effective_to and data.effective_to < data.effective_from:
        raise HTTPException(status_code=422, detail={"code": "payroll_invalid_effective_range", "path": "effective_to", "message": "Effective end date cannot precede the start date.", "remediation": "Choose an end date on or after effective_from."})
    overlap = await db.scalar(select(SocialInsuranceContributorType.id).where(SocialInsuranceContributorType.organization_id == actor.organization_id, SocialInsuranceContributorType.code == data.code, SocialInsuranceContributorType.effective_from <= (data.effective_to or date.max), (SocialInsuranceContributorType.effective_to.is_(None) | (SocialInsuranceContributorType.effective_to >= data.effective_from))).limit(1))
    if overlap:
        raise HTTPException(status_code=409, detail={"code": "payroll_contributor_type_effective_overlap", "path": "effective_from", "message": "Another contributor type version overlaps this effective range.", "remediation": "Use a non-overlapping effective range for this contributor code."})
    row = SocialInsuranceContributorType(organization_id=actor.organization_id, created_by_account_id=actor.account_id, status="draft", **data.model_dump(exclude={"status"}))
    db.add(row); await db.commit(); await db.refresh(row)
    return _contributor_type_out(row)


@router.post("/statutory-profiles/{profile_id}/contributor-types/{contributor_type_id}/publish")
async def publish_payroll_contributor_type(profile_id: int, contributor_type_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "approve")
    profile = await db.scalar(select(StatutoryConfigProfile.id).where(StatutoryConfigProfile.id == profile_id, StatutoryConfigProfile.organization_id == actor.organization_id))
    if not profile:
        raise HTTPException(status_code=404, detail="Statutory profile not found")
    row = await db.scalar(select(SocialInsuranceContributorType).where(SocialInsuranceContributorType.id == contributor_type_id, SocialInsuranceContributorType.organization_id == actor.organization_id))
    if not row:
        raise HTTPException(status_code=404, detail="Contributor type not found")
    if not row.source_references:
        raise HTTPException(status_code=422, detail={"code": "payroll_contributor_type_source_required", "path": "source_references", "remediation": "Attach the authoritative statutory source before publication."})
    row.status = "active"
    await db.commit(); await db.refresh(row)
    return _contributor_type_out(row)


async def _profile_rule_rows(db: AsyncSession, actor: ActorContext, profile_id: int, model: Any) -> list[Any]:
    profile = await db.scalar(select(StatutoryConfigProfile).where(StatutoryConfigProfile.id == profile_id, StatutoryConfigProfile.organization_id == actor.organization_id))
    if not profile:
        raise HTTPException(status_code=404, detail="Statutory profile not found")
    return list((await db.execute(select(model).where(model.profile_id == profile_id).order_by(model.position, model.id))).scalars().all())


async def _draft_payroll_profile(db: AsyncSession, actor: ActorContext, profile_id: int) -> StatutoryConfigProfile:
    profile = await db.scalar(select(StatutoryConfigProfile).where(StatutoryConfigProfile.id == profile_id, StatutoryConfigProfile.organization_id == actor.organization_id).with_for_update())
    if not profile:
        raise HTTPException(status_code=404, detail="Statutory profile not found")
    if profile.status in {"published", "active"}:
        raise HTTPException(status_code=409, detail={"code": "payroll_profile_immutable", "path": "profile_id", "message": "Published profiles are immutable.", "remediation": "Create an effective-dated successor profile."})
    return profile


@router.get("/statutory-profiles/{profile_id}/shi-rules")
async def list_payroll_shi_rules(profile_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "view")
    rows = await _profile_rule_rows(db, actor, profile_id, SHIRateTier)
    return [{"id": row.id, "payer": row.payer, "insurance_fund": row.insurance_fund, "insured_category": row.insured_category, "hazard_class": row.hazard_class, "rate": str(row.rate), "base_floor": str(row.base_floor), "lower_bound": str(row.lower_bound), "upper_bound": str(row.upper_bound) if row.upper_bound is not None else None, "calculation_mode": row.calculation_mode, "fixed_amount": str(row.fixed_amount), "base_tax": str(row.base_tax), "base_ceiling_policy": getattr(row, "base_ceiling_policy", "profile"), "formula": row.formula, "exemption_code": row.exemption_code, "position": row.position} for row in rows]


@router.post("/statutory-profiles/{profile_id}/shi-rules", status_code=status.HTTP_201_CREATED)
async def add_payroll_shi_rule(profile_id: int, data: SHIRateInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "edit_setup")
    if data.calculation_mode == "formula": await payroll_capability(db, actor, "edit_formula")
    await _draft_payroll_profile(db, actor, profile_id)
    if data.upper_bound is not None and data.upper_bound <= data.lower_bound:
        raise HTTPException(status_code=422, detail={"code": "payroll_invalid_shi_tier", "path": "upper_bound", "message": "Upper bound must be greater than lower bound.", "remediation": "Correct the tier bounds."})
    if data.calculation_mode == "formula":
        try:
            _SafeFormula(data.formula or "")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"code": "payroll_invalid_shi_formula", "path": "formula", "message": str(exc), "remediation": "Use the safe formula DSL."}) from exc
    duplicate = await db.scalar(select(SHIRateTier.id).where(SHIRateTier.profile_id == profile_id, SHIRateTier.payer == data.payer, SHIRateTier.insurance_fund == data.insurance_fund, SHIRateTier.insured_category == data.insured_category, SHIRateTier.hazard_class == data.hazard_class, SHIRateTier.position == data.position))
    if duplicate:
        raise HTTPException(status_code=409, detail={"code": "payroll_shi_rule_position_exists", "path": "position", "message": "Another SHI rule uses this position for the same contributor/fund/hazard combination.", "remediation": "Choose another position or edit the existing rule."})
    row = SHIRateTier(profile_id=profile_id, **data.model_dump())
    db.add(row); await db.commit(); await db.refresh(row)
    return {"id": row.id, **{key: value for key, value in data.model_dump().items()}}


@router.get("/statutory-profiles/{profile_id}/pit-rules")
async def list_payroll_pit_rules(profile_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "view")
    rows = await _profile_rule_rows(db, actor, profile_id, PITBracketTier)
    return [{"id": row.id, "period_basis": row.period_basis, "lower_bound": str(row.lower_bound), "upper_bound": str(row.upper_bound) if row.upper_bound is not None else None, "marginal_rate": str(row.marginal_rate), "base_tax": str(row.base_tax), "position": row.position} for row in rows]


@router.post("/statutory-profiles/{profile_id}/pit-rules", status_code=status.HTTP_201_CREATED)
async def add_payroll_pit_rule(profile_id: int, data: PITBracketInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "edit_setup")
    await _draft_payroll_profile(db, actor, profile_id)
    if data.upper_bound is not None and data.upper_bound <= data.lower_bound:
        raise HTTPException(status_code=422, detail={"code": "payroll_invalid_pit_bracket", "path": "upper_bound", "message": "Upper bound must be greater than lower bound.", "remediation": "Correct the bracket bounds."})
    duplicate = await db.scalar(select(PITBracketTier.id).where(PITBracketTier.profile_id == profile_id, PITBracketTier.period_basis == data.period_basis, PITBracketTier.position == data.position))
    if duplicate:
        raise HTTPException(status_code=409, detail={"code": "payroll_pit_rule_position_exists", "path": "position", "message": "Another PIT bracket uses this position for the period basis.", "remediation": "Choose another position or edit the existing bracket."})
    row = PITBracketTier(profile_id=profile_id, **data.model_dump())
    db.add(row); await db.commit(); await db.refresh(row)
    return {"id": row.id, **{key: value for key, value in data.model_dump().items()}}


@router.get("/statutory-profiles/{profile_id}/relief-rules")
async def list_payroll_relief_rules(profile_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "view")
    rows = await _profile_rule_rows(db, actor, profile_id, TaxReliefTier)
    return [{"id": row.id, "eligibility_code": row.eligibility_code, "lower_bound": str(row.lower_bound), "upper_bound": str(row.upper_bound) if row.upper_bound is not None else None, "fixed_amount": str(row.fixed_amount), "amount_basis": row.amount_basis, "formula": row.formula, "position": row.position} for row in rows]


@router.post("/statutory-profiles/{profile_id}/relief-rules", status_code=status.HTTP_201_CREATED)
async def add_payroll_relief_rule(profile_id: int, data: ReliefTierInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "edit_setup")
    if data.formula: await payroll_capability(db, actor, "edit_formula")
    await _draft_payroll_profile(db, actor, profile_id)
    if data.upper_bound is not None and data.upper_bound <= data.lower_bound:
        raise HTTPException(status_code=422, detail={"code": "payroll_invalid_relief_tier", "path": "upper_bound", "message": "Upper bound must be greater than lower bound.", "remediation": "Correct the relief tier bounds."})
    if data.formula:
        try:
            _SafeFormula(data.formula)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"code": "payroll_invalid_relief_formula", "path": "formula", "message": str(exc), "remediation": "Use the safe formula DSL."}) from exc
    duplicate = await db.scalar(select(TaxReliefTier.id).where(TaxReliefTier.profile_id == profile_id, TaxReliefTier.eligibility_code == data.eligibility_code, TaxReliefTier.position == data.position))
    if duplicate:
        raise HTTPException(status_code=409, detail={"code": "payroll_relief_rule_position_exists", "path": "position", "message": "Another relief tier uses this position for the eligibility code.", "remediation": "Choose another position or edit the existing tier."})
    row = TaxReliefTier(profile_id=profile_id, **data.model_dump())
    db.add(row); await db.commit(); await db.refresh(row)
    return {"id": row.id, **{key: value for key, value in data.model_dump().items()}}


@router.get("/work-policies")
async def list_payroll_work_policies(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "view")
    rows = (await db.execute(select(PayrollWorkPolicy).where(PayrollWorkPolicy.organization_id == actor.organization_id).order_by(PayrollWorkPolicy.effective_from.desc(), PayrollWorkPolicy.id.desc()))).scalars().all()
    return [_work_policy_out(row) for row in rows]


@router.post("/work-policies", status_code=status.HTTP_201_CREATED)
async def create_payroll_work_policy(data: WorkPolicyInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "edit_setup")
    if data.effective_to and data.effective_to < data.effective_from:
        raise HTTPException(status_code=422, detail={"code": "payroll_invalid_effective_range", "path": "effective_to", "message": "Effective end date cannot precede the start date.", "remediation": "Choose an end date on or after effective_from."})
    if sorted(set(data.workweek)) != data.workweek or any(day < 1 or day > 7 for day in data.workweek):
        raise HTTPException(status_code=422, detail={"code": "payroll_invalid_workweek", "path": "workweek", "message": "Workweek values must be unique ISO weekdays from 1 to 7.", "remediation": "Enter a sorted list such as [1, 2, 3, 4, 5]."})
    validate_overtime_rules(data.overtime_rules)
    overlap = await db.scalar(select(PayrollWorkPolicy.id).where(PayrollWorkPolicy.organization_id == actor.organization_id, PayrollWorkPolicy.scope_type == data.scope_type, PayrollWorkPolicy.scope_key == data.scope_key, PayrollWorkPolicy.effective_from <= (data.effective_to or date.max), (PayrollWorkPolicy.effective_to.is_(None) | (PayrollWorkPolicy.effective_to >= data.effective_from))).limit(1))
    if overlap:
        raise HTTPException(status_code=409, detail={"code": "payroll_work_policy_effective_overlap", "path": "effective_from", "message": "Another policy overlaps this effective range.", "remediation": "Use a non-overlapping date or revise the existing draft."})
    row = PayrollWorkPolicy(organization_id=actor.organization_id, created_by_account_id=actor.account_id, status="draft", **data.model_dump())
    db.add(row); await db.commit(); await db.refresh(row)
    return _work_policy_out(row)


@router.post("/formulas/validate")
async def validate_payroll_formula(data: FormulaValidationInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "edit_formula")
    try:
        formula = _SafeFormula(data.formula)
        unknown = sorted(formula.dependencies - set(data.variables))
        return {"valid": not unknown, "dependencies": sorted(formula.dependencies), "unknown_variables": unknown, "message": "Formula is valid" if not unknown else "Provide values for every referenced variable."}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "payroll_formula_invalid", "path": "formula", "message": str(exc), "remediation": "Use only allowlisted arithmetic, comparisons, and min/max/abs/round_money/if_else functions."}) from exc


@router.post("/formula-context/preview")
async def preview_payroll_formula(data: FormulaPreviewInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "edit_formula")
    try:
        compiled = _SafeFormula(data.formula)
        value = compiled.evaluate(data.context, data.quantum)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "payroll_formula_preview_failed", "path": "formula", "message": str(exc), "remediation": "Correct the formula or provide finite values for every referenced variable."}) from exc
    return {"value": str(value), "dependencies": sorted(compiled.dependencies), "context": {key: str(value) for key, value in data.context.items()}}


@router.get("/formula-context")
async def list_payroll_formula_variables(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "view")
    rows = (await db.execute(select(PayrollFormulaVariable).where(PayrollFormulaVariable.organization_id == actor.organization_id, PayrollFormulaVariable.is_active.is_(True)).order_by(PayrollFormulaVariable.code))).scalars().all()
    return [{"id": row.id, "code": row.code, "label": row.label, "data_type": row.data_type, "default_value": row.default_value, "source": row.source, "required": row.required, "minimum": str(row.minimum) if row.minimum is not None else None, "maximum": str(row.maximum) if row.maximum is not None else None} for row in rows]


@router.post("/formula-context", status_code=status.HTTP_201_CREATED)
async def create_payroll_formula_variable(data: FormulaVariableInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "edit_setup")
    if data.minimum is not None and data.maximum is not None and data.maximum < data.minimum:
        raise HTTPException(status_code=422, detail={"code": "payroll_formula_variable_range_invalid", "path": "maximum", "message": "Maximum must be greater than or equal to minimum.", "remediation": "Correct the allowed variable range."})
    if data.data_type in {"decimal", "integer"} and data.default_value is not None:
        try:
            default = Decimal(data.default_value)
        except Exception as exc:
            raise HTTPException(status_code=422, detail={"code": "payroll_formula_variable_default_invalid", "path": "default_value", "message": "The default must be a finite number for a numeric variable.", "remediation": "Use a decimal or integer value."}) from exc
        if not default.is_finite() or (data.data_type == "integer" and default != default.to_integral_value()):
            raise HTTPException(status_code=422, detail={"code": "payroll_formula_variable_default_invalid", "path": "default_value", "message": "The numeric default has the wrong type or is not finite.", "remediation": "Use a finite decimal or whole-number default."})
        if data.minimum is not None and default < data.minimum or data.maximum is not None and default > data.maximum:
            raise HTTPException(status_code=422, detail={"code": "payroll_formula_variable_default_out_of_range", "path": "default_value", "message": "The default is outside the allowed range.", "remediation": "Adjust the default or widen the minimum/maximum range."})
    duplicate = await db.scalar(select(PayrollFormulaVariable.id).where(PayrollFormulaVariable.organization_id == actor.organization_id, PayrollFormulaVariable.code == data.code))
    if duplicate:
        raise HTTPException(status_code=409, detail={"code": "payroll_formula_variable_exists", "path": "code"})
    row = PayrollFormulaVariable(organization_id=actor.organization_id, **data.model_dump())
    db.add(row); await db.commit(); await db.refresh(row)
    return {"id": row.id, "code": row.code, "label": row.label, "data_type": row.data_type, "default_value": row.default_value, "source": row.source, "required": row.required, "minimum": str(row.minimum) if row.minimum is not None else None, "maximum": str(row.maximum) if row.maximum is not None else None}


@router.post("/statutory-profiles/{profile_id}/simulate")
async def simulate_payroll_statutory_rules(profile_id: int, data: StatutorySimulationInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "edit_setup")
    if any(item.get("amount_mode") == "formula" for item in data.components): await payroll_capability(db, actor, "edit_formula")
    profile = await db.scalar(select(StatutoryConfigProfile).where(StatutoryConfigProfile.id == profile_id, StatutoryConfigProfile.organization_id == actor.organization_id))
    if not profile:
        raise HTTPException(status_code=404, detail="Statutory profile not found")
    rules = await load_rules(db, profile, insured_category=data.insured_category, hazard_class=data.hazard_class)
    if data.components:
        definitions = tuple(ComponentDefinition(code=str(item["code"]), label=str(item.get("label", item["code"])), component_kind=str(item.get("component_kind", "earning")), formula=str(item.get("formula", "0")), amount_mode=str(item.get("amount_mode", "formula")), percentage_basis=item.get("percentage_basis"), taxable=bool(item.get("taxable", True)), shi_subject=bool(item.get("shi_subject", True)), non_taxable_allowance=bool(item.get("non_taxable_allowance", False)), payer=str(item.get("payer", "employee")), position=int(item.get("position", index))) for index, item in enumerate(data.components))
        try:
            calc = calculate_payslip(CalculationInput(base_salary=data.base_salary, context=data.context, components=definitions, other_deductions=data.other_deductions, relief_eligibilities=frozenset(data.relief_eligibilities), exemption_codes=frozenset(data.exemption_codes), prior_month_shi_base=data.prior_month_shi_base), rules)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"code": "payroll_simulation_invalid", "path": "components", "message": str(exc), "remediation": "Correct the formula, dependency, or deduction inputs before previewing."}) from exc
        shi_base, employee_shi, employer_shi = calc.shi_base, calc.employee_shi, calc.employer_shi
        shi_trace = (calc.trace.get("shi") or {})
        pit, relief, net = calc.pit_before_relief, calc.relief, calc.net_pay
        components = [{"code": line["code"], "label": line["label"], "amount": str(line["amount"]), "formula": line["formula"], "kind": line["component_kind"]} for line in calc.lines]
    else:
        components = []
        try:
            shi_base, employee_shi, employer_shi, shi_trace = compute_shi(data.shi_subject_gross, rules, prior_month_base=data.prior_month_shi_base, exemption_codes=frozenset(data.exemption_codes))
            pit = compute_progressive_pit(data.taxable_income, rules.pit_brackets, mode=rules.pit_calculation_mode, formula=rules.pit_formula, quantum=rules.rounding_quantum)
            relief = min(pit, _relief_for_income(data.taxable_income, frozenset(data.relief_eligibilities), rules))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"code": "payroll_simulation_invalid", "path": "taxable_income", "message": str(exc), "remediation": "Correct the statutory formula or preview inputs."}) from exc
        net = data.taxable_income - employee_shi - pit + relief - data.other_deductions
        if net < Decimal("0"):
            raise HTTPException(status_code=422, detail={"code": "payroll_negative_net_preview", "path": "other_deductions", "message": "The preview would produce negative net pay.", "remediation": "Reduce deductions or record the excess advance for carry-forward."})
    taxable_preview = calc.taxable_income if data.components else data.taxable_income
    ladder = [{"step": "shi_base", "amount": str(shi_base)}, {"step": "employee_shi", "amount": str(employee_shi)}, {"step": "employer_shi", "amount": str(employer_shi)}, {"step": "taxable_income", "amount": str(taxable_preview)}, {"step": "pit_before_relief", "amount": str(pit)}, {"step": "pit_relief", "amount": str(relief)}, {"step": "net_pay_preview", "amount": str(net)}]
    return {"profile_id": profile.id, "calculation_mode": {"pit": rules.pit_calculation_mode, "shi": sorted({row.calculation_mode for row in rules.shi_rates})}, "components": components, "deductions": {"employee_shi": str(employee_shi), "pit": str(max(Decimal("0"), pit - relief)), "other": str(data.other_deductions), "total": str(employee_shi + max(Decimal("0"), pit - relief) + data.other_deductions)}, "net_pay": str(net), "ladder": ladder, "calculation_ladder": ladder, "shi": {"by_fund": {key: str(value) for key, value in (shi_trace.get("by_fund") or {}).items()}, "rules": shi_trace.get("rules") or []}, "pit_before_relief": str(pit), "pit_relief": str(relief)}


@router.get("/report-templates")
async def list_payroll_report_templates(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "view")
    rows = (await db.execute(select(PayrollReportTemplate).where(PayrollReportTemplate.organization_id == actor.organization_id).order_by(PayrollReportTemplate.kind, PayrollReportTemplate.version.desc()))).scalars().all()
    return [_report_template_out(row) for row in rows]


@router.post("/report-templates", status_code=status.HTTP_201_CREATED)
async def create_payroll_report_template(data: ReportTemplateInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "edit_setup")
    duplicate = await db.scalar(select(PayrollReportTemplate.id).where(PayrollReportTemplate.organization_id == actor.organization_id, PayrollReportTemplate.kind == data.kind, PayrollReportTemplate.version == data.version))
    if duplicate:
        raise HTTPException(status_code=409, detail={"code": "payroll_report_template_version_exists", "path": "version", "remediation": "Choose the next available version."})
    columns = {item.get("key") for item in (data.template.get("columns") or []) if isinstance(item, dict)}
    missing = sorted(set(data.required_keys) - columns)
    if missing:
        raise HTTPException(status_code=422, detail={"code": "payroll_report_template_required_keys_missing", "path": "template.columns", "missing": missing})
    checksum = hashlib.sha256(json.dumps(data.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    row = PayrollReportTemplate(organization_id=actor.organization_id, created_by_account_id=actor.account_id, checksum=checksum, **data.model_dump())
    db.add(row); await db.commit(); await db.refresh(row)
    return _report_template_out(row)


@router.put("/report-templates/{template_id}")
async def update_payroll_report_template(template_id: int, data: ReportTemplateInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "edit_setup")
    row = await db.scalar(select(PayrollReportTemplate).where(PayrollReportTemplate.id == template_id, PayrollReportTemplate.organization_id == actor.organization_id).with_for_update())
    if not row:
        raise HTTPException(status_code=404, detail="Report template not found")
    if row.status != "draft":
        raise HTTPException(status_code=409, detail={"code": "payroll_report_template_immutable", "remediation": "Create a successor version instead of editing a published template."})
    duplicate = await db.scalar(select(PayrollReportTemplate.id).where(PayrollReportTemplate.organization_id == actor.organization_id, PayrollReportTemplate.kind == data.kind, PayrollReportTemplate.version == data.version, PayrollReportTemplate.id != row.id))
    if duplicate:
        raise HTTPException(status_code=409, detail={"code": "payroll_report_template_version_exists", "path": "version", "remediation": "Choose the next available version."})
    columns = {item.get("key") for item in (data.template.get("columns") or []) if isinstance(item, dict)}
    missing = sorted(set(data.required_keys) - columns)
    if missing:
        raise HTTPException(status_code=422, detail={"code": "payroll_report_template_required_keys_missing", "path": "template.columns", "missing": missing})
    payload = data.model_dump(mode="json")
    row.kind = data.kind; row.version = data.version; row.template = data.template; row.required_keys = data.required_keys; row.source_references = data.source_references
    row.checksum = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    await db.commit(); await db.refresh(row)
    return _report_template_out(row)


@router.post("/work-policies/{policy_id}/publish")
async def publish_payroll_work_policy(policy_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "approve")
    row = await db.scalar(select(PayrollWorkPolicy).where(PayrollWorkPolicy.id == policy_id, PayrollWorkPolicy.organization_id == actor.organization_id))
    if not row:
        raise HTTPException(status_code=404, detail="Work policy not found")
    if not row.source_references:
        raise HTTPException(status_code=422, detail={"code": "payroll_work_policy_source_required", "path": "source_references", "remediation": "Attach the authoritative labor-law source before publication."})
    overlap = await db.scalar(select(PayrollWorkPolicy.id).where(PayrollWorkPolicy.organization_id == actor.organization_id, PayrollWorkPolicy.id != row.id, PayrollWorkPolicy.scope_type == row.scope_type, PayrollWorkPolicy.scope_key == row.scope_key, PayrollWorkPolicy.status.in_(("active", "published")), PayrollWorkPolicy.effective_from <= (row.effective_to or date.max), (PayrollWorkPolicy.effective_to.is_(None) | (PayrollWorkPolicy.effective_to >= row.effective_from))).limit(1))
    if overlap:
        raise HTTPException(status_code=409, detail={"code": "payroll_work_policy_effective_overlap", "path": "effective_from", "remediation": "Close or supersede the existing effective policy first."})
    row.status = "active"
    await db.commit(); await db.refresh(row)
    return _work_policy_out(row)


@router.post("/report-templates/{template_id}/publish")
async def publish_payroll_report_template(template_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "approve")
    row = await db.scalar(select(PayrollReportTemplate).where(PayrollReportTemplate.id == template_id, PayrollReportTemplate.organization_id == actor.organization_id))
    if not row:
        raise HTTPException(status_code=404, detail="Report template not found")
    if not row.source_references:
        raise HTTPException(status_code=422, detail={"code": "payroll_report_template_source_required", "path": "source_references", "remediation": "Attach the authoritative statutory/report source before publication."})
    row.status = "published"; row.published_by_account_id = actor.account_id; row.published_at = datetime.now(timezone.utc)
    await db.commit(); await db.refresh(row)
    return _report_template_out(row)


def _is_payroll_admin(actor: ActorContext) -> bool:
    return bool({"admin", "hr"}.intersection(actor.roles))


def _mark_deprecated(response: Response) -> None:
    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = "Wed, 30 Jun 2027 00:00:00 GMT"
    response.headers["Link"] = '</v1/erp/payroll/runs>; rel="successor-version"'


async def _employee_scope(db: AsyncSession, actor: ActorContext, requested: int | None) -> int | None:
    if _is_payroll_admin(actor):
        await payroll_capability(db, actor, "view")
        return requested
    if actor.employee_id is None or (requested is not None and requested != actor.employee_id):
        raise HTTPException(status_code=403, detail={"code": "payroll_employee_scope_required"})
    return actor.employee_id


def _declaration_out(row: EmployeeTaxExemptionDeclaration) -> dict[str, Any]:
    return {"id": row.id, "employee_id": row.employee_id, "category_id": row.category_id, "tax_year": row.tax_year, "declared_amount": str(row.declared_amount), "status": row.status, "note": row.note, "submitted_at": row.submitted_at.isoformat() if row.submitted_at else None}


def _benefit_application_out(row: EmployeeBenefitApplication) -> dict[str, Any]:
    return {"id": row.id, "employee_id": row.employee_id, "salary_component_id": row.salary_component_id, "tax_year": row.tax_year, "requested_amount": str(row.requested_amount), "approved_amount": str(row.approved_amount), "status": row.status, "note": row.note}


def _benefit_claim_out(row: EmployeeBenefitClaim) -> dict[str, Any]:
    return {"id": row.id, "application_id": row.application_id, "claim_date": row.claim_date.isoformat(), "amount": str(row.amount), "reference": row.reference, "status": row.status, "payroll_run_id": row.payroll_run_id}


def _run_out(run: PayrollRun) -> dict[str, Any]:
    snapshot = run.input_snapshot or {}
    return {"id": run.id, "run_number": run.run_number, "run_type": run.run_type, "period_start": run.period_start.isoformat(), "period_end": run.period_end.isoformat(), "settlement_key": run.settlement_key, "tax_point_date": run.tax_point_date.isoformat(), "status": run.status, "workflow_version": run.workflow_version, "document_status": run.document_status, "payroll_frequency": run.payroll_frequency, "posting_date": run.posting_date.isoformat() if run.posting_date else None, "employee_filter": run.employee_filter or snapshot.get("employee_filter") or {}, "employee_ids": list(snapshot.get("employee_ids") or []), "employee_selection": snapshot.get("employee_selection"), "employee_validation_errors": list(snapshot.get("employee_validation_errors") or []), "validate_attendance": snapshot.get("validate_attendance", True), "attendance_policy": snapshot.get("attendance_policy") or {}, "salary_slips_created": run.salary_slips_created, "salary_slips_submitted": run.salary_slips_submitted, "payment_status": run.payment_status, "payment_account_id": run.payment_account_id, "cost_center_id": run.cost_center_id, "payroll_period_id": run.payroll_period_id, "bank_entry_id": run.bank_entry_id, "reversal_of_run_id": run.reversal_of_run_id, "replacement_of_run_id": run.replacement_of_run_id, "statutory_profile_id": run.statutory_profile_id, "posting_profile_id": run.posting_profile_id, "erp_document_id": run.erp_document_id, "total_gross": str(run.total_gross), "total_employee_shi": str(run.total_employee_shi), "total_employer_shi": str(run.total_employer_shi), "total_pit": str(run.total_pit), "total_net": str(run.total_net), "snapshot_checksum": run.snapshot_checksum, "is_example_profile": bool((run.config_snapshot or {}).get("is_example")), "reconciliation": run.reconciliation_snapshot or {}, "approval_workflow": run.approval_workflow or {}, "approved_at": run.approved_at.isoformat() if run.approved_at else None, "posted_at": run.posted_at.isoformat() if run.posted_at else None, "payslips_published_at": run.payslips_published_at.isoformat() if run.payslips_published_at else None, "rejected_at": run.rejected_at.isoformat() if run.rejected_at else None, "rejection_reason": run.rejection_reason, "reversed_at": run.reversed_at.isoformat() if run.reversed_at else None}


def _slip_out(slip: Payslip, lines: list[PayslipLineItem] | None = None, statutory_lines: list[PayslipStatutoryLine] | None = None) -> dict[str, Any]:
    result = {"id": slip.id, "payroll_run_id": slip.payroll_run_id, "employee_id": slip.employee_id, "document_status": slip.document_status, "submitted_at": slip.submitted_at.isoformat() if slip.submitted_at else None, "published_at": slip.published_at.isoformat() if slip.published_at else None, "cancelled_at": slip.cancelled_at.isoformat() if slip.cancelled_at else None, "gross": str(slip.gross), "taxable_income": str(slip.taxable_income), "shi_subject_gross": str(slip.shi_subject_gross), "shi_base": str(slip.shi_base), "employee_shi": str(slip.employee_shi), "employer_shi": str(slip.employer_shi), "pit": str(slip.pit), "pit_relief": str(slip.pit_relief), "advance_offset": str(slip.advance_offset), "net_pay": str(slip.net_pay), "snapshot_checksum": slip.snapshot_checksum, "ytd": slip.ytd_snapshot, "trace": slip.calculation_trace}
    if lines is not None: result["lines"] = [{"code": row.component_code, "component_master_id": row.component_master_id, "label": row.label, "kind": row.component_kind, "amount": str(row.amount), "taxable": row.taxable, "shi_subject": row.shi_subject, "payer": row.payer, "formula": row.formula_snapshot, "trace": row.trace} for row in lines]
    if statutory_lines is not None: result["statutory_lines"] = [{"contributor_code": row.contributor_code, "payer": row.payer, "insurance_fund": row.insurance_fund, "hazard_class": row.hazard_class, "calculation_mode": row.calculation_mode, "base": str(row.base), "lower_bound": str(row.lower_bound), "upper_bound": str(row.upper_bound) if row.upper_bound is not None else None, "rate": str(row.rate), "amount": str(row.amount), "formula": row.formula_snapshot, "trace": row.trace} for row in statutory_lines]
    return result


def _payment_batch_out(batch: PayrollPaymentBatch, allocations: list[PayrollPaymentAllocation] | None = None) -> dict[str, Any]:
    result = {
        "id": batch.id, "payroll_run_id": batch.payroll_run_id, "batch_reference": batch.batch_reference,
        "payment_account_id": batch.payment_account_id, "payable_account_id": batch.payable_account_id,
        "posting_date": batch.posting_date.isoformat(), "currency": batch.currency, "status": batch.status,
        "retry_of_batch_id": batch.retry_of_batch_id, "export_artifact_id": batch.export_artifact_id,
        "bank_reference": batch.bank_reference, "bank_confirmed_at": batch.bank_confirmed_at.isoformat() if batch.bank_confirmed_at else None,
        "total_amount": str(batch.total_amount),
    }
    if allocations is not None:
        result["allocations"] = [{
            "id": row.id, "payslip_id": row.payslip_id, "employee_id": row.employee_id, "amount": str(row.amount),
            "status": row.status, "attempt_number": row.attempt_number, "transaction_reference": row.transaction_reference,
            "submitted_at": row.submitted_at.isoformat() if row.submitted_at else None,
            "settled_at": row.settled_at.isoformat() if row.settled_at else None,
            "rejected_at": row.rejected_at.isoformat() if row.rejected_at else None,
            "rejection_reason": row.rejection_reason,
        } for row in allocations]
    return result


@router.get("/profiles")
async def list_profiles(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "view")
    profiles = (await db.execute(select(StatutoryConfigProfile).where(StatutoryConfigProfile.organization_id == actor.organization_id).order_by(StatutoryConfigProfile.effective_from.desc(), StatutoryConfigProfile.version.desc()))).scalars().all()
    output = []
    for profile in profiles:
        rates = (await db.execute(select(SHIRateTier).where(SHIRateTier.profile_id == profile.id).order_by(SHIRateTier.position))).scalars().all()
        brackets = (await db.execute(select(PITBracketTier).where(PITBracketTier.profile_id == profile.id).order_by(PITBracketTier.position))).scalars().all()
        reliefs = (await db.execute(select(TaxReliefTier).where(TaxReliefTier.profile_id == profile.id).order_by(TaxReliefTier.position))).scalars().all()
        output.append(profile_out(profile, rates=rates, brackets=brackets, reliefs=reliefs))
    return output


@router.post("/profiles", status_code=status.HTTP_201_CREATED)
async def create_profile(data: StatutoryProfileInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "administer")
    if data.pit_calculation_mode == "formula" or data.pit_formula or any(row.calculation_mode == "formula" for row in data.shi_rates) or any(row.formula for row in data.relief_tiers): await payroll_capability(db, actor, "edit_formula")
    profile = await create_statutory_profile(db, actor, data)
    await record_change(db, actor=actor, topic="payroll", aggregate_type="statutory_config_profile", aggregate_id=profile.id, operation="created", after={"code": profile.code, "version": profile.version, "is_example": profile.is_example})
    await db.commit(); await db.refresh(profile)
    return profile_out(profile)


@router.post("/profiles/{profile_id}/publish")
async def publish_profile_route(profile_id: int, data: PublishProfileInput = PublishProfileInput(), db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "approve")
    profile = await db.scalar(select(StatutoryConfigProfile).where(StatutoryConfigProfile.id == profile_id, StatutoryConfigProfile.organization_id == actor.organization_id))
    if not profile: raise HTTPException(status_code=404, detail="Profile not found")
    await publish_profile(db, actor, profile, data.acknowledge_example)
    await record_change(db, actor=actor, topic="payroll", aggregate_type="statutory_config_profile", aggregate_id=profile.id, operation="published", after={"code": profile.code, "version": profile.version, "is_example": profile.is_example})
    await db.commit(); await db.refresh(profile)
    return profile_out(profile)


@router.put("/profiles/{profile_id}")
async def update_profile_route(profile_id: int, data: StatutoryProfileInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "administer")
    if data.pit_calculation_mode == "formula" or data.pit_formula or any(row.calculation_mode == "formula" for row in data.shi_rates) or any(row.formula for row in data.relief_tiers): await payroll_capability(db, actor, "edit_formula")
    profile = await db.scalar(select(StatutoryConfigProfile).where(StatutoryConfigProfile.id == profile_id, StatutoryConfigProfile.organization_id == actor.organization_id))
    if not profile: raise HTTPException(status_code=404, detail="Profile not found")
    if profile.status in {"published", "active"}:
        successor = await bump_statutory_profile(db, actor, profile, data.effective_from)
        await update_statutory_profile(db, actor, successor, data.model_copy(update={"version": successor.version}))
        await record_change(db, actor=actor, topic="payroll", aggregate_type="statutory_config_profile", aggregate_id=successor.id, operation="bumped", after={"source_profile_id": profile.id, "version": successor.version})
        await db.commit(); await db.refresh(successor)
        return profile_out(successor, rates=data.shi_rates, brackets=data.pit_brackets, reliefs=data.relief_tiers)
    await update_statutory_profile(db, actor, profile, data)
    await record_change(db, actor=actor, topic="payroll", aggregate_type="statutory_config_profile", aggregate_id=profile.id, operation="updated", after={"code": profile.code, "version": profile.version, "status": profile.status})
    await db.commit(); await db.refresh(profile)
    return profile_out(profile, rates=data.shi_rates, brackets=data.pit_brackets, reliefs=data.relief_tiers)


@router.post("/profiles/{profile_id}/bump-version", status_code=status.HTTP_201_CREATED)
async def bump_profile_route(profile_id: int, data: VersionBumpInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "edit_setup")
    profile = await db.scalar(select(StatutoryConfigProfile).where(StatutoryConfigProfile.id == profile_id, StatutoryConfigProfile.organization_id == actor.organization_id))
    if not profile: raise HTTPException(status_code=404, detail="Profile not found")
    successor = await bump_statutory_profile(db, actor, profile, data.effective_from)
    await record_change(db, actor=actor, topic="payroll", aggregate_type="statutory_config_profile", aggregate_id=successor.id, operation="bumped", after={"source_profile_id": profile.id, "version": successor.version})
    await db.commit(); await db.refresh(successor)
    return profile_out(successor)


@router.delete("/profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_profile_route(profile_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "administer")
    profile = await db.scalar(select(StatutoryConfigProfile).where(StatutoryConfigProfile.id == profile_id, StatutoryConfigProfile.organization_id == actor.organization_id))
    if not profile: raise HTTPException(status_code=404, detail="Profile not found")
    await delete_statutory_profile(db, actor, profile)
    await record_change(db, actor=actor, topic="payroll", aggregate_type="statutory_config_profile", aggregate_id=profile_id, operation="deleted", after={"profile_id": profile_id})
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/salary-structures")
async def list_salary_structures(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "view")
    structures = (await db.execute(select(SalaryStructure).where(SalaryStructure.organization_id == actor.organization_id).order_by(SalaryStructure.code, SalaryStructure.version.desc()))).scalars().all()
    result = []
    for structure in structures:
        components = (await db.execute(select(SalaryComponent).where(SalaryComponent.salary_structure_id == structure.id).order_by(SalaryComponent.position))).scalars().all()
        result.append({"id": structure.id, "code": structure.code, "name": structure.name, "version": structure.version, "status": structure.status, "effective_from": structure.effective_from.isoformat(), "effective_to": structure.effective_to.isoformat() if structure.effective_to else None, "currency": structure.currency, "checksum": structure.checksum, "source_structure_id": structure.source_structure_id, "components": [{"id": row.id, "component_master_id": row.component_master_id, "code": row.code, "name": row.name, "component_kind": row.component_kind, "formula": row.formula, "amount_mode": row.amount_mode, "percentage_basis": row.percentage_basis, "proration_basis": row.proration_basis, "is_taxable": row.is_taxable, "is_shi_subject": row.is_shi_subject, "is_non_taxable_allowance": row.is_non_taxable_allowance, "is_flexible_benefit": row.is_flexible_benefit, "max_benefit_amount_yearly": str(row.max_benefit_amount_yearly), "pay_against_benefit_claim": row.pay_against_benefit_claim, "only_tax_impact": row.only_tax_impact, "payer": row.payer, "position": row.position, "account_id": row.account_id, "cost_center_id": row.cost_center_id} for row in components]})
    return result


@router.post("/salary-structures", status_code=status.HTTP_201_CREATED)
async def create_structure(data: SalaryStructureInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "administer")
    if any(row.amount_mode == "formula" for row in data.components): await payroll_capability(db, actor, "edit_formula")
    structure = await create_salary_structure(db, actor, data)
    await record_change(db, actor=actor, topic="payroll", aggregate_type="salary_structure", aggregate_id=structure.id, operation="created", after={"code": structure.code, "version": structure.version})
    await db.commit(); await db.refresh(structure)
    return {"id": structure.id, "code": structure.code, "name": structure.name, "status": structure.status, "checksum": structure.checksum}


@router.post("/salary-structures/{structure_id}/publish")
async def publish_structure(structure_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "approve")
    structure = await db.scalar(select(SalaryStructure).where(SalaryStructure.id == structure_id, SalaryStructure.organization_id == actor.organization_id))
    if not structure: raise HTTPException(status_code=404, detail="Salary structure not found")
    if structure.status in {"published", "active"}: raise HTTPException(status_code=409, detail={"code": "payroll_salary_structure_already_published"})
    components = (await db.execute(select(SalaryComponent).where(SalaryComponent.salary_structure_id == structure.id))).scalars().all()
    if not components: raise HTTPException(status_code=422, detail={"code": "payroll_salary_components_required"})
    component_codes = {row.code for row in components}
    builtin_variables = {"base_salary", "payable_workdays", "scheduled_workdays", "payable_calendar_days", "scheduled_calendar_days", "payable_hours", "scheduled_hours", "prior_ytd_gross", "prior_ytd_taxable", "prior_ytd_pit", "prior_month_shi_base", "minimum_wage", "shi_ceiling_multiplier", "periods_per_year", "overtime_hours", "weekday_overtime_hours", "rest_day_overtime_hours", "public_holiday_overtime_hours", "night_overtime_hours"}
    configured_variables = set((await db.execute(select(PayrollFormulaVariable.code).where(PayrollFormulaVariable.organization_id == actor.organization_id, PayrollFormulaVariable.is_active.is_(True)))).scalars().all())
    for row in components:
        expression = row.formula if row.amount_mode != "percentage" else f"({row.percentage_basis or 'base_salary'}) * ({row.formula})"
        try:
            compiled = _SafeFormula(expression)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"code": "payroll_invalid_formula", "path": f"components.{row.code}.formula", "message": str(exc), "remediation": "Correct the formula using the safe formula editor."}) from exc
        unknown = sorted(compiled.dependencies - builtin_variables - component_codes - configured_variables)
        if unknown:
            raise HTTPException(status_code=422, detail={"code": "payroll_formula_unknown_variable", "path": f"components.{row.code}.formula", "message": f"Unknown formula variable(s): {', '.join(unknown)}", "remediation": "Define the variable in Formula context or correct the expression."})
    others = (await db.execute(select(SalaryStructure).where(SalaryStructure.organization_id == actor.organization_id, SalaryStructure.id != structure.id, SalaryStructure.code == structure.code, SalaryStructure.status.in_(("published", "active")), (SalaryStructure.superseded_on.is_(None) | (SalaryStructure.superseded_on > structure.effective_from))))).scalars().all()
    if any(row.effective_from <= (structure.effective_to or date.max) and (row.effective_to is None or row.effective_to >= structure.effective_from) for row in others):
        raise HTTPException(status_code=409, detail={"code": "payroll_salary_structure_effective_overlap"})
    structure.status = "published"; structure.published_by_account_id = actor.account_id
    from datetime import datetime, timezone
    structure.published_at = datetime.now(timezone.utc)
    version_snapshot = await db.scalar(select(SalaryStructureVersion).where(SalaryStructureVersion.salary_structure_id == structure.id, SalaryStructureVersion.version == structure.version))
    if version_snapshot:
        version_snapshot.status = "published"; version_snapshot.published_by_account_id = actor.account_id; version_snapshot.published_at = structure.published_at
    await record_change(db, actor=actor, topic="payroll", aggregate_type="salary_structure", aggregate_id=structure.id, operation="published", after={"code": structure.code, "version": structure.version})
    await db.commit(); await db.refresh(structure)
    return {"id": structure.id, "code": structure.code, "version": structure.version, "status": structure.status, "checksum": structure.checksum}


@router.put("/salary-structures/{structure_id}")
async def update_structure_route(structure_id: int, data: SalaryStructureInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "administer")
    if any(row.amount_mode == "formula" for row in data.components): await payroll_capability(db, actor, "edit_formula")
    structure = await db.scalar(select(SalaryStructure).where(SalaryStructure.id == structure_id, SalaryStructure.organization_id == actor.organization_id))
    if not structure: raise HTTPException(status_code=404, detail="Salary structure not found")
    if structure.status in {"published", "active"}:
        successor = await bump_salary_structure(db, actor, structure, data.effective_from, data)
        await record_change(db, actor=actor, topic="payroll", aggregate_type="salary_structure", aggregate_id=successor.id, operation="bumped", after={"source_structure_id": structure.id, "version": successor.version})
        await db.commit(); await db.refresh(successor)
        return {"id": successor.id, "code": successor.code, "name": successor.name, "version": successor.version, "status": successor.status, "source_structure_id": structure.id, "checksum": successor.checksum}
    await update_salary_structure(db, actor, structure, data)
    await record_change(db, actor=actor, topic="payroll", aggregate_type="salary_structure", aggregate_id=structure.id, operation="updated", after={"code": structure.code, "version": structure.version, "status": structure.status})
    await db.commit(); await db.refresh(structure)
    return {"id": structure.id, "code": structure.code, "name": structure.name, "version": structure.version, "status": structure.status, "effective_from": structure.effective_from.isoformat(), "effective_to": structure.effective_to.isoformat() if structure.effective_to else None, "currency": structure.currency, "checksum": structure.checksum, "components": [{"code": item.code, "name": item.name, "component_kind": item.component_kind, "formula": item.formula, "proration_basis": item.proration_basis, "is_taxable": item.is_taxable, "is_shi_subject": item.is_shi_subject, "is_non_taxable_allowance": item.is_non_taxable_allowance, "is_flexible_benefit": item.is_flexible_benefit, "max_benefit_amount_yearly": str(item.max_benefit_amount_yearly), "pay_against_benefit_claim": item.pay_against_benefit_claim, "only_tax_impact": item.only_tax_impact, "account_id": item.account_id, "cost_center_id": item.cost_center_id} for item in data.components]}


@router.post("/salary-structures/{structure_id}/bump-version", status_code=status.HTTP_201_CREATED)
async def bump_structure_route(structure_id: int, data: VersionBumpInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "edit_setup")
    structure = await db.scalar(select(SalaryStructure).where(SalaryStructure.id == structure_id, SalaryStructure.organization_id == actor.organization_id))
    if not structure: raise HTTPException(status_code=404, detail="Salary structure not found")
    successor = await bump_salary_structure(db, actor, structure, data.effective_from)
    await record_change(db, actor=actor, topic="payroll", aggregate_type="salary_structure", aggregate_id=successor.id, operation="bumped", after={"source_structure_id": structure.id, "version": successor.version})
    await db.commit(); await db.refresh(successor)
    return {"id": successor.id, "code": successor.code, "name": successor.name, "version": successor.version, "status": successor.status, "source_structure_id": structure.id, "effective_from": successor.effective_from.isoformat(), "checksum": successor.checksum}


@router.post("/salary-structures/{structure_id}/clone", status_code=status.HTTP_201_CREATED)
async def clone_salary_structure(structure_id: int, effective_from: date, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "edit_setup")
    source = await db.scalar(select(SalaryStructure).where(SalaryStructure.id == structure_id, SalaryStructure.organization_id == actor.organization_id))
    if not source:
        raise HTTPException(status_code=404, detail="Salary structure not found")
    components = (await db.execute(select(SalaryComponent).where(SalaryComponent.salary_structure_id == source.id).order_by(SalaryComponent.position))).scalars().all()
    clone_data = SalaryStructureInput.model_validate({"code": source.code, "name": source.name, "effective_from": effective_from, "effective_to": None, "currency": source.currency, "components": [{"component_master_id": row.component_master_id, "code": row.code, "name": row.name, "component_kind": row.component_kind, "formula": row.formula, "proration_basis": row.proration_basis, "is_taxable": row.is_taxable, "is_shi_subject": row.is_shi_subject, "is_non_taxable_allowance": row.is_non_taxable_allowance, "is_leave_average_eligible": row.is_leave_average_eligible, "is_flexible_benefit": row.is_flexible_benefit, "max_benefit_amount_yearly": row.max_benefit_amount_yearly, "pay_against_benefit_claim": row.pay_against_benefit_claim, "only_tax_impact": row.only_tax_impact, "payer": row.payer, "position": row.position, "account_id": row.account_id, "cost_center_id": row.cost_center_id, "metadata_json": row.metadata_json} for row in components]})
    clone = await create_salary_structure(db, actor, clone_data)
    clone.source_structure_id = source.id
    await record_change(db, actor=actor, topic="payroll", aggregate_type="salary_structure", aggregate_id=clone.id, operation="cloned", after={"source_structure_id": source.id, "effective_from": effective_from.isoformat()})
    await db.commit(); await db.refresh(clone)
    return {"id": clone.id, "code": clone.code, "version": clone.version, "status": clone.status, "source_structure_id": source.id, "effective_from": clone.effective_from.isoformat()}


@router.post("/salary-structures/{structure_id}/archive")
async def archive_salary_structure(structure_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "edit_setup")
    structure = await db.scalar(select(SalaryStructure).where(SalaryStructure.id == structure_id, SalaryStructure.organization_id == actor.organization_id).with_for_update())
    if not structure:
        raise HTTPException(status_code=404, detail="Salary structure not found")
    if structure.status in {"published", "active"}:
        raise HTTPException(status_code=409, detail={"code": "payroll_salary_structure_immutable", "allowed_actions": ["bump_version", "clone"]})
    elif structure.status != "archived":
        raise HTTPException(status_code=409, detail={"code": "payroll_salary_structure_not_published"})
    await record_change(db, actor=actor, topic="payroll", aggregate_type="salary_structure", aggregate_id=structure.id, operation="archived", after={"status": structure.status})
    await db.commit(); await db.refresh(structure)
    return {"id": structure.id, "status": structure.status}


@router.get("/salary-structures/{structure_id}/preview")
async def preview_salary_structure(structure_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "view_salary")
    structure = await db.scalar(select(SalaryStructure).where(SalaryStructure.id == structure_id, SalaryStructure.organization_id == actor.organization_id))
    if not structure:
        raise HTTPException(status_code=404, detail="Salary structure not found")
    components = (await db.execute(select(SalaryComponent).where(SalaryComponent.salary_structure_id == structure.id).order_by(SalaryComponent.position))).scalars().all()
    return {"id": structure.id, "code": structure.code, "version": structure.version, "status": structure.status, "effective_from": structure.effective_from.isoformat(), "components": [{"code": row.code, "formula": row.formula, "kind": row.component_kind, "proration_basis": row.proration_basis, "account_id": row.account_id, "cost_center_id": row.cost_center_id} for row in components]}


@router.delete("/salary-structures/{structure_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_structure_route(structure_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "administer")
    structure = await db.scalar(select(SalaryStructure).where(SalaryStructure.id == structure_id, SalaryStructure.organization_id == actor.organization_id))
    if not structure: raise HTTPException(status_code=404, detail="Salary structure not found")
    await delete_salary_structure(db, actor, structure)
    await record_change(db, actor=actor, topic="payroll", aggregate_type="salary_structure", aggregate_id=structure_id, operation="deleted", after={"structure_id": structure_id})
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/employee-profiles")
async def list_employee_payroll_profiles(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "view")
    profiles = (await db.execute(select(EmployeePayrollProfile).where(EmployeePayrollProfile.organization_id == actor.organization_id).order_by(EmployeePayrollProfile.employee_id, EmployeePayrollProfile.effective_from.desc()))).scalars().all()
    return [{"id": profile.id, "employee_id": profile.employee_id, "salary_structure_id": profile.salary_structure_id, "effective_from": profile.effective_from.isoformat(), "effective_to": profile.effective_to.isoformat() if profile.effective_to else None, "base_salary": str(profile.base_salary), "insured_category": profile.insured_category, "hazard_class": profile.hazard_class, "payment_method": profile.payment_method} for profile in profiles]


@router.post("/employees/{employee_id}/profile", status_code=status.HTTP_201_CREATED)
async def save_employee_profile(employee_id: int, data: EmployeePayrollInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "administer")
    if data.employee_id != employee_id: raise HTTPException(status_code=422, detail={"code": "payroll_employee_id_mismatch"})
    profile = await create_employee_profile(db, actor, employee_id, data)
    await record_change(db, actor=actor, topic="payroll", aggregate_type="employee_payroll_profile", aggregate_id=profile.id, operation="created", after={"employee_id": employee_id, "salary_structure_id": profile.salary_structure_id, "effective_from": profile.effective_from.isoformat()})
    await db.commit(); await db.refresh(profile)
    return {"id": profile.id, "employee_id": profile.employee_id, "salary_structure_id": profile.salary_structure_id, "effective_from": profile.effective_from.isoformat(), "base_salary": str(profile.base_salary), "insured_category": profile.insured_category, "hazard_class": profile.hazard_class, "residency_status": profile.residency_status, "tax_relief_eligibility": profile.tax_relief_eligibility, "payment_method": profile.payment_method}


@router.get("/employees/{employee_id}/profile")
async def get_employee_profile(employee_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "administer")
    profile = await db.scalar(select(EmployeePayrollProfile).where(EmployeePayrollProfile.organization_id == actor.organization_id, EmployeePayrollProfile.employee_id == employee_id).order_by(EmployeePayrollProfile.effective_from.desc()).limit(1))
    if not profile: raise HTTPException(status_code=404, detail="Employee payroll profile not found")
    return {"id": profile.id, "employee_id": profile.employee_id, "salary_structure_id": profile.salary_structure_id, "effective_from": profile.effective_from.isoformat(), "effective_to": profile.effective_to.isoformat() if profile.effective_to else None, "base_salary": str(profile.base_salary), "insured_category": profile.insured_category, "hazard_class": profile.hazard_class, "residency_status": profile.residency_status, "tax_relief_eligibility": profile.tax_relief_eligibility, "exemption_flags": profile.exemption_flags, "payment_method": profile.payment_method}


@router.post("/employees/{employee_id}/salary-assignment/revise", status_code=status.HTTP_201_CREATED)
async def revise_employee_salary_assignment(employee_id: int, data: EmployeePayrollInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    # The service closes/validates effective-dated assignments and creates a
    # linked revision while bank history remains attached to Employee.
    return await save_employee_profile(employee_id, data, db, actor)


@router.post("/employees/{employee_id}/bank-account", status_code=status.HTTP_201_CREATED)
async def save_bank_account(employee_id: int, data: BankAccountInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "administer")
    account = await create_bank_account(db, actor, employee_id, data)
    await record_change(db, actor=actor, topic="payroll", aggregate_type="employee_bank_account", aggregate_id=account.id, operation="created", after={"employee_id": employee_id, "bank_code": account.bank_code, "account_last4": account.account_last4, "is_primary": account.is_primary})
    await db.commit(); await db.refresh(account)
    return {"id": account.id, "bank_code": account.bank_code, "account_last4": account.account_last4, "is_primary": account.is_primary, "valid_from": account.valid_from.isoformat(), "valid_to": account.valid_to.isoformat() if account.valid_to else None}


@router.get("/employees/{employee_id}/bank-accounts")
async def list_employee_bank_accounts(employee_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "administer")
    employee = await db.scalar(select(Employee).where(Employee.id == employee_id, Employee.organization_id == actor.organization_id))
    if not employee: raise HTTPException(status_code=404, detail="Employee not found")
    accounts = (await db.execute(select(EmployeeBankAccount).where(EmployeeBankAccount.employee_id == employee_id).order_by(EmployeeBankAccount.is_primary.desc(), EmployeeBankAccount.valid_from.desc()))).scalars().all()
    return [{"id": account.id, "bank_code": account.bank_code, "account_last4": account.account_last4, "is_primary": account.is_primary, "valid_from": account.valid_from.isoformat(), "valid_to": account.valid_to.isoformat() if account.valid_to else None} for account in accounts]


@router.get("/tax-benefits/exemption-categories")
async def list_tax_exemption_categories(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    rows = (await db.execute(select(PayrollTaxExemptionCategory).where(PayrollTaxExemptionCategory.organization_id == actor.organization_id).order_by(PayrollTaxExemptionCategory.code))).scalars().all()
    return [{"id": row.id, "code": row.code, "name": row.name, "treatment": row.treatment, "annual_limit": str(row.annual_limit), "requires_proof": row.requires_proof, "is_active": row.is_active} for row in rows]


@router.get("/tax-benefits/flexible-components")
async def list_flexible_benefit_components(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    rows = (await db.execute(select(SalaryComponent, SalaryStructure).join(SalaryStructure, SalaryStructure.id == SalaryComponent.salary_structure_id).where(SalaryStructure.organization_id == actor.organization_id, SalaryStructure.status.in_(("published", "active")), SalaryComponent.is_flexible_benefit.is_(True)).order_by(SalaryStructure.name, SalaryComponent.name))).all()
    return [{"id": component.id, "name": component.name, "code": component.code, "structure": structure.name, "max_benefit_amount_yearly": str(component.max_benefit_amount_yearly), "pay_against_benefit_claim": component.pay_against_benefit_claim, "only_tax_impact": component.only_tax_impact} for component, structure in rows]


@router.post("/tax-benefits/exemption-categories", status_code=status.HTTP_201_CREATED)
async def create_tax_exemption_category(data: TaxExemptionCategoryInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "administer")
    row = PayrollTaxExemptionCategory(organization_id=actor.organization_id, **data.model_dump(), created_by_account_id=actor.account_id)
    db.add(row); await db.flush()
    await record_change(db, actor=actor, topic="payroll", aggregate_type="tax_exemption_category", aggregate_id=row.id, operation="created", after={"code": row.code, "treatment": row.treatment})
    await db.commit(); await db.refresh(row)
    return {"id": row.id, "code": row.code, "name": row.name, "treatment": row.treatment, "annual_limit": str(row.annual_limit), "requires_proof": row.requires_proof, "is_active": row.is_active}


@router.put("/tax-benefits/exemption-categories/{category_id}")
async def update_tax_exemption_category(category_id: int, data: TaxExemptionCategoryUpdateInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "administer")
    row = await db.scalar(select(PayrollTaxExemptionCategory).where(PayrollTaxExemptionCategory.id == category_id, PayrollTaxExemptionCategory.organization_id == actor.organization_id).with_for_update())
    if not row:
        raise HTTPException(status_code=404, detail="Tax exemption category not found")
    row.code = data.code; row.name = data.name; row.treatment = data.treatment; row.annual_limit = data.annual_limit; row.requires_proof = data.requires_proof; row.is_active = data.is_active
    await record_change(db, actor=actor, topic="payroll", aggregate_type="tax_exemption_category", aggregate_id=row.id, operation="updated", after={"code": row.code, "is_active": row.is_active})
    await db.commit(); await db.refresh(row)
    return {"id": row.id, "code": row.code, "name": row.name, "treatment": row.treatment, "annual_limit": str(row.annual_limit), "requires_proof": row.requires_proof, "is_active": row.is_active}


@router.get("/tax-benefits/declarations")
async def list_tax_declarations(tax_year: int | None = None, employee_id: int | None = None, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    scoped_employee = await _employee_scope(db, actor, employee_id)
    query = select(EmployeeTaxExemptionDeclaration).where(EmployeeTaxExemptionDeclaration.organization_id == actor.organization_id)
    if scoped_employee is not None: query = query.where(EmployeeTaxExemptionDeclaration.employee_id == scoped_employee)
    if tax_year is not None: query = query.where(EmployeeTaxExemptionDeclaration.tax_year == tax_year)
    rows = (await db.execute(query.order_by(EmployeeTaxExemptionDeclaration.tax_year.desc(), EmployeeTaxExemptionDeclaration.id.desc()))).scalars().all()
    return [_declaration_out(row) for row in rows]


@router.post("/tax-benefits/declarations", status_code=status.HTTP_201_CREATED)
async def create_tax_declaration(data: TaxDeclarationInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    employee_id = await _employee_scope(db, actor, data.employee_id)
    if employee_id is None: raise HTTPException(status_code=422, detail={"code": "payroll_employee_required"})
    category = await db.scalar(select(PayrollTaxExemptionCategory).where(PayrollTaxExemptionCategory.id == data.category_id, PayrollTaxExemptionCategory.organization_id == actor.organization_id, PayrollTaxExemptionCategory.is_active.is_(True)))
    if not category: raise HTTPException(status_code=404, detail="Tax exemption category not found")
    if Decimal(str(category.annual_limit)) > 0 and data.declared_amount > Decimal(str(category.annual_limit)):
        raise HTTPException(status_code=422, detail={"code": "payroll_tax_declaration_exceeds_limit", "annual_limit": str(category.annual_limit)})
    profile = await db.scalar(select(EmployeePayrollProfile.id).where(EmployeePayrollProfile.organization_id == actor.organization_id, EmployeePayrollProfile.employee_id == employee_id).limit(1))
    if not profile: raise HTTPException(status_code=404, detail="Employee payroll profile not found")
    row = EmployeeTaxExemptionDeclaration(organization_id=actor.organization_id, employee_id=employee_id, category_id=data.category_id, tax_year=data.tax_year, declared_amount=data.declared_amount, note=data.note, created_by_account_id=actor.account_id)
    db.add(row); await db.flush(); await db.commit(); await db.refresh(row)
    return _declaration_out(row)


@router.post("/tax-benefits/declarations/{declaration_id}/submit")
async def submit_tax_declaration(declaration_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    row = await db.scalar(select(EmployeeTaxExemptionDeclaration).where(EmployeeTaxExemptionDeclaration.id == declaration_id, EmployeeTaxExemptionDeclaration.organization_id == actor.organization_id).with_for_update())
    if not row: raise HTTPException(status_code=404, detail="Tax declaration not found")
    await _employee_scope(db, actor, row.employee_id)
    if row.status != "draft": raise HTTPException(status_code=409, detail={"code": "payroll_tax_declaration_not_draft"})
    row.status = "submitted"; row.submitted_at = datetime.now(timezone.utc)
    await db.commit(); await db.refresh(row); return _declaration_out(row)


@router.post("/tax-benefits/declarations/{declaration_id}/review")
async def review_tax_declaration(declaration_id: int, data: ReviewDecisionInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "approve")
    row = await db.scalar(select(EmployeeTaxExemptionDeclaration).where(EmployeeTaxExemptionDeclaration.id == declaration_id, EmployeeTaxExemptionDeclaration.organization_id == actor.organization_id).with_for_update())
    if not row: raise HTTPException(status_code=404, detail="Tax declaration not found")
    if row.status != "submitted": raise HTTPException(status_code=409, detail={"code": "payroll_tax_declaration_not_submitted"})
    row.status = "approved" if data.approve else "rejected"; row.reviewed_by_account_id = actor.account_id; row.reviewed_at = datetime.now(timezone.utc)
    await record_change(db, actor=actor, topic="payroll", aggregate_type="tax_exemption_declaration", aggregate_id=row.id, operation=row.status, after={"employee_id": row.employee_id, "tax_year": row.tax_year})
    await db.commit(); await db.refresh(row); return _declaration_out(row)


@router.get("/tax-benefits/proofs")
async def list_tax_proofs(declaration_id: int | None = None, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    query = select(EmployeeTaxExemptionProof, EmployeeTaxExemptionDeclaration).join(EmployeeTaxExemptionDeclaration, EmployeeTaxExemptionDeclaration.id == EmployeeTaxExemptionProof.declaration_id).where(EmployeeTaxExemptionProof.organization_id == actor.organization_id)
    if declaration_id is not None: query = query.where(EmployeeTaxExemptionProof.declaration_id == declaration_id)
    rows = (await db.execute(query.order_by(EmployeeTaxExemptionProof.id.desc()))).all()
    if not _is_payroll_admin(actor):
        if actor.employee_id is None: return []
        rows = [(proof, declaration) for proof, declaration in rows if declaration.employee_id == actor.employee_id]
    else:
        await payroll_capability(db, actor, "view")
    return [{"id": proof.id, "declaration_id": proof.declaration_id, "amount": str(proof.amount), "reference": proof.reference, "status": proof.status} for proof, _ in rows]


@router.post("/tax-benefits/declarations/{declaration_id}/proofs", status_code=status.HTTP_201_CREATED)
async def create_tax_proof(declaration_id: int, data: TaxProofInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    declaration = await db.scalar(select(EmployeeTaxExemptionDeclaration).where(EmployeeTaxExemptionDeclaration.id == declaration_id, EmployeeTaxExemptionDeclaration.organization_id == actor.organization_id))
    if not declaration: raise HTTPException(status_code=404, detail="Tax declaration not found")
    await _employee_scope(db, actor, declaration.employee_id)
    if declaration.status not in {"submitted", "approved"}: raise HTTPException(status_code=409, detail={"code": "payroll_tax_declaration_not_submitted"})
    existing = await db.scalar(select(func.coalesce(func.sum(EmployeeTaxExemptionProof.amount), 0)).where(EmployeeTaxExemptionProof.declaration_id == declaration.id, EmployeeTaxExemptionProof.status.in_(("submitted", "approved"))))
    if Decimal(str(existing or 0)) + data.amount > Decimal(str(declaration.declared_amount)):
        raise HTTPException(status_code=422, detail={"code": "payroll_tax_proof_exceeds_declaration"})
    proof = EmployeeTaxExemptionProof(organization_id=actor.organization_id, declaration_id=declaration.id, **data.model_dump(), created_by_account_id=actor.account_id)
    db.add(proof); await db.flush(); await db.commit(); await db.refresh(proof)
    return {"id": proof.id, "declaration_id": proof.declaration_id, "amount": str(proof.amount), "reference": proof.reference, "status": proof.status}


@router.post("/tax-benefits/proofs/{proof_id}/review")
async def review_tax_proof(proof_id: int, data: ReviewDecisionInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "approve")
    proof = await db.scalar(select(EmployeeTaxExemptionProof).where(EmployeeTaxExemptionProof.id == proof_id, EmployeeTaxExemptionProof.organization_id == actor.organization_id).with_for_update())
    if not proof: raise HTTPException(status_code=404, detail="Tax proof not found")
    if proof.status != "submitted": raise HTTPException(status_code=409, detail={"code": "payroll_tax_proof_not_submitted"})
    proof.status = "approved" if data.approve else "rejected"; proof.reviewed_by_account_id = actor.account_id; proof.reviewed_at = datetime.now(timezone.utc)
    await db.commit(); await db.refresh(proof)
    return {"id": proof.id, "declaration_id": proof.declaration_id, "amount": str(proof.amount), "reference": proof.reference, "status": proof.status}


@router.get("/tax-benefits/benefit-applications")
async def list_benefit_applications(tax_year: int | None = None, employee_id: int | None = None, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    scoped_employee = await _employee_scope(db, actor, employee_id)
    query = select(EmployeeBenefitApplication).where(EmployeeBenefitApplication.organization_id == actor.organization_id)
    if scoped_employee is not None: query = query.where(EmployeeBenefitApplication.employee_id == scoped_employee)
    if tax_year is not None: query = query.where(EmployeeBenefitApplication.tax_year == tax_year)
    rows = (await db.execute(query.order_by(EmployeeBenefitApplication.tax_year.desc(), EmployeeBenefitApplication.id.desc()))).scalars().all()
    return [_benefit_application_out(row) for row in rows]


@router.post("/tax-benefits/benefit-applications", status_code=status.HTTP_201_CREATED)
async def create_benefit_application(data: BenefitApplicationInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    employee_id = await _employee_scope(db, actor, data.employee_id)
    if employee_id is None: raise HTTPException(status_code=422, detail={"code": "payroll_employee_required"})
    component = await db.scalar(select(SalaryComponent).join(SalaryStructure, SalaryStructure.id == SalaryComponent.salary_structure_id).where(SalaryComponent.id == data.salary_component_id, SalaryStructure.organization_id == actor.organization_id, SalaryComponent.is_flexible_benefit.is_(True)))
    if not component: raise HTTPException(status_code=404, detail="Flexible benefit component not found")
    assigned = await db.scalar(select(EmployeePayrollProfile.id).where(EmployeePayrollProfile.organization_id == actor.organization_id, EmployeePayrollProfile.employee_id == employee_id, EmployeePayrollProfile.salary_structure_id == component.salary_structure_id, EmployeePayrollProfile.effective_from <= date(data.tax_year, 12, 31), (EmployeePayrollProfile.effective_to.is_(None) | (EmployeePayrollProfile.effective_to >= date(data.tax_year, 1, 1)))).limit(1))
    if not assigned: raise HTTPException(status_code=422, detail={"code": "payroll_benefit_component_not_assigned"})
    if Decimal(str(component.max_benefit_amount_yearly)) > 0 and data.requested_amount > Decimal(str(component.max_benefit_amount_yearly)):
        raise HTTPException(status_code=422, detail={"code": "payroll_benefit_application_exceeds_limit", "annual_limit": str(component.max_benefit_amount_yearly)})
    row = EmployeeBenefitApplication(organization_id=actor.organization_id, employee_id=employee_id, salary_component_id=component.id, tax_year=data.tax_year, requested_amount=data.requested_amount, note=data.note, created_by_account_id=actor.account_id)
    db.add(row); await db.flush(); await db.commit(); await db.refresh(row); return _benefit_application_out(row)


@router.post("/tax-benefits/benefit-applications/{application_id}/submit")
async def submit_benefit_application(application_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    row = await db.scalar(select(EmployeeBenefitApplication).where(EmployeeBenefitApplication.id == application_id, EmployeeBenefitApplication.organization_id == actor.organization_id).with_for_update())
    if not row: raise HTTPException(status_code=404, detail="Benefit application not found")
    await _employee_scope(db, actor, row.employee_id)
    if row.status != "draft": raise HTTPException(status_code=409, detail={"code": "payroll_benefit_application_not_draft"})
    row.status = "submitted"; row.submitted_at = datetime.now(timezone.utc)
    await db.commit(); await db.refresh(row); return _benefit_application_out(row)


@router.post("/tax-benefits/benefit-applications/{application_id}/review")
async def review_benefit_application(application_id: int, data: BenefitApplicationReviewInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "approve")
    row = await db.scalar(select(EmployeeBenefitApplication).where(EmployeeBenefitApplication.id == application_id, EmployeeBenefitApplication.organization_id == actor.organization_id).with_for_update())
    if not row: raise HTTPException(status_code=404, detail="Benefit application not found")
    if row.status != "submitted": raise HTTPException(status_code=409, detail={"code": "payroll_benefit_application_not_submitted"})
    if data.approve and data.approved_amount > row.requested_amount: raise HTTPException(status_code=422, detail={"code": "payroll_benefit_approval_exceeds_request"})
    row.status = "approved" if data.approve else "rejected"; row.approved_amount = data.approved_amount if data.approve else Decimal("0"); row.reviewed_by_account_id = actor.account_id; row.reviewed_at = datetime.now(timezone.utc)
    await record_change(db, actor=actor, topic="payroll", aggregate_type="employee_benefit_application", aggregate_id=row.id, operation=row.status, after={"employee_id": row.employee_id, "approved_amount": str(row.approved_amount)})
    await db.commit(); await db.refresh(row); return _benefit_application_out(row)


@router.get("/tax-benefits/benefit-claims")
async def list_benefit_claims(employee_id: int | None = None, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    scoped_employee = await _employee_scope(db, actor, employee_id)
    query = select(EmployeeBenefitClaim).join(EmployeeBenefitApplication, EmployeeBenefitApplication.id == EmployeeBenefitClaim.application_id).where(EmployeeBenefitClaim.organization_id == actor.organization_id)
    if scoped_employee is not None: query = query.where(EmployeeBenefitApplication.employee_id == scoped_employee)
    rows = (await db.execute(query.order_by(EmployeeBenefitClaim.claim_date.desc(), EmployeeBenefitClaim.id.desc()))).scalars().all()
    return [_benefit_claim_out(row) for row in rows]


@router.post("/tax-benefits/benefit-claims", status_code=status.HTTP_201_CREATED)
async def create_benefit_claim(data: BenefitClaimInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    application = await db.scalar(select(EmployeeBenefitApplication).where(EmployeeBenefitApplication.id == data.application_id, EmployeeBenefitApplication.organization_id == actor.organization_id).with_for_update())
    if not application: raise HTTPException(status_code=404, detail="Benefit application not found")
    await _employee_scope(db, actor, application.employee_id)
    if application.status != "approved": raise HTTPException(status_code=409, detail={"code": "payroll_benefit_application_not_approved"})
    component = await db.get(SalaryComponent, application.salary_component_id)
    if not component or not component.pay_against_benefit_claim:
        raise HTTPException(status_code=409, detail={"code": "payroll_benefit_not_claim_based"})
    if data.claim_date.year != application.tax_year: raise HTTPException(status_code=422, detail={"code": "payroll_benefit_claim_year_mismatch"})
    await validate_claim_balance(db, application, data.amount)
    claim = EmployeeBenefitClaim(organization_id=actor.organization_id, application_id=application.id, **data.model_dump(exclude={"application_id"}), created_by_account_id=actor.account_id)
    db.add(claim); await db.flush(); await db.commit(); await db.refresh(claim); return _benefit_claim_out(claim)


@router.post("/tax-benefits/benefit-claims/{claim_id}/review")
async def review_benefit_claim(claim_id: int, data: ReviewDecisionInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "approve")
    claim = await db.scalar(select(EmployeeBenefitClaim).where(EmployeeBenefitClaim.id == claim_id, EmployeeBenefitClaim.organization_id == actor.organization_id).with_for_update())
    if not claim: raise HTTPException(status_code=404, detail="Benefit claim not found")
    if claim.status != "submitted": raise HTTPException(status_code=409, detail={"code": "payroll_benefit_claim_not_submitted"})
    application = await db.get(EmployeeBenefitApplication, claim.application_id)
    if data.approve: await validate_claim_balance(db, application, Decimal(str(claim.amount)))
    claim.status = "approved" if data.approve else "rejected"; claim.reviewed_by_account_id = actor.account_id; claim.reviewed_at = datetime.now(timezone.utc)
    await record_change(db, actor=actor, topic="payroll", aggregate_type="employee_benefit_claim", aggregate_id=claim.id, operation=claim.status, after={"application_id": claim.application_id, "amount": str(claim.amount)})
    await db.commit(); await db.refresh(claim); return _benefit_claim_out(claim)


@router.get("/tax-benefits/reports/income-tax-computation")
async def income_tax_computation(tax_year: int, employee_id: int | None = None, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    scoped_employee = await _employee_scope(db, actor, employee_id)
    query = select(Payslip).join(PayrollRun, PayrollRun.id == Payslip.payroll_run_id).where(Payslip.organization_id == actor.organization_id, PayrollRun.tax_point_date >= date(tax_year, 1, 1), PayrollRun.tax_point_date < date(tax_year + 1, 1, 1), PayrollRun.status.in_(("calculated", "in_review", "approved", "posted", "paid")), PayrollRun.run_type != "advance")
    if scoped_employee is not None: query = query.where(Payslip.employee_id == scoped_employee)
    slips = (await db.execute(query.order_by(Payslip.employee_id, PayrollRun.tax_point_date))).scalars().all()
    totals: dict[int, dict[str, Decimal]] = {}
    for slip in slips:
        row = totals.setdefault(slip.employee_id, {"gross": Decimal("0"), "taxable_income": Decimal("0"), "employee_shi": Decimal("0"), "pit_relief": Decimal("0"), "pit": Decimal("0")})
        for key in row: row[key] += Decimal(str(getattr(slip, key)))
    result = []
    for item_employee_id, values in totals.items():
        adjustments = await approved_tax_adjustments(db, organization_id=actor.organization_id, employee_id=item_employee_id, tax_year=tax_year)
        result.append({"employee_id": item_employee_id, **{key: str(value) for key, value in values.items()}, "approved_tax_deduction": str(adjustments["deduction"]), "approved_tax_credit": str(adjustments["credit"])})
    return {"tax_year": tax_year, "rows": result}


@router.get("/posting-profiles/default")
async def get_posting_profile(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "view")
    row = await db.scalar(select(PayrollPostingProfile).where(PayrollPostingProfile.organization_id == actor.organization_id, PayrollPostingProfile.code == "default", PayrollPostingProfile.is_active.is_(True)))
    if not row:
        return None
    return {"id": row.id, "code": row.code, "account_roles": row.account_roles, "is_active": row.is_active}


@router.put("/posting-profiles/default")
async def save_posting_profile(data: PostingProfileInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "administer")
    accounts = (await db.execute(select(ERPAccount.id).where(ERPAccount.organization_id == actor.organization_id, ERPAccount.id.in_(list(data.account_roles.values()))))).scalars().all()
    if len(accounts) != len(set(data.account_roles.values())): raise HTTPException(status_code=422, detail={"code": "payroll_posting_account_invalid"})
    row = await db.scalar(select(PayrollPostingProfile).where(PayrollPostingProfile.organization_id == actor.organization_id, PayrollPostingProfile.code == "default"))
    if row: row.account_roles = data.account_roles; row.is_active = True
    else: row = PayrollPostingProfile(organization_id=actor.organization_id, code="default", account_roles=data.account_roles); db.add(row)
    await db.flush()
    await record_change(db, actor=actor, topic="payroll", aggregate_type="payroll_posting_profile", aggregate_id=row.id, operation="upserted", after={"code": row.code, "account_role_keys": sorted(row.account_roles)})
    await db.commit(); await db.refresh(row); return {"id": row.id, "code": row.code, "account_roles": row.account_roles, "is_active": row.is_active}


@router.get("/bank-export-profiles")
async def list_bank_export_profiles(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "view")
    rows = list((await db.execute(select(PayrollBankExportProfile).where(PayrollBankExportProfile.organization_id == actor.organization_id).order_by(PayrollBankExportProfile.bank_code, PayrollBankExportProfile.version.desc()))).scalars().all())
    return [{"id": row.id, "bank_code": row.bank_code, "version": row.version, "status": row.status, "format": row.format, "template": row.template, "is_provisional": row.is_provisional} for row in rows]


@router.post("/bank-export-profiles", status_code=status.HTTP_201_CREATED)
async def save_bank_export_profile(data: BankExportProfileInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "administer")
    values = data.model_dump()
    values["is_provisional"] = True
    values["template"] = {key: value for key, value in values["template"].items() if key != "validation"}
    row = PayrollBankExportProfile(organization_id=actor.organization_id, **values); db.add(row); await db.flush()
    await record_change(db, actor=actor, topic="payroll", aggregate_type="payroll_bank_export_profile", aggregate_id=row.id, operation="created", after={"bank_code": row.bank_code, "version": row.version, "format": row.format, "is_provisional": row.is_provisional})
    await db.commit(); await db.refresh(row)
    return {"id": row.id, "bank_code": row.bank_code, "version": row.version, "status": row.status, "format": row.format, "is_provisional": row.is_provisional}


@router.put("/bank-export-profiles/{profile_id}")
async def update_bank_export_profile(profile_id: int, data: BankExportProfileInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "administer")
    row = await db.scalar(select(PayrollBankExportProfile).where(PayrollBankExportProfile.id == profile_id, PayrollBankExportProfile.organization_id == actor.organization_id).with_for_update())
    if not row: raise HTTPException(status_code=404, detail="Bank export profile not found")
    if row.status != "draft": raise HTTPException(status_code=409, detail={"code": "payroll_bank_template_immutable"})
    values = data.model_dump()
    values["is_provisional"] = True
    values["template"] = {key: value for key, value in values["template"].items() if key != "validation"}
    for key, value in values.items(): setattr(row, key, value)
    await record_change(db, actor=actor, topic="payroll", aggregate_type="payroll_bank_export_profile", aggregate_id=row.id, operation="updated", after={"bank_code": row.bank_code, "version": row.version})
    await db.commit(); await db.refresh(row)
    return {"id": row.id, "bank_code": row.bank_code, "version": row.version, "status": row.status, "format": row.format, "is_provisional": row.is_provisional}


@router.delete("/bank-export-profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bank_export_profile(profile_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "administer")
    row = await db.scalar(select(PayrollBankExportProfile).where(PayrollBankExportProfile.id == profile_id, PayrollBankExportProfile.organization_id == actor.organization_id).with_for_update())
    if not row: raise HTTPException(status_code=404, detail="Bank export profile not found")
    if row.status != "draft": raise HTTPException(status_code=409, detail={"code": "payroll_bank_template_immutable"})
    await db.delete(row); await record_change(db, actor=actor, topic="payroll", aggregate_type="payroll_bank_export_profile", aggregate_id=profile_id, operation="deleted", after={"profile_id": profile_id}); await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/bank-export-profiles/{profile_id}/validate-sample")
async def validate_bank_export_sample(profile_id: int, data: BankTemplateSampleInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "approve")
    row = await db.scalar(select(PayrollBankExportProfile).where(PayrollBankExportProfile.id == profile_id, PayrollBankExportProfile.organization_id == actor.organization_id).with_for_update())
    if not row: raise HTTPException(status_code=404, detail="Bank export profile not found")
    if row.status != "draft": raise HTTPException(status_code=409, detail={"code": "payroll_bank_template_immutable"})
    try:
        expected = base64.b64decode(data.expected_content_base64, validate=True)
        _, actual = render_bank_export(data.sample_rows, row.template, row.format)
    except (binascii.Error, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(status_code=422, detail={"code": "payroll_bank_template_sample_invalid"}) from exc
    if not expected or actual != expected:
        raise HTTPException(status_code=422, detail={"code": "payroll_bank_template_sample_mismatch", "message": "The rendered layout does not match the bank-issued sample."})
    checksum = hashlib.sha256(expected).hexdigest()
    row.template = {**row.template, "validation": {"bank_sample_checksum": checksum, "golden_file_passed": True, "bank_sample_reference": data.bank_sample_reference}}
    row.is_provisional = False
    await record_change(db, actor=actor, topic="payroll", aggregate_type="payroll_bank_export_profile", aggregate_id=row.id, operation="sample_validated", after={"sample_checksum": checksum, "bank_sample_reference": data.bank_sample_reference})
    await db.commit()
    return {"id": row.id, "is_provisional": False, "sample_checksum": checksum}


@router.post("/bank-export-profiles/{profile_id}/publish")
async def publish_bank_export_profile(profile_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "approve")
    row = await db.scalar(select(PayrollBankExportProfile).where(PayrollBankExportProfile.id == profile_id, PayrollBankExportProfile.organization_id == actor.organization_id))
    if not row: raise HTTPException(status_code=404, detail="Bank export profile not found")
    columns = row.template.get("columns") if isinstance(row.template, dict) else None
    if not columns or not isinstance(columns, list) or any(not isinstance(column, dict) or not isinstance(column.get("key"), str) or not column["key"] for column in columns):
        raise HTTPException(status_code=422, detail={"code": "payroll_bank_template_columns_required"})
    if len({column["key"] for column in columns}) != len(columns):
        raise HTTPException(status_code=422, detail={"code": "payroll_bank_template_duplicate_column"})
    validation = row.template.get("validation") if isinstance(row.template, dict) else None
    if row.is_provisional or not isinstance(validation, dict) or not validation.get("bank_sample_checksum") or validation.get("golden_file_passed") is not True:
        raise HTTPException(status_code=409, detail={"code": "payroll_bank_template_requires_verified_sample", "message": "A bank-issued sample and passing golden-file validation are required before publication."})
    row.status = "published"
    await record_change(db, actor=actor, topic="payroll", aggregate_type="payroll_bank_export_profile", aggregate_id=row.id, operation="published", after={"bank_code": row.bank_code, "version": row.version, "is_provisional": row.is_provisional})
    await db.commit(); await db.refresh(row)
    return {"id": row.id, "bank_code": row.bank_code, "version": row.version, "status": row.status, "format": row.format, "is_provisional": row.is_provisional}


# ─── Frappe-style document endpoints ───────────────────────────────────────


@router.get("/payroll-periods")
async def list_payroll_periods(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "view")
    rows = (await db.execute(select(PayrollPeriod).where(PayrollPeriod.organization_id == actor.organization_id).order_by(PayrollPeriod.start_date.desc()))).scalars().all()
    return [period_out(row) for row in rows]


@router.post("/payroll-periods", status_code=status.HTTP_201_CREATED)
async def create_payroll_period_route(data: PayrollPeriodInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "administer")
    row = await create_payroll_period(db, actor, data)
    await record_change(db, actor=actor, topic="payroll", aggregate_type="payroll_period", aggregate_id=row.id, operation="created", after={"code": row.code})
    await db.commit(); await db.refresh(row)
    return period_out(row)


@router.put("/payroll-periods/{period_id}")
async def update_payroll_period_route(period_id: int, data: PayrollPeriodInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "administer")
    row = await db.scalar(select(PayrollPeriod).where(PayrollPeriod.id == period_id, PayrollPeriod.organization_id == actor.organization_id).with_for_update())
    if not row: raise HTTPException(status_code=404, detail="Payroll period not found")
    if row.status != "open": raise HTTPException(status_code=409, detail={"code": "payroll_period_immutable"})
    linked = await db.scalar(select(PayrollRun.id).where(PayrollRun.payroll_period_id == row.id).limit(1))
    if linked: raise HTTPException(status_code=409, detail={"code": "payroll_period_referenced"})
    if data.end_date < data.start_date: raise HTTPException(status_code=422, detail={"code": "payroll_invalid_period"})
    duplicate = await db.scalar(select(PayrollPeriod.id).where(PayrollPeriod.organization_id == actor.organization_id, PayrollPeriod.code == data.code, PayrollPeriod.id != row.id))
    if duplicate: raise HTTPException(status_code=409, detail={"code": "payroll_period_exists"})
    profile = await db.scalar(select(StatutoryConfigProfile).where(StatutoryConfigProfile.id == data.statutory_profile_id, StatutoryConfigProfile.organization_id == actor.organization_id))
    if not profile or profile.status not in {"published", "active"} or profile.effective_from > data.start_date or (profile.effective_to and profile.effective_to < data.end_date): raise HTTPException(status_code=404, detail="Statutory profile not found")
    overlap = await db.scalar(select(PayrollPeriod.id).where(PayrollPeriod.organization_id == actor.organization_id, PayrollPeriod.id != row.id, PayrollPeriod.status == "open", PayrollPeriod.start_date <= data.end_date, PayrollPeriod.end_date >= data.start_date))
    if overlap: raise HTTPException(status_code=409, detail={"code": "payroll_period_overlap"})
    row.code = data.code; row.name = data.name; row.start_date = data.start_date; row.end_date = data.end_date; row.tax_year = data.tax_year; row.payroll_frequency = data.payroll_frequency; row.statutory_profile_id = data.statutory_profile_id
    await record_change(db, actor=actor, topic="payroll", aggregate_type="payroll_period", aggregate_id=period_id, operation="updated", after={"code": data.code})
    await db.commit(); await db.refresh(row); return period_out(row)


@router.delete("/payroll-periods/{period_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_payroll_period_route(period_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "administer")
    row = await db.scalar(select(PayrollPeriod).where(PayrollPeriod.id == period_id, PayrollPeriod.organization_id == actor.organization_id).with_for_update())
    if not row: raise HTTPException(status_code=404, detail="Payroll period not found")
    if row.status != "open": raise HTTPException(status_code=409, detail={"code": "payroll_period_immutable"})
    linked = await db.scalar(select(PayrollRun.id).where(PayrollRun.payroll_period_id == row.id).limit(1))
    if linked: raise HTTPException(status_code=409, detail={"code": "payroll_period_referenced"})
    await db.delete(row); await record_change(db, actor=actor, topic="payroll", aggregate_type="payroll_period", aggregate_id=period_id, operation="deleted", after={"period_id": period_id}); await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/salary-components")
async def list_salary_component_masters(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "view")
    rows = (await db.execute(select(PayrollSalaryComponentMaster).where(PayrollSalaryComponentMaster.organization_id == actor.organization_id).order_by(PayrollSalaryComponentMaster.code))).scalars().all()
    return [component_master_out(row) for row in rows]


@router.get("/components/{component_id}/usage")
async def get_salary_component_usage(component_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "view")
    return await component_master_usage(db, actor, component_id)


@router.post("/salary-components", status_code=status.HTTP_201_CREATED)
async def create_salary_component_master_route(data: SalaryComponentMasterInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "administer")
    if data.amount_mode == "formula": await payroll_capability(db, actor, "edit_formula")
    row = await create_component_master(db, actor, data)
    await record_change(db, actor=actor, topic="payroll", aggregate_type="salary_component_master", aggregate_id=row.id, operation="created", after={"code": row.code})
    await db.commit(); await db.refresh(row)
    return component_master_out(row)


@router.put("/salary-components/{component_id}")
async def update_salary_component_master_route(component_id: int, data: SalaryComponentMasterInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "administer")
    if data.amount_mode == "formula": await payroll_capability(db, actor, "edit_formula")
    row = await db.scalar(select(PayrollSalaryComponentMaster).where(PayrollSalaryComponentMaster.id == component_id, PayrollSalaryComponentMaster.organization_id == actor.organization_id))
    if not row:
        raise HTTPException(status_code=404, detail="Salary component not found")
    row = await update_component_master(db, actor, row, data)
    await record_change(db, actor=actor, topic="payroll", aggregate_type="salary_component_master", aggregate_id=row.id, operation="updated", after={"code": row.code})
    await db.commit(); await db.refresh(row)
    return component_master_out(row)


@router.delete("/salary-components/{component_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_salary_component_master_route(component_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "administer")
    row = await db.scalar(select(PayrollSalaryComponentMaster).where(PayrollSalaryComponentMaster.id == component_id, PayrollSalaryComponentMaster.organization_id == actor.organization_id).with_for_update())
    if not row:
        raise HTTPException(status_code=404, detail="Salary component not found")
    await delete_component_master(db, actor, row)
    await record_change(db, actor=actor, topic="payroll", aggregate_type="salary_component_master", aggregate_id=component_id, operation="deleted", after={"component_id": component_id})
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/salary-components/{component_id}/archive")
async def archive_salary_component_master_route(component_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "edit_setup")
    row = await db.scalar(select(PayrollSalaryComponentMaster).where(PayrollSalaryComponentMaster.id == component_id, PayrollSalaryComponentMaster.organization_id == actor.organization_id).with_for_update())
    if not row:
        raise HTTPException(status_code=404, detail="Salary component not found")
    row = await archive_component_master(db, actor, row)
    await record_change(db, actor=actor, topic="payroll", aggregate_type="salary_component_master", aggregate_id=row.id, operation="archived", after={"status": row.status})
    await db.commit(); await db.refresh(row)
    return component_master_out(row)


@router.post("/salary-components/{component_id}/clone", status_code=status.HTTP_201_CREATED)
async def clone_salary_component_master_route(component_id: int, data: SalaryComponentMasterInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "edit_setup")
    if data.amount_mode == "formula": await payroll_capability(db, actor, "edit_formula")
    source = await db.scalar(select(PayrollSalaryComponentMaster).where(PayrollSalaryComponentMaster.id == component_id, PayrollSalaryComponentMaster.organization_id == actor.organization_id))
    if not source:
        raise HTTPException(status_code=404, detail="Salary component not found")
    row = await create_component_master(db, actor, data)
    row.source_salary_component_id = source.source_salary_component_id or source.id
    await record_change(db, actor=actor, topic="payroll", aggregate_type="salary_component_master", aggregate_id=row.id, operation="cloned", after={"source_component_id": source.id})
    await db.commit(); await db.refresh(row)
    return component_master_out(row)


@router.get("/salary-structure-assignments")
async def list_salary_structure_assignments(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "view")
    rows = (await db.execute(select(EmployeePayrollProfile).where(EmployeePayrollProfile.organization_id == actor.organization_id).order_by(EmployeePayrollProfile.effective_from.desc()))).scalars().all()
    return [{"id": row.id, "employee_id": row.employee_id, "salary_structure_id": row.salary_structure_id, "effective_from": row.effective_from.isoformat(), "effective_to": row.effective_to.isoformat() if row.effective_to else None, "base_salary": str(row.base_salary), "payment_method": row.payment_method, "document_status": row.document_status} for row in rows]


@router.post("/salary-structure-assignments", status_code=status.HTTP_201_CREATED)
async def create_salary_structure_assignment_route(data: SalaryStructureAssignmentInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "administer")
    row = await create_assignment(db, actor, data)
    await record_change(db, actor=actor, topic="payroll", aggregate_type="salary_structure_assignment", aggregate_id=row.id, operation="submitted", after={"employee_id": row.employee_id, "salary_structure_id": row.salary_structure_id})
    await db.commit(); await db.refresh(row)
    return {"id": row.id, "employee_id": row.employee_id, "salary_structure_id": row.salary_structure_id, "effective_from": row.effective_from.isoformat(), "effective_to": row.effective_to.isoformat() if row.effective_to else None, "base_salary": str(row.base_salary), "payment_method": row.payment_method, "document_status": row.document_status}


@router.post("/salary-structure-assignments/bulk-assign", status_code=status.HTTP_201_CREATED)
async def bulk_salary_structure_assignment_route(data: BulkSalaryStructureAssignmentInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "administer")
    rows = await create_bulk_assignments(db, actor, data)
    await record_change(db, actor=actor, topic="payroll", aggregate_type="salary_structure_assignment", aggregate_id=rows[0].id if rows else None, operation="bulk_submitted", after={"employee_ids": data.employee_ids, "salary_structure_id": data.salary_structure_id})
    await db.commit()
    return {"created": len(rows), "assignments": [{"id": row.id, "employee_id": row.employee_id, "salary_structure_id": row.salary_structure_id, "effective_from": row.effective_from.isoformat(), "base_salary": str(row.base_salary), "document_status": row.document_status} for row in rows]}


@router.get("/additional-salaries")
async def list_additional_salaries(employee_id: int | None = None, status_filter: str | None = Query(default=None, alias="status"), db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "view")
    query = select(AdditionalSalary).where(AdditionalSalary.organization_id == actor.organization_id)
    if employee_id is not None:
        scoped = await _employee_scope(db, actor, employee_id)
        query = query.where(AdditionalSalary.employee_id == scoped)
    if status_filter:
        query = query.where(AdditionalSalary.status == status_filter)
    rows = (await db.execute(query.order_by(AdditionalSalary.payroll_date.desc(), AdditionalSalary.id.desc()))).scalars().all()
    return [additional_salary_out(row, row.component_code) for row in rows]


@router.post("/additional-salaries", status_code=status.HTTP_201_CREATED)
async def create_additional_salary_route(data: AdditionalSalaryInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    if not _is_payroll_admin(actor) and actor.employee_id != data.employee_id:
        raise HTTPException(status_code=403, detail={"code": "payroll_employee_scope_required"})
    await payroll_capability(db, actor, "create")
    row = await create_additional_salary(db, actor, data)
    await record_change(db, actor=actor, topic="payroll", aggregate_type="additional_salary", aggregate_id=row.id, operation="created", after={"number": row.number, "employee_id": row.employee_id, "amount": str(row.amount)})
    await db.commit(); await db.refresh(row)
    return additional_salary_out(row, row.component_code)


@router.post("/additional-salaries/{salary_id}/submit")
async def submit_additional_salary_route(salary_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "approve")
    row = await db.scalar(select(AdditionalSalary).where(AdditionalSalary.id == salary_id, AdditionalSalary.organization_id == actor.organization_id).with_for_update())
    if not row:
        raise HTTPException(status_code=404, detail="Additional Salary not found")
    await submit_additional_salary(db, actor, row)
    await record_change(db, actor=actor, topic="payroll", aggregate_type="additional_salary", aggregate_id=row.id, operation="submitted", after={"status": row.status})
    await db.commit(); await db.refresh(row)
    return additional_salary_out(row, row.component_code)


@router.post("/additional-salaries/{salary_id}/cancel")
async def cancel_additional_salary_route(salary_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "approve")
    row = await db.scalar(select(AdditionalSalary).where(AdditionalSalary.id == salary_id, AdditionalSalary.organization_id == actor.organization_id).with_for_update())
    if not row:
        raise HTTPException(status_code=404, detail="Additional Salary not found")
    await cancel_additional_salary(db, actor, row)
    await record_change(db, actor=actor, topic="payroll", aggregate_type="additional_salary", aggregate_id=row.id, operation="cancelled", after={"status": row.status})
    await db.commit(); await db.refresh(row)
    return additional_salary_out(row, row.component_code)


@router.post("/payroll-entries", status_code=status.HTTP_201_CREATED)
async def create_payroll_entry_route(data: PayrollEntryInput, response: Response, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    _mark_deprecated(response)
    raise HTTPException(status_code=410, detail={"code": "payroll_legacy_write_gone", "successor": "/v1/erp/payroll/runs"})
    await payroll_capability(db, actor, "create")
    run = await create_payroll_entry(db, actor, data)
    await record_change(db, actor=actor, topic="payroll", aggregate_type="payroll_entry", aggregate_id=run.id, operation="created", after={"number": run.run_number, "workflow_version": run.workflow_version})
    await db.commit(); await db.refresh(run)
    return _run_out(run)


@router.get("/payroll-entries")
async def list_payroll_entries(response: Response, status_filter: str | None = Query(default=None, alias="status"), db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    _mark_deprecated(response)
    await payroll_capability(db, actor, "view")
    query = select(PayrollRun).where(PayrollRun.organization_id == actor.organization_id, PayrollRun.workflow_version == "frappe_v1")
    if status_filter:
        query = query.where(PayrollRun.document_status == status_filter)
    rows = (await db.execute(query.order_by(PayrollRun.posting_date.desc().nullslast(), PayrollRun.id.desc()))).scalars().all()
    return [_run_out(row) for row in rows]


@router.get("/payroll-entries/{entry_id}")
async def get_payroll_entry(entry_id: int, response: Response, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    _mark_deprecated(response)
    await payroll_capability(db, actor, "view")
    run = await db.scalar(select(PayrollRun).where(PayrollRun.id == entry_id, PayrollRun.organization_id == actor.organization_id, PayrollRun.workflow_version == "frappe_v1"))
    if not run:
        raise HTTPException(status_code=404, detail="Payroll Entry not found")
    slips = (await db.execute(select(Payslip).where(Payslip.payroll_run_id == run.id).order_by(Payslip.employee_id))).scalars().all()
    bank_entry = await db.scalar(select(PayrollBankEntry).where(PayrollBankEntry.payroll_run_id == run.id))
    serialized_slips = [_slip_out(row) for row in slips]
    return {**_run_out(run), "employee_selection": (run.input_snapshot or {}).get("employee_selection"), "validate_attendance": (run.input_snapshot or {}).get("validate_attendance", True), "salary_slips": serialized_slips, "payslips": serialized_slips, "bank_entry": bank_entry_out(bank_entry) if bank_entry else None}


@router.post("/payroll-entries/{entry_id}/get-employees")
async def get_payroll_entry_employees(entry_id: int, data: GetEmployeesInput = GetEmployeesInput(), db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    raise HTTPException(status_code=410, detail={"code": "payroll_legacy_write_gone", "successor": "/v1/erp/payroll/runs/preflight"})
    await payroll_capability(db, actor, "create")
    run = await db.scalar(select(PayrollRun).where(PayrollRun.id == entry_id, PayrollRun.organization_id == actor.organization_id, PayrollRun.workflow_version == "frappe_v1").with_for_update())
    if not run:
        raise HTTPException(status_code=404, detail="Payroll Entry not found")
    result = await get_employees(db, actor, run, data)
    await record_change(db, actor=actor, topic="payroll", aggregate_type="payroll_entry", aggregate_id=run.id, operation="employees_selected", after={"employee_ids": result["employee_ids"], "errors": len(result["errors"]), "warnings": len(result["warnings"])})
    await db.commit(); await db.refresh(run)
    return {"payroll_entry": _run_out(run), "payroll_entry_id": run.id, **result}


@router.post("/payroll-entries/{entry_id}/create-salary-slips")
async def create_payroll_entry_salary_slips(entry_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    raise HTTPException(status_code=410, detail={"code": "payroll_legacy_write_gone", "successor": "/v1/erp/payroll/runs/{run_id}/calculate"})
    await payroll_capability(db, actor, "create")
    run = await db.scalar(select(PayrollRun).where(PayrollRun.id == entry_id, PayrollRun.organization_id == actor.organization_id, PayrollRun.workflow_version == "frappe_v1").with_for_update())
    if not run:
        raise HTTPException(status_code=404, detail="Payroll Entry not found")
    slips = await create_salary_slips(db, actor, run)
    await record_change(db, actor=actor, topic="payroll", aggregate_type="payroll_entry", aggregate_id=run.id, operation="salary_slips_created", after={"count": len(slips), "total_net": str(run.total_net)})
    await db.commit(); await db.refresh(run)
    serialized_slips = [_slip_out(row) for row in slips]
    return {**_run_out(run), "salary_slips": serialized_slips, "payslips": serialized_slips}


@router.post("/payroll-entries/{entry_id}/submit-salary-slips")
async def submit_payroll_entry_salary_slips(entry_id: int, data: PayslipPublicationInput = PayslipPublicationInput(), db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    raise HTTPException(status_code=410, detail={"code": "payroll_legacy_write_gone", "successor": "/v1/erp/payroll/runs/{run_id}/publish-payslips"})
    await payroll_capability(db, actor, "post")
    run = await db.scalar(select(PayrollRun).where(PayrollRun.id == entry_id, PayrollRun.organization_id == actor.organization_id, PayrollRun.workflow_version == "frappe_v1").with_for_update())
    if not run:
        raise HTTPException(status_code=404, detail="Payroll Entry not found")
    await submit_salary_slips(db, actor, run)
    if data.notify_employees:
        employee_ids = list((await db.execute(select(Payslip.employee_id).where(Payslip.payroll_run_id == run.id))).scalars().all())
        await create_notifications(db, organization_id=actor.organization_id, kind="event", title="Your payslip is ready", body=f"Payslip for {run.period_start:%Y-%m-%d} to {run.period_end:%Y-%m-%d} is available in Payroll.", dedup_key=f"payroll-payslips:{run.id}", employee_ids=employee_ids, target_url="/erp/payroll", payload={"payroll_run_id": run.id})
    await record_change(db, actor=actor, topic="payroll", aggregate_type="payroll_entry", aggregate_id=run.id, operation="salary_slips_submitted", after={"erp_document_id": run.erp_document_id, "notified": data.notify_employees})
    await db.commit(); await db.refresh(run)
    return _run_out(run)


@router.post("/payroll-entries/{entry_id}/make-bank-entry", status_code=status.HTTP_201_CREATED)
async def make_payroll_entry_bank_entry(entry_id: int, data: BankEntryInput = BankEntryInput(), db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    raise HTTPException(status_code=410, detail={"code": "payroll_legacy_write_gone", "successor": "/v1/erp/payroll/runs/{run_id}/payments"})
    await payroll_capability(db, actor, "post")
    run = await db.scalar(select(PayrollRun).where(PayrollRun.id == entry_id, PayrollRun.organization_id == actor.organization_id, PayrollRun.workflow_version == "frappe_v1").with_for_update())
    if not run:
        raise HTTPException(status_code=404, detail="Payroll Entry not found")
    row = await make_bank_entry(db, actor, run, data)
    await record_change(db, actor=actor, topic="payroll", aggregate_type="bank_entry", aggregate_id=row.id, operation="created", after={"payroll_entry_id": run.id, "amount": str(row.amount)})
    await db.commit(); await db.refresh(row)
    return bank_entry_out(row)


@router.post("/bank-entries/{bank_entry_id}/submit")
async def submit_payroll_bank_entry(bank_entry_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    raise HTTPException(status_code=410, detail={"code": "payroll_legacy_write_gone", "successor": "/v1/erp/payroll/runs/{run_id}/payments"})
    await payroll_capability(db, actor, "post")
    row = await db.scalar(select(PayrollBankEntry).where(PayrollBankEntry.id == bank_entry_id, PayrollBankEntry.organization_id == actor.organization_id).with_for_update())
    if not row:
        raise HTTPException(status_code=404, detail="Bank Entry not found")
    await submit_bank_entry(db, actor, row)
    await record_change(db, actor=actor, topic="payroll", aggregate_type="bank_entry", aggregate_id=row.id, operation="submitted", after={"erp_document_id": row.erp_document_id, "amount": str(row.amount)})
    await db.commit(); await db.refresh(row)
    return bank_entry_out(row)


@router.post("/payroll-entries/{entry_id}/cancel")
async def cancel_payroll_entry(entry_id: int, data: PayrollCancelInput = PayrollCancelInput(), db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    raise HTTPException(status_code=410, detail={"code": "payroll_legacy_write_gone", "successor": "/v1/erp/payroll/runs/{run_id}/reverse"})
    await payroll_capability(db, actor, "post")
    run = await db.scalar(select(PayrollRun).where(PayrollRun.id == entry_id, PayrollRun.organization_id == actor.organization_id, PayrollRun.workflow_version == "frappe_v1").with_for_update())
    if not run:
        raise HTTPException(status_code=404, detail="Payroll Entry not found")
    if run.document_status == "cancelled":
        return _run_out(run)
    if run.status in {"draft", "calculated"}:
        run.status = "cancelled"; run.document_status = "cancelled"
        slips = (await db.execute(select(Payslip).where(Payslip.payroll_run_id == run.id))).scalars().all()
        for slip in slips:
            slip.document_status = "cancelled"; slip.cancelled_at = datetime.now(timezone.utc)
        await record_change(db, actor=actor, topic="payroll", aggregate_type="payroll_entry", aggregate_id=run.id, operation="cancelled", after={"reason": data.reason})
        await db.commit(); await db.refresh(run)
        return _run_out(run)
    reversal = await reverse_run(db, actor, run)
    reversal.workflow_version = "legacy"
    reversal.document_status = "submitted"
    await post_run(db, actor, reversal)
    # Keep the submitted source immutable while moving its document state to
    # cancelled.  The reversal carries the negative GL/accumulator entries.
    run.status = "cancelled"
    run.document_status = "cancelled"
    cancelled_at = datetime.now(timezone.utc)
    if run.bank_entry_id:
        bank_entry = await db.scalar(select(PayrollBankEntry).where(PayrollBankEntry.id == run.bank_entry_id, PayrollBankEntry.organization_id == actor.organization_id).with_for_update())
        if bank_entry and bank_entry.status == "draft":
            bank_entry.status = "cancelled"
    source_slips = (await db.execute(select(Payslip).where(Payslip.payroll_run_id == run.id))).scalars().all()
    for slip in source_slips:
        slip.document_status = "cancelled"
        slip.cancelled_at = cancelled_at
    await record_change(db, actor=actor, topic="payroll", aggregate_type="payroll_entry", aggregate_id=run.id, operation="cancelled_by_reversal", after={"reason": data.reason, "reversal_id": reversal.id})
    await db.commit(); await db.refresh(reversal)
    return {"cancelled_entry_id": run.id, "reversal": _run_out(reversal)}


@router.post("/payroll-entries/{entry_id}/amend", status_code=status.HTTP_201_CREATED)
async def amend_payroll_entry(entry_id: int, data: PayrollEntryInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    raise HTTPException(status_code=410, detail={"code": "payroll_legacy_write_gone", "successor": "/v1/erp/payroll/runs/{run_id}/replace"})
    await payroll_capability(db, actor, "create")
    source = await db.scalar(select(PayrollRun).where(PayrollRun.id == entry_id, PayrollRun.organization_id == actor.organization_id, PayrollRun.workflow_version == "frappe_v1"))
    if not source or source.status not in {"posted", "paid"}:
        raise HTTPException(status_code=409, detail={"code": "payroll_entry_requires_submitted_for_amend"})
    replacement = await create_payroll_entry(db, actor, data)
    replacement.replacement_of_run_id = source.id
    replacement.input_snapshot = {**(replacement.input_snapshot or {}), "replacement_of_run_id": source.id}
    await record_change(db, actor=actor, topic="payroll", aggregate_type="payroll_entry", aggregate_id=replacement.id, operation="amended", after={"replacement_of_run_id": source.id})
    await db.commit(); await db.refresh(replacement)
    return _run_out(replacement)


@router.get("/salary-slips")
async def list_salary_slips(run_id: int | None = None, status_filter: str | None = Query(default=None, alias="status"), employee_id: int | None = None, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "view")
    query = select(Payslip).join(PayrollRun, PayrollRun.id == Payslip.payroll_run_id).where(Payslip.organization_id == actor.organization_id, PayrollRun.workflow_version.in_(("frappe_v1", "unified_v2")))
    if run_id is not None:
        query = query.where(Payslip.payroll_run_id == run_id)
    if employee_id is not None:
        query = query.where(Payslip.employee_id == await _employee_scope(db, actor, employee_id))
    if status_filter:
        query = query.where(Payslip.document_status == status_filter)
    rows = (await db.execute(query.order_by(Payslip.created_at.desc()))).scalars().all()
    return [_slip_out(row) for row in rows]


@router.get("/reports/salary-register")
async def salary_register_report(run_id: int | None = None, report_format: Literal["json", "csv", "xlsx", "pdf"] = Query(default="json", alias="format"), db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "export" if report_format != "json" else "view")
    query = select(Payslip, PayrollRun).join(PayrollRun, PayrollRun.id == Payslip.payroll_run_id).where(Payslip.organization_id == actor.organization_id, PayrollRun.workflow_version.in_(("frappe_v1", "unified_v2")))
    if run_id is not None:
        query = query.where(Payslip.payroll_run_id == run_id)
    rows = (await db.execute(query.order_by(Payslip.employee_id))).all()
    line_items = (await db.execute(select(PayslipLineItem).where(PayslipLineItem.payslip_id.in_([slip.id for slip, _ in rows])).order_by(PayslipLineItem.payslip_id, PayslipLineItem.position))).scalars().all() if rows else []
    lines_by_slip: dict[int, list[dict[str, Any]]] = {}
    for line in line_items:
        lines_by_slip.setdefault(line.payslip_id, []).append({"code": line.component_code, "label": line.label, "kind": line.component_kind, "amount": str(line.amount), "trace": line.trace or {}})
    payload = [{"salary_slip_id": slip.id, "payroll_entry_id": run.id, "payroll_entry_number": run.run_number, "employee_id": slip.employee_id, "employee_name": (slip.employee_profile_snapshot or {}).get("employee_name"), "department": (slip.employee_profile_snapshot or {}).get("department"), "job_title": (slip.employee_profile_snapshot or {}).get("job_title"), "gross": str(slip.gross), "taxable_income": str(slip.taxable_income), "employee_shi": str(slip.employee_shi), "employer_shi": str(slip.employer_shi), "pit": str(slip.pit), "pit_relief": str(slip.pit_relief), "advance_offset": str(slip.advance_offset), "net_pay": str(slip.net_pay), "status": slip.document_status, "lines": lines_by_slip.get(slip.id, []), "calculation_trace": slip.calculation_trace or {}} for slip, run in rows]
    if report_format == "json":
        return payload
    template = await db.scalar(select(PayrollReportTemplate).where(PayrollReportTemplate.organization_id == actor.organization_id, PayrollReportTemplate.kind == "salary_register", PayrollReportTemplate.status == "published").order_by(PayrollReportTemplate.version.desc()).limit(1))
    columns = (template.template or {}).get("columns") if template else None
    columns = columns or [{"key": key, "header": key} for key in ("salary_slip_id", "payroll_entry_id", "payroll_entry_number", "employee_id", "gross", "taxable_income", "employee_shi", "employer_shi", "pit", "net_pay", "status")]
    required = set((template.required_keys if template else []) or [])
    configured = {column.get("key") for column in columns if isinstance(column, dict)}
    if required - configured:
        raise HTTPException(status_code=409, detail={"code": "payroll_report_template_invalid", "path": "template.columns", "missing": sorted(required - configured), "message": "Required register fields cannot be removed.", "remediation": "Restore the required columns in the published report template."})
    if report_format == "pdf":
        filename, content = "salary-register.pdf", render_report_pdf(payload, columns)
        media_type = "application/pdf"
    else:
        filename, content = render_bank_export(payload, {"columns": columns, "filename": f"salary-register.{report_format}"}, report_format)
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if report_format == "xlsx" else "text/csv; charset=utf-8"
    return Response(content=content, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/reports/bank-remittance")
async def bank_remittance_report(run_id: int | None = None, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "export")
    query = select(Payslip, PayrollRun, EmployeePayrollProfile).join(PayrollRun, PayrollRun.id == Payslip.payroll_run_id).join(EmployeePayrollProfile, (EmployeePayrollProfile.employee_id == Payslip.employee_id) & (EmployeePayrollProfile.organization_id == actor.organization_id)).where(Payslip.organization_id == actor.organization_id, PayrollRun.workflow_version.in_(("frappe_v1", "unified_v2")), EmployeePayrollProfile.effective_from <= PayrollRun.tax_point_date, (EmployeePayrollProfile.effective_to.is_(None) | (EmployeePayrollProfile.effective_to >= PayrollRun.tax_point_date)))
    if run_id is not None:
        query = query.where(Payslip.payroll_run_id == run_id)
    rows = (await db.execute(query.order_by(Payslip.employee_id))).all()
    result = []
    for slip, run, profile in rows:
        account = await db.scalar(select(EmployeeBankAccount).where(EmployeeBankAccount.employee_id == slip.employee_id, EmployeeBankAccount.is_primary.is_(True)).order_by(EmployeeBankAccount.id.desc()))
        result.append({"salary_slip_id": slip.id, "payroll_entry_id": run.id, "employee_id": slip.employee_id, "bank_code": account.bank_code if account else None, "account_last4": account.account_last4 if account else None, "amount": str(slip.net_pay), "currency": "MNT", "payment_status": run.payment_status})
    return result


@router.post("/runs", status_code=status.HTTP_201_CREATED)
async def create_payroll_run(data: PayrollRunInput, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "create")
    payload = data.model_dump(mode="json")
    request_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if idempotency_key:
        if len(idempotency_key) > 255: raise HTTPException(status_code=422, detail="Idempotency-Key is too long")
        prior = await db.scalar(select(IdempotencyRecord).where(IdempotencyRecord.account_id == actor.account_id, IdempotencyRecord.operation == "payroll.run.create", IdempotencyRecord.key == idempotency_key))
        if prior:
            if prior.request_hash != request_hash: raise HTTPException(status_code=409, detail={"code": "payroll_idempotency_conflict"})
            return prior.response_body
    run = await create_run(db, actor, data); await db.flush()
    await record_change(db, actor=actor, topic="payroll", aggregate_type="payroll_run", aggregate_id=run.id, operation="created", after={"run_number": run.run_number, "run_type": run.run_type, "settlement_key": run.settlement_key, "statutory_profile_id": run.statutory_profile_id})
    result = _run_out(run)
    if idempotency_key:
        db.add(IdempotencyRecord(account_id=actor.account_id, operation="payroll.run.create", key=idempotency_key, request_hash=request_hash, response_status=201, response_body=result, expires_at=datetime.now(timezone.utc) + timedelta(days=1)))
    await db.commit(); await db.refresh(run); return result


@router.get("/runs/{run_id}/cycle-inputs")
async def get_payroll_cycle_inputs(run_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "view")
    run = await db.scalar(select(PayrollRun).where(PayrollRun.id == run_id, PayrollRun.organization_id == actor.organization_id, PayrollRun.workflow_version == "unified_v2"))
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    snapshot = run.input_snapshot or {}
    employees = {row.id: row for row in (await db.execute(select(Employee).where(Employee.organization_id == actor.organization_id, Employee.id.in_(snapshot.get("employee_ids") or [])))).scalars().all()}
    canonical = snapshot.get("canonical_inputs") or {}
    corrections = snapshot.get("cycle_input_corrections") or {}
    return {"run_id": run.id, "period_start": run.period_start.isoformat(), "period_end": run.period_end.isoformat(), "status": run.status, "employees": [{"employee_id": int(key), "employee_name": employees.get(int(key)).name if employees.get(int(key)) else None, "scheduled_hours": inputs.get("scheduled_hours", "0"), "actual_worked_hours": inputs.get("actual_worked_hours", "0"), "payable_workdays": inputs.get("payable_workdays", "0"), "source": inputs.get("payable_hours_source"), "days": inputs.get("days", []), "correction": corrections.get(key), "editable": run.status == "draft"} for key, inputs in canonical.items()]}


@router.put("/runs/{run_id}/cycle-inputs")
async def save_payroll_cycle_input(run_id: int, data: PayrollCycleInputCorrection, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "edit_setup")
    run = await db.scalar(select(PayrollRun).where(PayrollRun.id == run_id, PayrollRun.organization_id == actor.organization_id, PayrollRun.workflow_version == "unified_v2").with_for_update())
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status != "draft":
        raise HTTPException(status_code=409, detail={"code": "payroll_run_immutable", "status": run.status})
    snapshot = dict(run.input_snapshot or {})
    employee_key = str(data.employee_id)
    if data.employee_id not in (snapshot.get("employee_ids") or []):
        raise HTTPException(status_code=422, detail={"code": "payroll_cycle_input_employee_not_in_run"})
    corrections = dict(snapshot.get("cycle_input_corrections") or {})
    prior = corrections.get(employee_key) or {}
    corrections[employee_key] = {"revision": int(prior.get("revision", 0)) + 1, "status": "pending_approval", "submitted_by_account_id": actor.account_id, "actual_worked_hours": str(data.actual_worked_hours), "overtime_by_type": {key: str(value) for key, value in data.overtime_by_type.items()}, "evidence_reference": data.evidence_reference.strip(), "reason": data.reason.strip(), "submitted_at": datetime.now(timezone.utc).isoformat()}
    snapshot["cycle_input_corrections"] = corrections
    run.input_snapshot = snapshot
    run.snapshot_checksum = hashlib.sha256(json.dumps({"input": snapshot, "config": run.config_snapshot or {}}, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
    await db.flush()
    return {"employee_id": data.employee_id, **corrections[employee_key]}


@router.post("/runs/{run_id}/cycle-inputs/{employee_id}/approve")
async def approve_payroll_cycle_input(run_id: int, employee_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "approve")
    run = await db.scalar(select(PayrollRun).where(PayrollRun.id == run_id, PayrollRun.organization_id == actor.organization_id, PayrollRun.workflow_version == "unified_v2").with_for_update())
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status != "draft":
        raise HTTPException(status_code=409, detail={"code": "payroll_run_immutable", "status": run.status})
    snapshot = dict(run.input_snapshot or {})
    employee_key = str(employee_id)
    corrections = dict(snapshot.get("cycle_input_corrections") or {})
    correction = corrections.get(employee_key)
    if not correction or correction.get("status") != "pending_approval":
        raise HTTPException(status_code=409, detail={"code": "payroll_cycle_input_not_pending"})
    if correction.get("submitted_by_account_id") == actor.account_id:
        raise HTTPException(status_code=403, detail={"code": "payroll_cycle_input_separation_of_duties", "message": "A different approver must approve this correction."})
    correction = {**correction, "status": "approved", "approved_by_account_id": actor.account_id, "approved_at": datetime.now(timezone.utc).isoformat()}
    corrections[employee_key] = correction
    overrides = dict(snapshot.get("overrides") or {})
    overrides[employee_key] = {**(overrides.get(employee_key) or {}), "actual_worked_hours": correction["actual_worked_hours"], "overtime_by_type": correction["overtime_by_type"], "cycle_input_correction_revision": correction["revision"]}
    snapshot["cycle_input_corrections"] = corrections
    snapshot["overrides"] = overrides
    snapshot["attendance_input_errors"] = [item for item in (snapshot.get("attendance_input_errors") or []) if int(item.get("employee_id", -1)) != employee_id]
    run.input_snapshot = snapshot
    run.snapshot_checksum = hashlib.sha256(json.dumps({"input": snapshot, "config": run.config_snapshot or {}}, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
    await db.flush()
    return {"employee_id": employee_id, **correction}


@router.post("/runs/preflight")
async def preflight_payroll_run(data: PayrollRunInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "create")
    return await preflight_run(db, actor, data)


@router.get("/runs")
async def list_payroll_runs(status_filter: str | None = Query(default=None, alias="status"), workflow_version: str = Query(default="unified_v2"), db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "view")
    query = select(PayrollRun).where(PayrollRun.organization_id == actor.organization_id, PayrollRun.workflow_version == workflow_version)
    if status_filter: query = query.where(PayrollRun.status == status_filter)
    return [_run_out(row) for row in (await db.execute(query.order_by(PayrollRun.period_end.desc(), PayrollRun.id.desc()))).scalars().all()]


@router.post("/runs/{run_id}/calculate")
async def calculate_payroll_run(run_id: int, data: CalculateRunInput = CalculateRunInput(), db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "calculate")
    run = await db.scalar(select(PayrollRun).where(PayrollRun.id == run_id, PayrollRun.organization_id == actor.organization_id).with_for_update())
    if not run: raise HTTPException(status_code=404, detail="Payroll run not found")
    if run.config_snapshot.get("is_example") and not data.acknowledge_example: raise HTTPException(status_code=409, detail={"code": "payroll_example_profile_requires_acknowledgement"})
    try:
        await calculate_run(db, actor, run)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "payroll_calculation_invalid", "path": "run", "message": str(exc), "remediation": "Review the formula trace, statutory tiers, work policy, and deductions before recalculating."}) from exc
    await record_change(db, actor=actor, topic="payroll", aggregate_type="payroll_run", aggregate_id=run.id, operation="calculated", after={"status": run.status, "total_gross": str(run.total_gross), "total_net": str(run.total_net), "snapshot_checksum": run.snapshot_checksum})
    await db.commit(); await db.refresh(run); return _run_out(run)


@router.get("/runs/{run_id}/reconciliation")
async def get_payroll_reconciliation(run_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "view")
    run = await db.scalar(select(PayrollRun).where(PayrollRun.id == run_id, PayrollRun.organization_id == actor.organization_id).with_for_update())
    if not run: raise HTTPException(status_code=404, detail="Payroll run not found")
    report = await reconcile_run(db, actor, run)
    await db.commit()
    return report


@router.get("/runs/{run_id}/posting-preview")
async def get_payroll_posting_preview(run_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    try:
        await payroll_capability(db, actor, "view_salary")
    except HTTPException as exc:
        if exc.status_code != 403: raise
        await payroll_capability(db, actor, "post")
    run = await db.scalar(select(PayrollRun).where(PayrollRun.id == run_id, PayrollRun.organization_id == actor.organization_id))
    if not run:
        raise HTTPException(status_code=404, detail="Payroll run not found")
    return await posting_preview(db, actor, run)


@router.post("/runs/{run_id}/reconciliation/resolve")
async def resolve_payroll_reconciliation(run_id: int, data: ReconciliationResolutionInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "review")
    run = await db.scalar(select(PayrollRun).where(PayrollRun.id == run_id, PayrollRun.organization_id == actor.organization_id).with_for_update())
    if not run: raise HTTPException(status_code=404, detail="Payroll run not found")
    report = await reconcile_run(db, actor, run)
    known = {item["key"] for item in report["issues"]}
    unknown = sorted(set(data.issue_keys) - known)
    if unknown: raise HTTPException(status_code=422, detail={"code": "payroll_reconciliation_issue_unknown", "issue_keys": unknown})
    resolved = set(report.get("resolved_issue_keys") or []) | set(data.issue_keys)
    report["resolved_issue_keys"] = sorted(resolved)
    report["resolution_notes"] = [*(report.get("resolution_notes") or []), {"note": data.note, "issue_keys": data.issue_keys, "account_id": actor.account_id, "resolved_at": datetime.now(timezone.utc).isoformat()}]
    run.reconciliation_snapshot = report
    report = await reconcile_run(db, actor, run)
    await record_change(db, actor=actor, topic="payroll", aggregate_type="payroll_run", aggregate_id=run.id, operation="reconciliation_resolved", after={"issue_keys": data.issue_keys, "unresolved_errors": report["unresolved_errors"]})
    await db.commit()
    return report


@router.post("/runs/{run_id}/approve")
async def approve_payroll_run(run_id: int, data: PayrollApprovalInput = PayrollApprovalInput(), db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    run = await db.scalar(select(PayrollRun).where(PayrollRun.id == run_id, PayrollRun.organization_id == actor.organization_id).with_for_update())
    if not run: raise HTTPException(status_code=404, detail="Payroll run not found")
    if run.status != "in_review": raise HTTPException(status_code=409, detail={"code": "payroll_run_requires_review"})
    report = await reconcile_run(db, actor, run)
    if report["unresolved_errors"]: raise HTTPException(status_code=409, detail={"code": "payroll_reconciliation_errors_unresolved", "count": report["unresolved_errors"]})
    stages = list((run.approval_workflow or {}).get("stages") or [
        {"key": "payroll_manager", "label": "Payroll Manager", "status": "pending"},
        {"key": "hr_director", "label": "HR Director", "status": "pending"},
        {"key": "finance", "label": "Finance / CFO", "status": "pending"},
    ])
    pending = next((stage for stage in stages if stage.get("status") != "approved"), None)
    if not pending: raise HTTPException(status_code=409, detail={"code": "payroll_approval_workflow_complete"})
    stage_action = {"payroll_manager": "approve_payroll_manager", "hr_director": "approve_hr_director", "finance": "approve_finance"}.get(pending["key"], "approve")
    await payroll_capability(db, actor, stage_action)
    if data.stage and data.stage != pending["key"]: raise HTTPException(status_code=409, detail={"code": "payroll_approval_stage_out_of_order", "next_stage": pending["key"]})
    used_accounts = {stage.get("approved_by_account_id") for stage in stages if stage.get("approved_by_account_id") is not None}
    if actor.account_id in used_accounts: raise HTTPException(status_code=403, detail={"code": "payroll_approval_requires_distinct_approver", "stage": pending["key"]})
    if run.created_by_account_id == actor.account_id: raise HTTPException(status_code=403, detail={"code": "payroll_separation_of_duties"})
    pending.update({"status": "approved", "approved_by_account_id": actor.account_id, "approved_at": datetime.now(timezone.utc).isoformat(), "comment": data.comment})
    complete = all(stage.get("status") == "approved" for stage in stages)
    run.approval_workflow = {"stages": stages, "locked": complete}
    if complete:
        run.status = "approved"; run.approved_by_account_id = actor.account_id; run.approved_at = datetime.now(timezone.utc)
    await record_change(db, actor=actor, topic="payroll", aggregate_type="payroll_run", aggregate_id=run.id, operation="approval_stage_signed", after={"stage": pending["key"], "status": run.status, "approved_by_account_id": actor.account_id, "complete": complete})
    await db.commit(); await db.refresh(run); return _run_out(run)


@router.post("/runs/{run_id}/review")
async def review_payroll_run(run_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "review")
    run = await db.scalar(select(PayrollRun).where(PayrollRun.id == run_id, PayrollRun.organization_id == actor.organization_id).with_for_update())
    if not run: raise HTTPException(status_code=404, detail="Payroll run not found")
    if run.status != "calculated": raise HTTPException(status_code=409, detail={"code": "payroll_run_requires_calculation"})
    report = await reconcile_run(db, actor, run)
    if report["unresolved_errors"]: raise HTTPException(status_code=409, detail={"code": "payroll_reconciliation_errors_unresolved", "count": report["unresolved_errors"]})
    run.status = "in_review"
    run.approval_workflow = {"stages": [
        {"key": "payroll_manager", "label": "Payroll Manager", "status": "pending"},
        {"key": "hr_director", "label": "HR Director", "status": "pending"},
        {"key": "finance", "label": "Finance / CFO", "status": "pending"},
    ], "locked": False}
    await record_change(db, actor=actor, topic="payroll", aggregate_type="payroll_run", aggregate_id=run.id, operation="reviewed", after={"status": run.status})
    await db.commit(); await db.refresh(run); return _run_out(run)


@router.post("/runs/{run_id}/return")
async def return_payroll_run(run_id: int, data: PayrollReturnInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    """Return a run from review to calculation with an auditable reason."""
    raise HTTPException(status_code=410, detail={"code": "payroll_return_gone", "successor": f"/v1/erp/payroll/runs/{run_id}/reject"})


@router.post("/runs/{run_id}/reject")
async def reject_payroll_run(run_id: int, data: PayrollReturnInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "review")
    run = await db.scalar(select(PayrollRun).where(PayrollRun.id == run_id, PayrollRun.organization_id == actor.organization_id).with_for_update())
    if not run:
        raise HTTPException(status_code=404, detail="Payroll run not found")
    if run.status != "in_review":
        raise HTTPException(status_code=409, detail={"code": "payroll_run_requires_review", "status": run.status})
    run.status = "rejected"; run.rejected_at = datetime.now(timezone.utc); run.rejected_by_account_id = actor.account_id; run.rejection_reason = data.reason
    run.approval_workflow = {**(run.approval_workflow or {}), "locked": True, "rejected_reason": data.reason, "rejected_by_account_id": actor.account_id, "rejected_at": run.rejected_at.isoformat()}
    await record_change(db, actor=actor, topic="payroll", aggregate_type="payroll_run", aggregate_id=run.id, operation="rejected", after={"reason": data.reason, "status": run.status})
    await db.commit(); await db.refresh(run)
    return _run_out(run)


@router.post("/runs/{run_id}/post")
async def post_payroll_run(run_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "post")
    run = await db.scalar(select(PayrollRun).where(PayrollRun.id == run_id, PayrollRun.organization_id == actor.organization_id).with_for_update())
    if not run: raise HTTPException(status_code=404, detail="Payroll run not found")
    document = await post_run(db, actor, run)
    await record_change(db, actor=actor, topic="payroll", aggregate_type="payroll_run", aggregate_id=run.id, operation="posted", after={"status": run.status, "erp_document_id": document.id, "snapshot_checksum": run.snapshot_checksum})
    await db.commit(); await db.refresh(run); return {**_run_out(run), "erp_document_id": document.id}


@router.post("/runs/{run_id}/reverse")
async def reverse_payroll_run(run_id: int, data: PayrollRunReversalInput = PayrollRunReversalInput(reason="Payroll reversal"), db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "post")
    run = await db.scalar(select(PayrollRun).where(PayrollRun.id == run_id, PayrollRun.organization_id == actor.organization_id).with_for_update())
    if not run: raise HTTPException(status_code=404, detail="Payroll run not found")
    reversal = await reverse_run(db, actor, run)
    reversal.posting_date = data.posting_date or run.posting_date or run.tax_point_date
    reversal.config_snapshot = {**(reversal.config_snapshot or {}), "reversal_reason": data.reason}
    reversal.snapshot_checksum = hashlib.sha256(json.dumps({"input": reversal.input_snapshot, "config": reversal.config_snapshot, "payslips": [row.snapshot_checksum for row in (await db.execute(select(Payslip).where(Payslip.payroll_run_id == reversal.id))).scalars().all()]}, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
    await post_run(db, actor, reversal)
    await record_change(db, actor=actor, topic="payroll", aggregate_type="payroll_run", aggregate_id=reversal.id, operation="reversal_created", after={"reversal_of_run_id": run.id, "source_checksum": run.snapshot_checksum})
    await db.commit(); await db.refresh(reversal)
    return _run_out(reversal)


@router.post("/payment-allocations/{allocation_id}/reverse")
async def reverse_payroll_payment_allocation(allocation_id: int, data: PayrollPaymentReversalInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "pay")
    reversal = await reverse_payment_allocation(db, actor, allocation_id, data)
    await record_change(db, actor=actor, topic="payroll", aggregate_type="payroll_payment_reversal", aggregate_id=reversal.id, operation="created", after={"payment_allocation_id": allocation_id, "reversal_erp_document_id": reversal.reversal_erp_document_id})
    await db.commit(); await db.refresh(reversal)
    return {"id": reversal.id, "payment_allocation_id": reversal.payment_allocation_id, "original_erp_document_id": reversal.original_erp_document_id, "reversal_erp_document_id": reversal.reversal_erp_document_id, "reason": reversal.reason, "transaction_reference": reversal.transaction_reference, "evidence": reversal.evidence}


@router.post("/runs/{run_id}/payments", status_code=status.HTTP_201_CREATED)
async def prepare_payroll_payment_batch(run_id: int, data: PaymentBatchInput = PaymentBatchInput(), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "pay")
    payload = data.model_dump(mode="json")
    request_hash = hashlib.sha256(json.dumps({"run_id": run_id, **payload}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if idempotency_key:
        if len(idempotency_key) > 255:
            raise HTTPException(status_code=422, detail={"code": "payroll_idempotency_key_too_long"})
        prior = await db.scalar(select(IdempotencyRecord).where(IdempotencyRecord.account_id == actor.account_id, IdempotencyRecord.operation == "payroll.payment.prepare", IdempotencyRecord.key == idempotency_key))
        if prior:
            if prior.request_hash != request_hash:
                raise HTTPException(status_code=409, detail={"code": "payroll_idempotency_conflict"})
            return prior.response_body
    run = await db.scalar(select(PayrollRun).where(PayrollRun.id == run_id, PayrollRun.organization_id == actor.organization_id).with_for_update())
    if not run:
        raise HTTPException(status_code=404, detail="Payroll run not found")
    batch = await create_payment_batch(db, actor, run, data)
    await record_change(db, actor=actor, topic="payroll", aggregate_type="payroll_payment_batch", aggregate_id=batch.id, operation="prepared", after={"run_id": run.id, "amount": str(batch.total_amount), "retry_of_batch_id": batch.retry_of_batch_id})
    await db.flush()
    allocations = list((await db.execute(select(PayrollPaymentAllocation).where(PayrollPaymentAllocation.payment_batch_id == batch.id).order_by(PayrollPaymentAllocation.id))).scalars().all())
    result = _payment_batch_out(batch, allocations)
    if idempotency_key:
        db.add(IdempotencyRecord(account_id=actor.account_id, operation="payroll.payment.prepare", key=idempotency_key, request_hash=request_hash, response_status=201, response_body=result, expires_at=datetime.now(timezone.utc) + timedelta(days=1)))
    await db.commit()
    return result


@router.get("/payments/{payment_id}")
async def get_payroll_payment_batch(payment_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "view")
    batch = await db.scalar(select(PayrollPaymentBatch).where(PayrollPaymentBatch.id == payment_id, PayrollPaymentBatch.organization_id == actor.organization_id))
    if not batch:
        raise HTTPException(status_code=404, detail="Payment batch not found")
    allocations = list((await db.execute(select(PayrollPaymentAllocation).where(PayrollPaymentAllocation.payment_batch_id == batch.id).order_by(PayrollPaymentAllocation.id))).scalars().all())
    return _payment_batch_out(batch, allocations)


@router.get("/payments")
async def list_payroll_payment_batches(run_id: int | None = None, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "view")
    query = select(PayrollPaymentBatch).where(PayrollPaymentBatch.organization_id == actor.organization_id)
    if run_id is not None:
        query = query.where(PayrollPaymentBatch.payroll_run_id == run_id)
    rows = (await db.execute(query.order_by(PayrollPaymentBatch.created_at.desc()))).scalars().all()
    return [_payment_batch_out(row) for row in rows]


@router.get("/payment-allocations")
async def list_payroll_payment_allocations(run_id: int | None = None, status_filter: str | None = Query(default=None, alias="status"), db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "view")
    query = select(PayrollPaymentAllocation).join(PayrollPaymentBatch, PayrollPaymentBatch.id == PayrollPaymentAllocation.payment_batch_id).where(PayrollPaymentAllocation.organization_id == actor.organization_id)
    if run_id is not None:
        query = query.where(PayrollPaymentBatch.payroll_run_id == run_id)
    if status_filter:
        query = query.where(PayrollPaymentAllocation.status == status_filter)
    rows = (await db.execute(query.order_by(PayrollPaymentAllocation.created_at.desc()))).scalars().all()
    return [{"id": row.id, "payment_batch_id": row.payment_batch_id, "payslip_id": row.payslip_id, "employee_id": row.employee_id, "amount": str(row.amount), "status": row.status, "attempt_number": row.attempt_number, "transaction_reference": row.transaction_reference, "settled_at": row.settled_at.isoformat() if row.settled_at else None, "rejection_reason": row.rejection_reason} for row in rows]


@router.post("/payments/{payment_id}/submit-bank")
async def submit_payroll_payment_batch(payment_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    """Mark a prepared batch as transmitted without creating settlement GL."""
    await payroll_capability(db, actor, "pay")
    batch = await db.scalar(select(PayrollPaymentBatch).where(PayrollPaymentBatch.id == payment_id, PayrollPaymentBatch.organization_id == actor.organization_id).with_for_update())
    if not batch:
        raise HTTPException(status_code=404, detail="Payment batch not found")
    if batch.status not in {"prepared", "partially_settled"}:
        raise HTTPException(status_code=409, detail={"code": "payroll_payment_batch_not_submittable"})
    allocations = list((await db.execute(select(PayrollPaymentAllocation).where(PayrollPaymentAllocation.payment_batch_id == batch.id).with_for_update())).scalars().all())
    for allocation in allocations:
        if allocation.status == "pending":
            allocation.status = "bank_submitted"
            allocation.submitted_at = datetime.now(timezone.utc)
    batch.status = "bank_submitted"
    await record_change(db, actor=actor, topic="payroll", aggregate_type="payroll_payment_batch", aggregate_id=batch.id, operation="bank_submitted", after={"allocation_count": len(allocations)})
    await db.commit(); await db.refresh(batch)
    return _payment_batch_out(batch, allocations)


@router.post("/payments/{payment_id}/allocations/{allocation_id}/settle")
async def settle_payroll_payment(payment_id: int, allocation_id: int, data: PaymentSettlementInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "pay")
    allocation = await db.scalar(select(PayrollPaymentAllocation).where(PayrollPaymentAllocation.id == allocation_id, PayrollPaymentAllocation.payment_batch_id == payment_id, PayrollPaymentAllocation.organization_id == actor.organization_id))
    if not allocation:
        raise HTTPException(status_code=404, detail="Payment allocation not found")
    allocation = await settle_payment_allocation(db, actor, allocation_id, data)
    await record_change(db, actor=actor, topic="payroll", aggregate_type="payroll_payment_allocation", aggregate_id=allocation.id, operation="settled", after={"transaction_reference": allocation.transaction_reference, "erp_document_id": allocation.erp_document_id})
    await db.commit(); await db.refresh(allocation)
    return {"id": allocation.id, "status": allocation.status, "transaction_reference": allocation.transaction_reference, "settled_at": allocation.settled_at.isoformat() if allocation.settled_at else None}


@router.post("/payments/{payment_id}/allocations/{allocation_id}/reject")
async def reject_payroll_payment(payment_id: int, allocation_id: int, data: PaymentRejectInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "pay")
    allocation = await db.scalar(select(PayrollPaymentAllocation).where(PayrollPaymentAllocation.id == allocation_id, PayrollPaymentAllocation.payment_batch_id == payment_id, PayrollPaymentAllocation.organization_id == actor.organization_id))
    if not allocation:
        raise HTTPException(status_code=404, detail="Payment allocation not found")
    allocation = await reject_payment_allocation(db, actor, allocation_id, data.reason)
    await record_change(db, actor=actor, topic="payroll", aggregate_type="payroll_payment_allocation", aggregate_id=allocation.id, operation="rejected", after={"reason": data.reason})
    await db.commit(); await db.refresh(allocation)
    return {"id": allocation.id, "status": allocation.status, "rejection_reason": allocation.rejection_reason}


@router.get("/bank-statement-imports")
async def list_payroll_bank_statements(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "view")
    rows = (await db.execute(select(PayrollStatementImport).where(PayrollStatementImport.organization_id == actor.organization_id).order_by(PayrollStatementImport.id.desc()))).scalars().all()
    return [{"id": row.id, "status": row.status, "source_checksum": row.source_checksum, "payment_account_id": row.payment_account_id} for row in rows]


@router.post("/bank-statement-imports", status_code=status.HTTP_201_CREATED)
async def import_payroll_bank_statement(data: StatementImportInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "pay")
    account = await db.scalar(select(ERPAccount).where(
        ERPAccount.id == data.payment_account_id, ERPAccount.organization_id == actor.organization_id,
        ERPAccount.is_active.is_(True), ERPAccount.is_group.is_(False), ERPAccount.purpose.in_(("bank", "cash")),
    ))
    if not account:
        raise HTTPException(status_code=422, detail={"code": "payroll_statement_account_invalid"})
    existing = await db.scalar(select(PayrollStatementImport).where(PayrollStatementImport.organization_id == actor.organization_id, PayrollStatementImport.source_checksum == data.source_checksum))
    if existing:
        raise HTTPException(status_code=409, detail={"code": "payroll_statement_duplicate", "import_id": existing.id})
    statement = PayrollStatementImport(organization_id=actor.organization_id, payment_account_id=account.id, source_checksum=data.source_checksum, statement_start=data.statement_start, statement_end=data.statement_end, created_by_account_id=actor.account_id)
    db.add(statement); await db.flush()
    for index, line in enumerate(data.lines):
        fingerprint = hashlib.sha256(f"{line.transaction_reference or ''}|{line.transaction_date}|{line.amount}|{line.currency}|{index}".encode()).hexdigest()
        db.add(PayrollStatementLine(statement_import_id=statement.id, line_fingerprint=fingerprint, transaction_reference=line.transaction_reference, transaction_date=line.transaction_date, amount=line.amount, currency=line.currency.upper(), description=line.description, fee_amount=line.fee_amount))
    await record_change(db, actor=actor, topic="payroll", aggregate_type="payroll_statement_import", aggregate_id=statement.id, operation="imported", after={"source_checksum": statement.source_checksum, "line_count": len(data.lines)})
    await db.commit(); await db.refresh(statement)
    return {"id": statement.id, "status": statement.status, "source_checksum": statement.source_checksum, "line_count": len(data.lines)}


@router.get("/bank-statement-imports/{import_id}")
async def get_payroll_bank_statement(import_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "view")
    statement = await db.scalar(select(PayrollStatementImport).where(PayrollStatementImport.id == import_id, PayrollStatementImport.organization_id == actor.organization_id))
    if not statement:
        raise HTTPException(status_code=404, detail="Statement import not found")
    lines = list((await db.execute(select(PayrollStatementLine).where(PayrollStatementLine.statement_import_id == statement.id).order_by(PayrollStatementLine.transaction_date, PayrollStatementLine.id))).scalars().all())
    return {"id": statement.id, "status": statement.status, "source_checksum": statement.source_checksum, "payment_account_id": statement.payment_account_id, "lines": [{"id": row.id, "transaction_reference": row.transaction_reference, "transaction_date": row.transaction_date.isoformat(), "amount": str(row.amount), "currency": row.currency, "description": row.description, "match_status": row.match_status, "matched_allocation_id": row.matched_allocation_id, "fee_amount": str(row.fee_amount)} for row in lines]}


@router.post("/bank-statement-lines/{line_id}/match/{allocation_id}")
async def match_payroll_statement_line(line_id: int, allocation_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "pay")
    line = await db.scalar(select(PayrollStatementLine).join(PayrollStatementImport, PayrollStatementImport.id == PayrollStatementLine.statement_import_id).where(PayrollStatementLine.id == line_id, PayrollStatementImport.organization_id == actor.organization_id).with_for_update())
    allocation = await db.scalar(select(PayrollPaymentAllocation).where(PayrollPaymentAllocation.id == allocation_id, PayrollPaymentAllocation.organization_id == actor.organization_id).with_for_update())
    if not line or not allocation:
        raise HTTPException(status_code=404, detail="Statement line or payment allocation not found")
    batch = await db.scalar(select(PayrollPaymentBatch).where(PayrollPaymentBatch.id == allocation.payment_batch_id, PayrollPaymentBatch.organization_id == actor.organization_id))
    statement = await db.scalar(select(PayrollStatementImport).where(PayrollStatementImport.id == line.statement_import_id, PayrollStatementImport.organization_id == actor.organization_id))
    if not batch or not statement or line.match_status == "matched" or allocation.status != "settled" or Decimal(str(line.amount)) != Decimal(str(allocation.amount)) or line.currency != batch.currency or statement.payment_account_id != batch.payment_account_id or (line.transaction_reference and line.transaction_reference != allocation.transaction_reference):
        raise HTTPException(status_code=422, detail={"code": "payroll_statement_match_mismatch"})
    already_matched = await db.scalar(select(PayrollStatementLine.id).where(PayrollStatementLine.matched_allocation_id == allocation.id, PayrollStatementLine.match_status == "matched").limit(1))
    if already_matched:
        raise HTTPException(status_code=409, detail={"code": "payroll_allocation_already_reconciled"})
    line.match_status = "matched"; line.matched_allocation_id = allocation.id; line.matched_at = datetime.now(timezone.utc)
    if statement:
        remaining = await db.scalar(select(func.count(PayrollStatementLine.id)).where(PayrollStatementLine.statement_import_id == statement.id, PayrollStatementLine.match_status != "matched"))
        statement.status = "reconciled" if not remaining else "partially_reconciled"
    await record_change(db, actor=actor, topic="payroll", aggregate_type="payroll_statement_line", aggregate_id=line.id, operation="matched", after={"allocation_id": allocation.id})
    await db.commit()
    return {"id": line.id, "match_status": line.match_status, "matched_allocation_id": line.matched_allocation_id}


@router.post("/runs/{run_id}/replace", status_code=status.HTTP_201_CREATED)
async def replace_payroll_run(run_id: int, data: PayrollRunInput, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "create")
    request_hash = hashlib.sha256(json.dumps({"run_id": run_id, **data.model_dump(mode="json")}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if idempotency_key:
        if len(idempotency_key) > 255: raise HTTPException(status_code=422, detail={"code": "payroll_idempotency_key_too_long"})
        prior = await db.scalar(select(IdempotencyRecord).where(IdempotencyRecord.account_id == actor.account_id, IdempotencyRecord.operation == "payroll.run.replace", IdempotencyRecord.key == idempotency_key))
        if prior:
            if prior.request_hash != request_hash: raise HTTPException(status_code=409, detail={"code": "payroll_idempotency_conflict"})
            return prior.response_body
    source = await db.scalar(select(PayrollRun).where(PayrollRun.id == run_id, PayrollRun.organization_id == actor.organization_id).with_for_update())
    if not source: raise HTTPException(status_code=404, detail="Payroll run not found")
    replacement = await create_replacement_run(db, actor, source, data)
    await record_change(db, actor=actor, topic="payroll", aggregate_type="payroll_run", aggregate_id=replacement.id, operation="replacement_created", after={"replacement_of_run_id": source.id, "source_checksum": source.snapshot_checksum})
    result = _run_out(replacement)
    if idempotency_key:
        db.add(IdempotencyRecord(account_id=actor.account_id, operation="payroll.run.replace", key=idempotency_key, request_hash=request_hash, response_status=201, response_body=result, expires_at=datetime.now(timezone.utc) + timedelta(days=1)))
    await db.commit(); await db.refresh(replacement)
    return result


@router.get("/runs/{run_id}")
async def get_payroll_run(run_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "view")
    run = await db.scalar(select(PayrollRun).where(PayrollRun.id == run_id, PayrollRun.organization_id == actor.organization_id))
    if not run: raise HTTPException(status_code=404, detail="Payroll run not found")
    try:
        await payroll_capability(db, actor, "view_salary")
        slips = (await db.execute(select(Payslip).where(Payslip.payroll_run_id == run.id).order_by(Payslip.employee_id))).scalars().all()
    except HTTPException as exc:
        if exc.status_code != 403: raise
        slips = []
    payout_artifact_kinds = sorted(set((await db.execute(select(PayrollExportArtifact.kind).where(PayrollExportArtifact.payroll_run_id == run.id, PayrollExportArtifact.kind.in_(("bank_payout", "cash_vouchers"))))).scalars().all()))
    return {**_run_out(run), "payslips": [_slip_out(row) for row in slips], "payout_artifact_kinds": payout_artifact_kinds}


@router.get("/runs/{run_id}/payslips")
async def get_run_payslips(run_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "view_salary")
    run = await db.scalar(select(PayrollRun).where(PayrollRun.id == run_id, PayrollRun.organization_id == actor.organization_id))
    if not run: raise HTTPException(status_code=404, detail="Payroll run not found")
    slips = (await db.execute(select(Payslip).where(Payslip.payroll_run_id == run.id).order_by(Payslip.employee_id))).scalars().all()
    return [_slip_out(row, list((await db.execute(select(PayslipLineItem).where(PayslipLineItem.payslip_id == row.id).order_by(PayslipLineItem.position))).scalars().all()), list((await db.execute(select(PayslipStatutoryLine).where(PayslipStatutoryLine.payslip_id == row.id).order_by(PayslipStatutoryLine.position))).scalars().all())) for row in slips]


@router.get("/me/payslips")
async def get_my_payslips(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    if actor.employee_id is None: return []
    slips = (await db.execute(select(Payslip).join(PayrollRun, PayrollRun.id == Payslip.payroll_run_id).where(Payslip.organization_id == actor.organization_id, Payslip.employee_id == actor.employee_id, Payslip.document_status != "cancelled", PayrollRun.status.in_(("settled", "paid", "payslips_released")), PayrollRun.payslips_published_at.is_not(None)).order_by(Payslip.created_at.desc()))).scalars().all()
    return [_slip_out(row) for row in slips]


@router.get("/me/payslips/{payslip_id}/download")
async def download_my_payslip(payslip_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    if actor.employee_id is None:
        raise HTTPException(status_code=404, detail="Payslip not found")
    slip = await db.scalar(select(Payslip).join(PayrollRun, PayrollRun.id == Payslip.payroll_run_id).where(Payslip.id == payslip_id, Payslip.organization_id == actor.organization_id, Payslip.employee_id == actor.employee_id, Payslip.document_status != "cancelled", PayrollRun.status.in_(("settled", "paid", "payslips_released")), PayrollRun.payslips_published_at.is_not(None)))
    if not slip:
        raise HTTPException(status_code=404, detail="Payslip not found")
    lines = list((await db.execute(select(PayslipLineItem).where(PayslipLineItem.payslip_id == slip.id).order_by(PayslipLineItem.position))).scalars().all())
    statutory_lines = list((await db.execute(select(PayslipStatutoryLine).where(PayslipStatutoryLine.payslip_id == slip.id).order_by(PayslipStatutoryLine.position))).scalars().all())
    payload = json.dumps(_slip_out(slip, lines, statutory_lines), ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    await record_change(db, actor=actor, topic="payroll", aggregate_type="payslip", aggregate_id=slip.id, operation="self_downloaded", after={"payroll_run_id": slip.payroll_run_id, "checksum": slip.snapshot_checksum})
    await db.commit()
    return Response(content=payload, media_type="application/json", headers={"Content-Disposition": f'attachment; filename="payslip-{slip.id}.json"', "X-Payslip-Checksum": slip.snapshot_checksum})


@router.post("/me/payslips/{payslip_id}/protected-download")
async def download_protected_payslip(payslip_id: int, data: ProtectedPayslipInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    if actor.employee_id is None: raise HTTPException(status_code=404, detail="Payslip not found")
    slip = await db.scalar(select(Payslip).join(PayrollRun, PayrollRun.id == Payslip.payroll_run_id).where(Payslip.id == payslip_id, Payslip.organization_id == actor.organization_id, Payslip.employee_id == actor.employee_id, Payslip.document_status != "cancelled", PayrollRun.status.in_(("settled", "paid", "payslips_released")), PayrollRun.payslips_published_at.is_not(None)))
    if not slip: raise HTTPException(status_code=404, detail="Payslip not found")
    run = await db.get(PayrollRun, slip.payroll_run_id)
    line_items = list((await db.execute(select(PayslipLineItem).where(PayslipLineItem.payslip_id == slip.id).order_by(PayslipLineItem.position))).scalars().all())
    pdf = render_protected_payslip([
        "OYUNS ALL-IN-ONE - PAYSLIP", f"Payroll run: {run.run_number}", f"Period: {run.period_start} - {run.period_end}",
        f"Employee: {slip.employee_id}", *[f"{item.label}: {item.amount} MNT" for item in line_items],
        f"Gross pay: {slip.gross} MNT", f"Employee SHI: {slip.employee_shi} MNT", f"PIT: {slip.pit} MNT", f"Net pay: {slip.net_pay} MNT",
    ], data.password)
    await record_change(db, actor=actor, topic="payroll", aggregate_type="payslip", aggregate_id=slip.id, operation="protected_pdf_downloaded", after={"payroll_run_id": slip.payroll_run_id, "checksum": slip.snapshot_checksum})
    await db.commit()
    return Response(content=pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="payslip-{slip.id}.pdf"', "X-Payslip-Checksum": slip.snapshot_checksum})


@router.post("/runs/{run_id}/publish-payslips")
async def publish_run_payslips(run_id: int, data: PayslipPublicationInput = PayslipPublicationInput(), db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "release_slips")
    run = await db.scalar(select(PayrollRun).where(PayrollRun.id == run_id, PayrollRun.organization_id == actor.organization_id).with_for_update())
    if not run: raise HTTPException(status_code=404, detail="Payroll run not found")
    if run.status not in {"settled", "paid", "payslips_released"} or run.payment_status not in {"settled", "paid"}: raise HTTPException(status_code=409, detail={"code": "payroll_run_requires_settlement"})
    remaining = await payment_coverage(db, actor.organization_id, run.id)
    if remaining:
        raise HTTPException(status_code=409, detail={"code": "payroll_payments_incomplete", "unpaid_payslips": remaining})
    if not run.payslips_published_at:
        run.payslips_published_at = datetime.now(timezone.utc)
        run.status = "payslips_released"
        if data.notify_employees:
            employee_ids = list((await db.execute(select(Payslip.employee_id).where(Payslip.payroll_run_id == run.id))).scalars().all())
            await create_notifications(db, organization_id=actor.organization_id, kind="event", title="Your payslip is ready", body=f"Payslip for {run.period_start:%Y-%m-%d} to {run.period_end:%Y-%m-%d} is available in Payroll.", dedup_key=f"payroll-payslips:{run.id}", employee_ids=employee_ids, target_url="/erp/payroll", payload={"payroll_run_id": run.id})
        await record_change(db, actor=actor, topic="payroll", aggregate_type="payroll_run", aggregate_id=run.id, operation="payslips_published", after={"published_at": run.payslips_published_at.isoformat(), "notifications": data.notify_employees})
    await db.commit(); await db.refresh(run)
    return _run_out(run)


@router.post("/runs/{run_id}/release-payslips")
async def release_payroll_run_payslips(run_id: int, data: PayslipPublicationInput = PayslipPublicationInput(), db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    return await publish_run_payslips(run_id, data, db, actor)


@router.post("/runs/{run_id}/bank-export")
async def create_bank_export(run_id: int, data: BankExportRequest, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "export")
    run = await db.scalar(select(PayrollRun).where(PayrollRun.id == run_id, PayrollRun.organization_id == actor.organization_id))
    if not run or run.status not in {"posted", "payment_prepared", "partially_settled", "settled", "paid"}: raise HTTPException(status_code=409, detail={"code": "payroll_run_not_exportable"})
    # Provisional layouts are intentionally non-publishable/non-transmittable
    # until a bank-issued sample has passed validation and golden-file tests.
    template_query = select(PayrollBankExportProfile).where(PayrollBankExportProfile.organization_id == actor.organization_id, PayrollBankExportProfile.bank_code == data.bank_code, PayrollBankExportProfile.status == "published", PayrollBankExportProfile.is_provisional.is_(False))
    if data.version: template_query = template_query.where(PayrollBankExportProfile.version == data.version)
    template = await db.scalar(template_query.order_by(PayrollBankExportProfile.version.desc()).limit(1))
    if not template: raise HTTPException(status_code=404, detail={"code": "payroll_bank_template_missing"})
    slips = (await db.execute(select(Payslip).where(Payslip.payroll_run_id == run.id))).scalars().all()
    employees = {row.id: row for row in (await db.execute(select(Employee).where(Employee.id.in_([slip.employee_id for slip in slips])))).scalars().all()}
    accounts = {}
    bank_slips = []
    for slip in slips:
        profile = await db.scalar(select(EmployeePayrollProfile).where(EmployeePayrollProfile.employee_id == slip.employee_id, EmployeePayrollProfile.organization_id == actor.organization_id, EmployeePayrollProfile.effective_from <= run.tax_point_date, (EmployeePayrollProfile.effective_to.is_(None) | (EmployeePayrollProfile.effective_to >= run.tax_point_date))).order_by(EmployeePayrollProfile.effective_from.desc()).limit(1))
        if not profile or profile.payment_method != "bank": continue
        account = await db.scalar(select(EmployeeBankAccount).where(EmployeeBankAccount.employee_id == slip.employee_id, EmployeeBankAccount.is_primary.is_(True), EmployeeBankAccount.valid_from <= run.tax_point_date, (EmployeeBankAccount.valid_to.is_(None) | (EmployeeBankAccount.valid_to >= run.tax_point_date))).limit(1)) if profile else None
        if not account: raise HTTPException(status_code=422, detail={"code": "payroll_bank_account_missing", "employee_id": slip.employee_id})
        accounts[slip.employee_id] = account
        bank_slips.append(slip)
    if not bank_slips: raise HTTPException(status_code=422, detail={"code": "payroll_no_bank_payments"})
    rows = canonical_payout_rows(run, bank_slips, accounts, employees)
    posting = await db.scalar(select(PayrollPostingProfile).where(PayrollPostingProfile.organization_id == actor.organization_id, PayrollPostingProfile.code == "default", PayrollPostingProfile.is_active.is_(True)))
    bank_debit_account = (posting.account_roles or {}).get("bank") if posting else None
    if not bank_debit_account: raise HTTPException(status_code=422, detail={"code": "payroll_bank_debit_account_missing"})
    for row in rows: row["debit_account"] = bank_debit_account
    for row in rows: row["account_number"] = decrypt_secret(row.pop("account_number_ciphertext"))
    filename, content = render_bank_export(rows, template.template, data.format or template.format)
    checksum = hashlib.sha256(content).hexdigest(); encoded = base64.b64encode(content).decode("ascii")
    artifact = PayrollExportArtifact(organization_id=actor.organization_id, payroll_run_id=run.id, kind="bank_payout", format=data.format or template.format, template_version=f"{template.bank_code}:{template.version}", storage_key=f"inline:{checksum}", filename=filename, content_ciphertext=encrypt_secret(encoded), checksum=checksum, expires_at=datetime.now(timezone.utc) + timedelta(minutes=15), created_by_account_id=actor.account_id)
    db.add(artifact); await db.flush()
    await record_change(db, actor=actor, topic="payroll", aggregate_type="payroll_export_artifact", aggregate_id=artifact.id, operation="generated", after={"run_id": run.id, "kind": artifact.kind, "format": artifact.format, "template_version": artifact.template_version, "checksum": checksum, "expires_at": artifact.expires_at.isoformat()})
    await db.commit()
    # Do not return the rendered file inline: it may contain decrypted bank
    # account numbers.  Callers receive only a short-lived authenticated
    # artifact handle and download it through the guarded GET endpoint.
    return {"artifact_id": artifact.id, "filename": filename, "format": data.format or template.format, "checksum": checksum, "is_provisional": template.is_provisional, "expires_at": artifact.expires_at.isoformat(), "download_url": f"/v1/erp/payroll/exports/{artifact.id}"}


@router.post("/runs/{run_id}/cash-vouchers")
async def create_cash_vouchers(run_id: int, report_format: Literal["csv", "xlsx"] = Query(default="csv", alias="format"), db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "export")
    run = await db.scalar(select(PayrollRun).where(PayrollRun.id == run_id, PayrollRun.organization_id == actor.organization_id))
    if not run or run.status != "approved": raise HTTPException(status_code=409, detail={"code": "payroll_run_not_exportable"})
    slips = list((await db.execute(select(Payslip).where(Payslip.payroll_run_id == run.id).order_by(Payslip.employee_id))).scalars().all())
    employees = {row.id: row for row in (await db.execute(select(Employee).where(Employee.id.in_([slip.employee_id for slip in slips])))).scalars().all()}
    rows = []
    for slip in slips:
        profile = await db.scalar(select(EmployeePayrollProfile).where(EmployeePayrollProfile.employee_id == slip.employee_id, EmployeePayrollProfile.organization_id == actor.organization_id, EmployeePayrollProfile.effective_from <= run.tax_point_date, (EmployeePayrollProfile.effective_to.is_(None) | (EmployeePayrollProfile.effective_to >= run.tax_point_date))).order_by(EmployeePayrollProfile.effective_from.desc()).limit(1))
        if profile and profile.payment_method != "bank":
            rows.append({"voucher_reference": f"{run.run_number}-{slip.employee_id}", "employee_id": slip.employee_id, "employee_name": employees[slip.employee_id].name, "payment_method": profile.payment_method, "amount": str(slip.net_pay), "currency": (run.config_snapshot or {}).get("currency", "MNT"), "period": run.settlement_key, "recipient_signature": ""})
    if not rows: raise HTTPException(status_code=422, detail={"code": "payroll_no_manual_payments"})
    columns = [{"key": key, "header": key.replace("_", " ").title()} for key in rows[0]]
    filename, content = render_bank_export(rows, {"columns": columns, "filename": f"cash-vouchers-{run.run_number}.{report_format}"}, report_format)
    checksum = hashlib.sha256(content).hexdigest()
    artifact = PayrollExportArtifact(organization_id=actor.organization_id, payroll_run_id=run.id, kind="cash_vouchers", format=report_format, template_version="manual-v1", storage_key=f"inline:{checksum}", filename=filename, content_ciphertext=encrypt_secret(base64.b64encode(content).decode("ascii")), checksum=checksum, expires_at=datetime.now(timezone.utc) + timedelta(minutes=15), created_by_account_id=actor.account_id)
    db.add(artifact); await db.flush()
    await record_change(db, actor=actor, topic="payroll", aggregate_type="payroll_export_artifact", aggregate_id=artifact.id, operation="generated", after={"run_id": run.id, "kind": artifact.kind, "format": artifact.format, "checksum": checksum})
    await db.commit()
    return {"artifact_id": artifact.id, "filename": filename, "format": report_format, "checksum": checksum, "expires_at": artifact.expires_at.isoformat(), "download_url": f"/v1/erp/payroll/exports/{artifact.id}"}


@router.get("/exports/{artifact_id}")
async def download_payroll_export(artifact_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "export")
    artifact = await db.scalar(select(PayrollExportArtifact).where(PayrollExportArtifact.id == artifact_id, PayrollExportArtifact.organization_id == actor.organization_id))
    if not artifact: raise HTTPException(status_code=404, detail="Payroll export not found")
    if artifact.expires_at <= datetime.now(timezone.utc): raise HTTPException(status_code=410, detail={"code": "payroll_export_expired"})
    try:
        content = base64.b64decode(decrypt_secret(artifact.content_ciphertext), validate=True)
    except (ValueError, TypeError):
        raise HTTPException(status_code=500, detail={"code": "payroll_export_decryption_failed"})
    if hashlib.sha256(content).hexdigest() != artifact.checksum:
        raise HTTPException(status_code=409, detail={"code": "payroll_export_checksum_mismatch"})
    artifact.downloaded_at = datetime.now(timezone.utc)
    await record_change(db, actor=actor, topic="payroll", aggregate_type="payroll_export_artifact", aggregate_id=artifact.id, operation="downloaded", after={"run_id": artifact.payroll_run_id, "format": artifact.format, "checksum": artifact.checksum})
    await db.commit()
    media_type = "application/json" if artifact.format == "json" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if artifact.format == "xlsx" else "text/csv; charset=utf-8"
    return Response(content=content, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{artifact.filename}"', "X-Export-Checksum": artifact.checksum})


@router.get("/runs/{run_id}/reports/{report_kind}")
async def payroll_report(run_id: int, report_kind: str, report_format: Literal["json", "csv", "xlsx", "pdf"] = Query(default="json", alias="format"), tt11_period: Literal["run", "quarter", "annual"] = Query(default="run", alias="period"), db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "export")
    run = await db.scalar(select(PayrollRun).where(PayrollRun.id == run_id, PayrollRun.organization_id == actor.organization_id))
    if not run: raise HTTPException(status_code=404, detail="Payroll run not found")
    if run.status not in {"approved", "posted", "payment_prepared", "partially_settled", "settled", "payslips_released", "paid"}:
        raise HTTPException(status_code=409, detail={"code": "payroll_run_not_reportable", "status": run.status})
    report_runs = [run]
    if report_kind == "tt11" and tt11_period != "run":
        run_query = select(PayrollRun).where(
            PayrollRun.organization_id == actor.organization_id,
            PayrollRun.status.in_(("approved", "posted", "payment_prepared", "partially_settled", "settled", "payslips_released", "paid")),
            PayrollRun.tax_point_date >= date(run.tax_point_date.year, 1, 1),
            PayrollRun.tax_point_date < date(run.tax_point_date.year + 1, 1, 1),
        )
        if tt11_period == "quarter":
            quarter_start_month = ((run.tax_point_date.month - 1) // 3) * 3 + 1
            quarter_start = date(run.tax_point_date.year, quarter_start_month, 1)
            next_quarter = date(run.tax_point_date.year + (1 if quarter_start_month == 10 else 0), 1 if quarter_start_month == 10 else quarter_start_month + 3, 1)
            run_query = run_query.where(PayrollRun.tax_point_date >= quarter_start, PayrollRun.tax_point_date < next_quarter)
        report_runs = list((await db.execute(run_query.order_by(PayrollRun.tax_point_date, PayrollRun.id))).scalars().all())
    slips = (await db.execute(select(Payslip).where(Payslip.payroll_run_id.in_([item.id for item in report_runs])))).scalars().all()
    payload = []
    for row in slips:
        profile_snapshot = row.employee_profile_snapshot or {}
        input_snapshot = row.input_snapshot or {}
        override = input_snapshot.get("override") or {}
        resolved_units = input_snapshot.get("resolved_units") or {}
        pit_trace = (row.calculation_trace or {}).get("pit") or {}
        shi_trace = (row.calculation_trace or {}).get("shi") or {}
        payload.append({"employee_id": row.employee_id, "insured_code": profile_snapshot.get("insured_code"), "payable_days": str(override.get("payable_workdays", resolved_units.get("payable_workdays", "0"))), "gross": str(row.gross), "shi_subject_gross": str(row.shi_subject_gross), "taxable_income": str(row.taxable_income), "shi_base": str(row.shi_base), "employee_shi": str(row.employee_shi), "employer_shi": str(row.employer_shi), "shi_by_fund": shi_trace.get("by_fund") or {}, "shi_rules": shi_trace.get("rules") or [], "pit_before_relief": str(pit_trace.get("before_relief", "0")), "pit": str(row.pit), "pit_relief": str(row.pit_relief), "net_pay": str(row.net_pay)})
    if report_kind == "nd7a":
        organization = await db.get(Organization, actor.organization_id)
        result: dict[str, Any] = {"run": _run_out(run), "report": nd7a_summary(payload, {"organization_id": actor.organization_id, "organization_name": organization.name if organization else None, "currency": organization.base_currency if organization else "MNT"})}
        export_rows = [result["report"]["employer"]]
    elif report_kind == "nd7b":
        result = {"run": _run_out(run), "rows": nd7b_rows(payload)}
        export_rows = result["rows"]
    elif report_kind == "nd7":
        result: dict[str, Any] = {"run": _run_out(run), "summary": nd7_summary(payload)}
        export_rows = [result["summary"]]
    elif report_kind == "nd8":
        result = {"run": _run_out(run), "rows": nd8_rows(payload)}
        export_rows = result["rows"]
    elif report_kind == "tt11":
        result = {"run": _run_out(run), "summary": tt11_summary(payload), "rows": payload}
        export_rows = result["rows"]
    else:
        raise HTTPException(status_code=404, detail="Unknown payroll report")
    if report_format == "json":
        return result
    template = await db.scalar(select(PayrollReportTemplate).where(PayrollReportTemplate.organization_id == actor.organization_id, PayrollReportTemplate.kind == report_kind, PayrollReportTemplate.status == "published").order_by(PayrollReportTemplate.version.desc()).limit(1))
    columns = (template.template or {}).get("columns") if template else None
    columns = columns or [{"key": key, "header": key} for key in (list(export_rows[0].keys()) if export_rows else [])]
    required = set((template.required_keys if template else []) or [])
    configured = {column.get("key") for column in columns if isinstance(column, dict)}
    if required - configured:
        raise HTTPException(status_code=409, detail={"code": "payroll_report_template_invalid", "missing": sorted(required - configured), "remediation": "Restore required statutory columns before exporting."})
    if report_format == "pdf":
        filename, content = f"{report_kind}-{run.settlement_key}.pdf", render_report_pdf(export_rows, columns)
    else:
        filename, content = render_bank_export(export_rows, {"columns": columns, "filename": f"{report_kind}-{run.settlement_key}.{report_format}"}, report_format)
    media_type = "application/pdf" if report_format == "pdf" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if report_format == "xlsx" else "text/csv; charset=utf-8"
    return Response(content=content, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{filename}"'})
