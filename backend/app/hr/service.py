from __future__ import annotations

import hashlib
import secrets
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.enterprise_deps import ActorContext
from app.core.security import hash_account_password
from app.core.telegram_auth import verify_init_data
from app.models.models import (
    AttendanceLog,
    Department,
    Employee,
    EmployeeCompensationItem,
    EmployeeDetails,
    HolidayRecord,
    LeaveBalance,
    RoleAssignment,
    Schedule,
    TimeOff,
    UserAccount,
    WorkerInvite,
    WorkTimeEntry,
)


HR_ROLES = ("admin", "hr")
MANAGER_ROLES = ("admin", "hr", "manager", "team_lead")
LEAVE_TYPES = {"annual", "sick", "unpaid"}
ATTENDANCE_STATUSES = {"present", "remote", "absent", "late"}


def can_manage_hr(actor: ActorContext) -> bool:
    return actor.has_any_role(*HR_ROLES)


def can_manage_attendance(actor: ActorContext) -> bool:
    return actor.has_any_role(*MANAGER_ROLES)


async def employee_in_scope(db: AsyncSession, actor: ActorContext, employee_id: int, *, write: bool = False) -> Employee:
    employee = await db.scalar(select(Employee).where(Employee.id == employee_id, Employee.organization_id == actor.organization_id))
    if not employee:
        raise HTTPException(status_code=404, detail="Worker not found")
    if can_manage_hr(actor):
        return employee
    if actor.has_any_role("manager", "team_lead"):
        if employee_id == actor.employee_id:
            return employee
        report = await db.scalar(select(EmployeeDetails.id).where(EmployeeDetails.organization_id == actor.organization_id, EmployeeDetails.employee_id == employee_id, EmployeeDetails.manager_id == actor.employee_id))
        if report:
            return employee
    if employee_id != actor.employee_id:
        raise HTTPException(status_code=403, detail="Worker is outside your scope")
    if write and not actor.employee_id:
        raise HTTPException(status_code=403, detail="Account is not linked to an employee")
    return employee


async def ensure_details(db: AsyncSession, employee: Employee, *, start_date: date | None = None) -> EmployeeDetails:
    details = await db.scalar(select(EmployeeDetails).where(EmployeeDetails.employee_id == employee.id))
    if details:
        return details
    details = EmployeeDetails(
        organization_id=employee.organization_id,
        employee_id=employee.id,
        manager_id=employee.manager_id,
        job_title=employee.job_title,
        start_date=start_date,
        employment_status="active" if employee.is_active else "inactive",
    )
    db.add(details)
    await db.flush()
    return details


def _token_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _display_name(user: dict[str, Any]) -> str:
    first = str(user.get("first_name") or "").strip()
    last = str(user.get("last_name") or "").strip()
    return " ".join(part for part in (first, last) if part).strip()


def _apply_telegram_identity(employee: Employee, user: dict[str, Any], telegram_id: str) -> None:
    employee.telegram_id = telegram_id
    employee.telegram_username = user.get("username") or employee.telegram_username
    employee.first_name = user.get("first_name") or employee.first_name
    employee.last_name = user.get("last_name") or employee.last_name
    employee.photo_url = user.get("photo_url") or employee.photo_url
    if _display_name(user):
        employee.name = _display_name(user)


async def create_invite(db: AsyncSession, actor: ActorContext, employee: Employee) -> dict[str, Any]:
    if not settings.TELEGRAM_BOT_USERNAME.strip():
        raise HTTPException(status_code=503, detail="Telegram bot username is not configured")
    await db.execute(
        WorkerInvite.__table__.update()
        .where(WorkerInvite.employee_id == employee.id, WorkerInvite.organization_id == actor.organization_id, WorkerInvite.used_at.is_(None), WorkerInvite.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )
    raw = secrets.token_urlsafe(32)
    invite = WorkerInvite(
        organization_id=actor.organization_id,
        employee_id=employee.id,
        token_hash=_token_hash(raw),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=settings.HR_INVITE_EXPIRE_HOURS),
        created_by_account_id=actor.account_id,
    )
    db.add(invite)
    await db.flush()
    bot = settings.TELEGRAM_BOT_USERNAME.strip().lstrip("@")
    return {"invite_id": invite.id, "expires_at": invite.expires_at, "deep_link": f"https://t.me/{bot}?start=invite_{raw}"}


