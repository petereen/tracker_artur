from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator, model_validator

DEFAULT_TIMEZONE = "Asia/Ulaanbaatar"


PartyType = Literal["customer", "supplier", "prospect", "contact"]
StatusCategory = Literal["open", "in_progress", "waiting", "done", "cancelled"]
PeriodUnit = Literal["day", "month"]

_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
_CODE_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _blank_to_none(value: Any) -> Any:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


class _Clean(BaseModel):
    """Trims strings and turns blank form inputs into ``None``."""

    @model_validator(mode="before")
    @classmethod
    def _strip_blank(cls, values: Any) -> Any:
        if isinstance(values, dict):
            return {key: _blank_to_none(value) for key, value in values.items()}
        return values


def _check_code(value: str | None) -> str | None:
    if value is not None and not _CODE_RE.match(value):
        raise ValueError("Код зөвхөн латин үсэг, тоо, '.', '-' болон '_' агуулна")
    return value


def _check_email(value: str | None) -> str | None:
    if value is not None and not _EMAIL_RE.match(value):
        raise ValueError("И-мэйл хаяг буруу байна")
    return value


class _CodeRule(BaseModel):
    @field_validator("code", check_fields=False)
    @classmethod
    def _code_format(cls, value: str | None) -> str | None:
        return _check_code(value)


class _EmailRule(BaseModel):
    @field_validator("email", check_fields=False)
    @classmethod
    def _email_format(cls, value: str | None) -> str | None:
        return _check_email(value)


class PartyLink(BaseModel):
    label: str = Field(min_length=1, max_length=160)
    url: str = Field(min_length=1, max_length=1000)


class PartyFields(_Clean, _EmailRule):
    name_en: str | None = Field(default=None, max_length=240)
    business_name: str | None = Field(default=None, max_length=240)
    registry_no: str | None = Field(default=None, max_length=20)
    tax_id: str | None = Field(default=None, max_length=20)
    is_customer: bool | None = None
    is_supplier: bool | None = None
    is_individual: bool | None = None
    is_foreign: bool | None = None
    vat_payer: bool | None = None
    city_tax_payer: bool | None = None
    email: str | None = Field(default=None, max_length=240)
    phone: str | None = Field(default=None, max_length=80)
    website: str | None = Field(default=None, max_length=400)
    legal_address: str | None = Field(default=None, max_length=1000)
    location: str | None = Field(default=None, max_length=240)
    informal_address: str | None = Field(default=None, max_length=1000)
    tags: list[str] | None = None
    group_id: int | None = None
    responsible_employee_id: int | None = None
    parent_party_id: int | None = None
    settle_via_parent: bool | None = None
    customer_since: date | None = None
    inactive_since: date | None = None
    payment_term_id: int | None = None
    price_list_id: int | None = None
    settlement_account_id: int | None = None
    credit_limit: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    sales_discount_pct: Decimal | None = Field(default=None, ge=0, le=100)
    sales_note: str | None = Field(default=None, max_length=2000)
    sales_lead_days: int | None = Field(default=None, ge=0, le=3650)
    purchase_discount_pct: Decimal | None = Field(default=None, ge=0, le=100)
    purchase_note: str | None = Field(default=None, max_length=2000)
    purchase_lead_days: int | None = Field(default=None, ge=0, le=3650)
    delivery_terms: str | None = Field(default=None, max_length=1000)
    links: list[PartyLink] | None = None
    custom: dict[str, Any] | None = None
    is_active: bool | None = None

    @field_validator("registry_no")
    @classmethod
    def registry_upper(cls, value: str | None) -> str | None:
        return value.upper() if value else value

    @field_validator("currency")
    @classmethod
    def currency_upper(cls, value: str | None) -> str | None:
        return value.upper() if value else value


class PartyCreate(PartyFields, _CodeRule):
    name: str = Field(min_length=1, max_length=240)
    code: str | None = Field(default=None, max_length=64)
    party_type: PartyType | None = None
    # Dayansoft allows several branches to share one TIN once the user confirms.
    confirm_duplicate_tin: bool = False


