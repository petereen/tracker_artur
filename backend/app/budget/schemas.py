from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

Kind = Literal["income", "cogs", "expense", "other"]
Scenario = Literal["base", "optimistic", "conservative", "other"]
PeriodType = Literal["month", "quarter", "year", "custom"]

_CODE_RE = re.compile(r"^[A-Za-z0-9А-Яа-яӨөҮүЁё_.\-]+$")
MAX_BUDGET_DAYS = 366 * 5
MAX_AMOUNT = Decimal("1e15")


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

    @field_validator("code", check_fields=False)
    @classmethod
    def _code_format(cls, value: str | None) -> str | None:
        if value is not None and not _CODE_RE.match(value):
            raise ValueError("Код зөвхөн үсэг, тоо, '.', '-' болон '_' агуулна")
        return value


class GroupInput(_Clean):
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=240)
    kind: Kind = "expense"
    parent_id: int | None = None
    sort: int = Field(default=0, ge=0, le=100000)
    is_active: bool = True


class GroupPatch(_Clean):
    code: str | None = Field(default=None, min_length=1, max_length=40)
    name: str | None = Field(default=None, min_length=1, max_length=240)
    kind: Kind | None = None
    parent_id: int | None = None
    sort: int | None = Field(default=None, ge=0, le=100000)
    is_active: bool | None = None


class AccountInput(_Clean):
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=240)
    kind: Kind = "expense"
    group_id: int | None = None
    note: str | None = Field(default=None, max_length=2000)
    sort: int = Field(default=0, ge=0, le=100000)
    is_active: bool = True
    erp_account_ids: list[int] = Field(default_factory=list, max_length=500)


class AccountPatch(_Clean):
    code: str | None = Field(default=None, min_length=1, max_length=40)
    name: str | None = Field(default=None, min_length=1, max_length=240)
    kind: Kind | None = None
    group_id: int | None = None
    note: str | None = Field(default=None, max_length=2000)
    sort: int | None = Field(default=None, ge=0, le=100000)
    is_active: bool | None = None
    erp_account_ids: list[int] | None = Field(default=None, max_length=500)


class GenerateAccountsInput(BaseModel):
    """Create budget accounts from unlinked income/expense ledger accounts."""

    erp_account_ids: list[int] | None = Field(default=None, max_length=2000)


class _PeriodRule(BaseModel):
    @model_validator(mode="after")
    def _period(self) -> Any:
        start, end = getattr(self, "start_date", None), getattr(self, "end_date", None)
        if start and end:
            if start > end:
                raise ValueError("Эхлэх огноо дуусах огнооноос өмнө байх ёстой")
            if (end - start).days > MAX_BUDGET_DAYS:
                raise ValueError("Төсвийн хугацаа 5 жилээс хэтрэхгүй")
        return self


class BudgetCreate(_Clean, _PeriodRule):
    name: str = Field(min_length=1, max_length=240)
    purpose: str | None = Field(default=None, max_length=2000)
    scenario: Scenario = "base"
    period_type: PeriodType = "month"
    start_date: date
    end_date: date
    project_id: int | None = None


class BudgetPatch(_Clean, _PeriodRule):
    version: int | None = Field(default=None, ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=240)
    purpose: str | None = Field(default=None, max_length=2000)
    scenario: Scenario | None = None
    period_type: PeriodType | None = None
    start_date: date | None = None
    end_date: date | None = None
    project_id: int | None = None


class LineRow(_Clean):
    budget_account_id: int
    project_id: int | None = None
    party_group_id: int | None = None
    note: str | None = Field(default=None, max_length=1000)
    # Column start date (ISO) → signed amount. Missing columns mean zero.
    amounts: dict[date, Decimal] = Field(default_factory=dict)

    @field_validator("amounts")
    @classmethod
    def _amounts(cls, value: dict[date, Decimal]) -> dict[date, Decimal]:
        for amount in value.values():
            if not amount.is_finite() or abs(amount) >= MAX_AMOUNT:
                raise ValueError("Дүн хэт их эсвэл буруу байна")
        return value


class LinesInput(BaseModel):
    version: int = Field(ge=1)
    rows: list[LineRow] = Field(default_factory=list, max_length=2000)


class CopyInput(_Clean):
    name: str = Field(min_length=1, max_length=240)
    purpose: str | None = Field(default=None, max_length=2000)
    scenario: Scenario = "base"
    shift_years: int = Field(default=0, ge=-5, le=5)
    adjust_pct: Decimal = Field(default=Decimal("0"), ge=Decimal("-100"), le=Decimal("1000"))


class VersionInput(BaseModel):
    version: int | None = Field(default=None, ge=1)
