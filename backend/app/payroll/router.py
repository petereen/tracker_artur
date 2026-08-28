from __future__ import annotations

import base64
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
    PayrollBankEntry, PayrollExportArtifact, PayrollPeriod, PayrollPostingProfile, PayrollRun, PayrollSalaryComponentMaster, Payslip, PayslipLineItem, IdempotencyRecord,
    PayrollTaxExemptionCategory,
    SalaryComponent, SalaryStructure, SalaryStructureVersion, SHIRateTier, PITBracketTier, TaxReliefTier,
    StatutoryConfigProfile,
)
from app.services.enterprise_events import record_change
from app.services.secret_box import decrypt_secret, encrypt_secret
from app.services.user_notifications import create_notifications
from .exports import nd7_summary, nd8_rows, render_bank_export, render_protected_payslip, tt11_summary
from .schemas import (
    BankAccountInput, BankExportProfileInput, BankExportRequest, CalculateRunInput,
    EmployeePayrollInput, PayrollRunInput, PITBracketInput, PostingProfileInput,
    PublishProfileInput, ReliefTierInput, SalaryStructureInput, StatutoryProfileInput,
    BenefitApplicationInput, BenefitApplicationReviewInput, BenefitClaimInput,
    PayslipPublicationInput, PayrollApprovalInput, ProtectedPayslipInput, ReconciliationResolutionInput,
    ReviewDecisionInput, TaxDeclarationInput, TaxExemptionCategoryInput, TaxProofInput,
    AdditionalSalaryInput, BankEntryInput, BulkSalaryStructureAssignmentInput, GetEmployeesInput,
    PayrollCancelInput, PayrollEntryInput, PayrollPeriodInput, SalaryComponentMasterInput,
    SalaryStructureAssignmentInput,
)
from .tax_benefits import approved_tax_adjustments, validate_claim_balance
from .service import (
    calculate_run, canonical_payout_rows, create_bank_account, create_employee_profile,
    create_replacement_run, create_run, create_salary_structure, create_statutory_profile,
    delete_salary_structure, delete_statutory_profile, load_rules, post_run, profile_out, publish_profile, reconcile_run, reverse_run,
    update_salary_structure, update_statutory_profile,
)
from .frappe_service import (
    additional_salary_out, bank_entry_out, cancel_additional_salary, component_master_out,
    create_additional_salary, create_assignment, create_bulk_assignments, create_component_master,
    create_payroll_entry, create_payroll_period, create_salary_slips, get_employees,
    make_bank_entry, period_out, submit_additional_salary, submit_bank_entry,
    submit_salary_slips, update_component_master,
)


router = APIRouter()


async def payroll_capability(db: AsyncSession, actor: ActorContext, action: str) -> None:
    await require_capability(db, actor, "payroll", action)


def _is_payroll_admin(actor: ActorContext) -> bool:
    return bool({"admin", "manager", "hr"}.intersection(actor.roles))


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
    return {"id": run.id, "run_number": run.run_number, "run_type": run.run_type, "period_start": run.period_start.isoformat(), "period_end": run.period_end.isoformat(), "settlement_key": run.settlement_key, "tax_point_date": run.tax_point_date.isoformat(), "status": run.status, "workflow_version": run.workflow_version, "document_status": run.document_status, "payroll_frequency": run.payroll_frequency, "posting_date": run.posting_date.isoformat() if run.posting_date else None, "employee_filter": run.employee_filter or {}, "employee_ids": list((run.input_snapshot or {}).get("employee_ids") or []), "salary_slips_created": run.salary_slips_created, "salary_slips_submitted": run.salary_slips_submitted, "payment_status": run.payment_status, "payment_account_id": run.payment_account_id, "cost_center_id": run.cost_center_id, "payroll_period_id": run.payroll_period_id, "bank_entry_id": run.bank_entry_id, "reversal_of_run_id": run.reversal_of_run_id, "replacement_of_run_id": run.replacement_of_run_id, "statutory_profile_id": run.statutory_profile_id, "posting_profile_id": run.posting_profile_id, "erp_document_id": run.erp_document_id, "total_gross": str(run.total_gross), "total_employee_shi": str(run.total_employee_shi), "total_employer_shi": str(run.total_employer_shi), "total_pit": str(run.total_pit), "total_net": str(run.total_net), "snapshot_checksum": run.snapshot_checksum, "reconciliation": run.reconciliation_snapshot or {}, "approval_workflow": run.approval_workflow or {}, "approved_at": run.approved_at.isoformat() if run.approved_at else None, "posted_at": run.posted_at.isoformat() if run.posted_at else None, "payslips_published_at": run.payslips_published_at.isoformat() if run.payslips_published_at else None}