class PartyPatch(PartyFields, _CodeRule):
    name: str | None = Field(default=None, min_length=1, max_length=240)
    code: str | None = Field(default=None, max_length=64)
    party_type: PartyType | None = None
    confirm_duplicate_tin: bool = False
    version: int | None = None


class ContactInput(_Clean, _EmailRule):
    name: str = Field(min_length=1, max_length=240)
    nickname: str | None = Field(default=None, max_length=120)
    position: str | None = Field(default=None, max_length=160)
    phone: str | None = Field(default=None, max_length=80)
    email: str | None = Field(default=None, max_length=240)
    address: str | None = Field(default=None, max_length=1000)
    note: str | None = Field(default=None, max_length=2000)
    is_default: bool = False
    is_active: bool = True


class ContactPatch(_Clean, _EmailRule):
    name: str | None = Field(default=None, min_length=1, max_length=240)
    nickname: str | None = Field(default=None, max_length=120)
    position: str | None = Field(default=None, max_length=160)
    phone: str | None = Field(default=None, max_length=80)
    email: str | None = Field(default=None, max_length=240)
    address: str | None = Field(default=None, max_length=1000)
    note: str | None = Field(default=None, max_length=2000)
    is_default: bool | None = None
    is_active: bool | None = None


class BankAccountInput(_Clean):
    bank_name: str = Field(min_length=1, max_length=160)
    currency: str = Field(default="MNT", min_length=3, max_length=3)
    iban_prefix: str | None = Field(default=None, max_length=40)
    account_no: str = Field(min_length=1, max_length=64)
    account_name: str | None = Field(default=None, max_length=240)
    note: str | None = Field(default=None, max_length=1000)
    is_default: bool = False
    is_active: bool = True


class BankAccountPatch(_Clean):
    bank_name: str | None = Field(default=None, min_length=1, max_length=160)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    iban_prefix: str | None = Field(default=None, max_length=40)
    account_no: str | None = Field(default=None, min_length=1, max_length=64)
    account_name: str | None = Field(default=None, max_length=240)
    note: str | None = Field(default=None, max_length=1000)
    is_default: bool | None = None
    is_active: bool | None = None


class PartyGroupInput(_Clean, _CodeRule):
    code: str | None = Field(default=None, max_length=40)
    name: str = Field(min_length=1, max_length=160)
    parent_id: int | None = None
    is_default: bool = False
    is_foreign: bool = False
    default_settlement_account_id: int | None = None
    default_price_list_id: int | None = None
    is_active: bool = True


class PartyGroupPatch(_Clean, _CodeRule):
    code: str | None = Field(default=None, max_length=40)
    name: str | None = Field(default=None, min_length=1, max_length=160)
    parent_id: int | None = None
    is_default: bool | None = None
    is_foreign: bool | None = None
    default_settlement_account_id: int | None = None
    default_price_list_id: int | None = None
    is_active: bool | None = None


class PaymentTermInput(_Clean, _CodeRule):
    code: str | None = Field(default=None, max_length=20)
    name: str = Field(min_length=1, max_length=160)
    days: int = Field(default=0, ge=0, le=3650)
    period_unit: PeriodUnit = "day"
    period_value: int = Field(default=0, ge=0, le=120)
    is_active: bool = True


class PaymentTermPatch(_Clean, _CodeRule):
    code: str | None = Field(default=None, max_length=20)
    name: str | None = Field(default=None, min_length=1, max_length=160)
    days: int | None = Field(default=None, ge=0, le=3650)
    period_unit: PeriodUnit | None = None
    period_value: int | None = Field(default=None, ge=0, le=120)
    is_active: bool | None = None


