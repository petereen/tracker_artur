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
    is_active: bool | None = None
    restore: bool = False
    timezone: str | None = None


class MonthlyPayrollProfileInput(BaseModel):
    base_salary: Decimal = Field(ge=0)
    effective_from: date
    salary_type: Literal["PRORATION", "FIXED"] = "PRORATION"
    meal_allowance: Decimal = Field(default=Decimal("0"), ge=0)
    commute_allowance: Decimal = Field(default=Decimal("0"), ge=0)
    payment_frequency: Literal["MONTHLY", "BIWEEKLY", "WEEKLY"] = "MONTHLY"
    pay_days: list[int]
    advance_basis: Literal["FIXED", "PERCENT", "WORKED-TO-DATE"] = "FIXED"
    advance_values: list[Decimal] = Field(default_factory=list)
    daily_norm_hours: Decimal = Field(default=Decimal("8"), gt=0, le=24)
    insured_type: str = Field(default="01001", min_length=1, max_length=32)
    tax_relief_eligible: bool = True

    @model_validator(mode="after")
    def validate_schedule(self):
        required = {"MONTHLY": 1, "BIWEEKLY": 2, "WEEKLY": 4}[self.payment_frequency]
        if len(self.pay_days) != required or any(day < 1 or day > 31 for day in self.pay_days):
            raise ValueError(f"{self.payment_frequency} requires {required} pay day(s), each between 1 and 31")
        if self.pay_days != sorted(set(self.pay_days)):
            raise ValueError("Pay days must be unique and in ascending order")
        advance_count = max(0, required - 1)
        expected_values = advance_count if self.advance_basis in {"FIXED", "PERCENT"} else 0
        if len(self.advance_values) != expected_values:
            raise ValueError(f"{self.advance_basis} requires {expected_values} advance value(s)")
        if any(value < 0 for value in self.advance_values):
            raise ValueError("Advance values cannot be negative")
        if self.advance_basis == "PERCENT" and any(value > 100 for value in self.advance_values):
            raise ValueError("Advance percentages cannot exceed 100")
        return self


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
    status: Literal["approved", "rejected"] | None = None
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
