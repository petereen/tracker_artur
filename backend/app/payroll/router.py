from __future__ import annotations

import base64
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.enterprise_deps import ActorContext, get_actor
from app.erp.service import require_capability
from app.models.models import (
    Employee, EmployeeBankAccount, EmployeePayrollProfile, PayrollBankExportProfile,
    PayrollExportArtifact, PayrollPostingProfile, PayrollRun, Payslip, PayslipLineItem, IdempotencyRecord,
    SalaryComponent, SalaryStructure, SalaryStructureVersion, SHIRateTier, PITBracketTier, TaxReliefTier,
    StatutoryConfigProfile,
)
from app.services.enterprise_events import record_change
from app.services.secret_box import decrypt_secret, encrypt_secret
from .exports import nd7_summary, nd8_rows, render_bank_export, tt11_summary
from .schemas import (
    BankAccountInput, BankExportProfileInput, BankExportRequest, CalculateRunInput,
    EmployeePayrollInput, PayrollRunInput, PITBracketInput, PostingProfileInput,
    PublishProfileInput, ReliefTierInput, SalaryStructureInput, StatutoryProfileInput,
)
from .service import (
    calculate_run, canonical_payout_rows, create_bank_account, create_employee_profile,
    create_replacement_run, create_run, create_salary_structure, create_statutory_profile,
    load_rules, post_run, profile_out, publish_profile, reverse_run,
)


router = APIRouter()


async def payroll_capability(db: AsyncSession, actor: ActorContext, action: str) -> None:
    await require_capability(db, actor, "payroll", action)


def _run_out(run: PayrollRun) -> dict[str, Any]:
    return {"id": run.id, "run_number": run.run_number, "run_type": run.run_type, "period_start": run.period_start.isoformat(), "period_end": run.period_end.isoformat(), "settlement_key": run.settlement_key, "tax_point_date": run.tax_point_date.isoformat(), "status": run.status, "reversal_of_run_id": run.reversal_of_run_id, "replacement_of_run_id": run.replacement_of_run_id, "statutory_profile_id": run.statutory_profile_id, "posting_profile_id": run.posting_profile_id, "erp_document_id": run.erp_document_id, "total_gross": str(run.total_gross), "total_employee_shi": str(run.total_employee_shi), "total_employer_shi": str(run.total_employer_shi), "total_pit": str(run.total_pit), "total_net": str(run.total_net), "snapshot_checksum": run.snapshot_checksum}


def _slip_out(slip: Payslip, lines: list[PayslipLineItem] | None = None) -> dict[str, Any]:
    result = {"id": slip.id, "payroll_run_id": slip.payroll_run_id, "employee_id": slip.employee_id, "gross": str(slip.gross), "taxable_income": str(slip.taxable_income), "shi_subject_gross": str(slip.shi_subject_gross), "shi_base": str(slip.shi_base), "employee_shi": str(slip.employee_shi), "employer_shi": str(slip.employer_shi), "pit": str(slip.pit), "pit_relief": str(slip.pit_relief), "advance_offset": str(slip.advance_offset), "net_pay": str(slip.net_pay), "snapshot_checksum": slip.snapshot_checksum, "ytd": slip.ytd_snapshot, "trace": slip.calculation_trace}
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


@router.get("/salary-structures")
async def list_salary_structures(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "view")
    structures = (await db.execute(select(SalaryStructure).where(SalaryStructure.organization_id == actor.organization_id).order_by(SalaryStructure.code, SalaryStructure.version.desc()))).scalars().all()
    result = []
    for structure in structures:
        components = (await db.execute(select(SalaryComponent).where(SalaryComponent.salary_structure_id == structure.id).order_by(SalaryComponent.position))).scalars().all()
        result.append({"id": structure.id, "code": structure.code, "name": structure.name, "version": structure.version, "status": structure.status, "effective_from": structure.effective_from.isoformat(), "effective_to": structure.effective_to.isoformat() if structure.effective_to else None, "currency": structure.currency, "checksum": structure.checksum, "components": [{"code": row.code, "name": row.name, "component_kind": row.component_kind, "formula": row.formula, "proration_basis": row.proration_basis, "is_taxable": row.is_taxable, "is_shi_subject": row.is_shi_subject, "is_non_taxable_allowance": row.is_non_taxable_allowance, "payer": row.payer, "position": row.position, "account_id": row.account_id, "cost_center_id": row.cost_center_id} for row in components]})
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


