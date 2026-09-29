"""Budget domain rules (Dayansoft d161) and persistence helpers.

The sign convention drives everything: income is planned positive, cost of
sales and expenses negative, so profit = income + costs. Actuals use the same
convention (credit − debit), which makes ``variance = actual − expected`` read
the same way for every account kind: positive is favourable, negative is not.

Pure functions (periods, pro-rating, sign and variance rules) are free of I/O
so they can be unit-tested without a database.
"""

from __future__ import annotations

import calendar
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enterprise_deps import ActorContext
from app.erp.service import ERP_MODULES, MODULE_SETTINGS_KEY, require_capability
from app.models.budget import BudgetAccountGroup
from app.models.models import ERPModuleConfig, ERPSequence, Organization

BUDGET_RESOURCE = "budget"
SETTINGS_RESOURCE = "budget_settings"
BUDGET_ACTIONS = ("view", "create", "edit", "approve", "archive", "export")
SETTINGS_ACTIONS = ("view", "create", "edit", "archive")
BUDGET_SEQUENCE = "budget"
DEFAULT_TIMEZONE = "Asia/Ulaanbaatar"
MONEY = Decimal("0.01")
ZERO = Decimal("0")
# Within ±5% of the expected amount a line counts as “according to plan”.
ON_TRACK_TOLERANCE = Decimal("0.05")

# d161: “Орлого, ББӨ, Зардал гэж ялган үүсгэх” — seeded once, fully editable.
DEFAULT_GROUPS = (
    ("INCOME", "Орлого", "income", 10),
    ("COGS", "Борлуулсан бүтээгдэхүүний өртөг (ББӨ)", "cogs", 20),
    ("EXPENSE", "Үйл ажиллагааны зардал", "expense", 30),
)
KIND_LABELS = {"income": "Орлого", "cogs": "ББӨ", "expense": "Зардал", "other": "Бусад"}
# Chart-of-accounts classification → budget kind when generating accounts.
CLASSIFICATION_KINDS = {"income": "income", "expense": "expense"}


class BudgetError(HTTPException):
    def __init__(self, status_code: int, code: str, message: str, **extra: Any) -> None:
        super().__init__(status_code=status_code, detail={"code": code, "message": message, **extra})


# ─── Periods ───────────────────────────────────────────────────────────────────

def _month_end(value: date) -> date:
    return value.replace(day=calendar.monthrange(value.year, value.month)[1])


def _add_months(value: date, months: int) -> date:
    index = value.month - 1 + months
    year, month = value.year + index // 12, index % 12 + 1
    return date(year, month, min(value.day, calendar.monthrange(year, month)[1]))


