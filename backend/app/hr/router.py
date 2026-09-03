from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.enterprise_deps import ActorContext, get_actor, require_roles
from app.models.models import (
    AttendanceLog,
    Department,
    Employee,
    EmployeeCompensationItem,
    EmployeeDetails,
    EmployeePayrollProfile,
    LeaveBalance,
    PayrollRun,
    PayrollSalaryComponentMaster,
    AdditionalSalary,
    RoleAssignment,
    TimeOff,
    UserAccount,
    WorkerInvite,
)
from app.payroll.frappe_service import create_payroll_entry
from app.payroll.schemas import PayrollEntryInput
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
    PayrollGenerateInput,
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
    create_invite,
    employee_in_scope,
    ensure_details,
    leave_balance,
    leave_days,
    suggested_attendance,
)


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
        "end_date": details.end_date.isoformat() if details and details.end_date else None, "employment_status": details.employment_status if details else ("active" if employee.is_active else "inactive"),
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
async def list_hr_employees(search: str | None = Query(default=None, max_length=160), department_id: int | None = None, status_filter: str | None = Query(default=None, alias="status"), telegram_status: str | None = None, page: int = Query(default=1, ge=1), page_size: int = Query(default=50, ge=1, le=200), db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    query = select(Employee, EmployeeDetails).outerjoin(EmployeeDetails, EmployeeDetails.employee_id == Employee.id).where(Employee.organization_id == actor.organization_id, *_employee_scope_clause(actor))
    if search:
        term = f"%{search.strip()}%"
        query = query.where(or_(Employee.name.ilike(term), Employee.telegram_username.ilike(term), Employee.first_name.ilike(term), Employee.last_name.ilike(term), EmployeeDetails.job_title.ilike(term)))
    if department_id is not None: query = query.where(EmployeeDetails.department_id == department_id)
    if status_filter in {"active", "inactive", "terminated"}: query = query.where((EmployeeDetails.employment_status if status_filter != "active" else EmployeeDetails.employment_status) == status_filter)
    rows = (await db.execute(query.order_by(Employee.name).offset((page - 1) * page_size).limit(page_size))).all()
    items = [await _employee_out(db, actor, employee, details) for employee, details in rows]
    if telegram_status: items = [item for item in items if item["telegram_status"] == telegram_status]
    total = await db.scalar(select(func.count(Employee.id)).select_from(Employee).outerjoin(EmployeeDetails, EmployeeDetails.employee_id == Employee.id).where(Employee.organization_id == actor.organization_id, *_employee_scope_clause(actor))) or 0
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
    for key, value in patch.items(): setattr(details, key, value)
    if "employment_status" in patch: employee.is_active = patch["employment_status"] == "active"
    await record_change(db, actor=actor, topic="hr", aggregate_type="employee", aggregate_id=employee.id, operation="updated", after=data.model_dump(exclude_unset=True))
    await db.commit()
    return await _employee_out(db, actor, employee, details)


@router.delete("/employees/{employee_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_hr_employee(employee_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles(*HR_ROLES))):
    employee = await employee_in_scope(db, actor, employee_id, write=True)
    employee.is_active = False
    details = await ensure_details(db, employee); details.employment_status = "inactive"
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
        body=f"{employee.name if employee else 'Ажилтан'}-ны чөлөөний хүсэлт {status_label}.{feedback}",
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
    output = []
    current = start
    while current <= end:
        for employee in employees:
            log = by_key.get((employee.id, current)); suggestion = await suggested_attendance(db, employee, current)
            output.append({"id": log.id if log else None, "employee_id": employee.id, "employee_name": employee.name, "attendance_date": current.isoformat(), "status": log.status if log else suggestion.get("suggested_status"), "suggested_status": suggestion.get("suggested_status"), "on_leave": suggestion.get("on_leave", False), "source": log.source if log else "derived", "worked_minutes": log.worked_minutes if log else suggestion.get("worked_minutes", 0), "first_started_at": log.first_started_at if log else suggestion.get("first_started_at"), "last_ended_at": log.last_ended_at if log else suggestion.get("last_ended_at"), "confirmed": bool(log and log.confirmed_at), "version": log.version if log else None})
        current += timedelta(days=1)
    return output


@router.get("/attendance")
async def list_attendance(month: str | None = None, employee_id: int | None = None, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    try:
        start = date.fromisoformat((month or date.today().strftime("%Y-%m")) + "-01")
    except ValueError: raise HTTPException(status_code=422, detail="month must use YYYY-MM")
    end = date(start.year + (1 if start.month == 12 else 0), 1 if start.month == 12 else start.month + 1, 1) - timedelta(days=1)
    if employee_id: await employee_in_scope(db, actor, employee_id)
    return {"month": start.strftime("%Y-%m"), "items": await _attendance_items(db, actor, start, end, employee_id)}


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
    data = await list_attendance(month, None, db, actor)
    output = io.StringIO(); output.write("\ufeff")
    writer = csv.writer(output); writer.writerow(["Employee", "Date", "Status", "Worked minutes", "First started", "Last ended", "Source", "Confirmed"])
    for item in data["items"]: writer.writerow([item["employee_name"], item["attendance_date"], item["status"] or "", item["worked_minutes"], item["first_started_at"] or "", item["last_ended_at"] or "", item["source"], item["confirmed"]])
    return Response(content=output.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="attendance-{data["month"]}.csv"'})


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
async def generate_hr_payroll(data: PayrollGenerateInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles(*HR_ROLES)), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    employee_ids = data.employee_ids or list((await db.execute(select(Employee.id).where(Employee.organization_id == actor.organization_id, Employee.is_active.is_(True)))).scalars().all())
    employee_ids = sorted(set(employee_ids)); key = idempotency_key or f"{data.period_start}:{data.period_end}:{','.join(map(str, employee_ids))}"
    existing = await db.scalar(select(PayrollRun).where(PayrollRun.organization_id == actor.organization_id, PayrollRun.hr_generation_key == key))
    if existing: return {"run_id": existing.id, "run_number": existing.run_number, "idempotent": True, "period_start": existing.period_start, "period_end": existing.period_end}
    overrides: dict[str, dict] = {}
    leaves = (await db.execute(select(TimeOff).where(TimeOff.organization_id == actor.organization_id, TimeOff.employee_id.in_(employee_ids), TimeOff.status == "approved", TimeOff.time_off_type == "unpaid", TimeOff.starts_on <= data.period_end, TimeOff.ends_on >= data.period_start))).scalars().all()
    for leave in leaves:
        start, end = max(leave.starts_on, data.period_start), min(leave.ends_on, data.period_end)
        days = await leave_days(db, actor.organization_id, start, end)
        current = overrides.setdefault(str(leave.employee_id), {"unpaid_leave_days": Decimal("0"), "unpaid_leave_request_ids": []})
        current["unpaid_leave_days"] += Decimal(days); current["unpaid_leave_request_ids"].append(leave.id)
    run_input = PayrollEntryInput(run_type="final", period_start=data.period_start, period_end=data.period_end, posting_date=data.period_end, tax_point_date=data.tax_point_date or data.period_end, statutory_profile_id=data.statutory_profile_id, employee_ids=employee_ids, input_overrides={key: {k: str(v) if isinstance(v, Decimal) else v for k, v in value.items()} for key, value in overrides.items()}, validate_attendance=False)
    run = await create_payroll_entry(db, actor, run_input)
    run.hr_generation_key = key
    run.input_snapshot = {**(run.input_snapshot or {}), "hr_generated": True, "approved_unpaid_leave_ids": [row.id for row in leaves], "hr_input_overrides": {key: {k: str(v) if isinstance(v, Decimal) else v for k, v in value.items()} for key, value in overrides.items()}}
    masters = {row.id: row for row in (await db.execute(select(PayrollSalaryComponentMaster).where(PayrollSalaryComponentMaster.organization_id == actor.organization_id))).scalars().all()}
    for item in (await db.execute(select(EmployeeCompensationItem).where(EmployeeCompensationItem.organization_id == actor.organization_id, EmployeeCompensationItem.employee_id.in_(employee_ids), EmployeeCompensationItem.is_active.is_(True), EmployeeCompensationItem.effective_from <= data.period_end, or_(EmployeeCompensationItem.effective_to.is_(None), EmployeeCompensationItem.effective_to >= data.period_start)))).scalars().all():
        master = masters.get(item.component_master_id)
        if not master: continue
        number = f"HR-COMP-{item.id}-{data.period_end:%Y%m}"
        if not await db.scalar(select(AdditionalSalary.id).where(AdditionalSalary.organization_id == actor.organization_id, AdditionalSalary.number == number)):
            db.add(AdditionalSalary(organization_id=actor.organization_id, number=number, employee_id=item.employee_id, salary_component_id=master.id, payroll_date=data.period_end, amount=item.amount, component_kind=master.component_kind if master.component_kind in {"earning", "deduction"} else "earning", taxable=master.is_taxable, shi_subject=master.is_shi_subject, source="import", reference=f"hr-recurring:{item.id}:{data.period_end:%Y-%m}", status="submitted", created_by_account_id=actor.account_id))
    await record_change(db, actor=actor, topic="hr", aggregate_type="payroll_run", aggregate_id=run.id, operation="hr_generated", after={"run_id": run.id, "employee_count": len(employee_ids), "unpaid_leave_ids": [row.id for row in leaves]})
    await db.commit()
    return {"run_id": run.id, "run_number": run.run_number, "idempotent": False, "employee_ids": employee_ids, "unpaid_leave_ids": [row.id for row in leaves], "unpaid_leave_days": {key: str(value["unpaid_leave_days"]) for key, value in overrides.items()}, "next": f"/erp/payroll/payroll-entries/{run.id}"}


@router.get("/me")
async def get_my_hr_summary(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    if not actor.employee_id: return {"employee": None, "leave_balances": [], "payslips": []}
    employee = await employee_in_scope(db, actor, actor.employee_id)
    return {"employee": await _employee_out(db, actor, employee), "leave_balances": [await leave_balance(db, actor.organization_id, actor.employee_id, date.today().year, leave_type) for leave_type in ("annual", "sick", "unpaid")]}
