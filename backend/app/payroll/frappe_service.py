"""Frappe-style payroll document services backed by the OYUNS engine.

These services deliberately do not import or require Frappe.  They provide the
same document boundaries (Payroll Entry, Salary Slip, Additional Salary and
Bank Entry) while delegating all Mongolia-specific arithmetic to service.py.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enterprise_deps import ActorContext
from app.models.models import (
    AdditionalSalary,
    Employee,
    EmployeeBankAccount,
    EmployeePayrollProfile,
    ERPAccount,
    ERPDocument,
    ERPGeneralLedgerEntry,
    PayrollBankEntry,
    PayrollPeriod,
    PayrollPostingProfile,
    PayrollRun,
    PayrollSalaryComponentMaster,
    Payslip,
    StatutoryConfigProfile,
    WorkTimeEntry,
)
from .schemas import (
    AdditionalSalaryInput,
    BankEntryInput,
    BulkSalaryStructureAssignmentInput,
    GetEmployeesInput,
    PayrollEntryInput,
    PayrollPeriodInput,
    SalaryComponentMasterInput,
    SalaryStructureAssignmentInput,
)
from .service import calculate_run, create_employee_profile, ensure_profile_active, post_run


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value or 0))


def _run_number(prefix: str, year: int) -> str:
    # Keep the human-readable year while retaining microsecond precision so
    # concurrent document creates cannot collide on the unique number key.
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    return f"{prefix}-{year}-{stamp}"


def period_out(row: PayrollPeriod) -> dict[str, Any]:
    return {
        "id": row.id,
        "code": row.code,
        "name": row.name,
        "start_date": row.start_date.isoformat(),
        "end_date": row.end_date.isoformat(),
        "tax_year": row.tax_year,
        "payroll_frequency": row.payroll_frequency,
        "statutory_profile_id": row.statutory_profile_id,
        "status": row.status,
    }


def component_master_out(row: PayrollSalaryComponentMaster) -> dict[str, Any]:
    return {
        "id": row.id,
        "code": row.code,
        "name": row.name,
        "component_kind": row.component_kind,
        "formula": row.formula,
        "proration_basis": row.proration_basis,
        "is_taxable": row.is_taxable,
        "is_shi_subject": row.is_shi_subject,
        "is_non_taxable_allowance": row.is_non_taxable_allowance,
        "is_leave_average_eligible": row.is_leave_average_eligible,
        "is_flexible_benefit": row.is_flexible_benefit,
        "max_benefit_amount_yearly": str(row.max_benefit_amount_yearly),
        "pay_against_benefit_claim": row.pay_against_benefit_claim,
        "only_tax_impact": row.only_tax_impact,
        "payer": row.payer,
        "account_id": row.account_id,
        "cost_center_id": row.cost_center_id,
        "metadata_json": row.metadata_json or {},
        "status": row.status,
    }


def additional_salary_out(row: AdditionalSalary, component_code: str | None = None) -> dict[str, Any]:
    return {
        "id": row.id,
        "number": row.number,
        "employee_id": row.employee_id,
        "salary_component_id": row.salary_component_id,
        "salary_component_code": component_code,
        "payroll_date": row.payroll_date.isoformat(),
        "amount": str(row.amount),
        "component_kind": row.component_kind,
        "taxable": row.taxable,
        "shi_subject": row.shi_subject,
        "source": row.source,
        "reference": row.reference,
        "status": row.status,
        "payroll_run_id": row.payroll_run_id,
        "submitted_at": row.submitted_at.isoformat() if row.submitted_at else None,
    }


def bank_entry_out(row: PayrollBankEntry) -> dict[str, Any]:
    return {
        "id": row.id,
        "number": row.number,
        "payroll_entry_id": row.payroll_run_id,
        "payment_account_id": row.payment_account_id,
        "posting_date": row.posting_date.isoformat(),
        "amount": str(row.amount),
        "currency": row.currency,
        "status": row.status,
        "erp_document_id": row.erp_document_id,
        "submitted_at": row.submitted_at.isoformat() if row.submitted_at else None,
    }


async def create_payroll_period(db: AsyncSession, actor: ActorContext, data: PayrollPeriodInput) -> PayrollPeriod:
    if data.end_date < data.start_date:
        raise HTTPException(status_code=422, detail={"code": "payroll_invalid_period"})
    profile = await db.scalar(select(StatutoryConfigProfile).where(StatutoryConfigProfile.id == data.statutory_profile_id, StatutoryConfigProfile.organization_id == actor.organization_id))
    if not profile or profile.status not in {"published", "active"} or profile.effective_from > data.start_date or (profile.effective_to and profile.effective_to < data.end_date):
        raise HTTPException(status_code=404, detail="Statutory profile not found")
    duplicate = await db.scalar(select(PayrollPeriod.id).where(PayrollPeriod.organization_id == actor.organization_id, PayrollPeriod.code == data.code))
    if duplicate:
        raise HTTPException(status_code=409, detail={"code": "payroll_period_exists"})
    overlap = await db.scalar(select(PayrollPeriod.id).where(
        PayrollPeriod.organization_id == actor.organization_id,
        PayrollPeriod.status == "open",
        PayrollPeriod.start_date <= data.end_date,
        PayrollPeriod.end_date >= data.start_date,
    ))
    if overlap:
        raise HTTPException(status_code=409, detail={"code": "payroll_period_overlap"})
    row = PayrollPeriod(organization_id=actor.organization_id, code=data.code, name=data.name, start_date=data.start_date, end_date=data.end_date, tax_year=data.tax_year, payroll_frequency=data.payroll_frequency, statutory_profile_id=data.statutory_profile_id, created_by_account_id=actor.account_id)
    db.add(row)
    await db.flush()
    return row


async def create_component_master(db: AsyncSession, actor: ActorContext, data: SalaryComponentMasterInput) -> PayrollSalaryComponentMaster:
    duplicate = await db.scalar(select(PayrollSalaryComponentMaster.id).where(PayrollSalaryComponentMaster.organization_id == actor.organization_id, PayrollSalaryComponentMaster.code == data.code))
    if duplicate:
        raise HTTPException(status_code=409, detail={"code": "payroll_component_master_exists"})
    row = PayrollSalaryComponentMaster(organization_id=actor.organization_id, created_by_account_id=actor.account_id, **data.model_dump())
    db.add(row)
    await db.flush()
    return row


async def update_component_master(db: AsyncSession, actor: ActorContext, row: PayrollSalaryComponentMaster, data: SalaryComponentMasterInput) -> PayrollSalaryComponentMaster:
    if row.organization_id != actor.organization_id:
        raise HTTPException(status_code=404, detail="Salary component not found")
    if row.status != "active":
        raise HTTPException(status_code=409, detail={"code": "payroll_component_master_inactive"})
    duplicate = await db.scalar(select(PayrollSalaryComponentMaster.id).where(PayrollSalaryComponentMaster.organization_id == actor.organization_id, PayrollSalaryComponentMaster.code == data.code, PayrollSalaryComponentMaster.id != row.id))
    if duplicate:
        raise HTTPException(status_code=409, detail={"code": "payroll_component_master_exists"})
    for key, value in data.model_dump().items():
        setattr(row, key, value)
    return row


async def create_assignment(db: AsyncSession, actor: ActorContext, data: SalaryStructureAssignmentInput) -> EmployeePayrollProfile:
    if data.document_status != "submitted":
        raise HTTPException(status_code=422, detail={"code": "payroll_assignment_must_be_submitted"})
    row = await create_employee_profile(db, actor, data.employee_id, data)
    row.document_status = "submitted"
    return row


async def create_bulk_assignments(db: AsyncSession, actor: ActorContext, data: BulkSalaryStructureAssignmentInput) -> list[EmployeePayrollProfile]:
    rows: list[EmployeePayrollProfile] = []
    for employee_id in dict.fromkeys(data.employee_ids):
        assignment = SalaryStructureAssignmentInput(employee_id=employee_id, salary_structure_id=data.salary_structure_id, effective_from=data.effective_from, effective_to=data.effective_to, base_salary=data.base_salary, insured_category=data.insured_category, hazard_class=data.hazard_class, residency_status=data.residency_status, tax_relief_eligibility=data.tax_relief_eligibility, exemption_flags=data.exemption_flags, payment_method=data.payment_method)
        rows.append(await create_assignment(db, actor, assignment))
    return rows


async def create_additional_salary(db: AsyncSession, actor: ActorContext, data: AdditionalSalaryInput) -> AdditionalSalary:
    component = await db.scalar(select(PayrollSalaryComponentMaster).where(PayrollSalaryComponentMaster.id == data.salary_component_id, PayrollSalaryComponentMaster.organization_id == actor.organization_id, PayrollSalaryComponentMaster.status == "active"))
    if not component:
        raise HTTPException(status_code=404, detail="Salary component not found")
    profile = await db.scalar(select(EmployeePayrollProfile).where(EmployeePayrollProfile.organization_id == actor.organization_id, EmployeePayrollProfile.employee_id == data.employee_id, EmployeePayrollProfile.effective_from <= data.payroll_date, (EmployeePayrollProfile.effective_to.is_(None) | (EmployeePayrollProfile.effective_to >= data.payroll_date))).limit(1))
    if not profile:
        raise HTTPException(status_code=422, detail={"code": "payroll_employee_profile_missing", "employee_id": data.employee_id})
    row = AdditionalSalary(organization_id=actor.organization_id, number=_run_number("ADD-SAL", data.payroll_date.year), created_by_account_id=actor.account_id, **data.model_dump())
    db.add(row)
    await db.flush()
    return row


async def submit_additional_salary(db: AsyncSession, actor: ActorContext, row: AdditionalSalary) -> AdditionalSalary:
    if row.organization_id != actor.organization_id:
        raise HTTPException(status_code=404, detail="Additional Salary not found")
    if row.status != "draft":
        raise HTTPException(status_code=409, detail={"code": "additional_salary_not_draft"})
    row.status = "submitted"
    row.submitted_by_account_id = actor.account_id
    row.submitted_at = datetime.now(timezone.utc)
    return row


async def cancel_additional_salary(db: AsyncSession, actor: ActorContext, row: AdditionalSalary) -> AdditionalSalary:
    if row.organization_id != actor.organization_id:
        raise HTTPException(status_code=404, detail="Additional Salary not found")
    if row.payroll_run_id is not None:
        raise HTTPException(status_code=409, detail={"code": "additional_salary_already_consumed"})
    if row.status == "cancelled":
        return row
    row.status = "cancelled"
    return row


async def create_payroll_entry(db: AsyncSession, actor: ActorContext, data: PayrollEntryInput) -> PayrollRun:
    if data.period_end < data.period_start:
        raise HTTPException(status_code=422, detail={"code": "payroll_invalid_period"})
    profile = await ensure_profile_active(db, data.statutory_profile_id, data.tax_point_date) if data.statutory_profile_id else None
    if profile is None and data.statutory_profile_id is None:
        profile = await db.scalar(select(StatutoryConfigProfile).where(StatutoryConfigProfile.organization_id == actor.organization_id, StatutoryConfigProfile.status.in_(("published", "active")), StatutoryConfigProfile.effective_from <= data.tax_point_date, (StatutoryConfigProfile.effective_to.is_(None) | (StatutoryConfigProfile.effective_to >= data.tax_point_date))).order_by(StatutoryConfigProfile.effective_from.desc(), StatutoryConfigProfile.version.desc()).limit(1))
    if not profile or profile.organization_id != actor.organization_id:
        raise HTTPException(status_code=409, detail={"code": "payroll_no_active_statutory_profile"})
    period = None
    if data.payroll_period_id:
        period = await db.scalar(select(PayrollPeriod).where(PayrollPeriod.id == data.payroll_period_id, PayrollPeriod.organization_id == actor.organization_id, PayrollPeriod.status == "open"))
        if not period:
            raise HTTPException(status_code=409, detail={"code": "payroll_period_not_open"})
        if period.start_date > data.period_start or period.end_date < data.period_end:
            raise HTTPException(status_code=422, detail={"code": "payroll_entry_outside_period"})
    snapshot = {"employee_ids": list(dict.fromkeys(data.employee_ids)), "overrides": data.input_overrides, "variable_inputs": [row.model_dump(mode="json") for row in data.variable_inputs], "approved_time_entry_ids": [], "approved_time_entries": [], "calendar": {"period_start": data.period_start.isoformat(), "period_end": data.period_end.isoformat(), "timezone": "Asia/Ulaanbaatar"}}
    config = {"profile_id": profile.id, "profile_version": profile.version, "profile_checksum": profile.checksum, "source_references": profile.source_references, "currency": profile.currency, "pit_withholding_method": profile.pit_withholding_method, "rounding_policy": profile.rounding_policy, "minimum_wage": str(profile.minimum_wage), "shi_ceiling_multiplier": str(profile.shi_ceiling_multiplier), "leave_policy": profile.leave_policy}
    run = PayrollRun(organization_id=actor.organization_id, run_number=_run_number("HR-PRUN", data.tax_point_date.year), run_type=data.run_type, period_start=data.period_start, period_end=data.period_end, settlement_key=data.period_end.strftime("%Y-%m"), tax_point_date=data.tax_point_date, status="draft", workflow_version="frappe_v1", document_status="draft", payroll_frequency=data.payroll_frequency, posting_date=data.posting_date, employee_filter=data.employee_filter, salary_slips_created=False, salary_slips_submitted=False, payment_status="unpaid", payment_account_id=data.payment_account_id, cost_center_id=data.cost_center_id, payroll_period_id=period.id if period else None, statutory_profile_id=profile.id, input_snapshot=snapshot, config_snapshot=config, snapshot_checksum="", created_by_account_id=actor.account_id)
    db.add(run)
    await db.flush()
    return run


async def get_employees(db: AsyncSession, actor: ActorContext, run: PayrollRun, data: GetEmployeesInput) -> dict[str, Any]:
    if run.organization_id != actor.organization_id or run.workflow_version != "frappe_v1":
        raise HTTPException(status_code=404, detail="Payroll Entry not found")
    if run.document_status != "draft" or run.salary_slips_created or run.salary_slips_submitted:
        raise HTTPException(status_code=409, detail={"code": "payroll_entry_not_editable"})
    requested_ids = list(dict.fromkeys(data.employee_ids or []))
    query = select(EmployeePayrollProfile, Employee).join(Employee, Employee.id == EmployeePayrollProfile.employee_id).where(
        EmployeePayrollProfile.organization_id == actor.organization_id,
        EmployeePayrollProfile.effective_from <= run.tax_point_date,
        (EmployeePayrollProfile.effective_to.is_(None) | (EmployeePayrollProfile.effective_to >= run.tax_point_date)),
        Employee.is_active.is_(True),
    )
    if requested_ids:
        query = query.where(EmployeePayrollProfile.employee_id.in_(requested_ids))
    if data.work_branch:
        query = query.where(Employee.work_branch == data.work_branch)
    if data.work_direction:
        query = query.where(Employee.work_direction == data.work_direction)
    if data.job_title:
        query = query.where(Employee.job_title == data.job_title)
    profiles = (await db.execute(query.order_by(Employee.name, EmployeePayrollProfile.effective_from.desc()))).all()
    selected: dict[int, tuple[EmployeePayrollProfile, Employee]] = {}
    for profile, employee in profiles:
        selected.setdefault(profile.employee_id, (profile, employee))
    if requested_ids:
        missing = sorted(set(requested_ids) - set(selected))
        if missing:
            raise HTTPException(status_code=422, detail={"code": "payroll_employee_profile_missing", "employee_ids": missing})
    if not selected:
        raise HTTPException(status_code=422, detail={"code": "payroll_no_employees"})
    errors: list[dict[str, Any]] = []
    attendance_warnings: list[dict[str, Any]] = []
    validate_attendance = run.input_snapshot.get("validate_attendance", True) if data.validate_attendance is None else data.validate_attendance
    for employee_id, (profile, employee) in selected.items():
        if profile.payment_method == "bank":
            account = await db.scalar(select(EmployeeBankAccount.id).where(EmployeeBankAccount.employee_payroll_profile_id == profile.id, EmployeeBankAccount.is_primary.is_(True), EmployeeBankAccount.valid_from <= run.tax_point_date, (EmployeeBankAccount.valid_to.is_(None) | (EmployeeBankAccount.valid_to >= run.tax_point_date))))
            if not account:
                errors.append({"employee_id": employee_id, "code": "payroll_bank_account_missing", "name": employee.name})
        if validate_attendance:
            attendance = await db.scalar(select(WorkTimeEntry.id).where(WorkTimeEntry.employee_id == employee_id, WorkTimeEntry.entry_type == "work", WorkTimeEntry.approval_status == "approved", WorkTimeEntry.started_at >= datetime.combine(run.period_start, datetime.min.time()), WorkTimeEntry.started_at <= datetime.combine(run.period_end, datetime.max.time())).limit(1))
            if attendance is None:
                issue = {"employee_id": employee_id, "code": "payroll_attendance_missing", "name": employee.name}
                errors.append(issue)
                attendance_warnings.append(issue)
    employee_ids = list(selected)
    entries = list((await db.execute(select(WorkTimeEntry).where(WorkTimeEntry.employee_id.in_(employee_ids), WorkTimeEntry.entry_type == "work", WorkTimeEntry.approval_status == "approved", WorkTimeEntry.started_at >= datetime.combine(run.period_start, datetime.min.time()), WorkTimeEntry.started_at <= datetime.combine(run.period_end, datetime.max.time())).order_by(WorkTimeEntry.started_at))).scalars().all())
    time_snapshot = [{"id": entry.id, "employee_id": entry.employee_id, "local_work_date": entry.local_work_date.isoformat() if entry.local_work_date else None, "started_at": entry.started_at.isoformat(), "ended_at": entry.ended_at.isoformat() if entry.ended_at else None, "approval_status": entry.approval_status, "hours": str(_decimal((entry.ended_at - entry.started_at).total_seconds()) / Decimal("3600")) if entry.ended_at else "0"} for entry in entries]
    run.employee_filter = {"work_branch": data.work_branch, "work_direction": data.work_direction, "job_title": data.job_title}
    run.input_snapshot = {**(run.input_snapshot or {}), "employee_ids": employee_ids, "validate_attendance": validate_attendance, "employee_validation_errors": errors, "approved_time_entry_ids": [entry.id for entry in entries], "approved_time_entries": time_snapshot}
    return {"employee_ids": employee_ids, "employees": [{"id": employee.id, "name": employee.name, "payment_method": profile.payment_method, "base_salary": str(profile.base_salary), "bank_ready": not any(item["employee_id"] == employee.id and item["code"] == "payroll_bank_account_missing" for item in errors)} for profile, employee in (selected.values())], "errors": errors, "warnings": attendance_warnings, "can_create_salary_slips": not errors}


async def create_salary_slips(db: AsyncSession, actor: ActorContext, run: PayrollRun) -> list[Payslip]:
    if run.organization_id != actor.organization_id or run.workflow_version != "frappe_v1":
        raise HTTPException(status_code=404, detail="Payroll Entry not found")
    if run.document_status != "draft" or run.salary_slips_submitted:
        raise HTTPException(status_code=409, detail={"code": "payroll_entry_not_editable"})
    if run.salary_slips_created:
        existing = list((await db.execute(select(Payslip).where(Payslip.payroll_run_id == run.id).order_by(Payslip.employee_id))).scalars().all())
        if existing:
            return existing
    validation_errors = list((run.input_snapshot or {}).get("employee_validation_errors") or [])
    if validation_errors:
        raise HTTPException(status_code=409, detail={"code": "payroll_employee_validation_failed", "errors": validation_errors})
    employee_ids = list((run.input_snapshot or {}).get("employee_ids") or [])
    if not employee_ids:
        raise HTTPException(status_code=422, detail={"code": "payroll_get_employees_first"})
    additional_result = await db.execute(
        select(AdditionalSalary, PayrollSalaryComponentMaster)
        .join(PayrollSalaryComponentMaster, PayrollSalaryComponentMaster.id == AdditionalSalary.salary_component_id)
        .where(
            AdditionalSalary.organization_id == actor.organization_id,
            AdditionalSalary.employee_id.in_(employee_ids),
            AdditionalSalary.payroll_date >= run.period_start,
            AdditionalSalary.payroll_date <= run.period_end,
            AdditionalSalary.status == "submitted",
            (AdditionalSalary.payroll_run_id.is_(None) | (AdditionalSalary.payroll_run_id == run.id)),
        )
        .order_by(AdditionalSalary.id)
    )
    additional = additional_result.all()
    existing_variables = list((run.input_snapshot or {}).get("variable_inputs") or [])
    represented = {int(item.get("additional_salary_id")) for item in existing_variables if item.get("additional_salary_id")}
    for row, component in additional:
        if row.id in represented:
            continue
        existing_variables.append({"employee_id": row.employee_id, "code": component.code, "label": component.name, "amount": str(row.amount), "component_kind": row.component_kind, "taxable": row.taxable, "shi_subject": row.shi_subject, "source": row.source, "reference": row.reference, "additional_salary_id": row.id})
        row.payroll_run_id = run.id
    run.input_snapshot = {**(run.input_snapshot or {}), "variable_inputs": existing_variables}
    slips = await calculate_run(db, actor, run)
    run.salary_slips_created = True
    run.document_status = "draft"
    for slip in slips:
        slip.document_status = "draft"
    return slips


async def submit_salary_slips(db: AsyncSession, actor: ActorContext, run: PayrollRun) -> PayrollRun:
    if run.workflow_version != "frappe_v1" or run.organization_id != actor.organization_id:
        raise HTTPException(status_code=404, detail="Payroll Entry not found")
    if run.status == "posted" and run.salary_slips_submitted:
        return run
    if run.status != "calculated" or not run.salary_slips_created:
        raise HTTPException(status_code=409, detail={"code": "payroll_salary_slips_not_ready"})
    await post_run(db, actor, run)
    now = datetime.now(timezone.utc)
    slips = (await db.execute(select(Payslip).where(Payslip.payroll_run_id == run.id))).scalars().all()
    for slip in slips:
        slip.document_status = "submitted"
        slip.submitted_at = now
        slip.published_at = now
    run.document_status = "submitted"
    run.salary_slips_submitted = True
    run.payment_status = "unpaid"
    # Reuse the existing ESS publication contract: submitted Frappe-style
    # slips are immediately visible to employees, while the separate bank
    # settlement remains unpaid until its Bank Entry is submitted.
    run.payslips_published_at = now
    return run


async def make_bank_entry(db: AsyncSession, actor: ActorContext, run: PayrollRun, data: BankEntryInput) -> PayrollBankEntry:
    if run.workflow_version != "frappe_v1" or run.organization_id != actor.organization_id:
        raise HTTPException(status_code=404, detail="Payroll Entry not found")
    if run.status != "posted" or not run.salary_slips_submitted:
        raise HTTPException(status_code=409, detail={"code": "payroll_entry_requires_submission"})
    if run.run_type == "advance":
        raise HTTPException(status_code=409, detail={"code": "payroll_advance_already_settled"})
    existing = await db.scalar(select(PayrollBankEntry).where(PayrollBankEntry.organization_id == actor.organization_id, PayrollBankEntry.payroll_run_id == run.id))
    if existing:
        return existing
    account_id = data.payment_account_id or run.payment_account_id
    if not account_id:
        raise HTTPException(status_code=422, detail={"code": "payroll_payment_account_missing"})
    account = await db.scalar(select(ERPAccount).where(ERPAccount.id == account_id, ERPAccount.organization_id == actor.organization_id, ERPAccount.is_active.is_(True), ERPAccount.is_group.is_(False)))
    if not account:
        raise HTTPException(status_code=422, detail={"code": "payroll_payment_account_invalid"})
    run.payment_account_id = account_id
    row = PayrollBankEntry(organization_id=actor.organization_id, number=_run_number("HR-BANK", run.tax_point_date.year), payroll_run_id=run.id, payment_account_id=account_id, posting_date=data.posting_date or run.posting_date or run.period_end, amount=run.total_net, currency="MNT", status="draft", created_by_account_id=actor.account_id)
    db.add(row)
    await db.flush()
    run.bank_entry_id = row.id
    return row


async def submit_bank_entry(db: AsyncSession, actor: ActorContext, row: PayrollBankEntry) -> PayrollBankEntry:
    if row.organization_id != actor.organization_id:
        raise HTTPException(status_code=404, detail="Bank Entry not found")
    if row.status == "submitted":
        return row
    if row.status != "draft":
        raise HTTPException(status_code=409, detail={"code": "payroll_bank_entry_not_draft"})
    run = await db.scalar(select(PayrollRun).where(PayrollRun.id == row.payroll_run_id, PayrollRun.organization_id == actor.organization_id).with_for_update())
    if not run or run.status != "posted":
        raise HTTPException(status_code=409, detail={"code": "payroll_entry_requires_submission"})
    posting = await db.scalar(select(PayrollPostingProfile).where(PayrollPostingProfile.organization_id == actor.organization_id, PayrollPostingProfile.code == "default", PayrollPostingProfile.is_active.is_(True)))
    if not posting or "net_pay_payable" not in (posting.account_roles or {}):
        raise HTTPException(status_code=422, detail={"code": "payroll_posting_accounts_incomplete", "missing": ["net_pay_payable"]})
    payable_id = posting.account_roles["net_pay_payable"]
    payable = await db.scalar(select(ERPAccount).where(ERPAccount.id == payable_id, ERPAccount.organization_id == actor.organization_id, ERPAccount.is_active.is_(True)))
    account = await db.scalar(select(ERPAccount).where(ERPAccount.id == row.payment_account_id, ERPAccount.organization_id == actor.organization_id, ERPAccount.is_active.is_(True)))
    if not payable or not account:
        raise HTTPException(status_code=422, detail={"code": "payroll_payment_account_invalid"})
    document = ERPDocument(organization_id=actor.organization_id, document_type="payroll_bank_entry", number=row.number, status="submitted", currency=row.currency, posting_date=row.posting_date, net_total=row.amount, grand_total=row.amount, outstanding_amount=Decimal("0"), source_document_id=run.erp_document_id, payload={"payroll_run_id": run.id, "bank_entry_id": row.id}, custom={})
    db.add(document)
    await db.flush()
    amount = _decimal(row.amount)
    db.add_all([
        ERPGeneralLedgerEntry(organization_id=actor.organization_id, document_id=document.id, account_id=payable.id, posting_date=row.posting_date, debit=amount, credit=Decimal("0"), memo=f"Salary payable settlement {run.run_number}"),
        ERPGeneralLedgerEntry(organization_id=actor.organization_id, document_id=document.id, account_id=account.id, posting_date=row.posting_date, debit=Decimal("0"), credit=amount, memo=f"Bank salary payment {run.run_number}"),
    ])
    row.erp_document_id = document.id
    row.status = "submitted"
    row.submitted_by_account_id = actor.account_id
    row.submitted_at = datetime.now(timezone.utc)
    run.bank_entry_id = row.id
    run.payment_status = "paid"
    return row