async def bind_invite(db: AsyncSession, raw_token: str, init_data: str) -> dict[str, Any]:
    user = verify_init_data(init_data)
    if not user or not str(user.get("id") or "").isdigit():
        raise HTTPException(status_code=401, detail="Invalid Telegram identity")
    return await bind_invite_user(db, raw_token, user)


async def bind_invite_user(db: AsyncSession, raw_token: str, user: dict[str, Any]) -> dict[str, Any]:
    telegram_id = str(user.get("id") or "")
    if not telegram_id.isdigit():
        raise HTTPException(status_code=401, detail="Invalid Telegram identity")
    now = datetime.now(timezone.utc)
    invite = await db.scalar(select(WorkerInvite).where(WorkerInvite.token_hash == _token_hash(raw_token)).with_for_update())
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")
    if invite.used_at:
        raise HTTPException(status_code=409, detail="Invite has already been used")
    if invite.revoked_at or invite.expires_at <= now:
        raise HTTPException(status_code=410, detail="Invite has expired")
    duplicate = await db.scalar(select(Employee.id).where(Employee.telegram_id == telegram_id, Employee.id != invite.employee_id))
    if duplicate:
        raise HTTPException(status_code=409, detail="This Telegram account is already connected")
    employee = await db.scalar(select(Employee).where(Employee.id == invite.employee_id, Employee.organization_id == invite.organization_id).with_for_update())
    if not employee:
        raise HTTPException(status_code=404, detail="Worker not found")
    _apply_telegram_identity(employee, user, telegram_id)
    employee.is_active = True
    employee.onboarded_at = employee.onboarded_at or now
    details = await ensure_details(db, employee, start_date=now.date())
    details.employment_status = "active"
    invite.used_at = now
    invite.bound_telegram_id = telegram_id
    account = await db.scalar(select(UserAccount).where(UserAccount.employee_id == employee.id).with_for_update())
    if not account:
        account = UserAccount(
            organization_id=invite.organization_id,
            employee_id=employee.id,
            email=f"telegram-{telegram_id}",
            password_hash=hash_account_password(secrets.token_urlsafe(48)),
            status="active",
            locale=employee.primary_language or "mn",
            must_change_password=True,
        )
        db.add(account)
        await db.flush()
    else:
        account.status = "active"
    has_member = await db.scalar(select(RoleAssignment.id).where(RoleAssignment.account_id == account.id, RoleAssignment.role == "member"))
    if not has_member:
        db.add(RoleAssignment(account_id=account.id, role="member"))
    await db.flush()
    return {"employee_id": employee.id, "account_id": account.id, "name": employee.name, "telegram_connected": True}


def working_days(start: date, end: date, holidays: set[date]) -> int:
    return sum(1 for offset in range((end - start).days + 1) if (start + timedelta(days=offset)).weekday() < 5 and start + timedelta(days=offset) not in holidays)


async def holiday_dates(db: AsyncSession, organization_id: int, start: date, end: date) -> set[date]:
    rows = (await db.execute(select(HolidayRecord.holiday_date).where(HolidayRecord.organization_id == organization_id, HolidayRecord.is_active.is_(True), HolidayRecord.holiday_date >= start, HolidayRecord.holiday_date <= end))).scalars().all()
    return set(rows)


async def leave_days(db: AsyncSession, organization_id: int, starts_on: date, ends_on: date) -> int:
    return working_days(starts_on, ends_on, await holiday_dates(db, organization_id, starts_on, ends_on))


