from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from dataclasses import replace

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.enterprise_deps import ActorContext, get_actor, require_roles
from app.models.models import (
    AttendanceLog,
    Department,
    Employee,
    EmployeeBankAccount,
    EmployeeCompensationItem,
    EmployeeDetails,
    EmployeePayrollProfile,
    HolidayRecord,
    MonthlyPayrollCalendarDay,
    MonthlyPayrollProfile,
    MonthlyPayrollRuleSet,
    MonthlyPayrollSalaryHistory,
    LeaveBalance,
    PayrollSalaryComponentMaster,
    AdditionalSalary,
    RoleAssignment,
    TimeOff,
    UserAccount,
    WorkerInvite,
)
from app.services.enterprise_events import record_change
from app.services.user_notifications import create_notifications
from .schemas import (
    AttendanceBulkUpdate,
    AttendanceUpdate,
    CompensationItemInput,
    DepartmentInput,
    DepartmentPatch,
    EmployeeCreate,
    EmployeePatch,
    InviteBindInput,
    LeaveBalancePatch,
    LeaveDecisionInput,
    LeaveRequestInput,
    LeaveRequestPatch,
    MonthlyPayrollProfileInput,
)
from .service import (
    ATTENDANCE_STATUSES,
    HR_ROLES,
    MANAGER_ROLES,
    LEAVE_TYPES,
    bind_invite,
    bind_invite_user,
    can_manage_attendance,
    can_manage_hr,
    archive_worker,
    create_invite,
    employee_in_scope,
    ensure_details,
    leave_balance,
    leave_days,
    set_worker_active,
    suggested_attendance,
)
from app.payroll.monthly_engine import (
    AdvanceBasis,
    CalendarDayType,
    PayrollProfile,
    PayrollRunType,
    PayrollRules,
    SalarySegment,
    calculate_monthly_run,
    month_calendar,
    pay_dates_for_month,
)
from app.payroll.monthly_workflow import ensure_default_rule_set
from app.payroll.schemas import BankAccountInput
from app.payroll.service import create_bank_account


router = APIRouter()


def _employee_scope_clause(actor: ActorContext):
    if can_manage_hr(actor):
        return []
    if actor.has_any_role("manager", "team_lead"):
        if actor.employee_id is None:
            return [Employee.id == -1]
        return [or_(Employee.id == actor.employee_id, EmployeeDetails.manager_id == actor.employee_id)]
    if actor.employee_id is None:
        return [Employee.id == -1]
    return [Employee.id == actor.employee_id]


async def _department(db: AsyncSession, actor: ActorContext, department_id: int) -> Department:
    row = await db.scalar(select(Department).where(Department.id == department_id, Department.organization_id == actor.organization_id))
    if not row:
        raise HTTPException(status_code=404, detail="Department not found")
    return row


async def _hr_account_ids(db: AsyncSession, organization_id: int) -> set[int]:
    return set((await db.execute(
        select(RoleAssignment.account_id).join(UserAccount, UserAccount.id == RoleAssignment.account_id).where(
            UserAccount.organization_id == organization_id,
            UserAccount.status == "active",
            RoleAssignment.role.in_(HR_ROLES),
        )
    )).scalars().all())


async def _employee_out(db: AsyncSession, actor: ActorContext, employee: Employee, details: EmployeeDetails | None = None) -> dict:
    details = details or await db.scalar(select(EmployeeDetails).where(EmployeeDetails.employee_id == employee.id))
    department = await db.scalar(select(Department).where(Department.id == details.department_id, Department.organization_id == actor.organization_id)) if details and details.department_id else None
    pending = await db.scalar(select(WorkerInvite.id).where(WorkerInvite.organization_id == actor.organization_id, WorkerInvite.employee_id == employee.id, WorkerInvite.used_at.is_(None), WorkerInvite.revoked_at.is_(None), WorkerInvite.expires_at > datetime.now(timezone.utc)))
    account = await db.scalar(select(UserAccount.id).where(UserAccount.organization_id == actor.organization_id, UserAccount.employee_id == employee.id, UserAccount.status == "active"))
    return {
        "id": employee.id, "name": employee.name, "first_name": employee.first_name, "last_name": employee.last_name,
        "telegram_id": employee.telegram_id, "telegram_username": employee.telegram_username, "photo_url": employee.photo_url or (employee.metadata_json or {}).get("avatar_url"),
        "timezone": employee.timezone or "Asia/Ulaanbaatar", "is_active": bool(employee.is_active),
        "department_id": details.department_id if details else None, "department_name": department.name if department else None,
        "manager_id": details.manager_id if details else employee.manager_id, "job_title": details.job_title if details else employee.job_title,
        "employment_role": details.employment_role if details else None, "start_date": details.start_date.isoformat() if details and details.start_date else None,
        "end_date": details.end_date.isoformat() if details and details.end_date else None, "employment_status": "active" if employee.is_active else "inactive",
        "is_archived": employee.deleted_at is not None,
        "telegram_status": "connected" if employee.telegram_id else "pending_invite" if pending else "not_invited", "account_id": account,
    }


@router.get("/departments")
async def list_departments(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    rows = (await db.execute(select(Department).where(Department.organization_id == actor.organization_id).order_by(Department.name))).scalars().all()
    return [{"id": row.id, "code": row.code, "name": row.name, "manager_employee_id": row.manager_employee_id, "is_active": row.is_active} for row in rows]


@router.post("/departments", status_code=status.HTTP_201_CREATED)
async def create_department(data: DepartmentInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles(*HR_ROLES))):
    if data.manager_employee_id:
        await employee_in_scope(db, actor, data.manager_employee_id)
    exists = await db.scalar(select(Department.id).where(Department.organization_id == actor.organization_id, Department.code == data.code))
    if exists:
        raise HTTPException(status_code=409, detail="Department code already exists")
    row = Department(organization_id=actor.organization_id, **data.model_dump())
    db.add(row); await db.flush()
    await record_change(db, actor=actor, topic="hr", aggregate_type="department", aggregate_id=row.id, operation="created", after=data.model_dump())
    await db.commit()
    return {"id": row.id, "code": row.code, "name": row.name, "manager_employee_id": row.manager_employee_id, "is_active": row.is_active}