def _slip_out(slip: Payslip, lines: list[PayslipLineItem] | None = None) -> dict[str, Any]:
    result = {"id": slip.id, "payroll_run_id": slip.payroll_run_id, "employee_id": slip.employee_id, "document_status": slip.document_status, "submitted_at": slip.submitted_at.isoformat() if slip.submitted_at else None, "published_at": slip.published_at.isoformat() if slip.published_at else None, "cancelled_at": slip.cancelled_at.isoformat() if slip.cancelled_at else None, "gross": str(slip.gross), "taxable_income": str(slip.taxable_income), "shi_subject_gross": str(slip.shi_subject_gross), "shi_base": str(slip.shi_base), "employee_shi": str(slip.employee_shi), "employer_shi": str(slip.employer_shi), "pit": str(slip.pit), "pit_relief": str(slip.pit_relief), "advance_offset": str(slip.advance_offset), "net_pay": str(slip.net_pay), "snapshot_checksum": slip.snapshot_checksum, "ytd": slip.ytd_snapshot, "trace": slip.calculation_trace}
    if lines is not None: result["lines"] = [{"code": row.component_code, "label": row.label, "kind": row.component_kind, "amount": str(row.amount), "taxable": row.taxable, "shi_subject": row.shi_subject, "payer": row.payer, "formula": row.formula_snapshot, "trace": row.trace} for row in lines]
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
    profile = await db.scalar(select(StatutoryConfigProfile).where(StatutoryConfigProfile.id == profile_id, StatutoryConfigProfile.organization_id == actor.organization_id))
    if not profile: raise HTTPException(status_code=404, detail="Profile not found")
    await update_statutory_profile(db, actor, profile, data)
    await record_change(db, actor=actor, topic="payroll", aggregate_type="statutory_config_profile", aggregate_id=profile.id, operation="updated", after={"code": profile.code, "version": profile.version, "status": profile.status})
    await db.commit(); await db.refresh(profile)
    return profile_out(profile, rates=data.shi_rates, brackets=data.pit_brackets, reliefs=data.relief_tiers)


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
        result.append({"id": structure.id, "code": structure.code, "name": structure.name, "version": structure.version, "status": structure.status, "effective_from": structure.effective_from.isoformat(), "effective_to": structure.effective_to.isoformat() if structure.effective_to else None, "currency": structure.currency, "checksum": structure.checksum, "components": [{"id": row.id, "component_master_id": row.component_master_id, "code": row.code, "name": row.name, "component_kind": row.component_kind, "formula": row.formula, "proration_basis": row.proration_basis, "is_taxable": row.is_taxable, "is_shi_subject": row.is_shi_subject, "is_non_taxable_allowance": row.is_non_taxable_allowance, "is_flexible_benefit": row.is_flexible_benefit, "max_benefit_amount_yearly": str(row.max_benefit_amount_yearly), "pay_against_benefit_claim": row.pay_against_benefit_claim, "only_tax_impact": row.only_tax_impact, "payer": row.payer, "position": row.position, "account_id": row.account_id, "cost_center_id": row.cost_center_id} for row in components]})
    return result