def _bucket_start(value: date, period_type: str) -> date:
    if period_type == "month":
        return value.replace(day=1)
    if period_type == "quarter":
        return date(value.year, 3 * ((value.month - 1) // 3) + 1, 1)
    if period_type == "year":
        return date(value.year, 1, 1)
    raise ValueError(period_type)


def _bucket_end(start: date, period_type: str) -> date:
    months = {"month": 1, "quarter": 3, "year": 12}[period_type]
    return _month_end(_add_months(start, months - 1))


def period_columns(period_type: str, start: date, end: date) -> list[tuple[date, date]]:
    """Planning columns for a budget, clipped to its own start/end dates."""
    if start > end:
        return []
    if period_type == "custom":
        return [(start, end)]
    columns: list[tuple[date, date]] = []
    bucket = _bucket_start(start, period_type)
    while bucket <= end:
        bucket_end = _bucket_end(bucket, period_type)
        columns.append((max(bucket, start), min(bucket_end, end)))
        bucket = date.fromordinal(bucket_end.toordinal() + 1)
    return columns


def column_label(period_type: str, start: date, end: date) -> str:
    if period_type == "month":
        return f"{start.year}.{start.month:02d}"
    if period_type == "quarter":
        return f"{start.year} Q{(start.month - 1) // 3 + 1}"
    if period_type == "year":
        return str(start.year)
    return f"{start.isoformat()} – {end.isoformat()}"


def bucket_key(value: date, granularity: str) -> tuple[date, date]:
    """Calendar month/quarter/year containing ``value`` (for pivot columns)."""
    start = _bucket_start(value, granularity)
    return start, _bucket_end(start, granularity)


def overlap_days(start: date, end: date, window_start: date, window_end: date) -> int:
    first, last = max(start, window_start), min(end, window_end)
    return max(0, (last - first).days + 1)


def prorate(amount: Decimal, start: date, end: date, window_start: date, window_end: date) -> Decimal:
    """Share of ``amount`` (spread evenly per day over start..end) inside the window."""
    total = (end - start).days + 1
    if total <= 0:
        return ZERO
    days = overlap_days(start, end, window_start, window_end)
    if days == 0:
        return ZERO
    if days == total:
        return Decimal(amount)
    return Decimal(amount) * Decimal(days) / Decimal(total)


def split_by_bucket(amount: Decimal, start: date, end: date, window_start: date, window_end: date, granularity: str) -> list[tuple[tuple[date, date], Decimal]]:
    """Pro-rate one entry into calendar buckets that intersect the window."""
    first, last = max(start, window_start), min(end, window_end)
    if first > last:
        return []
    parts: list[tuple[tuple[date, date], Decimal]] = []
    cursor = first
    while cursor <= last:
        bucket = bucket_key(cursor, granularity)
        piece_end = min(bucket[1], last)
        parts.append((bucket, prorate(amount, start, end, cursor, piece_end)))
        cursor = date.fromordinal(piece_end.toordinal() + 1)
    return parts


# ─── Sign & variance rules ─────────────────────────────────────────────────────

def expected_sign(kind: str) -> int:
    """+1 income, -1 cost of sales / expense, 0 = any sign (other)."""
    return {"income": 1, "cogs": -1, "expense": -1}.get(kind, 0)


def sign_ok(kind: str, amount: Decimal) -> bool:
    sign = expected_sign(kind)
    return sign == 0 or amount == 0 or (amount > 0) == (sign > 0)


def money(value: Decimal | int | float | str) -> Decimal:
    return Decimal(str(value)).quantize(MONEY, rounding=ROUND_HALF_UP)


def performance_pct(actual: Decimal, expected: Decimal) -> Decimal | None:
    """Гүйцэтгэл % = бодит / байх ёстой. Undefined without a plan."""
    if expected == 0:
        return None
    return (Decimal(actual) / Decimal(expected) * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def variance_status(expected: Decimal, actual: Decimal, tolerance: Decimal = ON_TRACK_TOLERANCE) -> str:
    """favorable / on_track / unfavorable (d161 🟢🟡🔴), independent of kind.

    With income positive and costs negative, ``actual − expected`` is positive
    both when income beats plan and when spending stays below plan.
    """
    if expected == 0:
        return "no_activity" if actual == 0 else "unplanned"
    variance = Decimal(actual) - Decimal(expected)
    band = abs(Decimal(expected)) * tolerance
    if variance > band:
        return "favorable"
    if variance < -band:
        return "unfavorable"
    return "on_track"


def measures(budgeted: Decimal, expected: Decimal, actual: Decimal) -> dict[str, Any]:
    budgeted, expected, actual = money(budgeted), money(expected), money(actual)
    pct = performance_pct(actual, expected)
    return {
        "budgeted": str(budgeted), "expected": str(expected), "actual": str(actual),
        "variance": str(actual - expected), "remaining": str(budgeted - actual),
        "performance_pct": None if pct is None else str(pct), "status": variance_status(expected, actual),
    }


def adjusted_amount(amount: Decimal, adjust_pct: Decimal) -> Decimal:
    """Scenario copy: scale the magnitude, keep the sign convention."""
    return money(Decimal(amount) * (Decimal(100) + Decimal(adjust_pct)) / Decimal(100))


def shift_years(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year + years)
    except ValueError:  # 29 Feb → 28 Feb
        return value.replace(year=value.year + years, day=28)


def local_today(timezone_name: str | None) -> date:
    try:
        zone = ZoneInfo(timezone_name or DEFAULT_TIMEZONE)
    except Exception:
        zone = ZoneInfo(DEFAULT_TIMEZONE)
    return datetime.now(zone).date()


def assert_unique_rows(rows: Iterable[tuple[int, int | None, int | None]]) -> None:
    seen: set[tuple[int, int | None, int | None]] = set()
    for key in rows:
        if key in seen:
            raise BudgetError(422, "budget_duplicate_row", "Ижил данс, төсөл, харилцагчийн бүлэгтэй мөр давхардсан байна")
        seen.add(key)


# ─── Permissions ───────────────────────────────────────────────────────────────

async def has_capability(db: AsyncSession, actor: ActorContext, resource: str, action: str) -> bool:
    try:
        await require_capability(db, actor, resource, action)
    except HTTPException as exc:
        if exc.status_code == 403:
            return False
        raise
    return True


async def require(db: AsyncSession, actor: ActorContext, resource: str, action: str) -> None:
    if not await has_capability(db, actor, resource, action):
        raise BudgetError(403, "budget_forbidden", "Энэ үйлдлийг хийх эрх танд олгогдоогүй байна", resource=resource, action=action)


async def capability_matrix(db: AsyncSession, actor: ActorContext) -> dict[str, dict[str, bool]]:
    return {
        "budgets": {action: await has_capability(db, actor, BUDGET_RESOURCE, action) for action in BUDGET_ACTIONS},
        "settings": {action: await has_capability(db, actor, SETTINGS_RESOURCE, action) for action in SETTINGS_ACTIONS},
    }


async def budget_module_enabled(db: AsyncSession, organization_id: int) -> bool:
    rows = (await db.execute(select(ERPModuleConfig).where(ERPModuleConfig.organization_id == organization_id))).scalars().all()
    if rows:
        return any(row.module == "budget" and row.enabled for row in rows)
    organization = await db.get(Organization, organization_id)
    configured = ((organization.settings or {}) if organization else {}).get(MODULE_SETTINGS_KEY) or {}
    return bool(configured.get("budget", False)) and "budget" in ERP_MODULES


# ─── Seeding & numbering ───────────────────────────────────────────────────────

async def ensure_budget_defaults(db: AsyncSession, organization_id: int) -> None:
    """Idempotently seed the income / cost of sales / expense groups."""
    has_group = await db.scalar(select(BudgetAccountGroup.id).where(BudgetAccountGroup.organization_id == organization_id).limit(1))
    if not has_group:
        db.add_all([BudgetAccountGroup(organization_id=organization_id, code=code, name=name, kind=kind, sort=sort) for code, name, kind, sort in DEFAULT_GROUPS])
        await db.flush()


async def next_budget_number(db: AsyncSession, organization_id: int) -> str:
    sequence = await db.scalar(select(ERPSequence).where(ERPSequence.organization_id == organization_id, ERPSequence.key == BUDGET_SEQUENCE).with_for_update())
    if sequence is None:
        sequence = ERPSequence(organization_id=organization_id, key=BUDGET_SEQUENCE, prefix="BUD-", next_number=1, padding=4)
        db.add(sequence)
        await db.flush()
    number = f"{sequence.prefix}{sequence.next_number:0{sequence.padding}d}"
    sequence.next_number += 1
    return number
