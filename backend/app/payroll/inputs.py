"""Canonical HR inputs shared by every Payroll Entry creation path."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.models.models import (
    AttendanceLog, Employee, EmployeeCompensationItem, EmployeeDetails, HolidayRecord,
    TimeOff, WorkTimeEntry, AdditionalSalary, PayrollSalaryComponentMaster,
    Schedule,
)


def payment_days(start: date, end: date, *, employment_start=None, employment_end=None,
                 holidays=(), attendance=None, leaves=(), approved_work=None,
                 validate_attendance=True, workweek=(0, 1, 2, 3, 4), hours_per_day=8):
    """Reconcile each calendar day once; approved leave overrides absence."""
    attendance, approved_work = attendance or {}, approved_work or {}
    holidays = set(holidays)
    scheduled = payable = unpaid = Decimal("0")
    hours = Decimal("0")
    missing, days, unpaid_leave_ids = [], [], set()
    for offset in range((end - start).days + 1):
        day = start + timedelta(days=offset)
        if day.weekday() not in workweek or day in holidays:
            continue
        scheduled += 1
        if (employment_start and day < employment_start) or (employment_end and day > employment_end):
            continue
        row = attendance.get(day)
        status = row.get("status") if row else None
        applicable = [leave for leave in leaves if leave["start"] <= day <= leave["end"]]
        unpaid_fraction = max((min(Decimal("1"), Decimal(str(leave.get("minutes") or hours_per_day * 60)) / Decimal(str(hours_per_day * 60))) for leave in applicable if leave["type"] == "unpaid"), default=Decimal("0"))
        if applicable:
            fraction, source = 1 - unpaid_fraction, "leave"
        elif status in {"present", "remote", "late"} or day in approved_work:
            fraction, source = Decimal("1"), "attendance" if row else "approved_worktime"
        elif status == "half_day":
            fraction, source = Decimal("0.5"), "attendance"
        elif status == "absent":
            fraction, source = Decimal("0"), "attendance"
        elif not validate_attendance:
            fraction, source = Decimal("1"), "leave_based_policy"
        else:
            fraction, source = Decimal("0"), "missing"
            missing.append(day.isoformat())
        payable += fraction
        unpaid += 1 - fraction if source != "missing" else 0
        unpaid_leave_ids.update(leave["id"] for leave in applicable if leave["type"] == "unpaid")
        worked = (row or {}).get("minutes") or approved_work.get(day) or hours_per_day * 60
        hours += Decimal(str(hours_per_day)) * fraction if applicable or not row else min(Decimal(str(worked)) / 60, Decimal(str(hours_per_day)) * fraction)
        days.append({"date": day.isoformat(), "fraction": str(fraction), "source": source,
                     "attendance_id": (row or {}).get("id"), "leave_ids": [leave["id"] for leave in applicable]})
    return {"scheduled_workdays": str(scheduled), "payable_workdays": str(payable),
            "scheduled_hours": str(scheduled * Decimal(str(hours_per_day))), "payable_hours": str(hours),
            "unpaid_leave_days": str(unpaid), "unpaid_leave_ids": sorted(unpaid_leave_ids),
            "missing_dates": missing, "days": days}


async def build_employee_inputs(db, run, employees, profiles):
    ids = [employee.id for employee in employees]
    org, start, end = run.organization_id, run.period_start, run.period_end
    details = {row.employee_id: row for row in (await db.execute(select(EmployeeDetails).where(EmployeeDetails.organization_id == org, EmployeeDetails.employee_id.in_(ids)))).scalars()}
    schedules = {row.employee_id: row for row in (await db.execute(select(Schedule).where(Schedule.employee_id.in_(ids)))).scalars()}
    holidays = list((await db.execute(select(HolidayRecord.holiday_date).where(HolidayRecord.organization_id == org, HolidayRecord.is_active.is_(True), HolidayRecord.holiday_date.between(start, end)))).scalars())
    logs = list((await db.execute(select(AttendanceLog).where(AttendanceLog.organization_id == org, AttendanceLog.employee_id.in_(ids), AttendanceLog.attendance_date.between(start, end), AttendanceLog.confirmed_at.is_not(None)))).scalars())
    leaves = list((await db.execute(select(TimeOff).where(TimeOff.organization_id == org, TimeOff.employee_id.in_(ids), TimeOff.status == "approved", TimeOff.starts_on <= end, TimeOff.ends_on >= start))).scalars())
    local_zone = ZoneInfo("Asia/Ulaanbaatar")
    work = list((await db.execute(select(WorkTimeEntry).join(Employee, Employee.id == WorkTimeEntry.employee_id).where(Employee.organization_id == org, WorkTimeEntry.employee_id.in_(ids), WorkTimeEntry.entry_type == "work", WorkTimeEntry.approval_status == "approved", WorkTimeEntry.ended_at.is_not(None), WorkTimeEntry.started_at >= datetime.combine(start, datetime.min.time(), local_zone), WorkTimeEntry.started_at < datetime.combine(end + timedelta(days=1), datetime.min.time(), local_zone)))).scalars())
    overrides, errors = {}, []
    for employee in employees:
        detail, profile = details.get(employee.id), profiles[employee.id]
        schedule = schedules.get(employee.id)
        workweek = tuple(max(0, min(6, int(day) - 1)) for day in (schedule.weekdays if schedule and schedule.weekdays else [1, 2, 3, 4, 5]))
        workweek = tuple(dict.fromkeys(workweek)) or (0, 1, 2, 3, 4)
        hours_per_day = Decimal(str(employee.weekly_capacity_minutes or 2400)) / Decimal(str(len(workweek) * 60))
        work_minutes = {}
        for entry in work:
            if entry.employee_id == employee.id:
                day = entry.local_work_date or entry.started_at.astimezone(local_zone).date()
                work_minutes[day] = work_minutes.get(day, 0) + max(0, (entry.ended_at - entry.started_at).total_seconds() / 60)
        inputs = payment_days(start, end, employment_start=detail.start_date if detail else None,
            employment_end=detail.end_date if detail else None, holidays=holidays,
            attendance={row.attendance_date: {"id": row.id, "status": row.status, "minutes": row.worked_minutes} for row in logs if row.employee_id == employee.id},
            leaves=[{"id": row.id, "start": row.starts_on, "end": row.ends_on, "type": row.time_off_type, "minutes": row.partial_day_minutes} for row in leaves if row.employee_id == employee.id],
            approved_work=work_minutes, validate_attendance=(run.input_snapshot or {}).get("validate_attendance", True),
            workweek=workweek, hours_per_day=hours_per_day)
        if inputs["missing_dates"]:
            errors.append({"employee_id": employee.id, "name": employee.name, "code": "payroll_attendance_missing", "dates": inputs["missing_dates"], "message": "Confirm attendance or approve leave for the missing dates."})
        inputs["employee_profile_id"] = profile.id
        inputs["attendance_policy"] = {
            "basis": "confirmed_hr_attendance_and_approved_leave",
            "missing_attendance": "error" if (run.input_snapshot or {}).get("validate_attendance", True) else "full_day",
            "timezone": local_zone.key,
            "workweek_iso": [day + 1 for day in workweek],
            "hours_per_day": str(hours_per_day),
        }
        # Calendar proration uses the employment window, independently of weekdays.
        eligible_start = max(start, detail.start_date) if detail and detail.start_date else start
        eligible_end = min(end, detail.end_date) if detail and detail.end_date else end
        inputs["scheduled_calendar_days"] = str((end - start).days + 1)
        inputs["payable_calendar_days"] = str(max(Decimal("0"), Decimal((eligible_end - eligible_start).days + 1) - Decimal(inputs["unpaid_leave_days"])))
        overrides[str(employee.id)] = inputs
    return overrides, errors


async def prepare_recurring_compensation(db, run):
    """Materialize recurring inputs once per employee compensation/month."""
    ids = (run.input_snapshot or {}).get("employee_ids", [])
    rows = (await db.execute(select(EmployeeCompensationItem, PayrollSalaryComponentMaster).join(PayrollSalaryComponentMaster, PayrollSalaryComponentMaster.id == EmployeeCompensationItem.component_master_id).where(EmployeeCompensationItem.organization_id == run.organization_id, EmployeeCompensationItem.employee_id.in_(ids), EmployeeCompensationItem.is_active.is_(True), EmployeeCompensationItem.effective_from <= run.period_end, (EmployeeCompensationItem.effective_to.is_(None) | (EmployeeCompensationItem.effective_to >= run.period_start)), PayrollSalaryComponentMaster.status == "active"))).all()
    if run.run_type == "advance":
        return
    for item, master in rows:
        number = f"HR-COMP-{item.id}-{run.period_end:%Y%m}"
        existing = await db.scalar(select(AdditionalSalary.id).where(AdditionalSalary.organization_id == run.organization_id, AdditionalSalary.number == number))
        if existing is None and master.component_kind in {"earning", "deduction"}:
            db.add(AdditionalSalary(organization_id=run.organization_id, number=number, employee_id=item.employee_id, salary_component_id=master.id, payroll_date=run.period_end, amount=item.amount, component_kind=master.component_kind, taxable=master.is_taxable, shi_subject=master.is_shi_subject, source="import", reference=f"hr-recurring:{item.id}:{run.period_end:%Y-%m}", status="submitted", created_by_account_id=run.created_by_account_id))
    await db.flush()