class StatusInput(_Clean, _CodeRule):
    code: str | None = Field(default=None, max_length=40)
    name: str = Field(min_length=1, max_length=120)
    sort: int = Field(default=0, ge=0, le=10000)
    color: str = "#64748B"
    category: StatusCategory = "open"
    is_active: bool = True

    @field_validator("color")
    @classmethod
    def color_hex(cls, value: str) -> str:
        if not _COLOR_RE.match(value):
            raise ValueError("Өнгө #RRGGBB хэлбэртэй байна")
        return value.upper()


class StatusPatch(_Clean, _CodeRule):
    code: str | None = Field(default=None, max_length=40)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    sort: int | None = Field(default=None, ge=0, le=10000)
    color: str | None = None
    category: StatusCategory | None = None
    is_active: bool | None = None

    @field_validator("color")
    @classmethod
    def color_hex(cls, value: str | None) -> str | None:
        if value is not None and not _COLOR_RE.match(value):
            raise ValueError("Өнгө #RRGGBB хэлбэртэй байна")
        return value.upper() if value else value


class ActivityTypeInput(_Clean, _CodeRule):
    code: str | None = Field(default=None, max_length=40)
    name: str = Field(min_length=1, max_length=120)
    sort: int = Field(default=0, ge=0, le=10000)
    is_active: bool = True


class ActivityTypePatch(_Clean, _CodeRule):
    code: str | None = Field(default=None, max_length=40)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    sort: int | None = Field(default=None, ge=0, le=10000)
    is_active: bool | None = None


class ActivityFields(_Clean):
    party_id: int | None = None
    contact_id: int | None = None
    contact_name: str | None = Field(default=None, max_length=240)
    contact_phone: str | None = Field(default=None, max_length=80)
    contact_email: str | None = Field(default=None, max_length=240)
    activity_at: datetime | None = None
    body: str | None = Field(default=None, max_length=20000)
    type_id: int | None = None
    # “Өмнө үүсгэсэн төрлөөс сонгох эсвэл шинэ төрлийг бичиж оруулах”.
    type_name: str | None = Field(default=None, max_length=120)
    is_important: bool | None = None
    due_at: datetime | None = None
    duration_minutes: int | None = Field(default=None, ge=0, le=100000)
    responsible_employee_id: int | None = None
    status_id: int | None = None
    completed_at: datetime | None = None
    completion_note: str | None = Field(default=None, max_length=5000)
    reference: str | None = Field(default=None, max_length=240)
    contract_id: int | None = None
    project_id: int | None = None
    is_closed: bool | None = None
    reviewed_by_employee_id: int | None = None
    reviewed_at: datetime | None = None
    expected_revenue: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    is_active: bool | None = None
    custom: dict[str, Any] | None = None

    @field_validator("currency")
    @classmethod
    def currency_upper(cls, value: str | None) -> str | None:
        return value.upper() if value else value

    @field_validator("activity_at", "due_at", "completed_at", "reviewed_at")
    @classmethod
    def local_when_naive(cls, value: datetime | None) -> datetime | None:
        # Form inputs without an offset are wall-clock times in the company zone.
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=ZoneInfo(DEFAULT_TIMEZONE))
        return value


class ActivityCreate(ActivityFields):
    subject: str = Field(min_length=1, max_length=500)


class ActivityPatch(ActivityFields):
    subject: str | None = Field(default=None, min_length=1, max_length=500)
    version: int | None = None


class ActivityBulkCreate(BaseModel):
    """“Нэмэх (метагаас)”: create the same activity for many parties at once."""

    party_ids: list[int] = Field(min_length=1, max_length=200)
    template: ActivityCreate


class ActivityCloseInput(_Clean):
    completion_note: str | None = Field(default=None, max_length=5000)


class ActivityTaskInput(_Clean):
    title: str | None = Field(default=None, max_length=500)
    deadline_at: datetime | None = None
    assignee_employee_id: int | None = None

    @field_validator("deadline_at")
    @classmethod
    def local_when_naive(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=ZoneInfo(DEFAULT_TIMEZONE))
        return value
