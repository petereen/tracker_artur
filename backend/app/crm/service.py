"""CRM domain rules and persistence helpers.

Pure functions (overdue maths, completion rules, party typing, diffs) are kept
free of I/O so they can be unit-tested without a database.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enterprise_deps import ActorContext
from app.erp.service import ERP_MODULES, MODULE_SETTINGS_KEY, require_capability
from app.models.crm import (
    FINISHED_STATUS_CATEGORIES,
    CRMActivity,
    CRMActivityType,
    ERPPartyGroup,
    ERPPaymentTerm,
    ERPStatus,
)
from app.models.models import (
    ERPDocument,
    ERPModuleConfig,
    ERPParty,
    ERPPriceList,
    ERPSequence,
    Organization,
)

ACTIVITY_REGISTER = "crm_activity"
STATUS_REGISTERS = frozenset({ACTIVITY_REGISTER})
PARTY_RESOURCE = "parties"
ACTIVITY_RESOURCE = "crm_activity"
SETTINGS_RESOURCE = "crm_settings"
PARTY_CODE_SEQUENCE = "crm_party_code"
PARTY_CODE_START = 10001
ACTIVITY_SEQUENCE = "crm_activity"
DEFAULT_TIMEZONE = "Asia/Ulaanbaatar"

# Seeded per organization the first time CRM is used. Everything is editable.
DEFAULT_ACTIVITY_STATUSES = (
    ("NEW", "Шинэ", 10, "#2D62EC", "open"),
    ("IN_PROGRESS", "Хийгдэж байгаа", 20, "#F59E0B", "in_progress"),
    ("WAITING", "Хүлээгдэж байгаа", 30, "#8B5CF6", "waiting"),
    ("DONE", "Дууссан", 40, "#16A34A", "done"),
)
DEFAULT_ACTIVITY_TYPES = (
    ("MEETING", "Уулзалт", 10), ("EVENT", "Event", 20), ("TRAINING", "Сургалт", 30),
    ("CALL", "Утас", 40), ("EMAIL", "Мэйл", 50), ("TASK", "Task", 60), ("SALES", "Борлуулалт", 70),
)
DEFAULT_PAYMENT_TERMS = (
    ("01", "Бэлэн", 0, "day", 0), ("02", "Зээл", 30, "day", 0),
    ("03", "Лимиттэй", 30, "day", 0), ("04", "Сардаа тэглэх", 0, "month", 1),
)
DEFAULT_PARTY_GROUP = ("CUSTOMERS", "Харилцагчид")

# Changes to these fields are surfaced in the customer change log (Лог).
PARTY_TRACKED_FIELDS = (
    "code", "name", "registry_no", "tax_id", "group_id", "price_list_id", "sales_discount_pct",
    "customer_since", "inactive_since", "status", "responsible_employee_id", "parent_party_id",
    "vat_payer", "city_tax_payer", "is_customer", "is_supplier", "payment_term_id", "credit_limit",
)


# ─── Pure rules ────────────────────────────────────────────────────────────────

def overdue_days(due_at: datetime | date | None, completed_at: datetime | date | None, today: date) -> int:
    """Хэтэрсэн хоног: completion (or today, while open) minus the deadline."""
    if due_at is None:
        return 0
    due = due_at.date() if isinstance(due_at, datetime) else due_at
    end = completed_at.date() if isinstance(completed_at, datetime) else (completed_at or today)
    return max(0, (end - due).days)


def activity_is_open(*, is_closed: bool, completed_at: datetime | None, status_category: str | None) -> bool:
    return not is_closed and completed_at is None and status_category not in FINISHED_STATUS_CATEGORIES


def activity_is_overdue(*, is_closed: bool, completed_at: datetime | None, status_category: str | None, due_at: datetime | None, now: datetime) -> bool:
    return bool(due_at and due_at < now and activity_is_open(is_closed=is_closed, completed_at=completed_at, status_category=status_category))


def completion_updates(*, is_closed: bool, was_closed: bool, completed_at: datetime | None, status_category: str | None, now: datetime) -> dict[str, Any]:
    """Derive bookkeeping timestamps from what the user changed.

    Statuses stay manual (Dayansoft has no automatic transitions); we only
    fill the completion date when the user marks the work finished and did
    not type one, and stamp ``closed_at`` when “Хаагдсан” is ticked.
    """
    updates: dict[str, Any] = {}
    finished = is_closed or status_category in FINISHED_STATUS_CATEGORIES
    if finished and completed_at is None:
        updates["completed_at"] = now
    if is_closed and not was_closed:
        updates["closed_at"] = now
    if not is_closed and was_closed:
        updates["closed_at"] = None
    return updates


def derive_party_type(*, is_customer: bool, is_supplier: bool, requested: str | None = None) -> str:
    if requested in {"prospect", "contact"}:
        return requested
    if is_supplier and not is_customer:
        return "supplier"
    if is_customer:
        return "customer"
    return requested or "prospect"


def party_flags_for_type(party_type: str) -> dict[str, bool]:
    """Legacy ``party_type`` → Dayansoft buyer/supplier flags."""
    return {"is_customer": party_type != "supplier", "is_supplier": party_type == "supplier"}


def normalize_tags(tags: Iterable[str] | None) -> list[str]:
    seen: dict[str, str] = {}
    for tag in tags or []:
        clean = " ".join(str(tag).split())[:60]
        if clean and clean.casefold() not in seen:
            seen[clean.casefold()] = clean
    return list(seen.values())[:30]


def _comparable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value.normalize())
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def field_changes(before: dict[str, Any], after: dict[str, Any], fields: Iterable[str]) -> dict[str, dict[str, Any]]:
    changes: dict[str, dict[str, Any]] = {}
    for field in fields:
        old, new = _comparable(before.get(field)), _comparable(after.get(field))
        if old != new:
            changes[field] = {"from": old, "to": new}
    return changes


def local_today(timezone_name: str | None) -> date:
    try:
        zone = ZoneInfo(timezone_name or DEFAULT_TIMEZONE)
    except Exception:
        zone = ZoneInfo(DEFAULT_TIMEZONE)
    return datetime.now(zone).date()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ─── Permissions ───────────────────────────────────────────────────────────────

async def has_capability(db: AsyncSession, actor: ActorContext, resource: str, action: str) -> bool:
    try:
        await require_capability(db, actor, resource, action)
    except HTTPException as exc:
        if exc.status_code == 403:
            return False
        raise
    return True


async def capability_matrix(db: AsyncSession, actor: ActorContext) -> dict[str, dict[str, bool]]:
    matrix: dict[str, dict[str, bool]] = {}
    for resource in (PARTY_RESOURCE, ACTIVITY_RESOURCE, SETTINGS_RESOURCE):
        matrix[resource] = {action: await has_capability(db, actor, resource, action) for action in ("view", "create", "edit", "archive")}
    return matrix


async def crm_module_enabled(db: AsyncSession, organization_id: int) -> bool:
    rows = (await db.execute(select(ERPModuleConfig).where(ERPModuleConfig.organization_id == organization_id))).scalars().all()
    if rows:
        return any(row.module == "crm" and row.enabled for row in rows)
    organization = await db.get(Organization, organization_id)
    configured = ((organization.settings or {}) if organization else {}).get(MODULE_SETTINGS_KEY) or {}
    return bool(configured.get("crm", False)) and "crm" in ERP_MODULES


# ─── Seeding & numbering ───────────────────────────────────────────────────────

async def ensure_crm_defaults(db: AsyncSession, organization_id: int) -> None:
    """Idempotently seed editable CRM reference data for an organization."""
    has_status = await db.scalar(select(ERPStatus.id).where(ERPStatus.organization_id == organization_id, ERPStatus.register == ACTIVITY_REGISTER).limit(1))
    if not has_status:
        db.add_all([ERPStatus(organization_id=organization_id, register=ACTIVITY_REGISTER, code=code, name=name, sort=sort, color=color, category=category)
                    for code, name, sort, color, category in DEFAULT_ACTIVITY_STATUSES])
    has_type = await db.scalar(select(CRMActivityType.id).where(CRMActivityType.organization_id == organization_id).limit(1))
    if not has_type:
        db.add_all([CRMActivityType(organization_id=organization_id, code=code, name=name, sort=sort) for code, name, sort in DEFAULT_ACTIVITY_TYPES])
    has_term = await db.scalar(select(ERPPaymentTerm.id).where(ERPPaymentTerm.organization_id == organization_id).limit(1))
    if not has_term:
        db.add_all([ERPPaymentTerm(organization_id=organization_id, code=code, name=name, days=days, period_unit=unit, period_value=value)
                    for code, name, days, unit, value in DEFAULT_PAYMENT_TERMS])
    has_group = await db.scalar(select(ERPPartyGroup.id).where(ERPPartyGroup.organization_id == organization_id).limit(1))
    if not has_group:
        code, name = DEFAULT_PARTY_GROUP
        db.add(ERPPartyGroup(organization_id=organization_id, code=code, name=name, is_default=True))
    await db.flush()


async def next_party_code(db: AsyncSession, organization_id: int) -> str:
    """Харилцагчийн код: 10001-ээс эхлэн 5 оронтой, skipping manually used codes."""
    sequence = await db.scalar(select(ERPSequence).where(ERPSequence.organization_id == organization_id, ERPSequence.key == PARTY_CODE_SEQUENCE).with_for_update())
    if sequence is None:
        sequence = ERPSequence(organization_id=organization_id, key=PARTY_CODE_SEQUENCE, prefix="", next_number=PARTY_CODE_START, padding=5)
        db.add(sequence)
        await db.flush()
    while True:
        code = f"{sequence.prefix}{sequence.next_number:0{sequence.padding}d}"
        sequence.next_number += 1
        taken = await db.scalar(select(ERPParty.id).where(ERPParty.organization_id == organization_id, ERPParty.code == code))
        if not taken:
            return code


async def next_activity_number(db: AsyncSession, organization_id: int) -> str:
    sequence = await db.scalar(select(ERPSequence).where(ERPSequence.organization_id == organization_id, ERPSequence.key == ACTIVITY_SEQUENCE).with_for_update())
    if sequence is None:
        sequence = ERPSequence(organization_id=organization_id, key=ACTIVITY_SEQUENCE, prefix="CRM-", next_number=1, padding=6)
        db.add(sequence)
        await db.flush()
    number = f"{sequence.prefix}{sequence.next_number:0{sequence.padding}d}"
    sequence.next_number += 1
    return number


async def next_simple_code(db: AsyncSession, model: Any, organization_id: int, prefix: str, *, extra_filter: Any = None) -> str:
    statement = select(func.count(model.id)).where(model.organization_id == organization_id)
    if extra_filter is not None:
        statement = statement.where(extra_filter)
    index = int(await db.scalar(statement) or 0) + 1
    while True:
        code = f"{prefix}{index:03d}"
        check = select(model.id).where(model.organization_id == organization_id, model.code == code)
        if extra_filter is not None:
            check = check.where(extra_filter)
        if not await db.scalar(check):
            return code
        index += 1


# ─── Party rules ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class DuplicateMatch:
    party_id: int
    code: str
    name: str
    reason: str  # "tax_id" | "registry_no" | "name"


async def find_duplicates(db: AsyncSession, organization_id: int, *, tax_id: str | None, registry_no: str | None, name: str | None, exclude_id: int | None = None) -> list[DuplicateMatch]:
    conditions = []
    if tax_id:
        conditions.append(ERPParty.tax_id == tax_id)
    if registry_no:
        conditions.append(ERPParty.registry_no == registry_no)
    if name:
        conditions.append(func.lower(ERPParty.name) == name.strip().lower())
    if not conditions:
        return []
    statement = select(ERPParty).where(ERPParty.organization_id == organization_id, or_(*conditions))
    if exclude_id is not None:
        statement = statement.where(ERPParty.id != exclude_id)
    matches: list[DuplicateMatch] = []
    for row in (await db.execute(statement.limit(20))).scalars().all():
        if tax_id and row.tax_id == tax_id:
            reason = "tax_id"
        elif registry_no and row.registry_no == registry_no:
            reason = "registry_no"
        else:
            reason = "name"
        matches.append(DuplicateMatch(party_id=row.id, code=row.code, name=row.name, reason=reason))
    return matches


async def party_references(db: AsyncSession, party: ERPParty) -> dict[str, int]:
    """Records that make a party undeletable (Dayansoft: deactivate instead)."""
    counts = {
        "documents": await db.scalar(select(func.count(ERPDocument.id)).where(ERPDocument.party_id == party.id)),
        "activities": await db.scalar(select(func.count(CRMActivity.id)).where(CRMActivity.party_id == party.id)),
        "child_parties": await db.scalar(select(func.count(ERPParty.id)).where(ERPParty.parent_party_id == party.id)),
        "price_lists": await db.scalar(select(func.count(ERPPriceList.id)).where(ERPPriceList.party_id == party.id)),
    }
    return {key: int(value or 0) for key, value in counts.items() if value}


async def descendant_party_ids(db: AsyncSession, organization_id: int, party_id: int) -> set[int]:
    """The party and every party below it in the head-customer tree."""
    found = {party_id}
    frontier = {party_id}
    while frontier:
        children = set((await db.execute(select(ERPParty.id).where(
            ERPParty.organization_id == organization_id, ERPParty.parent_party_id.in_(frontier),
        ))).scalars().all()) - found
        found |= children
        frontier = children
    return found


async def assert_parent_is_not_descendant(db: AsyncSession, organization_id: int, party_id: int, parent_id: int | None) -> None:
    if parent_id is None:
        return
    if parent_id in await descendant_party_ids(db, organization_id, party_id):
        raise HTTPException(status_code=422, detail={"code": "crm_party_parent_cycle", "message": "Толгой харилцагч нь өөрийн салбар байж болохгүй"})


async def assert_group_is_not_descendant(db: AsyncSession, organization_id: int, group_id: int, parent_id: int | None) -> None:
    current = parent_id
    seen: set[int] = set()
    while current is not None and current not in seen:
        if current == group_id:
            raise HTTPException(status_code=422, detail={"code": "crm_group_parent_cycle", "message": "Бүлэг өөрийн дэд бүлэгт харьяалагдаж болохгүй"})
        seen.add(current)
        current = await db.scalar(select(ERPPartyGroup.parent_id).where(ERPPartyGroup.id == current, ERPPartyGroup.organization_id == organization_id))