@router.post("/salary-structures", status_code=status.HTTP_201_CREATED)
async def create_structure(data: SalaryStructureInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "administer")
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
    others = (await db.execute(select(SalaryStructure).where(SalaryStructure.organization_id == actor.organization_id, SalaryStructure.id != structure.id, SalaryStructure.code == structure.code, SalaryStructure.status.in_(("published", "active"))))).scalars().all()
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
    structure = await db.scalar(select(SalaryStructure).where(SalaryStructure.id == structure_id, SalaryStructure.organization_id == actor.organization_id))
    if not structure: raise HTTPException(status_code=404, detail="Salary structure not found")
    await update_salary_structure(db, actor, structure, data)
    await record_change(db, actor=actor, topic="payroll", aggregate_type="salary_structure", aggregate_id=structure.id, operation="updated", after={"code": structure.code, "version": structure.version, "status": structure.status})
    await db.commit(); await db.refresh(structure)
    return {"id": structure.id, "code": structure.code, "name": structure.name, "version": structure.version, "status": structure.status, "effective_from": structure.effective_from.isoformat(), "effective_to": structure.effective_to.isoformat() if structure.effective_to else None, "currency": structure.currency, "checksum": structure.checksum, "components": [{"code": item.code, "name": item.name, "component_kind": item.component_kind, "formula": item.formula, "proration_basis": item.proration_basis, "is_taxable": item.is_taxable, "is_shi_subject": item.is_shi_subject, "is_non_taxable_allowance": item.is_non_taxable_allowance, "is_flexible_benefit": item.is_flexible_benefit, "max_benefit_amount_yearly": str(item.max_benefit_amount_yearly), "pay_against_benefit_claim": item.pay_against_benefit_claim, "only_tax_impact": item.only_tax_impact, "account_id": item.account_id, "cost_center_id": item.cost_center_id} for item in data.components]}


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
    profile = await db.scalar(select(EmployeePayrollProfile).where(EmployeePayrollProfile.organization_id == actor.organization_id, EmployeePayrollProfile.employee_id == employee_id).order_by(EmployeePayrollProfile.effective_from.desc()).limit(1))
    if not profile: raise HTTPException(status_code=404, detail="Employee payroll profile not found")
    accounts = (await db.execute(select(EmployeeBankAccount).where(EmployeeBankAccount.employee_payroll_profile_id == profile.id).order_by(EmployeeBankAccount.is_primary.desc(), EmployeeBankAccount.valid_from.desc()))).scalars().all()
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
    row = PayrollBankExportProfile(organization_id=actor.organization_id, **data.model_dump()); db.add(row); await db.flush()
    await record_change(db, actor=actor, topic="payroll", aggregate_type="payroll_bank_export_profile", aggregate_id=row.id, operation="created", after={"bank_code": row.bank_code, "version": row.version, "format": row.format, "is_provisional": row.is_provisional})
    await db.commit(); await db.refresh(row)
    return {"id": row.id, "bank_code": row.bank_code, "version": row.version, "status": row.status, "format": row.format, "is_provisional": row.is_provisional}


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


@router.get("/salary-components")
async def list_salary_component_masters(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "view")
    rows = (await db.execute(select(PayrollSalaryComponentMaster).where(PayrollSalaryComponentMaster.organization_id == actor.organization_id).order_by(PayrollSalaryComponentMaster.code))).scalars().all()
    return [component_master_out(row) for row in rows]


@router.post("/salary-components", status_code=status.HTTP_201_CREATED)
async def create_salary_component_master_route(data: SalaryComponentMasterInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "administer")
    row = await create_component_master(db, actor, data)
    await record_change(db, actor=actor, topic="payroll", aggregate_type="salary_component_master", aggregate_id=row.id, operation="created", after={"code": row.code})
    await db.commit(); await db.refresh(row)
    return component_master_out(row)


@router.put("/salary-components/{component_id}")
async def update_salary_component_master_route(component_id: int, data: SalaryComponentMasterInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "administer")
    row = await db.scalar(select(PayrollSalaryComponentMaster).where(PayrollSalaryComponentMaster.id == component_id, PayrollSalaryComponentMaster.organization_id == actor.organization_id))
    if not row:
        raise HTTPException(status_code=404, detail="Salary component not found")
    row = await update_component_master(db, actor, row, data)
    await record_change(db, actor=actor, topic="payroll", aggregate_type="salary_component_master", aggregate_id=row.id, operation="updated", after={"code": row.code})
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
    query = select(AdditionalSalary, PayrollSalaryComponentMaster.code).join(PayrollSalaryComponentMaster, PayrollSalaryComponentMaster.id == AdditionalSalary.salary_component_id).where(AdditionalSalary.organization_id == actor.organization_id)
    if employee_id is not None:
        scoped = await _employee_scope(db, actor, employee_id)
        query = query.where(AdditionalSalary.employee_id == scoped)
    if status_filter:
        query = query.where(AdditionalSalary.status == status_filter)
    rows = (await db.execute(query.order_by(AdditionalSalary.payroll_date.desc(), AdditionalSalary.id.desc()))).all()
    return [additional_salary_out(row, code) for row, code in rows]