@router.post("/runs/{run_id}/approve")
async def approve_payroll_run(run_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "approve")
    run = await db.scalar(select(PayrollRun).where(PayrollRun.id == run_id, PayrollRun.organization_id == actor.organization_id).with_for_update())
    if not run: raise HTTPException(status_code=404, detail="Payroll run not found")
    if run.status not in {"calculated", "in_review"}: raise HTTPException(status_code=409, detail={"code": "payroll_run_requires_calculation"})
    if run.created_by_account_id == actor.account_id and "admin" not in actor.roles: raise HTTPException(status_code=403, detail={"code": "payroll_separation_of_duties"})
    run.status = "approved"; run.approved_by_account_id = actor.account_id
    await record_change(db, actor=actor, topic="payroll", aggregate_type="payroll_run", aggregate_id=run.id, operation="approved", after={"status": run.status, "approved_by_account_id": actor.account_id})
    await db.commit(); await db.refresh(run); return _run_out(run)


@router.post("/runs/{run_id}/review")
async def review_payroll_run(run_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "review")
    run = await db.scalar(select(PayrollRun).where(PayrollRun.id == run_id, PayrollRun.organization_id == actor.organization_id).with_for_update())
    if not run: raise HTTPException(status_code=404, detail="Payroll run not found")
    if run.status != "calculated": raise HTTPException(status_code=409, detail={"code": "payroll_run_requires_calculation"})
    run.status = "in_review"
    await record_change(db, actor=actor, topic="payroll", aggregate_type="payroll_run", aggregate_id=run.id, operation="reviewed", after={"status": run.status})
    await db.commit(); await db.refresh(run); return _run_out(run)


@router.post("/runs/{run_id}/post")
async def post_payroll_run(run_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await payroll_capability(db, actor, "post")
    run = await db.scalar(select(PayrollRun).where(PayrollRun.id == run_id, PayrollRun.organization_id == actor.organization_id).with_for_update())
    if not run: raise HTTPException(status_code=404, detail="Payroll run not found")
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
    return {**_run_out(run), "payslips": [_slip_out(row) for row in slips]}


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
    slips = (await db.execute(select(Payslip).join(PayrollRun, PayrollRun.id == Payslip.payroll_run_id).where(Payslip.organization_id == actor.organization_id, Payslip.employee_id == actor.employee_id, PayrollRun.status.in_(("approved", "posted", "paid"))).order_by(Payslip.created_at.desc()))).scalars().all()
    return [_slip_out(row) for row in slips]


@router.get("/me/payslips/{payslip_id}/download")
async def download_my_payslip(payslip_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    if actor.employee_id is None:
        raise HTTPException(status_code=404, detail="Payslip not found")
    slip = await db.scalar(select(Payslip).join(PayrollRun, PayrollRun.id == Payslip.payroll_run_id).where(Payslip.id == payslip_id, Payslip.organization_id == actor.organization_id, Payslip.employee_id == actor.employee_id, PayrollRun.status.in_(("approved", "posted", "paid"))))
    if not slip:
        raise HTTPException(status_code=404, detail="Payslip not found")
    lines = list((await db.execute(select(PayslipLineItem).where(PayslipLineItem.payslip_id == slip.id).order_by(PayslipLineItem.position))).scalars().all())
    payload = json.dumps(_slip_out(slip, lines), ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    await record_change(db, actor=actor, topic="payroll", aggregate_type="payslip", aggregate_id=slip.id, operation="self_downloaded", after={"payroll_run_id": slip.payroll_run_id, "checksum": slip.snapshot_checksum})
    await db.commit()
    return Response(content=payload, media_type="application/json", headers={"Content-Disposition": f'attachment; filename="payslip-{slip.id}.json"', "X-Payslip-Checksum": slip.snapshot_checksum})


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
    for slip in slips:
        profile = await db.scalar(select(EmployeePayrollProfile).where(EmployeePayrollProfile.employee_id == slip.employee_id, EmployeePayrollProfile.organization_id == actor.organization_id, EmployeePayrollProfile.effective_from <= run.tax_point_date, (EmployeePayrollProfile.effective_to.is_(None) | (EmployeePayrollProfile.effective_to >= run.tax_point_date))).order_by(EmployeePayrollProfile.effective_from.desc()).limit(1))
        account = await db.scalar(select(EmployeeBankAccount).where(EmployeeBankAccount.employee_payroll_profile_id == profile.id, EmployeeBankAccount.is_primary.is_(True), EmployeeBankAccount.valid_from <= run.tax_point_date, (EmployeeBankAccount.valid_to.is_(None) | (EmployeeBankAccount.valid_to >= run.tax_point_date))).limit(1)) if profile else None
        if not account: raise HTTPException(status_code=422, detail={"code": "payroll_bank_account_missing", "employee_id": slip.employee_id})
        accounts[slip.employee_id] = account
    rows = canonical_payout_rows(run, slips, accounts, employees)
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
