import re
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .identity import normalize_registration_number, parse_registration_number


LeaveType = Literal["annual", "sick", "unpaid"]
AttendanceStatus = Literal["present", "remote", "absent", "late"]


EmploymentStatus = Literal["active", "probation", "on_leave", "suspended", "inactive", "terminated"]
EmploymentType = Literal["full_time", "part_time", "contract", "intern"]
Gender = Literal["male", "female"]

_PHONE_RE = re.compile(r"^\+?[0-9][0-9 ()-]{5,19}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_DEPARTMENT_CODE = r"^[A-Za-z0-9_-]+$"


def _blank_to_none(value):
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


class DepartmentInput(BaseModel):
    # Code is optional in the UI; the router derives one when it is blank.
    code: str | None = Field(default=None, max_length=80)
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    manager_employee_id: int | None = None

    @field_validator("code", "description", mode="before")
    @classmethod
    def blank(cls, value):
        return _blank_to_none(value)

    @field_validator("code")
    @classmethod
    def code_format(cls, value: str | None) -> str | None:
        if value is not None and not re.match(_DEPARTMENT_CODE, value):
            raise ValueError("Код зөвхөн латин үсэг, тоо, '-' болон '_' агуулна")
        return value

    @field_validator("name")
    @classmethod
    def name_stripped(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Хэлтсийн нэр хоосон байна")
        return value


class DepartmentPatch(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=80, pattern=_DEPARTMENT_CODE)
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    manager_employee_id: int | None = None
    is_active: bool | None = None


class _WorkerFields(BaseModel):
    """Profile fields shared by create and patch; all optional."""

    first_name: str | None = Field(default=None, max_length=120)
    last_name: str | None = Field(default=None, max_length=120)
    registration_number: str | None = Field(default=None, max_length=16)
    birthday: date | None = None
    gender: Gender | None = None
    phone_number: str | None = Field(default=None, max_length=32)
    email: str | None = Field(default=None, max_length=254)
    address: str | None = Field(default=None, max_length=1000)
    emergency_contact_name: str | None = Field(default=None, max_length=200)
    emergency_contact_phone: str | None = Field(default=None, max_length=32)
    department_id: int | None = None
    manager_id: int | None = None
    job_title: str | None = Field(default=None, max_length=160)
    employment_role: str | None = Field(default=None, max_length=160)
    employment_type: EmploymentType | None = None
    start_date: date | None = None
    probation_end_date: date | None = None
    end_date: date | None = None
    termination_reason: str | None = Field(default=None, max_length=2000)

    @field_validator(
        "first_name", "last_name", "registration_number", "phone_number", "email", "address",
        "emergency_contact_name", "emergency_contact_phone", "job_title", "employment_role", "termination_reason",
        mode="before",
    )
    @classmethod
    def blank(cls, value):
        return _blank_to_none(value)

    @field_validator("registration_number")
    @classmethod
    def registration_number_valid(cls, value: str | None) -> str | None:
        value = normalize_registration_number(value)
        if value is not None:
            parse_registration_number(value)
        return value

    @field_validator("phone_number", "emergency_contact_phone")
    @classmethod
    def phone_valid(cls, value: str | None) -> str | None:
        if value is not None and not _PHONE_RE.match(value):
            raise ValueError("Утасны дугаар буруу байна")
        return value

    @field_validator("email")
    @classmethod
    def email_valid(cls, value: str | None) -> str | None:
        if value is not None:
            value = value.lower()
            if not _EMAIL_RE.match(value):
                raise ValueError("Имэйл хаяг буруу байна")
        return value

    @model_validator(mode="after")
    def date_order(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("Ажлаас гарсан огноо ажилд орсон огнооноос өмнө байж болохгүй")
        if self.start_date and self.probation_end_date and self.probation_end_date < self.start_date:
            raise ValueError("Туршилтын хугацаа ажилд орсон огнооноос өмнө дуусах боломжгүй")
        return self


class EmployeeCreate(_WorkerFields):
    # Display name; derived from first/last name when omitted.
    name: str | None = Field(default=None, max_length=200)
    telegram_id: str | None = Field(default=None, max_length=80)
    employment_status: Literal["active", "probation"] = "active"
    timezone: str = "Asia/Ulaanbaatar"
    annual_leave_days: Decimal | None = Field(default=None, ge=0, le=366)

    @field_validator("name", "telegram_id", mode="before")
    @classmethod
    def blank_identity(cls, value):
        return _blank_to_none(value)

    @model_validator(mode="after")
    def display_name(self):
        if not self.name:
            self.name = " ".join(part for part in (self.first_name, self.last_name) if part) or None
        if not self.name:
            raise ValueError("Нэр оруулна уу")
        return self


class EmployeePatch(_WorkerFields):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    employment_status: EmploymentStatus | None = None
    is_active: bool | None = None
    restore: bool = False
    timezone: str | None = None


class MonthlyPayrollProfileInput(BaseModel):
    base_salary: Decimal = Field(ge=0)
    effective_from: date
    salary_type: Literal["PRORATION", "FIXED"] = "PRORATION"
    meal_allowance: Decimal = Field(default=Decimal("0"), ge=0)
    commute_allowance: Decimal = Field(default=Decimal("0"), ge=0)
    allowance_basis: Literal["FIXED", "WORKED_DAYS"] = "FIXED"
    allowance_payout: Literal["ADVANCE", "FINAL"] = "FINAL"
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
