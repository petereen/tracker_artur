from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


LeaveType = Literal["annual", "sick", "unpaid"]
AttendanceStatus = Literal["present", "remote", "absent", "late"]


class DepartmentInput(BaseModel):
    code: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=160)
    manager_employee_id: int | None = None


class DepartmentPatch(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    name: str | None = Field(default=None, min_length=1, max_length=160)
    manager_employee_id: int | None = None
    is_active: bool | None = None


class EmployeeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    telegram_id: str | None = Field(default=None, max_length=80)
    first_name: str | None = Field(default=None, max_length=120)
    last_name: str | None = Field(default=None, max_length=120)
    department_id: int | None = None
    manager_id: int | None = None
    job_title: str | None = Field(default=None, max_length=160)
    employment_role: str | None = Field(default=None, max_length=160)
    start_date: date | None = None
    timezone: str = "Asia/Ulaanbaatar"
    annual_leave_days: Decimal | None = Field(default=None, ge=0, le=366)


class EmployeePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    first_name: str | None = Field(default=None, max_length=120)
    last_name: str | None = Field(default=None, max_length=120)
    department_id: int | None = None
    manager_id: int | None = None
    job_title: str | None = Field(default=None, max_length=160)
    employment_role: str | None = Field(default=None, max_length=160)
    start_date: date | None = None
    end_date: date | None = None
    employment_status: Literal["active", "inactive", "terminated"] | None = None
    timezone: str | None = None


class LeaveRequestInput(BaseModel):
    employee_id: int | None = None
    leave_type: LeaveType = "annual"
    starts_on: date
    ends_on: date
    reason: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def valid_range(self):
        if self.ends_on < self.starts_on:
            raise ValueError("End date must not precede start date")
        return self


class LeaveRequestPatch(BaseModel):
    leave_type: LeaveType | None = None
    starts_on: date | None = None
    ends_on: date | None = None
    reason: str | None = Field(default=None, min_length=1, max_length=2000)
    version: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def valid_range(self):
        if self.starts_on and self.ends_on and self.ends_on < self.starts_on:
            raise ValueError("End date must not precede start date")
        return self


class LeaveDecisionInput(BaseModel):
    approve: bool
    feedback: str | None = Field(default=None, max_length=2000)
    version: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def rejection_feedback(self):
        if not self.approve and not (self.feedback or "").strip():
            raise ValueError("Feedback is required when rejecting a leave request")
        return self


class LeaveBalancePatch(BaseModel):
    year: int = Field(ge=2000, le=2200)
    leave_type: LeaveType = "annual"
    entitled_days: Decimal = Field(ge=0, le=366)
    carried_days: Decimal = Field(default=Decimal("0"), ge=0, le=366)
    adjustment_days: Decimal = Field(default=Decimal("0"), ge=-366, le=366)


class AttendanceUpdate(BaseModel):
    employee_id: int
    attendance_date: date
    status: AttendanceStatus
    note: str | None = Field(default=None, max_length=1000)
    version: int | None = Field(default=None, ge=1)


class AttendanceBulkUpdate(BaseModel):
    items: list[AttendanceUpdate] = Field(min_length=1, max_length=500)


class CompensationItemInput(BaseModel):
    component_master_id: int
    amount: Decimal = Field(gt=0)
    effective_from: date
    effective_to: date | None = None

    @model_validator(mode="after")
    def valid_range(self):
        if self.effective_to and self.effective_to < self.effective_from:
            raise ValueError("Effective end must not precede start")
        return self


class PayrollGenerateInput(BaseModel):
    period_start: date
    period_end: date
    tax_point_date: date | None = None
    employee_ids: list[int] = Field(default_factory=list)
    statutory_profile_id: int | None = None

    @model_validator(mode="after")
    def valid_range(self):
        if self.period_end < self.period_start:
            raise ValueError("Payroll end date must not precede start date")
        return self


class InviteBindInput(BaseModel):
    token: str = Field(min_length=20, max_length=512)
    init_data: str = Field(min_length=1, max_length=4096)