@router.post("/additional-salaries", status_code=status.HTTP_201_CREATED)
async def create_additional_salary_route(data: AdditionalSalaryInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    if not _is_payroll_admin(actor) and actor.employee_id != data.employee_id:
        raise HTTPException(status_code=403, detail={"code": "payroll_employee_scope_required"})
    await payroll_capability(db, actor, "create")
    row = await create_additional_salary(db, actor, data)
    await record_change(db, actor=actor, topic="payroll", aggregate_type="additional_salary", aggregate_id=row.id, operation="created", after={"number": row.number, "employee_id": row.employee_id, "amount": str(row.amount)})
    await db.commit(); await db.refresh(row)
    component = await db.get(PayrollSalaryComponentMaster, row.salary_component_id)
    return additional_salary_out(row, component.code if component else None)


@router.post("/additional-salaries/{salary_id}/submit")
async def submit_additional_salary_route(salary_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "approve")
    row = await db.scalar(select(AdditionalSalary).where(AdditionalSalary.id == salary_id, AdditionalSalary.organization_id == actor.organization_id).with_for_update())
    if not row:
        raise HTTPException(status_code=404, detail="Additional Salary not found")
    await submit_additional_salary(db, actor, row)
    await record_change(db, actor=actor, topic="payroll", aggregate_type="additional_salary", aggregate_id=row.id, operation="submitted", after={"status": row.status})
    await db.commit(); await db.refresh(row)
    component = await db.get(PayrollSalaryComponentMaster, row.salary_component_id)
    return additional_salary_out(row, component.code if component else None)


@router.post("/additional-salaries/{salary_id}/cancel")
async def cancel_additional_salary_route(salary_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "approve")
    row = await db.scalar(select(AdditionalSalary).where(AdditionalSalary.id == salary_id, AdditionalSalary.organization_id == actor.organization_id).with_for_update())
    if not row:
        raise HTTPException(status_code=404, detail="Additional Salary not found")
    await cancel_additional_salary(db, actor, row)
    await record_change(db, actor=actor, topic="payroll", aggregate_type="additional_salary", aggregate_id=row.id, operation="cancelled", after={"status": row.status})
    await db.commit(); await db.refresh(row)
    component = await db.get(PayrollSalaryComponentMaster, row.salary_component_id)
    return additional_salary_out(row, component.code if component else None)


@router.post("/payroll-entries", status_code=status.HTTP_201_CREATED)
async def create_payroll_entry_route(data: PayrollEntryInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "create")
    run = await create_payroll_entry(db, actor, data)
    await record_change(db, actor=actor, topic="payroll", aggregate_type="payroll_entry", aggregate_id=run.id, operation="created", after={"number": run.run_number, "workflow_version": run.workflow_version})
    await db.commit(); await db.refresh(run)
    return _run_out(run)


@router.get("/payroll-entries")
async def list_payroll_entries(status_filter: str | None = Query(default=None, alias="status"), db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "view")
    query = select(PayrollRun).where(PayrollRun.organization_id == actor.organization_id, PayrollRun.workflow_version == "frappe_v1")
    if status_filter:
        query = query.where(PayrollRun.document_status == status_filter)
    rows = (await db.execute(query.order_by(PayrollRun.posting_date.desc().nullslast(), PayrollRun.id.desc()))).scalars().all()
    return [_run_out(row) for row in rows]


@router.get("/payroll-entries/{entry_id}")
async def get_payroll_entry(entry_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "view")
    run = await db.scalar(select(PayrollRun).where(PayrollRun.id == entry_id, PayrollRun.organization_id == actor.organization_id, PayrollRun.workflow_version == "frappe_v1"))
    if not run:
        raise HTTPException(status_code=404, detail="Payroll Entry not found")
    slips = (await db.execute(select(Payslip).where(Payslip.payroll_run_id == run.id).order_by(Payslip.employee_id))).scalars().all()
    bank_entry = await db.scalar(select(PayrollBankEntry).where(PayrollBankEntry.payroll_run_id == run.id))
    serialized_slips = [_slip_out(row) for row in slips]
    return {**_run_out(run), "salary_slips": serialized_slips, "payslips": serialized_slips, "bank_entry": bank_entry_out(bank_entry) if bank_entry else None}


@router.post("/payroll-entries/{entry_id}/get-employees")
async def get_payroll_entry_employees(entry_id: int, data: GetEmployeesInput = GetEmployeesInput(), db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "create")
    run = await db.scalar(select(PayrollRun).where(PayrollRun.id == entry_id, PayrollRun.organization_id == actor.organization_id, PayrollRun.workflow_version == "frappe_v1").with_for_update())
    if not run:
        raise HTTPException(status_code=404, detail="Payroll Entry not found")
    result = await get_employees(db, actor, run, data)
    await record_change(db, actor=actor, topic="payroll", aggregate_type="payroll_entry", aggregate_id=run.id, operation="employees_selected", after={"employee_ids": result["employee_ids"], "errors": len(result["errors"]), "warnings": len(result["warnings"])})
    await db.commit(); await db.refresh(run)
    return {"payroll_entry": _run_out(run), **result}


@router.post("/payroll-entries/{entry_id}/create-salary-slips")
async def create_payroll_entry_salary_slips(entry_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
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
    query = select(Payslip).join(PayrollRun, PayrollRun.id == Payslip.payroll_run_id).where(Payslip.organization_id == actor.organization_id, PayrollRun.workflow_version == "frappe_v1")
    if run_id is not None:
        query = query.where(Payslip.payroll_run_id == run_id)
    if employee_id is not None:
        query = query.where(Payslip.employee_id == await _employee_scope(db, actor, employee_id))
    if status_filter:
        query = query.where(Payslip.document_status == status_filter)
    rows = (await db.execute(query.order_by(Payslip.created_at.desc()))).scalars().all()
    return [_slip_out(row) for row in rows]


@router.get("/reports/salary-register")
async def salary_register_report(run_id: int | None = None, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "view")
    query = select(Payslip, PayrollRun).join(PayrollRun, PayrollRun.id == Payslip.payroll_run_id).where(Payslip.organization_id == actor.organization_id, PayrollRun.workflow_version == "frappe_v1")
    if run_id is not None:
        query = query.where(Payslip.payroll_run_id == run_id)
    rows = (await db.execute(query.order_by(Payslip.employee_id))).all()
    return [{"salary_slip_id": slip.id, "payroll_entry_id": run.id, "payroll_entry_number": run.run_number, "employee_id": slip.employee_id, "gross": str(slip.gross), "employee_shi": str(slip.employee_shi), "employer_shi": str(slip.employer_shi), "pit": str(slip.pit), "net_pay": str(slip.net_pay), "status": slip.document_status} for slip, run in rows]


@router.get("/reports/bank-remittance")
async def bank_remittance_report(run_id: int | None = None, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "export")
    query = select(Payslip, PayrollRun, EmployeePayrollProfile).join(PayrollRun, PayrollRun.id == Payslip.payroll_run_id).join(EmployeePayrollProfile, (EmployeePayrollProfile.employee_id == Payslip.employee_id) & (EmployeePayrollProfile.organization_id == actor.organization_id)).where(Payslip.organization_id == actor.organization_id, PayrollRun.workflow_version == "frappe_v1", EmployeePayrollProfile.effective_from <= PayrollRun.tax_point_date, (EmployeePayrollProfile.effective_to.is_(None) | (EmployeePayrollProfile.effective_to >= PayrollRun.tax_point_date)))
    if run_id is not None:
        query = query.where(Payslip.payroll_run_id == run_id)
    rows = (await db.execute(query.order_by(Payslip.employee_id))).all()
    result = []
    for slip, run, profile in rows:
        account = await db.scalar(select(EmployeeBankAccount).where(EmployeeBankAccount.employee_payroll_profile_id == profile.id, EmployeeBankAccount.is_primary.is_(True)).order_by(EmployeeBankAccount.id.desc()))
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


@router.get("/runs")
async def list_payroll_runs(status_filter: str | None = Query(default=None, alias="status"), db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "view")
    query = select(PayrollRun).where(PayrollRun.organization_id == actor.organization_id)
    if status_filter: query = query.where(PayrollRun.status == status_filter)
    return [_run_out(row) for row in (await db.execute(query.order_by(PayrollRun.period_end.desc(), PayrollRun.id.desc()))).scalars().all()]


@router.post("/runs/{run_id}/calculate")
async def calculate_payroll_run(run_id: int, data: CalculateRunInput = CalculateRunInput(), db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "calculate")
    run = await db.scalar(select(PayrollRun).where(PayrollRun.id == run_id, PayrollRun.organization_id == actor.organization_id).with_for_update())
    if not run: raise HTTPException(status_code=404, detail="Payroll run not found")
    if run.config_snapshot.get("is_example") and not data.acknowledge_example: raise HTTPException(status_code=409, detail={"code": "payroll_example_profile_requires_acknowledgement"})
    await calculate_run(db, actor, run)
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
    await payroll_capability(db, actor, "approve")
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


@router.post("/runs/{run_id}/post")
async def post_payroll_run(run_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "post")
    run = await db.scalar(select(PayrollRun).where(PayrollRun.id == run_id, PayrollRun.organization_id == actor.organization_id).with_for_update())
    if not run: raise HTTPException(status_code=404, detail="Payroll run not found")
    profiles = list((await db.execute(select(EmployeePayrollProfile).where(EmployeePayrollProfile.organization_id == actor.organization_id, EmployeePayrollProfile.employee_id.in_((run.input_snapshot or {}).get("employee_ids") or []), EmployeePayrollProfile.effective_from <= run.tax_point_date, (EmployeePayrollProfile.effective_to.is_(None) | (EmployeePayrollProfile.effective_to >= run.tax_point_date))))).scalars().all())
    required_export_kinds = {"bank_payout" if profile.payment_method == "bank" else "cash_vouchers" for profile in profiles}
    created_export_kinds = set((await db.execute(select(PayrollExportArtifact.kind).where(PayrollExportArtifact.payroll_run_id == run.id, PayrollExportArtifact.kind.in_(required_export_kinds)))).scalars().all()) if required_export_kinds else set()
    if required_export_kinds - created_export_kinds: raise HTTPException(status_code=409, detail={"code": "payroll_payout_files_required", "missing": sorted(required_export_kinds - created_export_kinds)})
    document = await post_run(db, actor, run)
    await record_change(db, actor=actor, topic="payroll", aggregate_type="payroll_run", aggregate_id=run.id, operation="posted", after={"status": run.status, "erp_document_id": document.id, "snapshot_checksum": run.snapshot_checksum})
    await db.commit(); await db.refresh(run); return {**_run_out(run), "erp_document_id": document.id}


@router.post("/runs/{run_id}/reverse")
async def reverse_payroll_run(run_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "post")
    run = await db.scalar(select(PayrollRun).where(PayrollRun.id == run_id, PayrollRun.organization_id == actor.organization_id).with_for_update())
    if not run: raise HTTPException(status_code=404, detail="Payroll run not found")
    reversal = await reverse_run(db, actor, run)
    await record_change(db, actor=actor, topic="payroll", aggregate_type="payroll_run", aggregate_id=reversal.id, operation="reversal_created", after={"reversal_of_run_id": run.id, "source_checksum": run.snapshot_checksum})
    await db.commit(); await db.refresh(reversal)
    return _run_out(reversal)


@router.post("/runs/{run_id}/replace", status_code=status.HTTP_201_CREATED)
async def replace_payroll_run(run_id: int, data: PayrollRunInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "create")
    source = await db.scalar(select(PayrollRun).where(PayrollRun.id == run_id, PayrollRun.organization_id == actor.organization_id).with_for_update())
    if not source: raise HTTPException(status_code=404, detail="Payroll run not found")
    replacement = await create_replacement_run(db, actor, source, data)
    await record_change(db, actor=actor, topic="payroll", aggregate_type="payroll_run", aggregate_id=replacement.id, operation="replacement_created", after={"replacement_of_run_id": source.id, "source_checksum": source.snapshot_checksum})
    await db.commit(); await db.refresh(replacement)
    return _run_out(replacement)


@router.get("/runs/{run_id}")
async def get_payroll_run(run_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "view")
    run = await db.scalar(select(PayrollRun).where(PayrollRun.id == run_id, PayrollRun.organization_id == actor.organization_id))
    if not run: raise HTTPException(status_code=404, detail="Payroll run not found")
    slips = (await db.execute(select(Payslip).where(Payslip.payroll_run_id == run.id).order_by(Payslip.employee_id))).scalars().all()
    payout_artifact_kinds = sorted(set((await db.execute(select(PayrollExportArtifact.kind).where(PayrollExportArtifact.payroll_run_id == run.id, PayrollExportArtifact.kind.in_(("bank_payout", "cash_vouchers"))))).scalars().all()))
    return {**_run_out(run), "payslips": [_slip_out(row) for row in slips], "payout_artifact_kinds": payout_artifact_kinds}


@router.get("/runs/{run_id}/payslips")
async def get_run_payslips(run_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "view")
    run = await db.scalar(select(PayrollRun).where(PayrollRun.id == run_id, PayrollRun.organization_id == actor.organization_id))
    if not run: raise HTTPException(status_code=404, detail="Payroll run not found")
    slips = (await db.execute(select(Payslip).where(Payslip.payroll_run_id == run.id).order_by(Payslip.employee_id))).scalars().all()
    return [_slip_out(row, list((await db.execute(select(PayslipLineItem).where(PayslipLineItem.payslip_id == row.id).order_by(PayslipLineItem.position))).scalars().all())) for row in slips]


@router.get("/me/payslips")
async def get_my_payslips(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    if actor.employee_id is None: return []
    slips = (await db.execute(select(Payslip).join(PayrollRun, PayrollRun.id == Payslip.payroll_run_id).where(Payslip.organization_id == actor.organization_id, Payslip.employee_id == actor.employee_id, Payslip.document_status != "cancelled", PayrollRun.status.in_(("posted", "paid")), PayrollRun.payslips_published_at.is_not(None)).order_by(Payslip.created_at.desc()))).scalars().all()
    return [_slip_out(row) for row in slips]


@router.get("/me/payslips/{payslip_id}/download")
async def download_my_payslip(payslip_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    if actor.employee_id is None:
        raise HTTPException(status_code=404, detail="Payslip not found")
    slip = await db.scalar(select(Payslip).join(PayrollRun, PayrollRun.id == Payslip.payroll_run_id).where(Payslip.id == payslip_id, Payslip.organization_id == actor.organization_id, Payslip.employee_id == actor.employee_id, Payslip.document_status != "cancelled", PayrollRun.status.in_(("posted", "paid")), PayrollRun.payslips_published_at.is_not(None)))
    if not slip:
        raise HTTPException(status_code=404, detail="Payslip not found")
    lines = list((await db.execute(select(PayslipLineItem).where(PayslipLineItem.payslip_id == slip.id).order_by(PayslipLineItem.position))).scalars().all())
    payload = json.dumps(_slip_out(slip, lines), ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    await record_change(db, actor=actor, topic="payroll", aggregate_type="payslip", aggregate_id=slip.id, operation="self_downloaded", after={"payroll_run_id": slip.payroll_run_id, "checksum": slip.snapshot_checksum})
    await db.commit()
    return Response(content=payload, media_type="application/json", headers={"Content-Disposition": f'attachment; filename="payslip-{slip.id}.json"', "X-Payslip-Checksum": slip.snapshot_checksum})


@router.post("/me/payslips/{payslip_id}/protected-download")
async def download_protected_payslip(payslip_id: int, data: ProtectedPayslipInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    if actor.employee_id is None: raise HTTPException(status_code=404, detail="Payslip not found")
    slip = await db.scalar(select(Payslip).join(PayrollRun, PayrollRun.id == Payslip.payroll_run_id).where(Payslip.id == payslip_id, Payslip.organization_id == actor.organization_id, Payslip.employee_id == actor.employee_id, Payslip.document_status != "cancelled", PayrollRun.status.in_(("posted", "paid")), PayrollRun.payslips_published_at.is_not(None)))
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
    await payroll_capability(db, actor, "post")
    run = await db.scalar(select(PayrollRun).where(PayrollRun.id == run_id, PayrollRun.organization_id == actor.organization_id).with_for_update())
    if not run: raise HTTPException(status_code=404, detail="Payroll run not found")
    if run.status not in {"posted", "paid"}: raise HTTPException(status_code=409, detail={"code": "payroll_run_requires_posting"})
    if not run.payslips_published_at:
        run.payslips_published_at = datetime.now(timezone.utc)
        if data.notify_employees:
            employee_ids = list((await db.execute(select(Payslip.employee_id).where(Payslip.payroll_run_id == run.id))).scalars().all())
            await create_notifications(db, organization_id=actor.organization_id, kind="event", title="Your payslip is ready", body=f"Payslip for {run.period_start:%Y-%m-%d} to {run.period_end:%Y-%m-%d} is available in Payroll.", dedup_key=f"payroll-payslips:{run.id}", employee_ids=employee_ids, target_url="/erp/payroll", payload={"payroll_run_id": run.id})
        await record_change(db, actor=actor, topic="payroll", aggregate_type="payroll_run", aggregate_id=run.id, operation="payslips_published", after={"published_at": run.payslips_published_at.isoformat(), "notifications": data.notify_employees})
    await db.commit(); await db.refresh(run)
    return _run_out(run)


@router.post("/runs/{run_id}/bank-export")
async def create_bank_export(run_id: int, data: BankExportRequest, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "export")
    run = await db.scalar(select(PayrollRun).where(PayrollRun.id == run_id, PayrollRun.organization_id == actor.organization_id))
    if not run or run.status not in {"approved", "posted", "paid"}: raise HTTPException(status_code=409, detail={"code": "payroll_run_not_exportable"})
    template_query = select(PayrollBankExportProfile).where(PayrollBankExportProfile.organization_id == actor.organization_id, PayrollBankExportProfile.bank_code == data.bank_code, PayrollBankExportProfile.status.in_(("published", "active")))
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
        account = await db.scalar(select(EmployeeBankAccount).where(EmployeeBankAccount.employee_payroll_profile_id == profile.id, EmployeeBankAccount.is_primary.is_(True), EmployeeBankAccount.valid_from <= run.tax_point_date, (EmployeeBankAccount.valid_to.is_(None) | (EmployeeBankAccount.valid_to >= run.tax_point_date))).limit(1)) if profile else None
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
async def payroll_report(run_id: int, report_kind: str, report_format: Literal["json", "csv", "xlsx"] = Query(default="json", alias="format"), tt11_period: Literal["run", "quarter", "annual"] = Query(default="run", alias="period"), db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "export")
    run = await db.scalar(select(PayrollRun).where(PayrollRun.id == run_id, PayrollRun.organization_id == actor.organization_id))
    if not run: raise HTTPException(status_code=404, detail="Payroll run not found")
    if run.status not in {"approved", "posted", "paid"}:
        raise HTTPException(status_code=409, detail={"code": "payroll_run_not_reportable", "status": run.status})
    report_runs = [run]
    if report_kind == "tt11" and tt11_period != "run":
        run_query = select(PayrollRun).where(
            PayrollRun.organization_id == actor.organization_id,
            PayrollRun.status.in_(("approved", "posted", "paid")),
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
        payload.append({"employee_id": row.employee_id, "insured_code": profile_snapshot.get("insured_code"), "payable_days": str(override.get("payable_workdays", resolved_units.get("payable_workdays", "0"))), "gross": str(row.gross), "shi_subject_gross": str(row.shi_subject_gross), "taxable_income": str(row.taxable_income), "shi_base": str(row.shi_base), "employee_shi": str(row.employee_shi), "employer_shi": str(row.employer_shi), "shi_by_fund": shi_trace.get("by_fund") or {}, "pit_before_relief": str(pit_trace.get("before_relief", "0")), "pit": str(row.pit), "pit_relief": str(row.pit_relief), "net_pay": str(row.net_pay)})
    if report_kind == "nd7":
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
    columns = [{"key": key, "header": key} for key in (list(export_rows[0].keys()) if export_rows else [])]
    filename, content = render_bank_export(export_rows, {"columns": columns, "filename": f"{report_kind}-{run.settlement_key}.{report_format}"}, report_format)
    media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if report_format == "xlsx" else "text/csv; charset=utf-8"
    return Response(content=content, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{filename}"'})
