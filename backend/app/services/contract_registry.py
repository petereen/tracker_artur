"""Contract registry metadata (Dayansoft ERP d028 «Гэрээ бүртгэх»).

The contract lifecycle (draft → review → approval → signed archive) lives in
``app.routers.contracts``; this module owns the registry fields every contract
carries next to its body: internal code (auto-continued from the last one),
official number, group, CRM counterparty, contract date, amounts, penalty %,
payment term, links and free-form meta fields.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from typing import Any, Iterable, Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contracts import ContractArchiveEntry, ContractDocument, ContractFile, ContractGroup
from app.models.crm import ERPPaymentTerm
from app.models.models import ERPParty, ERPUnitOfMeasure


DEFAULT_CODE_PREFIX = "CT-"
DEFAULT_CODE_WIDTH = 4
CODE_LOCK_NAMESPACE = 7028  # pg_advisory_xact_lock(namespace, organization_id)
REFERENCE_FIELDS = ("group_id", "party_id", "unit_id", "payment_term_id")
REGISTRY_FIELDS = (
    "code", "contract_number", "group_id", "party_id", "signed_on", "quantity", "unit_id", "unit_price",
    "amount", "currency", "penalty_pct", "payment_term_id", "note", "links", "custom_fields",
)
_TRAILING_NUMBER = re.compile(r"^(.*?)(\d+)(\D*)$")


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


class ContractLink(BaseModel):
    """Линк — online link, shared-drive link or a file path to the scanned copy."""

    kind: Literal["online", "shared", "path"] = "online"
    label: str = Field(default="", max_length=160)
    url: str = Field(min_length=1, max_length=1000)

    @field_validator("label", "url")
    @classmethod
    def strip(cls, value: str) -> str:
        return value.strip()

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str, info) -> str:
        if not value:
            raise ValueError("Link is required")
        kind = info.data.get("kind", "online")
        if kind != "path" and not re.match(r"^https?://", value, re.IGNORECASE):
            raise ValueError("Online and shared links must start with http:// or https://")
        return value


class ContractCustomField(BaseModel):
    """Мета — organization-specific extra information."""

    label: str = Field(min_length=1, max_length=120)
    value: str = Field(default="", max_length=2000)

    @field_validator("label", "value")
    @classmethod
    def strip(cls, value: str) -> str:
        return value.strip()


class ContractRegistryInput(BaseModel):
    code: str | None = Field(default=None, max_length=64)
    contract_number: str | None = Field(default=None, max_length=120)
    group_id: int | None = None
    party_id: int | None = None
    signed_on: date | None = None
    quantity: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    unit_id: int | None = None
    unit_price: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    amount: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    penalty_pct: Decimal | None = Field(default=None, ge=0, le=100, max_digits=7, decimal_places=4)
    payment_term_id: int | None = None
    note: str | None = Field(default=None, max_length=5000)
    links: list[ContractLink] | None = Field(default=None, max_length=20)
    custom_fields: list[ContractCustomField] | None = Field(default=None, max_length=30)

    @field_validator("code", "contract_number", "note")
    @classmethod
    def clean_text(cls, value: str | None) -> str | None:
        return _clean_text(value)

    @field_validator("currency")
    @classmethod
    def clean_currency(cls, value: str | None) -> str | None:
        value = _clean_text(value)
        if value is None:
            return None
        if not value.isalpha():
            raise ValueError("Currency must be a 3-letter code")
        return value.upper()


class ContractRegistryPatch(ContractRegistryInput):
    """Registry data editable in every status, so contracts registered before the registry (or archived ones) can be completed.

    Only the keys present in the request are applied; ``code`` is re-validated when it changes.
    """

    is_active: bool | None = None


class ContractGroupInput(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=240)
    parent_id: int | None = None

    @field_validator("code", "name")
    @classmethod
    def strip(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Value is required")
        return value


class ContractGroupPatch(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=40)
    name: str | None = Field(default=None, min_length=1, max_length=240)
    parent_id: int | None = None
    is_active: bool | None = None

    @field_validator("code", "name")
    @classmethod
    def strip(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Value is required")
        return value


def registry_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def increment_code(previous: str | None) -> str:
    """Continue the numbering of ``previous`` (``ГЭ-2026/015`` → ``ГЭ-2026/016``)."""
    match = _TRAILING_NUMBER.match(previous or "")
    if not match:
        return f"{DEFAULT_CODE_PREFIX}{1:0{DEFAULT_CODE_WIDTH}d}"
    prefix, digits, suffix = match.groups()
    return f"{prefix}{int(digits) + 1:0{len(digits)}d}{suffix}"


async def _lock_codes(db: AsyncSession, organization_id: int) -> None:
    try:
        dialect = db.get_bind().dialect.name
    except Exception:  # pragma: no cover - unbound sessions in unit tests
        dialect = ""
    if dialect == "postgresql":
        await db.execute(select(func.pg_advisory_xact_lock(CODE_LOCK_NAMESPACE, organization_id)))


async def _code_taken(db: AsyncSession, organization_id: int, code: str, exclude_id: int | None = None, *, exclude_archive_id: int | None = None) -> bool:
    """Codes are unique across contract documents and manually archived contracts."""
    query = select(ContractDocument.id).where(ContractDocument.organization_id == organization_id, ContractDocument.code == code)
    if exclude_id is not None:
        query = query.where(ContractDocument.id != exclude_id)
    if await db.scalar(query.limit(1)):
        return True
    archived = select(ContractArchiveEntry.id).where(ContractArchiveEntry.organization_id == organization_id, ContractArchiveEntry.code == code, ContractArchiveEntry.deleted_at.is_(None))
    if exclude_archive_id is not None:
        archived = archived.where(ContractArchiveEntry.id != exclude_archive_id)
    return bool(await db.scalar(archived.limit(1)))


async def suggest_next_code(db: AsyncSession, organization_id: int) -> str:
    """Next free code, continuing from the most recently registered contract code."""
    previous = await db.scalar(
        select(ContractDocument.code)
        .where(ContractDocument.organization_id == organization_id, ContractDocument.code.is_not(None))
        .order_by(ContractDocument.created_at.desc(), ContractDocument.id.desc())
        .limit(1)
    )
    candidate = increment_code(previous)
    for _ in range(1000):
        if not await _code_taken(db, organization_id, candidate):
            return candidate
        candidate = increment_code(candidate)
    raise registry_error(409, "contract_code_exhausted", "Гэрээний дараагийн код олдсонгүй, кодыг гараар оруулна уу")


async def assign_code(db: AsyncSession, organization_id: int, requested: str | None, *, exclude_id: int | None = None, exclude_archive_id: int | None = None) -> str:
    """Validate a manual code or allocate the next one. Serialized per organization."""
    await _lock_codes(db, organization_id)
    if requested:
        if await _code_taken(db, organization_id, requested, exclude_id, exclude_archive_id=exclude_archive_id):
            raise registry_error(409, "contract_code_taken", f"“{requested}” код өөр гэрээнд олгогдсон байна")
        return requested
    return await suggest_next_code(db, organization_id)


async def assert_references(db: AsyncSession, organization_id: int, values: dict[str, Any], *, current: ContractDocument | ContractArchiveEntry | None = None) -> None:
    """Every referenced group / party / unit / payment term must belong to the organization.

    Inactive groups can stay on contracts that already use them but cannot be newly selected.
    """
    checks = (
        ("group_id", ContractGroup, "Гэрээний бүлэг олдсонгүй"),
        ("party_id", ERPParty, "Харилцагч олдсонгүй"),
        ("unit_id", ERPUnitOfMeasure, "Хэмжих нэгж олдсонгүй"),
        ("payment_term_id", ERPPaymentTerm, "Төлбөрийн нөхцөл олдсонгүй"),
    )
    for field, model, message in checks:
        value = values.get(field)
        if not value:
            continue
        row = await db.get(model, value)
        if row is None or row.organization_id != organization_id:
            raise registry_error(422, f"contract_{field.removesuffix('_id')}_not_found", message)
        unchanged = current is not None and getattr(current, field) == value
        if field == "group_id" and not row.is_active and not unchanged:
            raise registry_error(422, "contract_group_inactive", "Идэвхгүй бүлэгт гэрээ бүртгэх боломжгүй")


def links_payload(value: Iterable[ContractLink | dict] | None) -> list[dict[str, str]]:
    output = []
    for item in value or []:
        link = item if isinstance(item, ContractLink) else ContractLink.model_validate(item)
        output.append({"kind": link.kind, "label": link.label, "url": link.url})
    return output


def custom_fields_payload(value: Iterable[ContractCustomField | dict] | None) -> list[dict[str, str]]:
    output = []
    for item in value or []:
        field = item if isinstance(item, ContractCustomField) else ContractCustomField.model_validate(item)
        output.append({"label": field.label, "value": field.value})
    return output


def apply_registry(contract: ContractDocument | ContractArchiveEntry, values: dict[str, Any]) -> None:
    """Copy validated registry values onto ``contract`` (only keys present in ``values``)."""
    for field in REGISTRY_FIELDS:
        if field not in values or field == "code":
            continue
        value = values[field]
        if field == "links":
            value = links_payload(value)
        elif field == "custom_fields":
            value = custom_fields_payload(value)
        elif field == "currency":
            value = value or "MNT"
        setattr(contract, field, value)


def registry_snapshot(contract: ContractDocument | ContractArchiveEntry) -> dict[str, Any]:
    """Audit-friendly JSON view of the registry fields."""
    output: dict[str, Any] = {}
    for field in (*REGISTRY_FIELDS, "is_active"):
        value = getattr(contract, field, None)
        if isinstance(value, Decimal):
            value = str(value)
        elif isinstance(value, date):
            value = value.isoformat()
        output[field] = value
    return output


def _number(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def overdue_days(contract: ContractDocument | ContractArchiveEntry, today: date) -> int:
    """Хэтэрсэн хоног — days past the end date for active, not-rejected contracts (archive files have no term)."""
    end_on = getattr(contract, "effective_end_on", None)
    if not end_on or not contract.is_active or getattr(contract, "status", None) == "REJECTED":
        return 0
    return max((today - end_on).days, 0)


async def load_registry_context(db: AsyncSession, contracts: list[ContractDocument] | list[ContractArchiveEntry]) -> dict[str, Any]:
    """Batch-resolve names for the referenced registry rows plus file counts."""
    def ids(field: str) -> set[int]:
        return {getattr(row, field) for row in contracts if getattr(row, field)}

    ctx: dict[str, Any] = {"groups": {}, "parties": {}, "units": {}, "payment_terms": {}, "file_counts": {}}
    if group_ids := ids("group_id"):
        rows = (await db.execute(select(ContractGroup.id, ContractGroup.code, ContractGroup.name).where(ContractGroup.id.in_(group_ids)))).all()
        ctx["groups"] = {row.id: {"id": row.id, "code": row.code, "name": row.name} for row in rows}
    if party_ids := ids("party_id"):
        rows = (await db.execute(select(ERPParty.id, ERPParty.code, ERPParty.name, ERPParty.parent_party_id).where(ERPParty.id.in_(party_ids)))).all()
        parents = {row.parent_party_id for row in rows if row.parent_party_id}
        parent_rows = (await db.execute(select(ERPParty.id, ERPParty.code, ERPParty.name).where(ERPParty.id.in_(parents)))).all() if parents else []
        parent_map = {row.id: {"id": row.id, "code": row.code, "name": row.name} for row in parent_rows}
        ctx["parties"] = {
            row.id: {"id": row.id, "code": row.code, "name": row.name, "parent": parent_map.get(row.parent_party_id)}
            for row in rows
        }
    if unit_ids := ids("unit_id"):
        rows = (await db.execute(select(ERPUnitOfMeasure.id, ERPUnitOfMeasure.code, ERPUnitOfMeasure.name, ERPUnitOfMeasure.symbol).where(ERPUnitOfMeasure.id.in_(unit_ids)))).all()
        ctx["units"] = {row.id: {"id": row.id, "code": row.code, "name": row.name, "symbol": row.symbol} for row in rows}
    if term_ids := ids("payment_term_id"):
        rows = (await db.execute(select(ERPPaymentTerm.id, ERPPaymentTerm.code, ERPPaymentTerm.name).where(ERPPaymentTerm.id.in_(term_ids)))).all()
        ctx["payment_terms"] = {row.id: {"id": row.id, "code": row.code, "name": row.name} for row in rows}
    contract_ids = [row.id for row in contracts if row.id] if all(isinstance(row, ContractDocument) for row in contracts) else []
    if contract_ids:
        rows = (await db.execute(select(ContractFile.contract_id, func.count()).where(ContractFile.contract_id.in_(contract_ids)).group_by(ContractFile.contract_id))).all()
        ctx["file_counts"] = {contract_id: count for contract_id, count in rows}
    return ctx


def registry_out(contract: ContractDocument | ContractArchiveEntry, ctx: dict[str, Any], today: date) -> dict[str, Any]:
    party = ctx["parties"].get(contract.party_id)
    return {
        "code": contract.code,
        "contract_number": contract.contract_number,
        "group_id": contract.group_id,
        "group": ctx["groups"].get(contract.group_id),
        "party_id": contract.party_id,
        "party": {key: party[key] for key in ("id", "code", "name")} if party else None,
        "head_party": party["parent"] if party else None,
        "signed_on": contract.signed_on,
        "quantity": _number(contract.quantity),
        "unit_id": contract.unit_id,
        "unit": ctx["units"].get(contract.unit_id),
        "unit_price": _number(contract.unit_price),
        "amount": _number(contract.amount),
        "currency": contract.currency or "MNT",
        "penalty_pct": _number(contract.penalty_pct),
        "payment_term_id": contract.payment_term_id,
        "payment_term": ctx["payment_terms"].get(contract.payment_term_id),
        "note": contract.note,
        "is_active": contract.is_active if contract.is_active is not None else True,
        "links": list(contract.links or []),
        "custom_fields": list(contract.custom_fields or []),
        "overdue_days": overdue_days(contract, today),
        "file_count": ctx["file_counts"].get(contract.id, 0),
    }


async def assert_group_parent(db: AsyncSession, organization_id: int, group_id: int | None, parent_id: int | None) -> None:
    """Parent must exist in the organization and must not create a cycle."""
    if parent_id is None:
        return
    if group_id is not None and parent_id == group_id:
        raise registry_error(422, "contract_group_cycle", "Бүлэг өөрийгөө харьяалах боломжгүй")
    seen: set[int] = set()
    cursor: int | None = parent_id
    while cursor is not None:
        if cursor in seen:
            break
        seen.add(cursor)
        row = await db.get(ContractGroup, cursor)
        if row is None or row.organization_id != organization_id:
            raise registry_error(422, "contract_group_not_found", "Харьяа бүлэг олдсонгүй")
        if group_id is not None and row.parent_id == group_id:
            raise registry_error(422, "contract_group_cycle", "Бүлгийн харьяалал давхцаж байна")
        cursor = row.parent_id


def group_out(row: ContractGroup, contract_count: int = 0) -> dict[str, Any]:
    return {"id": row.id, "code": row.code, "name": row.name, "parent_id": row.parent_id, "is_active": row.is_active, "contract_count": contract_count}
