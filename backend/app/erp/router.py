from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.enterprise_deps import ActorContext, get_actor
from app.models.models import (
    ERPAccessRole, ERPAccount, ERPAccountRole, ERPCapability, ERPCustomField, ERPDocument, ERPDocumentLine,
    ERPGeneralLedgerEntry, ERPApprovalRule, ERPImportBatch, ERPPaymentAllocation, ERPPostingPeriod, ERPItem, ERPParty, ERPStockLedgerEntry, ERPWarehouse, IdempotencyRecord, Organization,
)
from app.services.enterprise_events import record_change
from app.erp.service import (
    DOCUMENT_MODULES, DOCUMENT_TYPES, ERP_MODULES, MODULE_SETTINGS_KEY, VALID_ACTIONS, as_money, calculate_lines,
    approval_required, bootstrap_organization, cancel_document, document_out, module_settings, next_number, post_document, require_capability, validate_custom_fields,
)


router = APIRouter()


class ModulesInput(BaseModel):
    modules: dict[str, bool]


class CapabilityInput(BaseModel):
    resource: str = Field(min_length=1, max_length=80)
    action: str


class AccessRoleInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    code: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_-]+$")
    description: str | None = None
    capabilities: list[CapabilityInput] = Field(default_factory=list)


class AccountRoleInput(BaseModel):
    account_id: int
    scope: dict[str, Any] = Field(default_factory=dict)


class CustomFieldInput(BaseModel):
    resource: str = Field(min_length=1, max_length=80)
    key: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(min_length=1, max_length=120)
    field_type: Literal["text", "number", "money", "date", "datetime", "boolean", "select", "reference"]
    options: dict[str, Any] = Field(default_factory=dict)
    required: bool = False
    posting_relevant: bool = False


class PartyInput(BaseModel):
    party_type: Literal["customer", "supplier", "prospect", "contact"]
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=240)
    email: str | None = None
    phone: str | None = None
    tax_id: str | None = None
    credit_limit: Decimal | None = None
    currency: str = Field(default="MNT", min_length=3, max_length=3)
    contacts: list[dict[str, Any]] = Field(default_factory=list)
    addresses: list[dict[str, Any]] = Field(default_factory=list)
    custom: dict[str, Any] = Field(default_factory=dict)


class ItemInput(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=240)
    item_type: Literal["product", "service", "asset", "raw_material", "finished_good"] = "product"
    item_group: str | None = None
    unit: str = Field(default="Nos", max_length=24)
    valuation_method: Literal["moving_average", "fifo", "standard"] = "moving_average"
    standard_cost: Decimal = Decimal("0")
    reorder_level: Decimal | None = None
    is_stock_item: bool = True
    custom: dict[str, Any] = Field(default_factory=dict)


class WarehouseInput(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=240)
    parent_id: int | None = None


class AccountInput(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=240)
    account_type: Literal["asset", "liability", "equity", "income", "expense", "cash", "receivable", "payable", "tax_payable", "tax_receivable", "inventory", "fixed_asset", "wip", "payroll_expense", "payroll_payable"]
    parent_id: int | None = None
    is_group: bool = False


class DocumentLineInput(BaseModel):
    item_id: int | None = None
    warehouse_id: int | None = None
    account_id: int | None = None
    description: str = Field(min_length=1, max_length=1000)
    quantity: Decimal = Decimal("1")
    rate: Decimal = Decimal("0")
    tax_rate: Decimal = Decimal("0")
    data: dict[str, Any] = Field(default_factory=dict)


class DocumentInput(BaseModel):
    party_id: int | None = None
    project_id: int | None = None
    source_document_id: int | None = None
    currency: str = Field(default="MNT", min_length=3, max_length=3)
    exchange_rate: Decimal = Decimal("1")
    posting_date: date = Field(default_factory=date.today)
    due_date: date | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    custom: dict[str, Any] = Field(default_factory=dict)
    lines: list[DocumentLineInput] = Field(default_factory=list)


class DocumentPatchInput(BaseModel):
    party_id: int | None = None
    project_id: int | None = None
    due_date: date | None = None
    payload: dict[str, Any] | None = None
    custom: dict[str, Any] | None = None
    lines: list[DocumentLineInput] | None = None


class PostingPeriodInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    starts_on: date
    ends_on: date


class ApprovalRuleInput(BaseModel):
    resource: str = Field(min_length=1, max_length=80)
    minimum_amount: Decimal = Decimal("0")
    required_access_role_id: int | None = None
    priority: int = Field(default=100, ge=1, le=10000)


class StockPolicyInput(BaseModel):
    allow_negative_stock: bool = False


class ImportPreviewInput(BaseModel):
    entity: Literal["parties", "items", "accounts", "opening_stock", "open_invoices"]
    rows: list[dict[str, Any]] = Field(min_length=1, max_length=5_000)
    source_format: Literal["generic", "erpnext_v15", "erpnext_v16"] = "generic"


CONVERSION_TARGETS = {
    "lead": {"opportunity"}, "opportunity": {"quotation"}, "quotation": {"sales_order", "sales_invoice"},
    "sales_order": {"delivery", "sales_invoice"}, "supplier_quotation": {"purchase_order"},
    "purchase_order": {"purchase_receipt", "purchase_invoice"}, "purchase_receipt": {"purchase_invoice"},
}


async def _organization(db: AsyncSession, actor: ActorContext) -> Organization:
    organization = await db.get(Organization, actor.organization_id)
    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")
    return organization


async def _document(db: AsyncSession, actor: ActorContext, document_id: int) -> ERPDocument:
    document = await db.scalar(select(ERPDocument).where(ERPDocument.id == document_id, ERPDocument.organization_id == actor.organization_id))
    if not document:
        raise HTTPException(status_code=404, detail="ERP document not found")
    return document