async def leave_balance(db: AsyncSession, organization_id: int, employee_id: int, year: int, leave_type: str) -> dict[str, Any]:
    row = await db.scalar(select(LeaveBalance).where(LeaveBalance.organization_id == organization_id, LeaveBalance.employee_id == employee_id, LeaveBalance.year == year, LeaveBalance.leave_type == leave_type))
    if not row:
        row = LeaveBalance(organization_id=organization_id, employee_id=employee_id, year=year, leave_type=leave_type)
        db.add(row)
        await db.flush()
    used = await db.scalar(select(func.coalesce(func.sum(TimeOff.working_days), 0)).where(TimeOff.organization_id == organization_id, TimeOff.employee_id == employee_id, TimeOff.time_off_type == leave_type, TimeOff.status == "approved", TimeOff.starts_on >= date(year, 1, 1), TimeOff.starts_on <= date(year, 12, 31))) or 0
    pending = await db.scalar(select(func.coalesce(func.sum(TimeOff.working_days), 0)).where(TimeOff.organization_id == organization_id, TimeOff.employee_id == employee_id, TimeOff.time_off_type == leave_type, TimeOff.status == "pending", TimeOff.starts_on >= date(year, 1, 1), TimeOff.starts_on <= date(year, 12, 31))) or 0
    total = Decimal(row.entitled_days or 0) + Decimal(row.carried_days or 0) + Decimal(row.adjustment_days or 0)
    return {"id": row.id, "employee_id": employee_id, "year": year, "leave_type": leave_type, "entitled_days": str(row.entitled_days), "carried_days": str(row.carried_days), "adjustment_days": str(row.adjustment_days), "used_days": str(Decimal(str(used))), "pending_days": str(Decimal(str(pending))), "available_days": str(max(Decimal("0"), total - Decimal(str(used)) - Decimal(str(pending))))}


async def worktime_summary(db: AsyncSession, employee_id: int, local_day: date) -> dict[str, Any]:
    rows = (await db.execute(select(WorkTimeEntry).where(WorkTimeEntry.employee_id == employee_id, WorkTimeEntry.local_work_date == local_day, WorkTimeEntry.entry_type == "work", WorkTimeEntry.approval_status == "approved").order_by(WorkTimeEntry.started_at))).scalars().all()
    minutes = sum(round((row.ended_at - row.started_at).total_seconds() / 60) for row in rows if row.ended_at)
    first = rows[0].started_at if rows else None
    last = next((row.ended_at for row in reversed(rows) if row.ended_at), None)
    modes = {row.mode for row in rows if row.mode}
    return {"worked_minutes": minutes, "first_started_at": first, "last_ended_at": last, "suggested_status": "remote" if modes and modes == {"remote"} else "present" if rows else None}


async def suggested_attendance(db: AsyncSession, employee: Employee, local_day: date) -> dict[str, Any]:
    summary = await worktime_summary(db, employee.id, local_day)
    approved_leave = await db.scalar(select(TimeOff.id).where(TimeOff.organization_id == employee.organization_id, TimeOff.employee_id == employee.id, TimeOff.status == "approved", TimeOff.starts_on <= local_day, TimeOff.ends_on >= local_day))
    summary["on_leave"] = bool(approved_leave)
    if summary["suggested_status"] or approved_leave:
        if summary["suggested_status"] and summary.get("first_started_at"):
            schedule = await db.scalar(select(Schedule).where(Schedule.employee_id == employee.id))
            if schedule and schedule.morning_time:
                local_started = summary["first_started_at"].astimezone(ZoneInfo(employee.timezone or "Asia/Ulaanbaatar")).replace(tzinfo=None)
                threshold = datetime.combine(local_day, schedule.morning_time) + timedelta(minutes=settings.HR_ATTENDANCE_LATE_MINUTES)
                if local_started > threshold:
                    summary["suggested_status"] = "late"
        return summary
    if local_day >= date.today():
        summary["suggested_status"] = None
        return summary
    schedule = await db.scalar(select(Schedule).where(Schedule.employee_id == employee.id))
    if schedule and schedule.morning_time:
        summary["suggested_status"] = "absent"
    return summary