@router.patch("/departments/{department_id}")
async def update_department(department_id: int, data: DepartmentPatch, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles(*HR_ROLES))):
    row = await _department(db, actor, department_id)
    if data.manager_employee_id:
        await employee_in_scope(db, actor, data.manager_employee_id)
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    await record_change(db, actor=actor, topic="hr", aggregate_type="department", aggregate_id=row.id, operation="updated", after=data.model_dump(exclude_unset=True))
    await db.commit()
    return {"id": row.id, "code": row.code, "name": row.name, "manager_employee_id": row.manager_employee_id, "is_active": row.is_active}


@router.delete("/departments/{department_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_department(department_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles(*HR_ROLES))):
    row = await _department(db, actor, department_id)
    row.is_active = False
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/employees")
async def list_hr_employees(search: str | None = Query(default=None, max_length=160), department_id: int | None = None, status_filter: str | None = Query(default=None, alias="status"), telegram_status: str | None = None, include_archived: bool = False, page: int = Query(default=1, ge=1), page_size: int = Query(default=50, ge=1, le=200), db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    query = select(Employee, EmployeeDetails).outerjoin(EmployeeDetails, EmployeeDetails.employee_id == Employee.id).where(Employee.organization_id == actor.organization_id, *_employee_scope_clause(actor))
    if search:
        term = f"%{search.strip()}%"
        query = query.where(or_(Employee.name.ilike(term), Employee.telegram_username.ilike(term), Employee.first_name.ilike(term), Employee.last_name.ilike(term), EmployeeDetails.job_title.ilike(term)))
    if department_id is not None: query = query.where(EmployeeDetails.department_id == department_id)
    if not include_archived: query = query.where(Employee.deleted_at.is_(None))
    if status_filter == "active": query = query.where(Employee.is_active.is_(True))
    elif status_filter in {"inactive", "terminated"}: query = query.where(Employee.is_active.is_(False))
    rows = (await db.execute(query.order_by(Employee.name).offset((page - 1) * page_size).limit(page_size))).all()
    items = [await _employee_out(db, actor, employee, details) for employee, details in rows]
    if telegram_status: items = [item for item in items if item["telegram_status"] == telegram_status]
    total_query = select(func.count(Employee.id)).select_from(Employee).outerjoin(EmployeeDetails, EmployeeDetails.employee_id == Employee.id).where(Employee.organization_id == actor.organization_id, *_employee_scope_clause(actor))
    if not include_archived: total_query = total_query.where(Employee.deleted_at.is_(None))
    if status_filter == "active": total_query = total_query.where(Employee.is_active.is_(True))
    elif status_filter in {"inactive", "terminated"}: total_query = total_query.where(Employee.is_active.is_(False))
    total = await db.scalar(total_query) or 0
    return {"items": items, "page": page, "page_size": page_size, "total": total}


@router.post("/employees", status_code=status.HTTP_201_CREATED)
async def create_hr_employee(data: EmployeeCreate, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles(*HR_ROLES))):
    if data.department_id: await _department(db, actor, data.department_id)
    if data.manager_id: await employee_in_scope(db, actor, data.manager_id)
    employee = Employee(organization_id=actor.organization_id, name=data.name, telegram_id=data.telegram_id, first_name=data.first_name, last_name=data.last_name, timezone=data.timezone, is_active=True)
    db.add(employee); await db.flush()
    details = EmployeeDetails(organization_id=actor.organization_id, employee_id=employee.id, department_id=data.department_id, manager_id=data.manager_id, job_title=data.job_title, employment_role=data.employment_role, start_date=data.start_date, employment_status="active")
    db.add(details); await db.flush()
    if data.annual_leave_days is not None:
        db.add(LeaveBalance(organization_id=actor.organization_id, employee_id=employee.id, year=date.today().year, leave_type="annual", entitled_days=data.annual_leave_days))
    invite = await create_invite(db, actor, employee)
    await record_change(db, actor=actor, topic="hr", aggregate_type="employee", aggregate_id=employee.id, operation="created", after={"employee_id": employee.id, "department_id": data.department_id})
    await db.commit()
    return {"employee": await _employee_out(db, actor, employee, details), "invite": invite}


@router.get("/employees/{employee_id}")
async def get_hr_employee(employee_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    employee = await employee_in_scope(db, actor, employee_id)
    return await _employee_out(db, actor, employee)


@router.patch("/employees/{employee_id}")
async def update_hr_employee(employee_id: int, data: EmployeePatch, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles(*HR_ROLES))):
    employee = await employee_in_scope(db, actor, employee_id, write=True)
    details = await ensure_details(db, employee)
    patch = data.model_dump(exclude_unset=True)
    if data.department_id is not None: await _department(db, actor, data.department_id)
    if data.manager_id is not None:
        if data.manager_id == employee_id: raise HTTPException(status_code=422, detail="A worker cannot manage themselves")
        await employee_in_scope(db, actor, data.manager_id)
    for key in ("name", "first_name", "last_name", "timezone"):
        if key in patch: setattr(employee, key, patch.pop(key))
    requested_active = patch.pop("is_active", None)
    employment_status = patch.pop("employment_status", None)
    restore = patch.pop("restore", False)
    for key, value in patch.items(): setattr(details, key, value)
    if employment_status is not None: requested_active = employment_status == "active"
    if requested_active is not None:
        await set_worker_active(db, employee, requested_active, restore=restore or (requested_active and employee.deleted_at is not None))
    await record_change(db, actor=actor, topic="hr", aggregate_type="employee", aggregate_id=employee.id, operation="updated", after=data.model_dump(exclude_unset=True))
    await db.commit()
    return await _employee_out(db, actor, employee, details)


@router.delete("/employees/{employee_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_hr_employee(employee_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles(*HR_ROLES))):
    employee = await employee_in_scope(db, actor, employee_id, write=True)
    await archive_worker(db, employee, account_id=actor.account_id)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/employees/{employee_id}/invite")
async def regenerate_employee_invite(employee_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles(*HR_ROLES))):
    employee = await employee_in_scope(db, actor, employee_id, write=True)
    invite = await create_invite(db, actor, employee)
    await db.commit()
    return invite


@router.post("/employees/{employee_id}/invite/revoke", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_employee_invite(employee_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles(*HR_ROLES))):
    await employee_in_scope(db, actor, employee_id, write=True)
    await db.execute(
        WorkerInvite.__table__.update()
        .where(
            WorkerInvite.organization_id == actor.organization_id,
            WorkerInvite.employee_id == employee_id,
            WorkerInvite.used_at.is_(None),
            WorkerInvite.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(timezone.utc))
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/invites/bind")
async def bind_employee_invite(data: InviteBindInput, db: AsyncSession = Depends(get_db)):
    result = await bind_invite(db, data.token, data.init_data)
    await db.commit()
    return result


@router.get("/leave-requests")
async def list_leave_requests(year: int | None = None, status_filter: str | None = Query(default=None, alias="status"), employee_id: int | None = None, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    query = select(TimeOff, Employee).join(Employee, Employee.id == TimeOff.employee_id).outerjoin(EmployeeDetails, EmployeeDetails.employee_id == Employee.id).where(TimeOff.organization_id == actor.organization_id, *_employee_scope_clause(actor))
    if employee_id: query = query.where(TimeOff.employee_id == employee_id)
    if year: query = query.where(TimeOff.starts_on <= date(year, 12, 31), TimeOff.ends_on >= date(year, 1, 1))
    if status_filter: query = query.where(TimeOff.status == status_filter)
    rows = (await db.execute(query.order_by(TimeOff.starts_on.desc(), TimeOff.id.desc()))).all()
    return [{"id": row.id, "employee_id": row.employee_id, "employee_name": employee.name, "leave_type": row.time_off_type, "starts_on": row.starts_on.isoformat(), "ends_on": row.ends_on.isoformat(), "working_days": str(row.working_days or 0), "reason": row.reason, "status": row.status, "reviewer_feedback": row.reviewer_feedback, "version": row.version} for row, employee in rows]


@router.post("/leave-requests", status_code=status.HTTP_201_CREATED)
async def submit_leave_request(data: LeaveRequestInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    employee_id = data.employee_id or actor.employee_id
    if employee_id is None: raise HTTPException(status_code=422, detail="Employee profile is required")
    employee = await employee_in_scope(db, actor, employee_id, write=True)
    days = await leave_days(db, actor.organization_id, data.starts_on, data.ends_on)
    overlap = await db.scalar(select(TimeOff.id).where(TimeOff.organization_id == actor.organization_id, TimeOff.employee_id == employee.id, TimeOff.status.in_(("pending", "approved")), TimeOff.starts_on <= data.ends_on, TimeOff.ends_on >= data.starts_on))
    if overlap: raise HTTPException(status_code=409, detail="Leave dates overlap an existing request")
    if data.leave_type == "annual":
        balance = await leave_balance(db, actor.organization_id, employee.id, data.starts_on.year, "annual")
        if Decimal(balance["available_days"]) < Decimal(days): raise HTTPException(status_code=409, detail={"code": "leave_balance_insufficient", "available_days": balance["available_days"]})
    approved = can_manage_hr(actor)
    row = TimeOff(organization_id=actor.organization_id, employee_id=employee.id, time_off_type=data.leave_type, starts_on=data.starts_on, ends_on=data.ends_on, working_days=days, reason=data.reason, status="approved" if approved else "pending", approved_by_account_id=actor.account_id if approved else None, reviewed_by_account_id=actor.account_id if approved else None, reviewed_at=datetime.now(timezone.utc) if approved else None)
    db.add(row); await db.flush()
    source_event = await record_change(db, actor=actor, topic="hr", aggregate_type="leave_request", aggregate_id=row.id, operation=row.status, after={"employee_id": employee.id, "leave_type": row.time_off_type, "working_days": days, "status": row.status})
    await create_notifications(
        db,
        organization_id=actor.organization_id,
        employee_ids={employee.id},
        account_ids=await _hr_account_ids(db, actor.organization_id),
        kind="hr_leave_requested",
        title="Шинэ чөлөөний хүсэлт",
        body=f"{employee.name} {data.starts_on}–{data.ends_on}-ны чөлөө хүсэлт илгээлээ.",
        target_url="/hr?tab=leave",
        payload={"leave_request_id": row.id, "status": row.status},
        source_event_id=source_event.id,
        dedup_key=f"hr-leave-requested:{row.id}",
        immediate=True,
    )
    await db.commit()
    return {"id": row.id, "status": row.status, "working_days": days, "employee_id": employee.id}


@router.patch("/leave-requests/{request_id}")
async def update_leave_request(request_id: int, data: LeaveRequestPatch, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    row = await db.scalar(select(TimeOff).where(TimeOff.id == request_id, TimeOff.organization_id == actor.organization_id).with_for_update())
    if not row:
        raise HTTPException(status_code=404, detail="Leave request not found")
    await employee_in_scope(db, actor, row.employee_id, write=True)
    if row.status not in {"pending", "approved"}:
        raise HTTPException(status_code=409, detail="Only pending or approved leave requests can be edited")
    if row.status == "approved" and not can_manage_hr(actor):
        raise HTTPException(status_code=403, detail="Only HR can edit approved leave requests")
    if data.version is not None and row.version != data.version:
        raise HTTPException(status_code=409, detail="Leave request changed")

    starts_on = data.starts_on or row.starts_on
    ends_on = data.ends_on or row.ends_on
    leave_type = data.leave_type or row.time_off_type
    reason = data.reason if data.reason is not None else row.reason
    new_status = data.status or row.status
    if data.status is not None and not can_manage_hr(actor):
        raise HTTPException(status_code=403, detail="Only HR can change leave request status")
    if data.status is not None and row.status != "approved":
        raise HTTPException(status_code=409, detail="Only approved leave requests can change status here")
    if ends_on < starts_on:
        raise HTTPException(status_code=422, detail="End date must not precede start date")

    if new_status in {"pending", "approved"}:
        overlap = await db.scalar(select(TimeOff.id).where(
            TimeOff.organization_id == actor.organization_id,
            TimeOff.employee_id == row.employee_id,
            TimeOff.id != row.id,
            TimeOff.status.in_(
                ("pending", "approved")
            ),
            TimeOff.starts_on <= ends_on,
            TimeOff.ends_on >= starts_on,
        ))
        if overlap:
            raise HTTPException(status_code=409, detail="Leave dates overlap an existing request")

    days = await leave_days(db, actor.organization_id, starts_on, ends_on)
    if new_status in {"pending", "approved"} and leave_type == "annual":
        balance = await leave_balance(db, actor.organization_id, row.employee_id, starts_on.year, "annual")
        available = Decimal(balance["available_days"])
        if row.time_off_type == "annual" and row.starts_on.year == starts_on.year:
            available += Decimal(str(row.working_days or 0))
        if available < Decimal(days):
            raise HTTPException(status_code=409, detail={"code": "leave_balance_insufficient", "available_days": str(available)})

    before = {"leave_type": row.time_off_type, "starts_on": row.starts_on.isoformat(), "ends_on": row.ends_on.isoformat(), "working_days": str(row.working_days or 0), "reason": row.reason, "status": row.status}
    row.time_off_type = leave_type
    row.starts_on = starts_on
    row.ends_on = ends_on
    row.working_days = days
    row.reason = reason
    row.status = new_status
    if new_status == "rejected":
        row.approved_by_account_id = None
        row.reviewed_by_account_id = actor.account_id
        row.reviewed_at = datetime.now(timezone.utc)
    row.version += 1
    after = {"leave_type": row.time_off_type, "starts_on": row.starts_on.isoformat(), "ends_on": row.ends_on.isoformat(), "working_days": str(row.working_days or 0), "reason": row.reason, "status": row.status}
    operation = "rejected" if new_status == "rejected" else "updated"
    source_event = await record_change(db, actor=actor, topic="hr", aggregate_type="leave_request", aggregate_id=row.id, operation=operation, version=row.version, before=before, after=after)
    await create_notifications(
        db,
        organization_id=actor.organization_id,
        employee_ids={row.employee_id},
        account_ids=await _hr_account_ids(db, actor.organization_id),
        kind=f"hr_leave_{operation}",
        title="Чөлөөний хүсэлт татгалзагдлаа" if new_status == "rejected" else "Чөлөөний хүсэлт засагдлаа",
        body="Таны чөлөөний хүсэлт татгалзагдлаа." if new_status == "rejected" else f"Таны чөлөөний хүсэлт {starts_on}–{ends_on} болж шинэчлэгдлээ.",
        target_url="/hr?tab=leave",
        payload={"leave_request_id": row.id, "status": row.status, "version": row.version},
        source_event_id=source_event.id,
        dedup_key=f"hr-leave-{operation}:{row.id}:v{row.version}",
        immediate=True,
    )
    await db.commit()
    return {"id": row.id, "status": row.status, "leave_type": row.time_off_type, "starts_on": starts_on.isoformat(), "ends_on": ends_on.isoformat(), "working_days": str(days), "reason": row.reason, "version": row.version}


@router.post("/leave-requests/{request_id}/decision")
async def decide_leave_request(request_id: int, data: LeaveDecisionInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles(*MANAGER_ROLES))):
    row = await db.scalar(select(TimeOff).where(TimeOff.id == request_id, TimeOff.organization_id == actor.organization_id).with_for_update())
    if not row: raise HTTPException(status_code=404, detail="Leave request not found")
    if row.status != "pending": raise HTTPException(status_code=409, detail="Leave request is no longer pending")
    if not can_manage_hr(actor):
        await employee_in_scope(db, actor, row.employee_id)
        if row.employee_id == actor.employee_id: raise HTTPException(status_code=403, detail="Managers cannot approve their own leave")
    if data.version is not None and row.version != data.version: raise HTTPException(status_code=409, detail="Leave request changed")
    row.status = "approved" if data.approve else "rejected"; row.reviewer_feedback = data.feedback; row.reviewed_by_account_id = actor.account_id; row.reviewed_at = datetime.now(timezone.utc); row.approved_by_account_id = actor.account_id if data.approve else None; row.version += 1
    source_event = await record_change(db, actor=actor, topic="hr", aggregate_type="leave_request", aggregate_id=row.id, operation=row.status, version=row.version, after={"status": row.status, "feedback": data.feedback})
    employee = await db.get(Employee, row.employee_id)
    status_label = "батлагдлаа" if row.status == "approved" else "татгалзлаа"
    feedback = f" Шалтгаан: {data.feedback}" if data.feedback else ""
    await create_notifications(
        db,
        organization_id=actor.organization_id,
        employee_ids={row.employee_id},
        account_ids=await _hr_account_ids(db, actor.organization_id),
        kind=f"hr_leave_{row.status}",
        title="Чөлөөний хүсэлтийн төлөв шинэчлэгдлээ",
        body=f"Таны чөлөөний хүсэлтийг {status_label}.{feedback}",
        target_url="/hr?tab=leave",
        payload={"leave_request_id": row.id, "status": row.status, "feedback": data.feedback},
        source_event_id=source_event.id,
        dedup_key=f"hr-leave-{row.status}:{row.id}:v{row.version}",
        immediate=True,
    )
    await db.commit()
    return {"id": row.id, "status": row.status, "version": row.version, "reviewer_feedback": row.reviewer_feedback}


@router.post("/leave-requests/{request_id}/cancel")
async def cancel_leave_request(request_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    row = await db.scalar(select(TimeOff).where(TimeOff.id == request_id, TimeOff.organization_id == actor.organization_id).with_for_update())
    if not row: raise HTTPException(status_code=404, detail="Leave request not found")
    await employee_in_scope(db, actor, row.employee_id, write=True)
    if row.status not in {"pending", "approved"}: raise HTTPException(status_code=409, detail="Leave request cannot be cancelled")
    row.status = "cancelled"; row.version += 1
    source_event = await record_change(db, actor=actor, topic="hr", aggregate_type="leave_request", aggregate_id=row.id, operation=row.status, version=row.version, after={"status": row.status})
    await create_notifications(
        db,
        organization_id=actor.organization_id,
        employee_ids={row.employee_id},
        account_ids=await _hr_account_ids(db, actor.organization_id),
        kind="hr_leave_cancelled",
        title="Чөлөөний хүсэлт цуцлагдлаа",
        body="Чөлөөний хүсэлт цуцлагдлаа.",
        target_url="/hr?tab=leave",
        payload={"leave_request_id": row.id, "status": row.status},
        source_event_id=source_event.id,
        dedup_key=f"hr-leave-cancelled:{row.id}:v{row.version}",
        immediate=True,
    )
    await db.commit()
    return {"id": row.id, "status": row.status, "version": row.version}


@router.get("/leave-balances")
async def get_leave_balances(year: int | None = None, employee_id: int | None = None, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    year = year or date.today().year
    target_ids = [employee_id] if employee_id else None
    if target_ids: await employee_in_scope(db, actor, employee_id)
    elif not can_manage_hr(actor): target_ids = [actor.employee_id] if actor.employee_id else []
    elif actor.has_any_role("manager", "team_lead"):
        target_ids = list((await db.execute(select(Employee.id).outerjoin(EmployeeDetails, EmployeeDetails.employee_id == Employee.id).where(Employee.organization_id == actor.organization_id, EmployeeDetails.manager_id == actor.employee_id))).scalars().all())
    if target_ids is None: target_ids = list((await db.execute(select(Employee.id).where(Employee.organization_id == actor.organization_id, Employee.is_active.is_(True)))).scalars().all())
    output = []
    for target in target_ids:
        for leave_type in ("annual", "sick", "unpaid"): output.append(await leave_balance(db, actor.organization_id, target, year, leave_type))
    await db.commit()
    return output


@router.put("/employees/{employee_id}/leave-balance")
async def set_leave_balance(employee_id: int, data: LeaveBalancePatch, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles(*HR_ROLES))):
    await employee_in_scope(db, actor, employee_id, write=True)
    row = await db.scalar(select(LeaveBalance).where(LeaveBalance.organization_id == actor.organization_id, LeaveBalance.employee_id == employee_id, LeaveBalance.year == data.year, LeaveBalance.leave_type == data.leave_type).with_for_update())
    if not row:
        row = LeaveBalance(organization_id=actor.organization_id, employee_id=employee_id, **data.model_dump()); db.add(row)
    else:
        for key, value in data.model_dump().items(): setattr(row, key, value)
    await db.commit()
    return await leave_balance(db, actor.organization_id, employee_id, data.year, data.leave_type)


async def _attendance_items(db: AsyncSession, actor: ActorContext, start: date, end: date, employee_id: int | None = None) -> list[dict]:
    query = select(Employee).outerjoin(EmployeeDetails, EmployeeDetails.employee_id == Employee.id).where(Employee.organization_id == actor.organization_id, Employee.is_active.is_(True), *_employee_scope_clause(actor))
    if employee_id: query = query.where(Employee.id == employee_id)
    employees = (await db.execute(query.order_by(Employee.name))).scalars().all()
    logs = (await db.execute(select(AttendanceLog).where(AttendanceLog.organization_id == actor.organization_id, AttendanceLog.attendance_date >= start, AttendanceLog.attendance_date <= end))).scalars().all()
    by_key = {(row.employee_id, row.attendance_date): row for row in logs}
    holiday_rows = (await db.execute(select(HolidayRecord.holiday_date, HolidayRecord.name).where(HolidayRecord.organization_id == actor.organization_id, HolidayRecord.is_active.is_(True), HolidayRecord.holiday_date >= start, HolidayRecord.holiday_date <= end))).all()
    holidays = {holiday_date: name for holiday_date, name in holiday_rows}
    output = []
    current = start
    while current <= end:
        for employee in employees:
            log = by_key.get((employee.id, current)); suggestion = await suggested_attendance(db, employee, current)
            non_working_day = current.weekday() >= 5 or current in holidays
            output.append({"id": log.id if log else None, "employee_id": employee.id, "employee_name": employee.name, "attendance_date": current.isoformat(), "status": log.status if log else suggestion.get("suggested_status"), "suggested_status": suggestion.get("suggested_status"), "on_leave": suggestion.get("on_leave", False), "source": log.source if log else "derived", "worked_minutes": log.worked_minutes if log else suggestion.get("worked_minutes", 0), "first_started_at": log.first_started_at if log else suggestion.get("first_started_at"), "last_ended_at": log.last_ended_at if log else suggestion.get("last_ended_at"), "confirmed": bool(log and log.confirmed_at), "version": log.version if log else None, "is_non_working_day": non_working_day, "non_working_day_name": holidays.get(current) or ("Амралтын өдөр" if current.weekday() >= 5 else None)})
        current += timedelta(days=1)
    return output


@router.get("/attendance")
async def list_attendance(month: str | None = None, employee_id: int | None = None, start_date: date | None = None, end_date: date | None = None, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    if (start_date is None) != (end_date is None): raise HTTPException(status_code=422, detail="start_date and end_date must be provided together")
    if start_date is not None:
        start, end = start_date, end_date
        if end < start or (end - start).days > 31: raise HTTPException(status_code=422, detail="Attendance range must be between 1 and 32 days")
        period = start.strftime("%Y-%m-%d")
    else:
        try:
            start = date.fromisoformat((month or date.today().strftime("%Y-%m")) + "-01")
        except ValueError: raise HTTPException(status_code=422, detail="month must use YYYY-MM")
        end = date(start.year + (1 if start.month == 12 else 0), 1 if start.month == 12 else start.month + 1, 1) - timedelta(days=1)
        period = start.strftime("%Y-%m")
    if employee_id: await employee_in_scope(db, actor, employee_id)
    return {"month": start.strftime("%Y-%m"), "period": period, "period_start": start.isoformat(), "period_end": end.isoformat(), "items": await _attendance_items(db, actor, start, end, employee_id)}


@router.put("/attendance", status_code=status.HTTP_200_OK)
async def update_attendance(data: AttendanceUpdate, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles(*MANAGER_ROLES))):
    if data.status not in ATTENDANCE_STATUSES: raise HTTPException(status_code=422, detail="Invalid attendance status")
    employee = await employee_in_scope(db, actor, data.employee_id, write=True)
    row = await db.scalar(select(AttendanceLog).where(AttendanceLog.organization_id == actor.organization_id, AttendanceLog.employee_id == employee.id, AttendanceLog.attendance_date == data.attendance_date).with_for_update())
    if row and data.version is not None and row.version != data.version: raise HTTPException(status_code=409, detail="Attendance changed")
    if not row:
        row = AttendanceLog(organization_id=actor.organization_id, employee_id=employee.id, attendance_date=data.attendance_date, status=data.status, source="manual", confirmed_by_account_id=actor.account_id, confirmed_at=datetime.now(timezone.utc), note=data.note); db.add(row)
    else:
        row.status = data.status; row.source = "manual"; row.confirmed_by_account_id = actor.account_id; row.confirmed_at = datetime.now(timezone.utc); row.note = data.note; row.version += 1
    await db.commit()
    return {"id": row.id, "employee_id": row.employee_id, "attendance_date": row.attendance_date, "status": row.status, "version": row.version}


@router.put("/attendance/bulk")
async def update_attendance_bulk(data: AttendanceBulkUpdate, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles(*MANAGER_ROLES))):
    result = []
    for item in data.items:
        result.append(await update_attendance(item, db, actor))
    return {"updated": result}


@router.get("/attendance/export.csv")
async def export_attendance(month: str | None = None, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles(*MANAGER_ROLES))):
    data = await list_attendance(month=month, employee_id=None, db=db, actor=actor)
    output = io.StringIO(); output.write("\ufeff")
    writer = csv.writer(output); writer.writerow(["Employee", "Date", "Status", "Worked minutes", "First started", "Last ended", "Source", "Confirmed"])
    for item in data["items"]: writer.writerow([item["employee_name"], item["attendance_date"], item["status"] or "", item["worked_minutes"], item["first_started_at"] or "", item["last_ended_at"] or "", item["source"], item["confirmed"]])
    return Response(content=output.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="attendance-{data["month"]}.csv"'})


def _plain_number(value) -> str:
    """Numeric column as a form value: 4000000.0000 -> "4000000", 8.50 -> "8.5"."""
    return format(Decimal(str(value if value is not None else 0)).normalize(), "f")


def _monthly_payroll_profile_out(profile: MonthlyPayrollProfile | None, history: list[MonthlyPayrollSalaryHistory], employee_id: int) -> dict:
    today = date.today()
    current = next((row for row in history if row.valid_from <= today), history[0] if history else None)
    return {
        "employee_id": employee_id,
        "base_salary": _plain_number(current.monthly_salary if current else 0),
        "effective_from": current.valid_from.isoformat() if current else today.isoformat(),
        "salary_type": profile.salary_type if profile else "PRORATION",
        "meal_allowance": _plain_number(profile.meal_allowance if profile else 0),
        "commute_allowance": _plain_number(profile.commute_allowance if profile else 0),
        "allowance_basis": profile.allowance_basis if profile else "FIXED",
        "allowance_payout": profile.allowance_payout if profile else "FINAL",
        "payment_frequency": profile.payment_frequency if profile else "MONTHLY",
        "pay_days": profile.pay_days if profile else [25],
        "advance_basis": profile.advance_basis if profile else "FIXED",
        "advance_values": [_plain_number(value) for value in (profile.advance_values if profile else [])],
        "daily_norm_hours": _plain_number(profile.daily_norm_hours if profile else 8),
        "insured_type": profile.insured_type if profile else "01001",
        "tax_relief_eligible": profile.tax_relief_eligible if profile else True,
        "salary_history": [{"monthly_salary": _plain_number(row.monthly_salary), "valid_from": row.valid_from.isoformat()} for row in history],
    }


@router.get("/employees/{employee_id}/payroll-profile")
async def get_monthly_payroll_profile(employee_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    if not can_manage_hr(actor): raise HTTPException(status_code=403, detail="Payroll profile is restricted to HR")
    await employee_in_scope(db, actor, employee_id)
    profile = await db.scalar(select(MonthlyPayrollProfile).where(MonthlyPayrollProfile.organization_id == actor.organization_id, MonthlyPayrollProfile.employee_id == employee_id))
    history = list((await db.execute(select(MonthlyPayrollSalaryHistory).join(MonthlyPayrollProfile, MonthlyPayrollProfile.id == MonthlyPayrollSalaryHistory.profile_id).where(MonthlyPayrollProfile.organization_id == actor.organization_id, MonthlyPayrollProfile.employee_id == employee_id).order_by(MonthlyPayrollSalaryHistory.valid_from.desc()))).scalars())
    return _monthly_payroll_profile_out(profile, history, employee_id)


@router.put("/employees/{employee_id}/payroll-profile")
async def save_monthly_payroll_profile(employee_id: int, data: MonthlyPayrollProfileInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles(*HR_ROLES))):
    employee = await employee_in_scope(db, actor, employee_id, write=True)
    if not employee.is_active or employee.deleted_at is not None:
        raise HTTPException(status_code=409, detail={"code": "payroll_profile_inactive_worker"})
    profile = await db.scalar(select(MonthlyPayrollProfile).where(MonthlyPayrollProfile.organization_id == actor.organization_id, MonthlyPayrollProfile.employee_id == employee_id).with_for_update())
    values = data.model_dump(exclude={"base_salary", "effective_from"})
    values["advance_values"] = [str(value) for value in data.advance_values]
    if profile is None:
        profile = MonthlyPayrollProfile(organization_id=actor.organization_id, employee_id=employee_id, **values)
        db.add(profile)
        await db.flush()
    else:
        for key, value in values.items(): setattr(profile, key, value)
    salary = await db.scalar(select(MonthlyPayrollSalaryHistory).where(MonthlyPayrollSalaryHistory.profile_id == profile.id, MonthlyPayrollSalaryHistory.valid_from == data.effective_from).with_for_update())
    if salary is None:
        salary = MonthlyPayrollSalaryHistory(profile_id=profile.id, monthly_salary=data.base_salary, valid_from=data.effective_from, created_by_account_id=actor.account_id)
        db.add(salary)
    else:
        salary.monthly_salary = data.base_salary
        salary.created_by_account_id = actor.account_id
    await record_change(db, actor=actor, topic="hr", aggregate_type="monthly_payroll_profile", aggregate_id=profile.id, operation="saved", after={"employee_id": employee_id, "effective_from": data.effective_from.isoformat(), "salary_type": data.salary_type, "payment_frequency": data.payment_frequency, "pay_days": data.pay_days})
    await db.commit()
    history = list((await db.execute(select(MonthlyPayrollSalaryHistory).where(MonthlyPayrollSalaryHistory.profile_id == profile.id).order_by(MonthlyPayrollSalaryHistory.valid_from.desc()))).scalars())
    return _monthly_payroll_profile_out(profile, history, employee_id)


@router.post("/employees/{employee_id}/payroll-profile/preview")
async def preview_monthly_payroll_profile(employee_id: int, data: MonthlyPayrollProfileInput, month: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"), db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    if not can_manage_hr(actor): raise HTTPException(status_code=403, detail="Payroll preview is restricted to HR")
    employee = await employee_in_scope(db, actor, employee_id)
    if not employee.is_active or employee.deleted_at is not None:
        raise HTTPException(status_code=409, detail={"code": "payroll_profile_inactive_worker"})
    try:
        year, month_number = (int(value) for value in (month or date.today().strftime("%Y-%m")).split("-"))
        period_start = date(year, month_number, 1)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "payroll_preview_month_invalid"}) from exc
    next_month = date(year + (month_number == 12), 1 if month_number == 12 else month_number + 1, 1)
    period_end = next_month - timedelta(days=1)
    await ensure_default_rule_set(db, actor.organization_id)
    rule_set = await db.scalar(select(MonthlyPayrollRuleSet).where(MonthlyPayrollRuleSet.organization_id == actor.organization_id, MonthlyPayrollRuleSet.status == "published", MonthlyPayrollRuleSet.valid_from <= period_start, (MonthlyPayrollRuleSet.valid_to.is_(None) | (MonthlyPayrollRuleSet.valid_to >= period_start))).order_by(MonthlyPayrollRuleSet.valid_from.desc(), MonthlyPayrollRuleSet.version.desc()).limit(1))
    if not rule_set:
        raise HTTPException(status_code=409, detail={"code": "payroll_monthly_rules_missing", "message": "Нийтлэгдсэн татварын дүрэм алга."})
    rules = PayrollRules(
        minimum_wage=Decimal(str(rule_set.minimum_wage)),
        shi_cap_multiplier=Decimal(str(rule_set.shi_cap_multiplier)),
        employee_shi_rates={key: Decimal(str(value)) for key, value in rule_set.employee_rates.items()},
        employer_shi_rates={key: Decimal(str(value)) for key, value in rule_set.employer_rates.items()},
        pit_brackets=tuple((Decimal(str(row["lower"])), Decimal(str(row["upper"])) if row.get("upper") is not None else None, Decimal(str(row["rate"])), Decimal(str(row.get("base_tax", 0))) ) for row in rule_set.pit_brackets),
        relief_tiers=tuple((Decimal(str(row["lower"])), Decimal(str(row["upper"])) if row.get("upper") is not None else None, Decimal(str(row["amount"]))) for row in rule_set.relief_tiers),
        overtime_multipliers={key: Decimal(str(value)) for key, value in rule_set.overtime_multipliers.items()},
    )
    calendar_rows = list((await db.execute(select(MonthlyPayrollCalendarDay).where(MonthlyPayrollCalendarDay.organization_id == actor.organization_id, MonthlyPayrollCalendarDay.calendar_date.between(period_start, period_end)))).scalars())
    holiday_rows = list((await db.execute(select(HolidayRecord).where(HolidayRecord.organization_id == actor.organization_id, HolidayRecord.is_active.is_(True), HolidayRecord.holiday_date.between(period_start, period_end)))).scalars())
    calendar_days = month_calendar(year, month_number, overrides={row.calendar_date: row.day_type for row in calendar_rows}, public_holidays={row.holiday_date: row.local_name or row.name for row in holiday_rows})
    working_dates = [day for day, kind in calendar_days.items() if kind is CalendarDayType.WORKING]
    if not working_dates:
        raise HTTPException(status_code=422, detail={"code": "payroll_calendar_has_no_working_days"})
    # «Бүтэн сарын тооцоо»: a full month at the salary being entered. A
    # mid-month effective date is split only in the actual payroll run.
    segments = [SalarySegment(data.base_salary, len(working_dates), Decimal(len(working_dates)) * data.daily_norm_hours)]
    profile = PayrollProfile(
        base_salary=data.base_salary, salary_type=data.salary_type,
        meal_allowance=data.meal_allowance, commute_allowance=data.commute_allowance, allowance_basis=data.allowance_basis, allowance_payout=data.allowance_payout,
        payment_frequency=data.payment_frequency, pay_days=tuple(data.pay_days),
        advance_basis=AdvanceBasis(data.advance_basis), daily_norm_hours=data.daily_norm_hours,
        insured_type=data.insured_type, tax_relief_eligible=data.tax_relief_eligible,
    )
    planned_hours = Decimal(len(working_dates)) * data.daily_norm_hours
    final = calculate_monthly_run(PayrollRunType.FINAL, profile, rules=rules, planned_days=len(working_dates), planned_hours=planned_hours, worked_normal_hours=planned_hours, worked_days=len(working_dates), salary_segments=segments)
    pay_dates = pay_dates_for_month(profile, year, month_number)
    advance_schedule = []
    advance_dates = pay_dates[:-1]
    for index, pay_date in enumerate(advance_dates):
        value = data.advance_values[index] if index < len(data.advance_values) else Decimal("0")
        advance_profile = replace(profile, advance_amount=value if data.advance_basis == "FIXED" else Decimal("0"), advance_percent=value if data.advance_basis == "PERCENT" else Decimal("40"))
        elapsed_days = sum(1 for day in working_dates if day < pay_date)
        advance_result = calculate_monthly_run(PayrollRunType.ADVANCE, advance_profile, rules=rules, planned_days=len(working_dates), planned_hours=planned_hours, worked_to_date_hours=Decimal(elapsed_days) * data.daily_norm_hours, elapsed_planned_days=elapsed_days, advance_pay_day=profile.pay_days[index], worked_days=len(working_dates))
        advance_schedule.append({"pay_date": pay_date.isoformat(), "basis": data.advance_basis, "value": str(value) if data.advance_basis != "WORKED-TO-DATE" else None, "estimated_amount": str(advance_result.advance)})
    return {"month": period_start.strftime("%Y-%m"), "gross": str(final.gross), "employee_shi": str(final.employee_shi), "taxable_income": str(final.taxable_income), "pit_before_relief": str(final.pit_before_relief), "relief": str(final.relief), "pit": str(final.pit), "net_pay": str(final.net_pay), "advance_schedule": advance_schedule}


@router.get("/employees/{employee_id}/payroll-bank-accounts")
async def list_monthly_payroll_bank_accounts(employee_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    if not can_manage_hr(actor):
        raise HTTPException(status_code=403, detail="Payroll bank details are restricted to HR")
    await employee_in_scope(db, actor, employee_id)
    accounts = (await db.execute(select(EmployeeBankAccount).where(
        EmployeeBankAccount.employee_id == employee_id,
    ).order_by(EmployeeBankAccount.is_primary.desc(), EmployeeBankAccount.valid_from.desc()))).scalars().all()
    return [{"id": item.id, "bank_code": item.bank_code, "account_last4": item.account_last4, "is_primary": item.is_primary, "valid_from": item.valid_from.isoformat(), "valid_to": item.valid_to.isoformat() if item.valid_to else None} for item in accounts]


@router.post("/employees/{employee_id}/payroll-bank-accounts", status_code=status.HTTP_201_CREATED)
async def save_monthly_payroll_bank_account(employee_id: int, data: BankAccountInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles(*HR_ROLES))):
    await employee_in_scope(db, actor, employee_id, write=True)
    account = await create_bank_account(db, actor, employee_id, data)
    await record_change(db, actor=actor, topic="hr", aggregate_type="employee_bank_account", aggregate_id=account.id, operation="created", after={"employee_id": employee_id, "bank_code": account.bank_code, "account_last4": account.account_last4, "is_primary": account.is_primary})
    await db.commit()
    await db.refresh(account)
    return {"id": account.id, "bank_code": account.bank_code, "account_last4": account.account_last4, "is_primary": account.is_primary, "valid_from": account.valid_from.isoformat(), "valid_to": account.valid_to.isoformat() if account.valid_to else None}


@router.get("/employees/{employee_id}/compensation")
async def list_compensation(employee_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    if not can_manage_hr(actor): raise HTTPException(status_code=403, detail="Compensation is restricted to HR")
    await employee_in_scope(db, actor, employee_id)
    rows = (await db.execute(select(EmployeeCompensationItem, PayrollSalaryComponentMaster).join(PayrollSalaryComponentMaster, PayrollSalaryComponentMaster.id == EmployeeCompensationItem.component_master_id).where(EmployeeCompensationItem.organization_id == actor.organization_id, EmployeeCompensationItem.employee_id == employee_id).order_by(EmployeeCompensationItem.effective_from.desc()))).all()
    return [{"id": row.id, "component_master_id": row.component_master_id, "component_name": master.name, "component_kind": master.component_kind, "amount": str(row.amount), "effective_from": row.effective_from.isoformat(), "effective_to": row.effective_to.isoformat() if row.effective_to else None, "is_active": row.is_active} for row, master in rows]


@router.post("/employees/{employee_id}/compensation", status_code=status.HTTP_201_CREATED)
async def add_compensation(employee_id: int, data: CompensationItemInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles(*HR_ROLES))):
    await employee_in_scope(db, actor, employee_id, write=True)
    master = await db.scalar(select(PayrollSalaryComponentMaster).where(PayrollSalaryComponentMaster.id == data.component_master_id, PayrollSalaryComponentMaster.organization_id == actor.organization_id, PayrollSalaryComponentMaster.status.in_(("active", "published"))))
    if not master: raise HTTPException(status_code=404, detail="Salary component not found")
    row = EmployeeCompensationItem(organization_id=actor.organization_id, employee_id=employee_id, **data.model_dump()); db.add(row); await db.flush(); await db.commit()
    return {"id": row.id, "employee_id": employee_id, "component_master_id": row.component_master_id, "amount": str(row.amount), "effective_from": row.effective_from.isoformat(), "effective_to": row.effective_to.isoformat() if row.effective_to else None}


@router.delete("/compensation/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_compensation(item_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles(*HR_ROLES))):
    row = await db.scalar(select(EmployeeCompensationItem).where(EmployeeCompensationItem.id == item_id, EmployeeCompensationItem.organization_id == actor.organization_id))
    if not row: raise HTTPException(status_code=404, detail="Compensation item not found")
    row.is_active = False; await db.commit(); return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/payroll/generate")
async def generate_hr_payroll():
    raise HTTPException(status_code=410, detail={"code": "payroll_workflow_retired", "message": "HR цалингийн хуучин үүсгэх урсгал хаагдсан. Сарын цалингийн самбарыг ашиглана уу.", "monthly_path": "/erp/payroll/monthly"})


@router.get("/me")
async def get_my_hr_summary(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    if not actor.employee_id: return {"employee": None, "leave_balances": [], "payslips": []}
    employee = await employee_in_scope(db, actor, actor.employee_id)
    return {"employee": await _employee_out(db, actor, employee), "leave_balances": [await leave_balance(db, actor.organization_id, actor.employee_id, date.today().year, leave_type) for leave_type in ("annual", "sick", "unpaid")]}