async def _document_lines(db: AsyncSession, document_id: int) -> list[ERPDocumentLine]:
    return (await db.execute(select(ERPDocumentLine).where(ERPDocumentLine.document_id == document_id).order_by(ERPDocumentLine.position))).scalars().all()


async def _write_document_lines(db: AsyncSession, document: ERPDocument, raw_lines: list[DocumentLineInput]) -> None:
    existing = await _document_lines(db, document.id)
    for line in existing:
        await db.delete(line)
    lines, net, tax, total = calculate_lines([line.model_dump() for line in raw_lines])
    document.net_total, document.tax_total, document.grand_total = net, tax, total
    document.outstanding_amount = total if document.document_type in {"sales_invoice", "purchase_invoice"} else Decimal("0")
    db.add_all([ERPDocumentLine(document_id=document.id, **line) for line in lines])


def _normalise_import_rows(entity: str, rows: list[dict[str, Any]], source_format: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Normalize generic and ERPNext-export column names without importing code."""
    aliases = {
        "parties": {"code": ("code", "name", "customer_name", "supplier_name"), "name": ("display_name", "party_name", "customer_name", "supplier_name", "name"), "party_type": ("party_type", "type")},
        "items": {"code": ("code", "item_code"), "name": ("name", "item_name", "description")},
        "accounts": {"code": ("code", "account_number", "name"), "name": ("name", "account_name"), "account_type": ("account_type", "root_type")},
        "opening_stock": {"item_code": ("item_code", "item"), "warehouse_code": ("warehouse_code", "warehouse"), "quantity": ("quantity", "actual_qty"), "rate": ("rate", "valuation_rate")},
        "open_invoices": {"party_code": ("party_code", "customer", "supplier"), "invoice_type": ("invoice_type", "type"), "amount": ("amount", "outstanding_amount", "grand_total"), "posting_date": ("posting_date",), "due_date": ("due_date", "due_date")},
    }
    required = {
        "parties": ("code", "name"), "items": ("code", "name"), "accounts": ("code", "name", "account_type"),
        "opening_stock": ("item_code", "warehouse_code", "quantity"), "open_invoices": ("party_code", "invoice_type", "amount"),
    }[entity]
    clean: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for index, raw in enumerate(rows, start=1):
        if not isinstance(raw, dict):
            errors.append({"row": index, "code": "invalid_row"}); continue
        row = dict(raw)
        for canonical, candidates in aliases[entity].items():
            if canonical not in row:
                row[canonical] = next((raw.get(candidate) for candidate in candidates if raw.get(candidate) not in (None, "")), None)
        missing = [key for key in required if row.get(key) in (None, "")]
        if missing:
            errors.append({"row": index, "code": "missing_required", "fields": missing}); continue
        try:
            if entity in {"opening_stock", "open_invoices"}:
                Decimal(str(row["quantity"] if entity == "opening_stock" else row["amount"]))
        except Exception:
            errors.append({"row": index, "code": "invalid_decimal"}); continue
        clean.append(row)
    return clean, errors


async def _idempotent_response(db: AsyncSession, actor: ActorContext, operation: str, key: str | None, payload: Any) -> dict[str, Any] | None:
    if not key:
        return None
    if len(key) > 255:
        raise HTTPException(status_code=422, detail="Idempotency-Key is too long")
    request_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
    record = await db.scalar(select(IdempotencyRecord).where(
        IdempotencyRecord.account_id == actor.account_id, IdempotencyRecord.operation == operation, IdempotencyRecord.key == key
    ))
    if record:
        if record.request_hash != request_hash:
            raise HTTPException(status_code=409, detail={"code": "erp_idempotency_conflict"})
        return record.response_body
    return None


async def _save_idempotent(db: AsyncSession, actor: ActorContext, operation: str, key: str | None, payload: Any, response: dict[str, Any]) -> None:
    if key:
        db.add(IdempotencyRecord(
            account_id=actor.account_id, operation=operation, key=key,
            request_hash=hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest(),
            response_status=201, response_body=response, expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        ))


@router.get("/meta")
async def meta(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    organization = await _organization(db, actor)
    fields = (await db.execute(select(ERPCustomField).where(ERPCustomField.organization_id == actor.organization_id, ERPCustomField.is_active.is_(True)))).scalars().all()
    role_rows = (await db.execute(select(ERPAccessRole).where(ERPAccessRole.organization_id == actor.organization_id))).scalars().all()
    return {
        "modules": module_settings(organization.settings), "module_labels": ERP_MODULES, "document_modules": DOCUMENT_MODULES,
        "actions": sorted(VALID_ACTIONS), "currency": organization.base_currency,
        "custom_fields": [{"resource": field.resource, "key": field.key, "label": field.label, "field_type": field.field_type,
            "options": field.options, "required": field.required, "posting_relevant": field.posting_relevant} for field in fields],
        "roles": [{"id": role.id, "name": role.name, "code": role.code, "description": role.description} for role in role_rows],
        "module_visibility_is_not_authorization": True,
    }


@router.put("/admin/modules")
async def update_modules(data: ModulesInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "erp_settings", "administer")
    unknown = set(data.modules).difference(ERP_MODULES)
    if unknown:
        raise HTTPException(status_code=422, detail={"code": "erp_unknown_module", "modules": sorted(unknown)})
    organization = await _organization(db, actor)
    settings = {**(organization.settings or {}), MODULE_SETTINGS_KEY: {name: bool(data.modules.get(name, False)) for name in ERP_MODULES}}
    organization.settings = settings
    await bootstrap_organization(db, organization.id)
    await record_change(db, actor=actor, topic="erp", aggregate_type="erp_module_settings", aggregate_id=organization.id, operation="updated", after={MODULE_SETTINGS_KEY: settings[MODULE_SETTINGS_KEY]})
    await db.commit()
    return {"modules": module_settings(settings), "notice": "Visibility changes do not disable APIs, integrations, or existing automations."}


@router.get("/admin/roles")
async def list_roles(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "erp_roles", "administer")
    roles = (await db.execute(select(ERPAccessRole).where(ERPAccessRole.organization_id == actor.organization_id).order_by(ERPAccessRole.name))).scalars().all()
    result = []
    for role in roles:
        capabilities = (await db.execute(select(ERPCapability).where(ERPCapability.access_role_id == role.id))).scalars().all()
        result.append({"id": role.id, "name": role.name, "code": role.code, "description": role.description, "is_system": role.is_system,
            "capabilities": [{"resource": cap.resource, "action": cap.action} for cap in capabilities]})
    return result


@router.post("/admin/roles", status_code=status.HTTP_201_CREATED)
async def create_role(data: AccessRoleInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "erp_roles", "administer")
    if any(cap.action not in VALID_ACTIONS and cap.action != "*" for cap in data.capabilities):
        raise HTTPException(status_code=422, detail="Unknown capability action")
    role = ERPAccessRole(organization_id=actor.organization_id, name=data.name, code=data.code, description=data.description)
    db.add(role)
    await db.flush()
    db.add_all([ERPCapability(access_role_id=role.id, resource=cap.resource, action=cap.action) for cap in data.capabilities])
    await record_change(db, actor=actor, topic="erp", aggregate_type="erp_access_role", aggregate_id=role.id, operation="created", after={"code": role.code})
    await db.commit()
    return {"id": role.id, "name": role.name, "code": role.code}


@router.post("/admin/roles/{role_id}/accounts", status_code=status.HTTP_201_CREATED)
async def assign_role(role_id: int, data: AccountRoleInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "erp_roles", "administer")
    role = await db.scalar(select(ERPAccessRole).where(ERPAccessRole.id == role_id, ERPAccessRole.organization_id == actor.organization_id))
    if not role:
        raise HTTPException(status_code=404, detail="ERP role not found")
    assignment = ERPAccountRole(account_id=data.account_id, access_role_id=role.id, scope=data.scope)
    db.add(assignment)
    await db.commit()
    return {"id": assignment.id, "role_id": role.id, "account_id": assignment.account_id, "scope": assignment.scope}


@router.post("/admin/custom-fields", status_code=status.HTTP_201_CREATED)
async def create_custom_field(data: CustomFieldInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "erp_custom_fields", "administer")
    if data.field_type == "select" and not data.options.get("choices"):
        raise HTTPException(status_code=422, detail="Select fields require options.choices")
    field = ERPCustomField(organization_id=actor.organization_id, **data.model_dump())
    db.add(field)
    await db.commit()
    return {"id": field.id, **data.model_dump()}


@router.get("/accounting/posting-periods")
async def list_posting_periods(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "accounts", "view")
    rows = (await db.execute(select(ERPPostingPeriod).where(ERPPostingPeriod.organization_id == actor.organization_id).order_by(ERPPostingPeriod.starts_on.desc()))).scalars().all()
    return [{"id": row.id, "name": row.name, "starts_on": row.starts_on.isoformat(), "ends_on": row.ends_on.isoformat(), "status": row.status, "closed_at": row.closed_at.isoformat() if row.closed_at else None} for row in rows]


@router.post("/accounting/posting-periods", status_code=status.HTTP_201_CREATED)
async def create_posting_period(data: PostingPeriodInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "accounts", "administer")
    if data.ends_on < data.starts_on:
        raise HTTPException(status_code=422, detail={"code": "erp_invalid_posting_period"})
    period = ERPPostingPeriod(organization_id=actor.organization_id, **data.model_dump())
    db.add(period)
    await db.commit()
    return {"id": period.id, "name": period.name, "starts_on": period.starts_on.isoformat(), "ends_on": period.ends_on.isoformat(), "status": period.status}


@router.post("/accounting/posting-periods/{period_id}/close")
async def close_posting_period(period_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "accounts", "administer")
    period = await db.scalar(select(ERPPostingPeriod).where(ERPPostingPeriod.id == period_id, ERPPostingPeriod.organization_id == actor.organization_id))
    if not period:
        raise HTTPException(status_code=404, detail="Posting period not found")
    period.status, period.closed_by_account_id, period.closed_at = "closed", actor.account_id, datetime.now(timezone.utc)
    await record_change(db, actor=actor, topic="erp", aggregate_type="erp_posting_period", aggregate_id=period.id, operation="closed", after={"name": period.name})
    await db.commit()
    return {"id": period.id, "status": period.status}


@router.get("/admin/approval-rules")
async def list_approval_rules(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "erp_approval_rules", "administer")
    rows = (await db.execute(select(ERPApprovalRule).where(ERPApprovalRule.organization_id == actor.organization_id).order_by(ERPApprovalRule.priority))).scalars().all()
    return [{"id": row.id, "resource": row.resource, "minimum_amount": str(row.minimum_amount), "required_access_role_id": row.required_access_role_id, "priority": row.priority, "is_active": row.is_active} for row in rows]


@router.post("/admin/approval-rules", status_code=status.HTTP_201_CREATED)
async def create_approval_rule(data: ApprovalRuleInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "erp_approval_rules", "administer")
    if data.resource != "*" and data.resource not in DOCUMENT_TYPES:
        raise HTTPException(status_code=422, detail={"code": "erp_unknown_approval_resource"})
    if data.minimum_amount < 0:
        raise HTTPException(status_code=422, detail={"code": "erp_invalid_approval_threshold"})
    rule = ERPApprovalRule(organization_id=actor.organization_id, **data.model_dump())
    db.add(rule)
    await db.commit()
    return {"id": rule.id, "resource": rule.resource, "minimum_amount": str(rule.minimum_amount), "priority": rule.priority}


@router.put("/stock/policy")
async def update_stock_policy(data: StockPolicyInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "stock", "administer")
    organization = await _organization(db, actor)
    organization.settings = {**(organization.settings or {}), "erp_stock_policy": data.model_dump()}
    await record_change(db, actor=actor, topic="erp", aggregate_type="erp_stock_policy", aggregate_id=organization.id, operation="updated", after=organization.settings["erp_stock_policy"])
    await db.commit()
    return organization.settings["erp_stock_policy"]


async def _create_import_preview(data: ImportPreviewInput, db: AsyncSession, actor: ActorContext) -> dict[str, Any]:
    await require_capability(db, actor, "erp_imports", "administer")
    rows, errors = _normalise_import_rows(data.entity, data.rows, data.source_format)
    batch = ERPImportBatch(
        organization_id=actor.organization_id, created_by_account_id=actor.account_id, entity=data.entity,
        source_format=data.source_format, state="validated" if not errors else "invalid", rows=rows, validation_errors=errors,
    )
    db.add(batch)
    await db.commit()
    return {"id": batch.id, "entity": batch.entity, "state": batch.state, "valid_rows": len(rows), "errors": errors}


@router.post("/imports/preview", status_code=status.HTTP_201_CREATED)
async def preview_import(data: ImportPreviewInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    return await _create_import_preview(data, db, actor)


@router.post("/imports/csv", status_code=status.HTTP_201_CREATED)
async def preview_csv_import(entity: Literal["parties", "items", "accounts", "opening_stock", "open_invoices"], file: UploadFile = File(...), source_format: Literal["generic", "erpnext_v15", "erpnext_v16"] = "generic", db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    if file.content_type not in {"text/csv", "application/csv", "application/vnd.ms-excel", "application/octet-stream"}:
        raise HTTPException(status_code=415, detail="Import files must be CSV")
    try:
        parsed = list(csv.DictReader(io.StringIO((await file.read()).decode("utf-8-sig"))))
    except UnicodeDecodeError:
        raise HTTPException(status_code=422, detail={"code": "erp_import_not_utf8"})
    return await _create_import_preview(ImportPreviewInput(entity=entity, rows=parsed, source_format=source_format), db, actor)


@router.get("/imports/{batch_id}")
async def get_import_batch(batch_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "erp_imports", "administer")
    batch = await db.scalar(select(ERPImportBatch).where(ERPImportBatch.id == batch_id, ERPImportBatch.organization_id == actor.organization_id))
    if not batch:
        raise HTTPException(status_code=404, detail="ERP import batch not found")
    return {"id": batch.id, "entity": batch.entity, "source_format": batch.source_format, "state": batch.state, "rows": batch.rows, "errors": batch.validation_errors}


@router.post("/imports/{batch_id}/commit")
async def commit_import_batch(batch_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "erp_imports", "administer")
    batch = await db.scalar(select(ERPImportBatch).where(ERPImportBatch.id == batch_id, ERPImportBatch.organization_id == actor.organization_id).with_for_update())
    if not batch:
        raise HTTPException(status_code=404, detail="ERP import batch not found")
    if batch.state == "committed":
        return {"id": batch.id, "state": batch.state, "replayed": True}
    if batch.state != "validated":
        raise HTTPException(status_code=409, detail={"code": "erp_import_not_validated"})
    await bootstrap_organization(db, actor.organization_id)
    created = 0
    for row in batch.rows:
        if batch.entity == "parties":
            if await db.scalar(select(ERPParty.id).where(ERPParty.organization_id == actor.organization_id, ERPParty.code == str(row["code"]))):
                raise HTTPException(status_code=409, detail={"code": "erp_import_duplicate_party", "code": row["code"]})
            kind = str(row.get("party_type") or "customer").casefold()
            if kind not in {"customer", "supplier", "prospect", "contact"}: kind = "customer"
            db.add(ERPParty(organization_id=actor.organization_id, party_type=kind, code=str(row["code"]), name=str(row["name"]), email=row.get("email"), phone=row.get("phone")))
        elif batch.entity == "items":
            if await db.scalar(select(ERPItem.id).where(ERPItem.organization_id == actor.organization_id, ERPItem.code == str(row["code"]))):
                raise HTTPException(status_code=409, detail={"code": "erp_import_duplicate_item", "code": row["code"]})
            db.add(ERPItem(organization_id=actor.organization_id, code=str(row["code"]), name=str(row["name"]), item_type=str(row.get("item_type") or "product"), unit=str(row.get("unit") or "Nos"), is_stock_item=str(row.get("is_stock_item", "true")).casefold() not in {"false", "0", "no"}))
        elif batch.entity == "accounts":
            if await db.scalar(select(ERPAccount.id).where(ERPAccount.organization_id == actor.organization_id, ERPAccount.code == str(row["code"]))):
                raise HTTPException(status_code=409, detail={"code": "erp_import_duplicate_account", "code": row["code"]})
            account_type = str(row["account_type"]).casefold().replace(" ", "_")
            db.add(ERPAccount(organization_id=actor.organization_id, code=str(row["code"]), name=str(row["name"]), account_type=account_type))
        elif batch.entity == "opening_stock":
            item = await db.scalar(select(ERPItem).where(ERPItem.organization_id == actor.organization_id, ERPItem.code == str(row["item_code"])))
            warehouse = await db.scalar(select(ERPWarehouse).where(ERPWarehouse.organization_id == actor.organization_id, ERPWarehouse.code == str(row["warehouse_code"])))
            if not item or not warehouse:
                raise HTTPException(status_code=422, detail={"code": "erp_import_stock_master_missing", "item_code": row["item_code"], "warehouse_code": row["warehouse_code"]})
            quantity, rate = Decimal(str(row["quantity"])), Decimal(str(row.get("rate") or 0))
            document = ERPDocument(organization_id=actor.organization_id, document_type="stock_entry", number=await next_number(db, actor.organization_id, "stock_entry"), posting_date=date.today(), payload={"movement_type": "receipt", "opening_balance": True})
            db.add(document); await db.flush()
            db.add(ERPDocumentLine(document_id=document.id, item_id=item.id, warehouse_id=warehouse.id, description=f"Opening stock: {item.name}", quantity=quantity, rate=rate, amount=as_money(quantity * rate)))
            await db.flush(); await post_document(db, document, actor)
        else:  # open_invoices
            party = await db.scalar(select(ERPParty).where(ERPParty.organization_id == actor.organization_id, ERPParty.code == str(row["party_code"])))
            kind = str(row["invoice_type"]).casefold()
            document_type = "purchase_invoice" if kind in {"purchase", "purchase_invoice", "supplier"} else "sales_invoice"
            if not party:
                raise HTTPException(status_code=422, detail={"code": "erp_import_party_missing", "party_code": row["party_code"]})
            amount = as_money(row["amount"])
            document = ERPDocument(organization_id=actor.organization_id, document_type=document_type, number=await next_number(db, actor.organization_id, document_type), party_id=party.id, posting_date=date.fromisoformat(str(row.get("posting_date") or date.today().isoformat())), due_date=date.fromisoformat(str(row["due_date"])) if row.get("due_date") else None, net_total=amount, grand_total=amount, outstanding_amount=amount, payload={"opening_balance": True})
            db.add(document); await db.flush(); await post_document(db, document, actor)
        created += 1
    batch.state, batch.committed_at = "committed", datetime.now(timezone.utc)
    await record_change(db, actor=actor, topic="erp", aggregate_type="erp_import_batch", aggregate_id=batch.id, operation="committed", after={"entity": batch.entity, "created": created})
    await db.commit()
    return {"id": batch.id, "state": batch.state, "created": created}


@router.get("/masters/parties")
async def list_parties(party_type: str | None = None, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "parties", "view")
    statement = select(ERPParty).where(ERPParty.organization_id == actor.organization_id)
    if party_type:
        statement = statement.where(ERPParty.party_type == party_type)
    rows = (await db.execute(statement.order_by(ERPParty.name))).scalars().all()
    return [{"id": row.id, "public_id": str(row.public_id), "party_type": row.party_type, "code": row.code, "name": row.name,
        "email": row.email, "phone": row.phone, "tax_id": row.tax_id, "currency": row.currency, "custom": row.custom} for row in rows]


@router.post("/masters/parties", status_code=status.HTTP_201_CREATED)
async def create_party(data: PartyInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "parties", "create")
    payload = data.model_dump()
    payload["custom"] = await validate_custom_fields(db, actor.organization_id, "party", data.custom)
    party = ERPParty(organization_id=actor.organization_id, **payload)
    db.add(party)
    await record_change(db, actor=actor, topic="erp", aggregate_type="erp_party", aggregate_id=0, operation="created", after={"code": data.code, "party_type": data.party_type})
    await db.commit()
    await db.refresh(party)
    return {"id": party.id, "public_id": str(party.public_id), "code": party.code, "name": party.name}


@router.get("/masters/items")
async def list_items(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "items", "view")
    rows = (await db.execute(select(ERPItem).where(ERPItem.organization_id == actor.organization_id).order_by(ERPItem.name))).scalars().all()
    return [{"id": row.id, "public_id": str(row.public_id), "code": row.code, "name": row.name, "item_type": row.item_type,
        "unit": row.unit, "valuation_method": row.valuation_method, "standard_cost": str(row.standard_cost), "reorder_level": str(row.reorder_level) if row.reorder_level is not None else None} for row in rows]


@router.post("/masters/items", status_code=status.HTTP_201_CREATED)
async def create_item(data: ItemInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "items", "create")
    payload = data.model_dump()
    payload["custom"] = await validate_custom_fields(db, actor.organization_id, "item", data.custom)
    item = ERPItem(organization_id=actor.organization_id, **payload)
    db.add(item)
    await db.commit()
    return {"id": item.id, "public_id": str(item.public_id), "code": item.code, "name": item.name}


@router.get("/masters/warehouses")
async def list_warehouses(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "warehouses", "view")
    rows = (await db.execute(select(ERPWarehouse).where(ERPWarehouse.organization_id == actor.organization_id).order_by(ERPWarehouse.name))).scalars().all()
    return [{"id": row.id, "code": row.code, "name": row.name, "parent_id": row.parent_id, "is_active": row.is_active} for row in rows]


@router.post("/masters/warehouses", status_code=status.HTTP_201_CREATED)
async def create_warehouse(data: WarehouseInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "warehouses", "create")
    warehouse = ERPWarehouse(organization_id=actor.organization_id, **data.model_dump())
    db.add(warehouse)
    await db.commit()
    return {"id": warehouse.id, "code": warehouse.code, "name": warehouse.name}


@router.get("/accounting/accounts")
async def list_accounts(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "accounts", "view")
    rows = (await db.execute(select(ERPAccount).where(ERPAccount.organization_id == actor.organization_id).order_by(ERPAccount.code))).scalars().all()
    return [{"id": row.id, "code": row.code, "name": row.name, "account_type": row.account_type, "parent_id": row.parent_id, "is_group": row.is_group} for row in rows]


@router.post("/accounting/accounts", status_code=status.HTTP_201_CREATED)
async def create_account(data: AccountInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "accounts", "create")
    account = ERPAccount(organization_id=actor.organization_id, **data.model_dump())
    db.add(account)
    await db.commit()
    return {"id": account.id, "code": account.code, "name": account.name, "account_type": account.account_type}


@router.get("/documents/{document_type}")
async def list_documents(document_type: str, document_status: str | None = Query(default=None, alias="status"), db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    if document_type not in DOCUMENT_TYPES:
        raise HTTPException(status_code=404, detail="Unknown ERP document type")
    await require_capability(db, actor, document_type, "view")
    statement = select(ERPDocument).where(ERPDocument.organization_id == actor.organization_id, ERPDocument.document_type == document_type)
    if document_status:
        statement = statement.where(ERPDocument.status == document_status)
    docs = (await db.execute(statement.order_by(ERPDocument.posting_date.desc(), ERPDocument.id.desc()))).scalars().all()
    return [document_out(doc) for doc in docs]


@router.post("/documents/{document_type}", status_code=status.HTTP_201_CREATED)
async def create_document(document_type: str, data: DocumentInput, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    if document_type not in DOCUMENT_TYPES:
        raise HTTPException(status_code=404, detail="Unknown ERP document type")
    await require_capability(db, actor, document_type, "create")
    prior = await _idempotent_response(db, actor, f"erp.document.{document_type}.create", idempotency_key, data.model_dump(mode="json"))
    if prior:
        return prior
    custom = await validate_custom_fields(db, actor.organization_id, f"document:{document_type}", data.custom)
    document = ERPDocument(
        organization_id=actor.organization_id, document_type=document_type, number=await next_number(db, actor.organization_id, document_type),
        party_id=data.party_id, project_id=data.project_id, source_document_id=data.source_document_id, currency=data.currency.upper(),
        exchange_rate=data.exchange_rate, posting_date=data.posting_date, due_date=data.due_date, payload=data.payload, custom=custom,
    )
    db.add(document)
    await db.flush()
    await _write_document_lines(db, document, data.lines)
    await db.flush()
    result = document_out(document, await _document_lines(db, document.id))
    await _save_idempotent(db, actor, f"erp.document.{document_type}.create", idempotency_key, data.model_dump(mode="json"), result)
    await record_change(db, actor=actor, topic="erp", aggregate_type=f"erp_{document_type}", aggregate_id=document.id, operation="created", version=document.version, after={"number": document.number, "status": document.status})
    await db.commit()
    return result


@router.get("/documents/by-id/{document_id}")
async def get_document(document_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    document = await _document(db, actor, document_id)
    await require_capability(db, actor, document.document_type, "view")
    return document_out(document, await _document_lines(db, document.id))


@router.patch("/documents/by-id/{document_id}")
async def update_document(document_id: int, data: DocumentPatchInput, if_match: int | None = Header(default=None, alias="If-Match"), db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    document = await _document(db, actor, document_id)
    await require_capability(db, actor, document.document_type, "edit")
    if document.status != "draft":
        raise HTTPException(status_code=409, detail={"code": "erp_submitted_document_immutable"})
    if if_match is None or if_match != document.version:
        raise HTTPException(status_code=409, detail={"code": "erp_version_conflict", "current_version": document.version})
    values = data.model_dump(exclude_unset=True)
    if "custom" in values:
        document.custom = await validate_custom_fields(db, actor.organization_id, f"document:{document.document_type}", values.pop("custom"))
    lines = values.pop("lines", None)
    for name, value in values.items():
        setattr(document, name, value)
    if lines is not None:
        await _write_document_lines(db, document, lines)
    document.version += 1
    await record_change(db, actor=actor, topic="erp", aggregate_type=f"erp_{document.document_type}", aggregate_id=document.id, operation="updated", version=document.version, after={"status": document.status})
    await db.commit()
    return document_out(document, await _document_lines(db, document.id))


@router.post("/documents/by-id/{document_id}/approve")
async def approve_document(document_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    document = await _document(db, actor, document_id)
    await require_capability(db, actor, document.document_type, "approve")
    if document.status != "draft":
        raise HTTPException(status_code=409, detail="Only draft documents can be approved")
    rule = await db.scalar(select(ERPApprovalRule).where(
        ERPApprovalRule.organization_id == actor.organization_id,
        ERPApprovalRule.resource.in_([document.document_type, "*"]),
        ERPApprovalRule.is_active.is_(True),
        ERPApprovalRule.minimum_amount <= document.grand_total,
    ).order_by(ERPApprovalRule.priority).limit(1))
    if rule and rule.required_access_role_id and "admin" not in actor.roles:
        assigned = await db.scalar(select(ERPAccountRole.id).where(
            ERPAccountRole.account_id == actor.account_id, ERPAccountRole.access_role_id == rule.required_access_role_id
        ))
        if not assigned:
            raise HTTPException(status_code=403, detail={"code": "erp_required_approver_role"})
    document.status = "approved"
    document.version += 1
    await record_change(db, actor=actor, topic="erp", aggregate_type=f"erp_{document.document_type}", aggregate_id=document.id, operation="approved", version=document.version, after={"status": document.status})
    await db.commit()
    return document_out(document)


@router.post("/documents/by-id/{document_id}/submit")
async def submit_document(document_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    document = await _document(db, actor, document_id)
    await require_capability(db, actor, document.document_type, "submit")
    if document.status not in {"draft", "approved"}:
        raise HTTPException(status_code=409, detail="Only draft or approved documents can be submitted")
    if await approval_required(db, document) and document.status != "approved":
        raise HTTPException(status_code=409, detail={"code": "erp_approval_required"})
    await post_document(db, document, actor)
    await record_change(db, actor=actor, topic="erp", aggregate_type=f"erp_{document.document_type}", aggregate_id=document.id, operation="submitted", version=document.version, after={"status": document.status, "grand_total": document.grand_total})
    await db.commit()
    return document_out(document, await _document_lines(db, document.id))


@router.post("/documents/by-id/{document_id}/cancel")
async def cancel(document_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    document = await _document(db, actor, document_id)
    await require_capability(db, actor, document.document_type, "cancel")
    if document.status != "submitted":
        raise HTTPException(status_code=409, detail="Only submitted documents can be cancelled")
    await cancel_document(db, document)
    await record_change(db, actor=actor, topic="erp", aggregate_type=f"erp_{document.document_type}", aggregate_id=document.id, operation="cancelled", version=document.version, after={"status": document.status})
    await db.commit()
    return document_out(document)


@router.post("/documents/by-id/{document_id}/amend", status_code=status.HTTP_201_CREATED)
async def amend(document_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    source = await _document(db, actor, document_id)
    await require_capability(db, actor, source.document_type, "create")
    if source.status != "cancelled":
        raise HTTPException(status_code=409, detail="Only cancelled documents can be amended")
    amendment = ERPDocument(
        organization_id=source.organization_id, document_type=source.document_type, number=await next_number(db, source.organization_id, source.document_type),
        party_id=source.party_id, project_id=source.project_id, source_document_id=source.source_document_id, amended_from_id=source.id,
        currency=source.currency, exchange_rate=source.exchange_rate, posting_date=source.posting_date, due_date=source.due_date,
        net_total=source.net_total, tax_total=source.tax_total, grand_total=source.grand_total, outstanding_amount=source.outstanding_amount,
        payload=source.payload, custom=source.custom,
    )
    db.add(amendment)
    await db.flush()
    source_lines = await _document_lines(db, source.id)
    db.add_all([ERPDocumentLine(document_id=amendment.id, item_id=line.item_id, warehouse_id=line.warehouse_id, account_id=line.account_id,
        description=line.description, quantity=line.quantity, rate=line.rate, amount=line.amount, tax_rate=line.tax_rate, tax_amount=line.tax_amount,
        position=line.position, data=line.data) for line in source_lines])
    await db.commit()
    return document_out(amendment, await _document_lines(db, amendment.id))


@router.post("/documents/by-id/{document_id}/convert/{target_type}", status_code=status.HTTP_201_CREATED)
async def convert_document(document_id: int, target_type: str, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    source = await _document(db, actor, document_id)
    if target_type not in CONVERSION_TARGETS.get(source.document_type, set()):
        raise HTTPException(status_code=422, detail={"code": "erp_invalid_document_conversion", "source": source.document_type, "target": target_type})
    await require_capability(db, actor, target_type, "create")
    if source.status == "cancelled":
        raise HTTPException(status_code=409, detail={"code": "erp_cancelled_document_cannot_convert"})
    converted = ERPDocument(
        organization_id=source.organization_id, document_type=target_type, number=await next_number(db, source.organization_id, target_type),
        party_id=source.party_id, project_id=source.project_id, source_document_id=source.id, currency=source.currency,
        exchange_rate=source.exchange_rate, posting_date=date.today(), due_date=source.due_date,
        payload={**(source.payload or {}), "converted_from": source.number},
    )
    db.add(converted)
    await db.flush()
    source_lines = await _document_lines(db, source.id)
    db.add_all([ERPDocumentLine(
        document_id=converted.id, item_id=line.item_id, warehouse_id=line.warehouse_id, account_id=line.account_id,
        description=line.description, quantity=line.quantity, rate=line.rate, amount=line.amount, tax_rate=line.tax_rate,
        tax_amount=line.tax_amount, position=line.position, data=line.data,
    ) for line in source_lines])
    converted.net_total, converted.tax_total, converted.grand_total = source.net_total, source.tax_total, source.grand_total
    converted.outstanding_amount = source.grand_total if target_type in {"sales_invoice", "purchase_invoice"} else Decimal("0")
    await record_change(db, actor=actor, topic="erp", aggregate_type=f"erp_{target_type}", aggregate_id=converted.id, operation="converted", version=converted.version, after={"number": converted.number, "source_document_id": source.id})
    await db.commit()
    return document_out(converted, await _document_lines(db, converted.id))


@router.get("/manufacturing/boms/{document_id}/costing")
async def bom_costing(document_id: int, margin_percent: Decimal | None = Query(default=None, ge=0, le=1000), db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    bom = await _document(db, actor, document_id)
    if bom.document_type != "bill_of_materials":
        raise HTTPException(status_code=422, detail={"code": "erp_not_a_bill_of_materials"})
    await require_capability(db, actor, "bill_of_materials", "view")
    lines = await _document_lines(db, bom.id)
    material_cost = sum((as_money(line.amount) for line in lines), Decimal("0"))
    machine_cost = labor_cost = Decimal("0")
    for operation in list((bom.payload or {}).get("operations") or []):
        if not isinstance(operation, dict):
            raise HTTPException(status_code=422, detail={"code": "erp_invalid_bom_operation"})
        minutes = Decimal(str(operation.get("minutes", 0)))
        machine_cost += as_money(Decimal(str(operation.get("machine_rate", 0))) * minutes / 60)
        labor_cost += as_money(Decimal(str(operation.get("labor_rate", 0))) * minutes / 60)
    total = as_money(material_cost + machine_cost + labor_cost)
    margin = margin_percent if margin_percent is not None else Decimal(str((bom.payload or {}).get("suggested_margin_percent", 0)))
    suggested = as_money(total * (Decimal("1") + margin / 100))
    return {"bom_id": bom.id, "currency": bom.currency, "material_cost": str(material_cost), "machine_cost": str(machine_cost), "labor_cost": str(labor_cost), "actual_cost": str(total), "margin_percent": str(margin), "suggested_selling_price": str(suggested)}


@router.get("/reports/dashboard")
async def dashboard(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "erp_dashboard", "view")
    docs = (await db.execute(select(ERPDocument).where(ERPDocument.organization_id == actor.organization_id, ERPDocument.status == "submitted"))).scalars().all()
    amounts = {kind: sum((as_money(doc.grand_total) for doc in docs if doc.document_type == kind), Decimal("0")) for kind in DOCUMENT_TYPES}
    stock_value = await db.scalar(select(func.coalesce(func.sum(ERPStockLedgerEntry.value_delta), 0)).where(ERPStockLedgerEntry.organization_id == actor.organization_id))
    open_queries = await db.scalar(select(func.count(ERPDocument.id)).where(ERPDocument.organization_id == actor.organization_id, ERPDocument.document_type == "support_ticket", ERPDocument.status.not_in(["cancelled", "submitted"])))
    return {"currency": (await _organization(db, actor)).base_currency, "revenue": str(amounts["sales_invoice"]), "expenses": str(amounts["purchase_invoice"]),
        "profit": str(amounts["sales_invoice"] - amounts["purchase_invoice"]), "cash_collected": str(amounts["payment_entry"]),
        "inventory_value": str(stock_value), "open_customer_queries": open_queries, "payroll_total": str(amounts["payroll_run"]),
        "production_cost": str(amounts["work_order"]), "upcoming_maintenance": sum(1 for doc in docs if doc.document_type == "maintenance_schedule")}


@router.get("/reports/stock-balance")
async def stock_balance(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "stock", "view")
    rows = (await db.execute(select(ERPStockLedgerEntry.item_id, ERPStockLedgerEntry.warehouse_id, func.sum(ERPStockLedgerEntry.quantity_delta).label("quantity"), func.sum(ERPStockLedgerEntry.value_delta).label("value")).where(
        ERPStockLedgerEntry.organization_id == actor.organization_id
    ).group_by(ERPStockLedgerEntry.item_id, ERPStockLedgerEntry.warehouse_id))).all()
    return [{"item_id": row.item_id, "warehouse_id": row.warehouse_id, "quantity": str(row.quantity), "value": str(row.value)} for row in rows]


@router.get("/reports/general-ledger")
async def general_ledger(account_id: int | None = None, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "accounts", "view")
    statement = select(ERPGeneralLedgerEntry).where(ERPGeneralLedgerEntry.organization_id == actor.organization_id)
    if account_id:
        statement = statement.where(ERPGeneralLedgerEntry.account_id == account_id)
    rows = (await db.execute(statement.order_by(ERPGeneralLedgerEntry.posting_date, ERPGeneralLedgerEntry.id))).scalars().all()
    return [{"id": row.id, "document_id": row.document_id, "account_id": row.account_id, "party_id": row.party_id, "posting_date": row.posting_date.isoformat(),
        "debit": str(row.debit), "credit": str(row.credit), "memo": row.memo, "reversal_of_id": row.reversal_of_id} for row in rows]


@router.get("/reports/trial-balance")
async def trial_balance(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "accounts", "view")
    totals = (await db.execute(select(
        ERPGeneralLedgerEntry.account_id, func.coalesce(func.sum(ERPGeneralLedgerEntry.debit), 0), func.coalesce(func.sum(ERPGeneralLedgerEntry.credit), 0),
    ).where(ERPGeneralLedgerEntry.organization_id == actor.organization_id).group_by(ERPGeneralLedgerEntry.account_id))).all()
    accounts = {account.id: account for account in (await db.execute(select(ERPAccount).where(ERPAccount.organization_id == actor.organization_id))).scalars().all()}
    rows = [{"account_id": account_id, "code": accounts[account_id].code, "name": accounts[account_id].name, "account_type": accounts[account_id].account_type,
        "debit": str(debit), "credit": str(credit), "balance": str(as_money(debit - credit))} for account_id, debit, credit in totals if account_id in accounts]
    return {"rows": rows, "total_debit": str(sum((as_money(row["debit"]) for row in rows), Decimal("0"))), "total_credit": str(sum((as_money(row["credit"]) for row in rows), Decimal("0")))}


@router.get("/reports/outstanding")
async def outstanding_invoices(kind: Literal["receivable", "payable"], db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    document_type = "sales_invoice" if kind == "receivable" else "purchase_invoice"
    await require_capability(db, actor, document_type, "view")
    rows = (await db.execute(select(ERPDocument).where(
        ERPDocument.organization_id == actor.organization_id, ERPDocument.document_type == document_type,
        ERPDocument.status == "submitted", ERPDocument.outstanding_amount > 0,
    ).order_by(ERPDocument.due_date, ERPDocument.id))).scalars().all()
    today = date.today()
    return [{"document_id": row.id, "number": row.number, "party_id": row.party_id, "due_date": row.due_date.isoformat() if row.due_date else None,
        "outstanding_amount": str(row.outstanding_amount), "currency": row.currency, "days_overdue": max((today - row.due_date).days, 0) if row.due_date else 0} for row in rows]
