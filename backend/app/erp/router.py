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
    ERPAccessRole, ERPAccount, ERPAccountingSettings, ERPAccountRole, ERPCapability, ERPCustomField, ERPDocument, ERPDocumentLine,
    Employee, PayrollRun, ERPFormDefinition, ERPMasterRequest, ERPGeneralLedgerEntry, ERPApprovalRule, ERPImportBatch, ERPPaymentAllocation, ERPPostingPeriod, ERPItem, ERPParty, ERPStockLedgerEntry, ERPTeamRole, ERPWarehouse, ERPWorkflowTransition, ERPModuleConfig, ERPUnitOfMeasure, ERPPriceList, ERPPriceListEntry, ERPDiscountTier, ERPReorderRule, ERPCostCenter, ERPTaxTemplate, ERPTaxTemplateRate, ERPInventoryLevel, ERPSourceLineAllocation, ERPStockValuationLayer, ERPBOMSnapshot, ERPAssetBook, ERPAssetDepreciationSchedule, ERPAssetMaintenanceRecord, ERPAssetDisposal, IdempotencyRecord, Organization, Project, Team, TeamMember, UserAccount,
)
from app.services.enterprise_events import record_change
from app.erp.service import (
    DOCUMENT_MODULES, DOCUMENT_TYPES, ERP_MODULES, MASTER_OPERATION_MODULES, MASTER_OPERATIONS, MODULE_SETTINGS_KEY, VALID_ACTIONS, as_money, calculate_lines,
    approval_required, bootstrap_organization, cancel_document, capability_scopes, default_workflow, document_out, ensure_definition, module_settings, next_number, operation_catalog, post_document, published_definition, record_workflow_transition, require_capability, require_phase5_gate, phase5_gate_status, scope_allows, validate_custom_fields, validate_definition_fields, validate_form_values, validate_workflow,
)
from app.payroll.router import router as payroll_router


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


class FormFieldInput(BaseModel):
    key: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(min_length=1, max_length=120)
    help_text: str | None = Field(default=None, max_length=500)
    field_type: Literal["text", "long_text", "number", "money", "date", "datetime", "boolean", "select", "multi_select", "reference"]
    section: Literal["header", "line", "master"]
    required: bool = False
    default: Any = None
    options: dict[str, Any] = Field(default_factory=dict)
    validation: dict[str, Any] = Field(default_factory=dict)
    position: int = Field(default=0, ge=0)


class FormDefinitionInput(BaseModel):
    fields: list[FormFieldInput] = Field(default_factory=list, max_length=200)
    workflow: dict[str, Any] = Field(default_factory=default_workflow)


class RolePatchInput(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    capabilities: list[CapabilityInput] | None = None


class TeamRoleInput(BaseModel):
    team_id: int
    scope: dict[str, Any] = Field(default_factory=dict)


class MasterRequestInput(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)
    custom: dict[str, Any] = Field(default_factory=dict)
    scope: dict[str, Any] = Field(default_factory=dict)


class WorkflowTransitionInput(BaseModel):
    to_state: str = Field(min_length=1, max_length=64)
    comment: str | None = Field(default=None, max_length=1000)
    version: int = Field(ge=1)


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
    classification: Literal["asset", "liability", "equity", "income", "expense"] | None = None
    purpose: str = Field(default="general", min_length=1, max_length=32)
    currency: str = Field(default="MNT", min_length=3, max_length=3)
    parent_id: int | None = None
    is_group: bool = False
    is_active: bool = True


class AccountingSettingsInput(BaseModel):
    base_currency: str = Field(default="MNT", min_length=3, max_length=3)
    fiscal_year_start_month: int = Field(default=1, ge=1, le=12)
    default_cost_center_id: int | None = None
    default_bank_account_id: int | None = None
    conversion_date: date | None = None


class UomRequestInput(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=120)
    symbol: str | None = Field(default=None, max_length=16)
    decimal_places: int = Field(default=2, ge=0, le=8)


class ReorderRuleRequestInput(BaseModel):
    item_id: int
    warehouse_id: int
    reorder_level: Decimal = Field(ge=0)
    reorder_quantity: Decimal = Field(ge=0)
    maximum_level: Decimal | None = Field(default=None, ge=0)


class PriceListRequestInput(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=240)
    party_id: int
    item_id: int
    rate: Decimal = Field(ge=0)
    minimum_quantity: Decimal = Field(default=Decimal("1"), gt=0)
    currency: str = Field(default="MNT", min_length=3, max_length=3)
    valid_from: date | None = None
    valid_to: date | None = None


class DiscountTierRequestInput(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=240)
    minimum_spend: Decimal = Field(default=Decimal("0"), ge=0)
    discount_percent: Decimal = Field(default=Decimal("0"), ge=0, le=100)


class CostCenterRequestInput(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=240)
    parent_id: int | None = None


class TaxTemplateRequestInput(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=240)
    direction: Literal["sales", "purchase"] = "sales"
    rates: list[dict[str, Any]] = Field(default_factory=list, max_length=20)


class DocumentLineInput(BaseModel):
    item_id: int | None = None
    warehouse_id: int | None = None
    account_id: int | None = None
    description: str = Field(min_length=1, max_length=1000)
    quantity: Decimal = Decimal("1")
    rate: Decimal = Decimal("0")
    discount_percent: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    discount_amount: Decimal = Field(default=Decimal("0"), ge=0)
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


class Phase5AcceptanceInput(BaseModel):
    reconciled_period_id: int = Field(gt=0)
    reconciled_at: date = Field(default_factory=date.today)
    evidence_ref: str = Field(min_length=1, max_length=240)


class AssetBookInput(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=240)
    currency: str = Field(default="MNT", min_length=3, max_length=3)
    depreciation_method: Literal["straight_line"] = "straight_line"
    useful_life_months: int = Field(gt=0, le=1200)
    residual_value: Decimal = Field(default=Decimal("0"), ge=0)


class BOMSnapshotInput(BaseModel):
    output_item_id: int = Field(gt=0)
    output_quantity: Decimal = Field(gt=0)
    lines: list[dict[str, Any]] = Field(default_factory=list, max_length=500)
    operations: list[dict[str, Any]] = Field(default_factory=list, max_length=100)


class WorkOrderCompletionInput(BaseModel):
    output_item_id: int = Field(gt=0)
    output_warehouse_id: int = Field(gt=0)
    produced_quantity: Decimal = Field(gt=0)
    actual_materials: list[dict[str, Any]] = Field(default_factory=list, max_length=500)


class DepreciationScheduleInput(BaseModel):
    asset_document_id: int = Field(gt=0)
    book_id: int = Field(gt=0)
    start_date: date
    periods: int = Field(gt=0, le=1200)


class MaintenanceRecordInput(BaseModel):
    asset_document_id: int = Field(gt=0)
    scheduled_date: date
    description: str = Field(min_length=1, max_length=1000)
    cost: Decimal = Field(default=Decimal("0"), ge=0)


class AssetDisposalInput(BaseModel):
    asset_document_id: int = Field(gt=0)
    disposal_date: date
    proceeds: Decimal = Field(default=Decimal("0"), ge=0)
    reason: str = Field(min_length=1, max_length=1000)


class ImportPreviewInput(BaseModel):
    entity: Literal["parties", "items", "accounts", "opening_stock", "open_invoices"]
    rows: list[dict[str, Any]] = Field(min_length=1, max_length=5_000)
    source_format: Literal["generic", "erpnext_v15", "erpnext_v16"] = "generic"


CONVERSION_TARGETS = {
    "lead": {"opportunity"}, "opportunity": {"quotation"}, "quotation": {"sales_order"},
    "sales_order": {"delivery"}, "delivery": {"sales_invoice"}, "sales_invoice": {"sales_credit_note"},
    "supplier_quotation": {"purchase_order"}, "purchase_order": {"purchase_receipt"},
    "purchase_receipt": {"purchase_invoice"}, "purchase_invoice": {"purchase_debit_note"},
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


MASTER_OPERATION_LITERAL = Literal[
    "party", "item", "supplier", "purchase_item", "supplier_price_list", "customer", "sales_catalog_item",
    "customer_discount_tier", "warehouse", "item_sku", "uom", "reorder_rule", "chart_account", "cost_center", "tax_template",
]


def _validate_master_payload(operation: str, payload: dict[str, Any]) -> dict[str, Any]:
    forced_party_type = {"supplier": "supplier", "customer": "customer"}.get(operation)
    if operation in {"party", "supplier", "customer"}:
        return PartyInput.model_validate({**payload, "party_type": forced_party_type or payload.get("party_type", "customer")}).model_dump(mode="json")
    if operation in {"item", "purchase_item", "sales_catalog_item", "item_sku"}:
        return ItemInput.model_validate({**payload, "item_type": payload.get("item_type", "product")}).model_dump(mode="json")
    if operation == "warehouse":
        return WarehouseInput.model_validate(payload).model_dump(mode="json")
    if operation == "chart_account":
        return AccountInput.model_validate(payload).model_dump(mode="json")
    if operation == "uom":
        return UomRequestInput.model_validate(payload).model_dump(mode="json")
    if operation == "reorder_rule":
        return ReorderRuleRequestInput.model_validate(payload).model_dump(mode="json")
    if operation == "supplier_price_list":
        return PriceListRequestInput.model_validate(payload).model_dump(mode="json")
    if operation == "customer_discount_tier":
        return DiscountTierRequestInput.model_validate(payload).model_dump(mode="json")
    if operation == "cost_center":
        return CostCenterRequestInput.model_validate(payload).model_dump(mode="json")
    if operation == "tax_template":
        return TaxTemplateRequestInput.model_validate(payload).model_dump(mode="json")
    raise HTTPException(status_code=422, detail={"code": "erp_invalid_master_request_operation", "operation": operation})


def _definition_out(definition: ERPFormDefinition) -> dict[str, Any]:
    return {"id": definition.id, "operation": definition.operation, "version": definition.version, "status": definition.status,
            "fields": definition.fields or [], "workflow": definition.workflow or {}, "published_at": definition.published_at,
            "archived_at": definition.archived_at, "updated_at": definition.updated_at}


async def _validated_scope(db: AsyncSession, organization_id: int, scope: dict[str, Any]) -> dict[str, Any]:
    allowed = {"warehouse_ids", "project_ids", "branch_codes"}
    unknown = set(scope).difference(allowed)
    if unknown:
        raise HTTPException(status_code=422, detail={"code": "erp_unknown_scope_dimension", "keys": sorted(unknown)})
    if not all(isinstance(values, list) for values in scope.values()):
        raise HTTPException(status_code=422, detail={"code": "erp_scope_values_must_be_lists"})
    result = {key: list(dict.fromkeys(values)) for key, values in scope.items() if values}
    warehouse_ids, project_ids = result.get("warehouse_ids", []), result.get("project_ids", [])
    if warehouse_ids:
        count = await db.scalar(select(func.count(ERPWarehouse.id)).where(ERPWarehouse.organization_id == organization_id, ERPWarehouse.id.in_(warehouse_ids)))
        if count != len(warehouse_ids): raise HTTPException(status_code=422, detail={"code": "erp_invalid_scope_warehouse"})
    if project_ids:
        count = await db.scalar(select(func.count(Project.id)).where(Project.organization_id == organization_id, Project.id.in_(project_ids)))
        if count != len(project_ids): raise HTTPException(status_code=422, detail={"code": "erp_invalid_scope_project"})
    branches = result.get("branch_codes", [])
    if branches:
        known = set((await db.execute(select(Employee.work_branch).where(Employee.work_branch.isnot(None)))).scalars().all())
        if not set(branches).issubset(known): raise HTTPException(status_code=422, detail={"code": "erp_invalid_scope_branch"})
    return result


async def _role_out(db: AsyncSession, role: ERPAccessRole) -> dict[str, Any]:
    capabilities = (await db.execute(select(ERPCapability).where(ERPCapability.access_role_id == role.id))).scalars().all()
    account_assignments = (await db.execute(select(ERPAccountRole).where(ERPAccountRole.access_role_id == role.id))).scalars().all()
    team_assignments = (await db.execute(select(ERPTeamRole).where(ERPTeamRole.access_role_id == role.id))).scalars().all()
    return {"id": role.id, "name": role.name, "code": role.code, "description": role.description, "is_system": role.is_system, "is_active": role.is_active,
            "capabilities": [{"resource": cap.resource, "action": cap.action} for cap in capabilities],
            "account_assignments": [{"id": assignment.id, "account_id": assignment.account_id, "scope": assignment.scope} for assignment in account_assignments],
            "team_assignments": [{"id": assignment.id, "team_id": assignment.team_id, "scope": assignment.scope} for assignment in team_assignments]}


async def _actor_erp_role_ids(db: AsyncSession, actor: ActorContext) -> set[int]:
    direct = select(ERPAccountRole.access_role_id).where(ERPAccountRole.account_id == actor.account_id)
    inherited = select(ERPTeamRole.access_role_id).join(TeamMember, TeamMember.team_id == ERPTeamRole.team_id).join(UserAccount, UserAccount.employee_id == TeamMember.employee_id).where(UserAccount.id == actor.account_id)
    return set((await db.execute(direct.union(inherited))).scalars().all())


async def _workflow_transition_allowed(db: AsyncSession, actor: ActorContext, workflow: dict[str, Any], current_state: str, to_state: str, requester_id: int | None) -> dict[str, Any]:
    transition = next((item for item in workflow.get("transitions", []) if item.get("from") == current_state and item.get("to") == to_state), None)
    if not transition: raise HTTPException(status_code=409, detail={"code": "erp_workflow_transition_not_allowed", "from_state": current_state, "to_state": to_state})
    if requester_id == actor.account_id and transition.get("requester_allowed"):
        return transition
    required_role_ids = set(transition.get("role_ids") or [])
    if required_role_ids and not required_role_ids.intersection(await _actor_erp_role_ids(db, actor)) and "admin" not in actor.roles:
        raise HTTPException(status_code=403, detail={"code": "erp_workflow_role_required"})
    return transition


async def _assert_document_scope(db: AsyncSession, actor: ActorContext, resource: str, action: str, *, project_id: int | None, branch_code: str | None, warehouse_ids: list[int | None]) -> None:
    scopes = await capability_scopes(db, actor, resource, action)
    if not scope_allows(scopes, {"project_ids": project_id, "branch_codes": branch_code}) or any(not scope_allows(scopes, {"warehouse_ids": warehouse_id}) for warehouse_id in warehouse_ids):
        raise HTTPException(status_code=403, detail={"code": "erp_scope_denied"})


async def _write_document_lines(db: AsyncSession, document: ERPDocument, raw_lines: list[DocumentLineInput]) -> None:
    existing = await _document_lines(db, document.id)
    for line in existing:
        await db.delete(line)
    try:
        lines, net, tax, total = calculate_lines([line.model_dump() for line in raw_lines])
    except ValueError as error:
        raise HTTPException(status_code=422, detail={"code": "erp_invalid_document_line", "message": str(error)}) from error
    document.net_total, document.tax_total, document.grand_total = net, tax, total
    document.outstanding_amount = total if document.document_type in {"sales_invoice", "purchase_invoice"} else Decimal("0")
    db.add_all([ERPDocumentLine(
        document_id=document.id, item_id=line.get("item_id"), warehouse_id=line.get("warehouse_id"), account_id=line.get("account_id"),
        description=line["description"], quantity=line["quantity"], rate=line["rate"], amount=line["amount"],
        discount_percent=line["discount_percent"], discount_amount=line["discount_amount"], tax_rate=line["tax_rate"],
        tax_amount=line["tax_amount"], position=line["position"], data=line.get("data") or {},
    ) for line in lines])


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
    config_rows = (await db.execute(select(ERPModuleConfig).where(ERPModuleConfig.organization_id == actor.organization_id))).scalars().all()
    modules = module_settings(organization.settings)
    if config_rows:
        modules = {name: False for name in ERP_MODULES}
        modules.update({row.module: bool(row.enabled) for row in config_rows})
    return {
        "modules": modules, "module_labels": ERP_MODULES, "document_modules": DOCUMENT_MODULES,
        "actions": sorted(VALID_ACTIONS), "currency": organization.base_currency,
        "custom_fields": [{"resource": field.resource, "key": field.key, "label": field.label, "field_type": field.field_type,
            "options": field.options, "required": field.required, "posting_relevant": field.posting_relevant} for field in fields],
        "roles": [{"id": role.id, "name": role.name, "code": role.code, "description": role.description} for role in role_rows],
        "module_visibility_is_not_authorization": True,
    }


@router.get("/catalog")
async def catalog(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    """The only operation/capability vocabulary accepted by ERP builder endpoints."""
    await _organization(db, actor)
    return operation_catalog()


@router.get("/admin/forms/{operation}")
async def get_form_definition(operation: str, include_history: bool = False, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "erp_custom_fields", "administer")
    if operation not in operation_catalog()["operations"]:
        raise HTTPException(status_code=404, detail="Unknown ERP operation")
    published = await ensure_definition(db, actor.organization_id, operation, actor.account_id)
    current = await db.scalar(select(ERPFormDefinition).where(ERPFormDefinition.organization_id == actor.organization_id, ERPFormDefinition.operation == operation, ERPFormDefinition.status == "draft")) or published
    result = _definition_out(current)
    if include_history:
        history = (await db.execute(select(ERPFormDefinition).where(ERPFormDefinition.organization_id == actor.organization_id, ERPFormDefinition.operation == operation).order_by(ERPFormDefinition.version.desc()))).scalars().all()
        result["history"] = [_definition_out(item) for item in history]
    await db.commit()
    return result


@router.get("/forms/{operation}")
async def get_published_form(operation: str, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    if operation not in operation_catalog()["operations"]:
        raise HTTPException(status_code=404, detail="Unknown ERP operation")
    resource = operation if operation in {"party", "item"} else operation
    await require_capability(db, actor, resource, "create")
    definition = await ensure_definition(db, actor.organization_id, operation, actor.account_id)
    await db.commit()
    return _definition_out(definition)


@router.put("/admin/forms/{operation}")
async def save_form_draft(operation: str, data: FormDefinitionInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "erp_custom_fields", "administer")
    catalog_entry = operation_catalog()["operations"].get(operation)
    if not catalog_entry: raise HTTPException(status_code=404, detail="Unknown ERP operation")
    published = await ensure_definition(db, actor.organization_id, operation, actor.account_id)
    draft = await db.scalar(select(ERPFormDefinition).where(ERPFormDefinition.organization_id == actor.organization_id, ERPFormDefinition.operation == operation, ERPFormDefinition.status == "draft"))
    fields = validate_definition_fields(operation, [field.model_dump() for field in data.fields])
    roles = set((await db.execute(select(ERPAccessRole.id).where(ERPAccessRole.organization_id == actor.organization_id, ERPAccessRole.is_active.is_(True)))).scalars().all())
    workflow = validate_workflow(data.workflow, roles, posting_capable=bool(catalog_entry["posting_capable"]))
    if draft is None:
        draft = ERPFormDefinition(organization_id=actor.organization_id, operation=operation, version=published.version + 1, status="draft", created_by_account_id=actor.account_id)
        db.add(draft)
    draft.fields, draft.workflow = fields, workflow
    await db.commit(); await db.refresh(draft)
    return _definition_out(draft)


@router.post("/admin/forms/{operation}/publish")
async def publish_form_draft(operation: str, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "erp_custom_fields", "administer")
    draft = await db.scalar(select(ERPFormDefinition).where(ERPFormDefinition.organization_id == actor.organization_id, ERPFormDefinition.operation == operation, ERPFormDefinition.status == "draft"))
    if not draft: raise HTTPException(status_code=409, detail={"code": "erp_no_form_draft"})
    catalog_entry = operation_catalog()["operations"].get(operation)
    if not catalog_entry: raise HTTPException(status_code=404, detail="Unknown ERP operation")
    roles = set((await db.execute(select(ERPAccessRole.id).where(ERPAccessRole.organization_id == actor.organization_id, ERPAccessRole.is_active.is_(True)))).scalars().all())
    draft.fields = validate_definition_fields(operation, draft.fields or [])
    draft.workflow = validate_workflow(draft.workflow or {}, roles, posting_capable=bool(catalog_entry["posting_capable"]))
    current = await published_definition(db, actor.organization_id, operation)
    if current: current.status, current.archived_at = "archived", datetime.now(timezone.utc)
    draft.status, draft.published_at = "published", datetime.now(timezone.utc)
    await record_change(db, actor=actor, topic="erp", aggregate_type="erp_form_definition", aggregate_id=draft.id, operation="published", after={"operation": operation, "version": draft.version})
    await db.commit(); return _definition_out(draft)


async def _materialize_master_request(db: AsyncSession, actor: ActorContext, request: ERPMasterRequest) -> tuple[str, int]:
    if request.materialized_entity_id:
        return request.materialized_entity_type or request.operation, request.materialized_entity_id
    payload = dict(request.payload or {})
    custom = payload.pop("custom", {})
    operation = request.operation
    if operation in {"party", "supplier", "customer"}:
        data = PartyInput.model_validate({**payload, "party_type": {"supplier": "supplier", "customer": "customer"}.get(operation, payload.get("party_type", "customer")), "custom": custom})
        exists = await db.scalar(select(ERPParty.id).where(ERPParty.organization_id == actor.organization_id, ERPParty.code == data.code))
        if exists: raise HTTPException(status_code=409, detail={"code": "erp_master_request_stale_duplicate", "field": "code"})
        entity = ERPParty(organization_id=actor.organization_id, **data.model_dump())
    elif operation in {"item", "purchase_item", "sales_catalog_item", "item_sku"}:
        data = ItemInput.model_validate({**payload, "custom": custom})
        exists = await db.scalar(select(ERPItem.id).where(ERPItem.organization_id == actor.organization_id, ERPItem.code == data.code))
        if exists: raise HTTPException(status_code=409, detail={"code": "erp_master_request_stale_duplicate", "field": "code"})
        entity = ERPItem(organization_id=actor.organization_id, **data.model_dump())
    elif operation == "warehouse":
        data = WarehouseInput.model_validate(payload)
        exists = await db.scalar(select(ERPWarehouse.id).where(ERPWarehouse.organization_id == actor.organization_id, ERPWarehouse.code == data.code))
        if exists: raise HTTPException(status_code=409, detail={"code": "erp_master_request_stale_duplicate", "field": "code"})
        entity = ERPWarehouse(organization_id=actor.organization_id, **data.model_dump())
    elif operation == "chart_account":
        data = AccountInput.model_validate(payload)
        exists = await db.scalar(select(ERPAccount.id).where(ERPAccount.organization_id == actor.organization_id, ERPAccount.code == data.code))
        if exists: raise HTTPException(status_code=409, detail={"code": "erp_master_request_stale_duplicate", "field": "code"})
        entity = ERPAccount(organization_id=actor.organization_id, **data.model_dump())
    elif operation == "uom":
        data = UomRequestInput.model_validate(payload)
        exists = await db.scalar(select(ERPUnitOfMeasure.id).where(ERPUnitOfMeasure.organization_id == actor.organization_id, ERPUnitOfMeasure.code == data.code))
        if exists: raise HTTPException(status_code=409, detail={"code": "erp_master_request_stale_duplicate", "field": "code"})
        entity = ERPUnitOfMeasure(organization_id=actor.organization_id, **data.model_dump())
    elif operation == "reorder_rule":
        data = ReorderRuleRequestInput.model_validate(payload)
        entity = ERPReorderRule(organization_id=actor.organization_id, **data.model_dump())
    elif operation == "supplier_price_list":
        data = PriceListRequestInput.model_validate(payload)
        exists = await db.scalar(select(ERPPriceList.id).where(ERPPriceList.organization_id == actor.organization_id, ERPPriceList.code == data.code))
        if exists: raise HTTPException(status_code=409, detail={"code": "erp_master_request_stale_duplicate", "field": "code"})
        entity = ERPPriceList(organization_id=actor.organization_id, code=data.code, name=data.name, party_id=data.party_id, currency=data.currency.upper(), valid_from=data.valid_from, valid_to=data.valid_to)
    elif operation == "customer_discount_tier":
        data = DiscountTierRequestInput.model_validate(payload)
        exists = await db.scalar(select(ERPDiscountTier.id).where(ERPDiscountTier.organization_id == actor.organization_id, ERPDiscountTier.code == data.code))
        if exists: raise HTTPException(status_code=409, detail={"code": "erp_master_request_stale_duplicate", "field": "code"})
        entity = ERPDiscountTier(organization_id=actor.organization_id, **data.model_dump())
    elif operation == "cost_center":
        data = CostCenterRequestInput.model_validate(payload)
        exists = await db.scalar(select(ERPCostCenter.id).where(ERPCostCenter.organization_id == actor.organization_id, ERPCostCenter.code == data.code))
        if exists: raise HTTPException(status_code=409, detail={"code": "erp_master_request_stale_duplicate", "field": "code"})
        entity = ERPCostCenter(organization_id=actor.organization_id, **data.model_dump())
    elif operation == "tax_template":
        data = TaxTemplateRequestInput.model_validate(payload)
        exists = await db.scalar(select(ERPTaxTemplate.id).where(ERPTaxTemplate.organization_id == actor.organization_id, ERPTaxTemplate.code == data.code))
        if exists: raise HTTPException(status_code=409, detail={"code": "erp_master_request_stale_duplicate", "field": "code"})
        entity = ERPTaxTemplate(organization_id=actor.organization_id, code=data.code, name=data.name, direction=data.direction)
    else:
        raise HTTPException(status_code=422, detail={"code": "erp_invalid_master_request_operation"})
    db.add(entity); await db.flush()
    if operation == "supplier_price_list":
        data = PriceListRequestInput.model_validate(payload)
        db.add(ERPPriceListEntry(price_list_id=entity.id, item_id=data.item_id, minimum_quantity=data.minimum_quantity, rate=data.rate))
    if operation == "tax_template":
        for rate in TaxTemplateRequestInput.model_validate(payload).rates:
            db.add(ERPTaxTemplateRate(tax_template_id=entity.id, name=str(rate.get("name") or "VAT"), rate=Decimal(str(rate.get("rate", 0))), account_id=rate.get("account_id")))
    request.materialized_entity_type, request.materialized_entity_id = operation, entity.id
    return operation, entity.id


@router.get("/master-requests/{operation}")
async def list_master_requests(operation: MASTER_OPERATION_LITERAL, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, operation, "view")
    rows = (await db.execute(select(ERPMasterRequest).where(ERPMasterRequest.organization_id == actor.organization_id, ERPMasterRequest.operation == operation).order_by(ERPMasterRequest.created_at.desc()))).scalars().all()
    scopes = await capability_scopes(db, actor, operation, "view")
    rows = [row for row in rows if all(all(scope_allows(scopes, {dimension: value}) for value in values) for dimension, values in (row.scope or {}).items())]
    return [{"id": row.id, "operation": row.operation, "definition_version": row.definition_version, "workflow_state": row.workflow_state, "status": row.workflow_state, "payload": row.payload, "payload_json": row.payload, "scope": row.scope, "version": row.version, "requested_by": row.requested_by_account_id, "approved_by": row.approved_by_account_id, "approved_at": row.approved_at, "materialized_entity_type": row.materialized_entity_type, "materialized_entity_id": row.materialized_entity_id, "created_at": row.created_at} for row in rows]


@router.post("/master-requests/{operation}", status_code=status.HTTP_201_CREATED)
async def create_master_request(operation: MASTER_OPERATION_LITERAL, data: MasterRequestInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, operation, "create")
    definition = await ensure_definition(db, actor.organization_id, operation, actor.account_id)
    form_values = validate_form_values(definition.fields or [], data.custom, "master")
    # Validate shape on creation, but do not materialize the ERP master until approved.
    payload = {**_validate_master_payload(operation, data.payload), "custom": form_values}
    request_scope = await _validated_scope(db, actor.organization_id, data.scope)
    scopes = await capability_scopes(db, actor, operation, "create")
    if any(not scope_allows(scopes, {dimension: value}) for dimension, values in request_scope.items() for value in values): raise HTTPException(status_code=403, detail={"code": "erp_scope_denied"})
    request = ERPMasterRequest(organization_id=actor.organization_id, operation=operation, definition_version=definition.version,
                               payload=payload, workflow_state=(definition.workflow or {}).get("initial_state", "draft"),
                               scope=request_scope, requested_by_account_id=actor.account_id)
    db.add(request); await db.flush()
    await record_workflow_transition(db, actor, entity_type="master_request", entity_id=request.id, operation=operation, definition_version=definition.version, from_state=None, to_state=request.workflow_state)
    await db.commit()
    return {"id": request.id, "operation": request.operation, "definition_version": request.definition_version, "workflow_state": request.workflow_state, "status": request.workflow_state, "payload": request.payload, "payload_json": request.payload, "requested_by": request.requested_by_account_id, "version": request.version}


@router.post("/master-requests/by-id/{request_id}/transition")
async def transition_master_request(request_id: int, data: WorkflowTransitionInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    request = await db.scalar(select(ERPMasterRequest).where(ERPMasterRequest.id == request_id, ERPMasterRequest.organization_id == actor.organization_id))
    if not request: raise HTTPException(status_code=404, detail="ERP master request not found")
    if data.version != request.version: raise HTTPException(status_code=409, detail={"code": "erp_version_conflict", "current_version": request.version})
    await require_capability(db, actor, request.operation, "approve" if data.to_state in {"approved", "rejected"} else "edit")
    scopes = await capability_scopes(db, actor, request.operation, "approve" if data.to_state in {"approved", "rejected"} else "edit")
    if any(not scope_allows(scopes, {dimension: value}) for dimension, values in (request.scope or {}).items() for value in values): raise HTTPException(status_code=403, detail={"code": "erp_scope_denied"})
    definition = await db.scalar(select(ERPFormDefinition).where(ERPFormDefinition.organization_id == actor.organization_id, ERPFormDefinition.operation == request.operation, ERPFormDefinition.version == request.definition_version))
    if not definition: raise HTTPException(status_code=409, detail={"code": "erp_definition_version_missing"})
    await _workflow_transition_allowed(db, actor, definition.workflow or {}, request.workflow_state, data.to_state, request.requested_by_account_id)
    before = request.workflow_state
    request.workflow_state, request.version = data.to_state, request.version + 1
    if data.to_state == "approved":
        await _materialize_master_request(db, actor, request)
        request.approved_by_account_id, request.approved_at = actor.account_id, datetime.now(timezone.utc)
    await record_workflow_transition(db, actor, entity_type="master_request", entity_id=request.id, operation=request.operation, definition_version=request.definition_version, from_state=before, to_state=data.to_state, comment=data.comment)
    await db.commit()
    return {"id": request.id, "workflow_state": request.workflow_state, "status": request.workflow_state, "version": request.version, "requested_by": request.requested_by_account_id, "approved_by": request.approved_by_account_id, "approved_at": request.approved_at, "payload_json": request.payload, "materialized_entity_type": request.materialized_entity_type, "materialized_entity_id": request.materialized_entity_id}


@router.put("/admin/modules")
async def update_modules(data: ModulesInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "erp_settings", "administer")
    unknown = set(data.modules).difference(ERP_MODULES)
    if unknown:
        raise HTTPException(status_code=422, detail={"code": "erp_unknown_module", "modules": sorted(unknown)})
    organization = await _organization(db, actor)
    for module in (set(data.modules) & set({"selling", "buying", "stock", "manufacturing", "assets_maintenance"})):
        if data.modules.get(module):
            acceptance = (organization.settings or {}).get("phase5_payroll_acceptance") or {}
            if not acceptance.get("reconciled_period_id"):
                raise HTTPException(status_code=409, detail={"code": "erp_phase5_payroll_acceptance_required", "module": module})
    for name in ERP_MODULES:
        row = await db.scalar(select(ERPModuleConfig).where(ERPModuleConfig.organization_id == organization.id, ERPModuleConfig.module == name).with_for_update())
        if row is None:
            row = ERPModuleConfig(organization_id=organization.id, module=name)
            db.add(row)
        row.enabled = bool(data.modules.get(name, False))
        row.updated_by_account_id = actor.account_id
    settings = {**(organization.settings or {}), MODULE_SETTINGS_KEY: {name: bool(data.modules.get(name, False)) for name in ERP_MODULES}}
    organization.settings = settings
    await bootstrap_organization(db, organization.id)
    await record_change(db, actor=actor, topic="erp", aggregate_type="erp_module_settings", aggregate_id=organization.id, operation="updated", after={MODULE_SETTINGS_KEY: settings[MODULE_SETTINGS_KEY]})
    await db.commit()
    return {"modules": module_settings(settings), "notice": "Visibility changes do not disable APIs, integrations, or existing automations."}


@router.get("/admin/phase5/acceptance")
async def get_phase5_acceptance(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "erp_settings", "view")
    return await phase5_gate_status(db, actor.organization_id)


@router.put("/admin/phase5/acceptance")
async def accept_phase5(data: Phase5AcceptanceInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "erp_settings", "administer")
    run = await db.scalar(select(PayrollRun).where(PayrollRun.id == data.reconciled_period_id, PayrollRun.organization_id == actor.organization_id))
    if not run or run.payment_status not in {"settled", "paid"}:
        raise HTTPException(status_code=409, detail={"code": "erp_phase5_payroll_period_not_reconciled", "run_id": data.reconciled_period_id})
    organization = await _organization(db, actor)
    acceptance = {"reconciled_period_id": run.id, "reconciled_at": data.reconciled_at.isoformat(), "evidence_ref": data.evidence_ref, "accepted_by_account_id": actor.account_id}
    organization.settings = {**(organization.settings or {}), "phase5_payroll_acceptance": acceptance}
    await record_change(db, actor=actor, topic="erp", aggregate_type="erp_phase5_acceptance", aggregate_id=organization.id, operation="accepted", after=acceptance)
    await db.commit()
    return {"accepted": True, **acceptance}


@router.get("/admin/roles")
async def list_roles(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "erp_roles", "administer")
    roles = (await db.execute(select(ERPAccessRole).where(ERPAccessRole.organization_id == actor.organization_id).order_by(ERPAccessRole.name))).scalars().all()
    return [await _role_out(db, role) for role in roles]


@router.post("/admin/roles", status_code=status.HTTP_201_CREATED)
async def create_role(data: AccessRoleInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "erp_roles", "administer")
    catalog_resources = set(operation_catalog()["operations"]) | {"*", "accounts", "parties", "items", "warehouses", "stock", "payroll", "erp_settings", "erp_roles", "erp_custom_fields", "erp_approval_rules", "erp_imports", "erp_dashboard"}
    if any((cap.action not in VALID_ACTIONS and cap.action != "*") or cap.resource not in catalog_resources for cap in data.capabilities):
        raise HTTPException(status_code=422, detail="Unknown capability action")
    role = ERPAccessRole(organization_id=actor.organization_id, name=data.name, code=data.code, description=data.description)
    db.add(role)
    await db.flush()
    db.add_all([ERPCapability(access_role_id=role.id, resource=cap.resource, action=cap.action) for cap in data.capabilities])
    await record_change(db, actor=actor, topic="erp", aggregate_type="erp_access_role", aggregate_id=role.id, operation="created", after={"code": role.code})
    await db.commit()
    return await _role_out(db, role)


@router.patch("/admin/roles/{role_id}")
async def update_role(role_id: int, data: RolePatchInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "erp_roles", "administer")
    role = await db.scalar(select(ERPAccessRole).where(ERPAccessRole.id == role_id, ERPAccessRole.organization_id == actor.organization_id))
    if not role: raise HTTPException(status_code=404, detail="ERP role not found")
    if role.is_system: raise HTTPException(status_code=409, detail={"code": "erp_system_role_immutable"})
    if data.name is not None: role.name = data.name
    if data.description is not None: role.description = data.description
    if data.capabilities is not None:
        catalog_resources = set(operation_catalog()["operations"]) | {"*", "accounts", "parties", "items", "warehouses", "stock", "payroll", "erp_settings", "erp_roles", "erp_custom_fields", "erp_approval_rules", "erp_imports", "erp_dashboard"}
        if any((cap.action not in VALID_ACTIONS and cap.action != "*") or cap.resource not in catalog_resources for cap in data.capabilities): raise HTTPException(status_code=422, detail="Unknown capability")
        old = (await db.execute(select(ERPCapability).where(ERPCapability.access_role_id == role.id))).scalars().all()
        for capability in old: await db.delete(capability)
        db.add_all([ERPCapability(access_role_id=role.id, resource=cap.resource, action=cap.action) for cap in data.capabilities])
    await db.commit(); return await _role_out(db, role)


@router.post("/admin/roles/{role_id}/clone", status_code=status.HTTP_201_CREATED)
async def clone_role(role_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "erp_roles", "administer")
    source = await db.scalar(select(ERPAccessRole).where(ERPAccessRole.id == role_id, ERPAccessRole.organization_id == actor.organization_id))
    if not source: raise HTTPException(status_code=404, detail="ERP role not found")
    copy = ERPAccessRole(organization_id=actor.organization_id, name=f"{source.name} copy", code=f"{source.code}-{int(datetime.now(timezone.utc).timestamp())}", description=source.description)
    db.add(copy); await db.flush()
    capabilities = (await db.execute(select(ERPCapability).where(ERPCapability.access_role_id == source.id))).scalars().all()
    db.add_all([ERPCapability(access_role_id=copy.id, resource=cap.resource, action=cap.action) for cap in capabilities])
    await db.commit(); return await _role_out(db, copy)


@router.post("/admin/roles/{role_id}/deactivate")
async def deactivate_role(role_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "erp_roles", "administer")
    role = await db.scalar(select(ERPAccessRole).where(ERPAccessRole.id == role_id, ERPAccessRole.organization_id == actor.organization_id))
    if not role: raise HTTPException(status_code=404, detail="ERP role not found")
    if role.is_system: raise HTTPException(status_code=409, detail={"code": "erp_system_role_immutable"})
    active_definitions = (await db.execute(select(ERPFormDefinition).where(ERPFormDefinition.organization_id == actor.organization_id, ERPFormDefinition.status == "published"))).scalars().all()
    if any(role_id in set(sum((transition.get("role_ids") or [] for transition in (definition.workflow or {}).get("transitions", [])), [])) for definition in active_definitions):
        raise HTTPException(status_code=409, detail={"code": "erp_role_used_by_published_workflow"})
    role.is_active = False; await db.commit(); return await _role_out(db, role)


@router.post("/admin/roles/{role_id}/accounts", status_code=status.HTTP_201_CREATED)
async def assign_role(role_id: int, data: AccountRoleInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "erp_roles", "administer")
    role = await db.scalar(select(ERPAccessRole).where(ERPAccessRole.id == role_id, ERPAccessRole.organization_id == actor.organization_id))
    if not role:
        raise HTTPException(status_code=404, detail="ERP role not found")
    account = await db.scalar(select(UserAccount).where(UserAccount.id == data.account_id, UserAccount.organization_id == actor.organization_id))
    if not account: raise HTTPException(status_code=422, detail={"code": "erp_invalid_role_account"})
    assignment = ERPAccountRole(account_id=data.account_id, access_role_id=role.id, scope=await _validated_scope(db, actor.organization_id, data.scope))
    db.add(assignment)
    await db.commit()
    return {"id": assignment.id, "role_id": role.id, "account_id": assignment.account_id, "scope": assignment.scope}


@router.delete("/admin/roles/{role_id}/accounts/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unassign_account_role(role_id: int, assignment_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "erp_roles", "administer")
    assignment = await db.scalar(select(ERPAccountRole).join(ERPAccessRole).where(ERPAccountRole.id == assignment_id, ERPAccountRole.access_role_id == role_id, ERPAccessRole.organization_id == actor.organization_id))
    if not assignment: raise HTTPException(status_code=404, detail="ERP role assignment not found")
    await db.delete(assignment); await db.commit()


@router.post("/admin/roles/{role_id}/teams", status_code=status.HTTP_201_CREATED)
async def assign_team_role(role_id: int, data: TeamRoleInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "erp_roles", "administer")
    role = await db.scalar(select(ERPAccessRole).where(ERPAccessRole.id == role_id, ERPAccessRole.organization_id == actor.organization_id))
    team = await db.scalar(select(Team).where(Team.id == data.team_id, Team.organization_id == actor.organization_id))
    if not role or not team: raise HTTPException(status_code=404, detail="ERP role or team not found")
    assignment = ERPTeamRole(team_id=team.id, access_role_id=role.id, scope=await _validated_scope(db, actor.organization_id, data.scope))
    db.add(assignment); await db.commit()
    return {"id": assignment.id, "role_id": role.id, "team_id": team.id, "scope": assignment.scope}


@router.delete("/admin/roles/{role_id}/teams/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unassign_team_role(role_id: int, assignment_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "erp_roles", "administer")
    assignment = await db.scalar(select(ERPTeamRole).join(ERPAccessRole).where(ERPTeamRole.id == assignment_id, ERPTeamRole.access_role_id == role_id, ERPAccessRole.organization_id == actor.organization_id))
    if not assignment: raise HTTPException(status_code=404, detail="ERP team role assignment not found")
    await db.delete(assignment); await db.commit()


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
    return [{"id": row.id, "code": row.code, "name": row.name, "account_type": row.account_type, "classification": row.classification, "purpose": row.purpose, "currency": row.currency, "parent_id": row.parent_id, "is_group": row.is_group, "is_active": row.is_active} for row in rows]


@router.post("/accounting/accounts", status_code=status.HTTP_201_CREATED)
async def create_account(data: AccountInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "accounts", "create")
    values = data.model_dump()
    values["currency"] = values["currency"].upper()
    values["classification"] = values["classification"] or (values["account_type"] if values["account_type"] in {"asset", "liability", "equity", "income", "expense"} else "asset")
    if values["parent_id"]:
        parent = await db.scalar(select(ERPAccount).where(ERPAccount.id == values["parent_id"], ERPAccount.organization_id == actor.organization_id))
        if not parent:
            raise HTTPException(status_code=422, detail={"code": "erp_account_parent_invalid"})
        if not parent.is_group or parent.id == values.get("id"):
            raise HTTPException(status_code=422, detail={"code": "erp_account_parent_must_be_group"})
    account = ERPAccount(organization_id=actor.organization_id, **values)
    db.add(account)
    await db.commit()
    return {"id": account.id, "code": account.code, "name": account.name, "account_type": account.account_type, "classification": account.classification, "purpose": account.purpose, "currency": account.currency, "is_group": account.is_group, "is_active": account.is_active}


@router.get("/accounting/settings")
async def get_accounting_settings(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "accounts", "view")
    settings = await db.scalar(select(ERPAccountingSettings).where(ERPAccountingSettings.organization_id == actor.organization_id))
    if settings is None:
        await bootstrap_organization(db, actor.organization_id)
        settings = await db.scalar(select(ERPAccountingSettings).where(ERPAccountingSettings.organization_id == actor.organization_id))
    return {"id": settings.id if settings else None, "base_currency": settings.base_currency if settings else "MNT", "fiscal_year_start_month": settings.fiscal_year_start_month if settings else 1, "default_cost_center_id": settings.default_cost_center_id if settings else None, "default_bank_account_id": settings.default_bank_account_id if settings else None, "conversion_date": settings.conversion_date.isoformat() if settings and settings.conversion_date else None}


@router.put("/accounting/settings")
async def update_accounting_settings(data: AccountingSettingsInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "accounts", "edit")
    settings = await db.scalar(select(ERPAccountingSettings).where(ERPAccountingSettings.organization_id == actor.organization_id).with_for_update())
    if settings is None:
        settings = ERPAccountingSettings(organization_id=actor.organization_id)
        db.add(settings)
    values = data.model_dump()
    values["base_currency"] = values["base_currency"].upper()
    if values["default_cost_center_id"] is not None and not await db.scalar(select(ERPCostCenter.id).where(ERPCostCenter.id == values["default_cost_center_id"], ERPCostCenter.organization_id == actor.organization_id, ERPCostCenter.is_active.is_(True))):
        raise HTTPException(status_code=422, detail={"code": "erp_cost_center_invalid"})
    if values["default_bank_account_id"] is not None and not await db.scalar(select(ERPAccount.id).where(ERPAccount.id == values["default_bank_account_id"], ERPAccount.organization_id == actor.organization_id, ERPAccount.is_active.is_(True), ERPAccount.is_group.is_(False), ERPAccount.purpose.in_(("bank", "cash")))):
        raise HTTPException(status_code=422, detail={"code": "erp_bank_account_invalid"})
    for key, value in values.items(): setattr(settings, key, value)
    await db.commit(); await db.refresh(settings)
    return {"id": settings.id, **values}


@router.get("/documents/{document_type}")
async def list_documents(
    document_type: str,
    document_status: str | None = Query(default=None, alias="status"),
    view: Literal["all", "drafts", "pending_approval", "approved", "archived"] = "all",
    search: str | None = None,
    party_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor),
):
    if document_type not in DOCUMENT_TYPES:
        raise HTTPException(status_code=404, detail="Unknown ERP document type")
    await require_capability(db, actor, document_type, "view")
    statement = select(ERPDocument).where(ERPDocument.organization_id == actor.organization_id, ERPDocument.document_type == document_type)
    if document_status:
        statement = statement.where(ERPDocument.status == document_status)
    if party_id is not None:
        statement = statement.where(ERPDocument.party_id == party_id)
    if date_from is not None:
        statement = statement.where(ERPDocument.posting_date >= date_from)
    if date_to is not None:
        statement = statement.where(ERPDocument.posting_date <= date_to)
    if view == "archived":
        statement = statement.where(ERPDocument.archived_at.is_not(None))
    else:
        statement = statement.where(ERPDocument.archived_at.is_(None))
    docs = (await db.execute(statement.order_by(ERPDocument.posting_date.desc(), ERPDocument.id.desc()))).scalars().all()
    scopes = await capability_scopes(db, actor, document_type, "view")
    visible = []
    for doc in docs:
        lines = await _document_lines(db, doc.id)
        if search and search.casefold() not in f"{doc.number} {(doc.payload or {}).get('title', '')}".casefold():
            continue
        if view == "drafts" and doc.workflow_state != "draft":
            continue
        if view == "pending_approval" and (doc.workflow_state in {"draft", "approved", "rejected", "cancelled"} or doc.status in {"submitted", "cancelled"}):
            continue
        if view == "approved" and doc.workflow_state != "approved" and doc.status not in {"approved", "submitted"}:
            continue
        if scope_allows(scopes, {"project_ids": doc.project_id, "branch_codes": (doc.payload or {}).get("branch_code")}) and all(scope_allows(scopes, {"warehouse_ids": line.warehouse_id}) for line in lines):
            visible.append(document_out(doc, lines))
    return visible


@router.post("/documents/{document_type}", status_code=status.HTTP_201_CREATED)
async def create_document(document_type: str, data: DocumentInput, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    if document_type not in DOCUMENT_TYPES:
        raise HTTPException(status_code=404, detail="Unknown ERP document type")
    if document_type in {"salary_structure", "payroll_run", "salary_slip"}:
        raise HTTPException(status_code=410, detail={"code": "payroll_use_dedicated_api", "path": "/v1/erp/payroll"})
    await require_phase5_gate(db, actor.organization_id, DOCUMENT_MODULES.get(document_type, ""))
    await require_capability(db, actor, document_type, "create")
    await _assert_document_scope(db, actor, document_type, "create", project_id=data.project_id, branch_code=data.payload.get("branch_code"), warehouse_ids=[line.warehouse_id for line in data.lines])
    prior = await _idempotent_response(db, actor, f"erp.document.{document_type}.create", idempotency_key, data.model_dump(mode="json"))
    if prior:
        return prior
    definition = await ensure_definition(db, actor.organization_id, document_type, actor.account_id)
    custom = validate_form_values(definition.fields or [], data.custom, "header")
    document = ERPDocument(
        organization_id=actor.organization_id, document_type=document_type, number=await next_number(db, actor.organization_id, document_type),
        party_id=data.party_id, project_id=data.project_id, source_document_id=data.source_document_id, currency=data.currency.upper(),
        exchange_rate=data.exchange_rate, posting_date=data.posting_date, due_date=data.due_date, payload=data.payload, custom=custom,
        definition_version=definition.version, workflow_state=(definition.workflow or {}).get("initial_state", "draft"),
    )
    db.add(document)
    await db.flush()
    for line in data.lines:
        line.data = validate_form_values(definition.fields or [], line.data, "line")
    await _write_document_lines(db, document, data.lines)
    await db.flush()
    await record_workflow_transition(db, actor, entity_type="document", entity_id=document.id, operation=document_type, definition_version=document.definition_version, from_state=None, to_state=document.workflow_state)
    result = document_out(document, await _document_lines(db, document.id))
    await _save_idempotent(db, actor, f"erp.document.{document_type}.create", idempotency_key, data.model_dump(mode="json"), result)
    await record_change(db, actor=actor, topic="erp", aggregate_type=f"erp_{document_type}", aggregate_id=document.id, operation="created", version=document.version, after={"number": document.number, "status": document.status})
    await db.commit()
    return result


@router.get("/documents/by-id/{document_id}")
async def get_document(document_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    document = await _document(db, actor, document_id)
    await require_capability(db, actor, document.document_type, "view")
    lines = await _document_lines(db, document.id)
    await _assert_document_scope(db, actor, document.document_type, "view", project_id=document.project_id, branch_code=(document.payload or {}).get("branch_code"), warehouse_ids=[line.warehouse_id for line in lines])
    result = document_out(document, lines)
    definition = await db.scalar(select(ERPFormDefinition).where(ERPFormDefinition.organization_id == actor.organization_id, ERPFormDefinition.operation == document.document_type, ERPFormDefinition.version == document.definition_version))
    history = (await db.execute(select(ERPWorkflowTransition).where(ERPWorkflowTransition.organization_id == actor.organization_id, ERPWorkflowTransition.entity_type == "document", ERPWorkflowTransition.entity_id == document.id).order_by(ERPWorkflowTransition.created_at))).scalars().all()
    result["workflow"] = definition.workflow if definition else None
    result["history"] = [{"from_state": row.from_state, "to_state": row.to_state, "comment": row.comment, "actor_account_id": row.actor_account_id, "created_at": row.created_at} for row in history]
    return result


@router.get("/documents/by-id/{document_id}/source-allocations")
async def list_source_allocations(document_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    document = await _document(db, actor, document_id)
    await require_capability(db, actor, document.document_type, "view")
    rows = (await db.execute(select(ERPSourceLineAllocation).where(ERPSourceLineAllocation.organization_id == actor.organization_id, ERPSourceLineAllocation.target_document_id == document.id))).scalars().all()
    return [{"id": row.id, "source_document_id": row.source_document_id, "source_line_id": row.source_line_id, "target_line_id": row.target_line_id, "quantity": str(row.quantity), "created_at": row.created_at} for row in rows]


@router.post("/documents/by-id/{document_id}/transition")
async def transition_document(document_id: int, data: WorkflowTransitionInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    document = await _document(db, actor, document_id)
    if data.version != document.version: raise HTTPException(status_code=409, detail={"code": "erp_version_conflict", "current_version": document.version})
    action = "approve" if data.to_state in {"approved", "rejected"} else "cancel" if data.to_state == "cancelled" else "submit" if data.to_state == "submitted" else "edit"
    await require_capability(db, actor, document.document_type, action)
    scoped_lines = await _document_lines(db, document.id)
    await _assert_document_scope(db, actor, document.document_type, action, project_id=document.project_id, branch_code=(document.payload or {}).get("branch_code"), warehouse_ids=[line.warehouse_id for line in scoped_lines])
    definition = await db.scalar(select(ERPFormDefinition).where(ERPFormDefinition.organization_id == actor.organization_id, ERPFormDefinition.operation == document.document_type, ERPFormDefinition.version == document.definition_version))
    if not definition: raise HTTPException(status_code=409, detail={"code": "erp_definition_version_missing"})
    await _workflow_transition_allowed(db, actor, definition.workflow or {}, document.workflow_state, data.to_state, None)
    before = document.workflow_state
    document.workflow_state = data.to_state
    if data.to_state == "approved":
        if operation_catalog()["operations"][document.document_type]["posting_capable"]:
            if await approval_required(db, document) and action != "approve": raise HTTPException(status_code=409, detail={"code": "erp_approval_required"})
            await post_document(db, document, actor)
        else:
            document.status = "approved"; document.version += 1
    elif data.to_state == "cancelled":
        if document.status == "submitted": await cancel_document(db, document)
        else: document.status, document.version = "cancelled", document.version + 1
    else:
        document.version += 1
    await record_workflow_transition(db, actor, entity_type="document", entity_id=document.id, operation=document.document_type, definition_version=document.definition_version, from_state=before, to_state=data.to_state, comment=data.comment)
    await db.commit()
    return document_out(document, await _document_lines(db, document.id))


@router.patch("/documents/by-id/{document_id}")
async def update_document(document_id: int, data: DocumentPatchInput, if_match: int | None = Header(default=None, alias="If-Match"), db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    document = await _document(db, actor, document_id)
    await require_capability(db, actor, document.document_type, "edit")
    current_lines = await _document_lines(db, document.id)
    await _assert_document_scope(db, actor, document.document_type, "edit", project_id=document.project_id, branch_code=(document.payload or {}).get("branch_code"), warehouse_ids=[line.warehouse_id for line in current_lines])
    if document.status != "draft":
        raise HTTPException(status_code=409, detail={"code": "erp_submitted_document_immutable"})
    if if_match is None or if_match != document.version:
        raise HTTPException(status_code=409, detail={"code": "erp_version_conflict", "current_version": document.version})
    definition = await db.scalar(select(ERPFormDefinition).where(ERPFormDefinition.organization_id == actor.organization_id, ERPFormDefinition.operation == document.document_type, ERPFormDefinition.version == document.definition_version))
    if not definition: raise HTTPException(status_code=409, detail={"code": "erp_definition_version_missing"})
    values = data.model_dump(exclude_unset=True)
    if "custom" in values:
        document.custom = validate_form_values(definition.fields or [], values.pop("custom"), "header")
    lines = values.pop("lines", None)
    if lines is not None:
        await _assert_document_scope(db, actor, document.document_type, "edit", project_id=values.get("project_id", document.project_id), branch_code=(values.get("payload") or document.payload or {}).get("branch_code"), warehouse_ids=[line.warehouse_id for line in lines])
    for name, value in values.items():
        setattr(document, name, value)
    if lines is not None:
        for line in lines:
            line.data = validate_form_values(definition.fields or [], line.data, "line")
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
    # Approval of a posting-capable document is a transactional finalization:
    # the document cannot become approved unless its immutable ledger/stock
    # movements are created successfully in this same transaction.
    posting_capable = document.document_type in set(operation_catalog()["operations"])
    if posting_capable and document.document_type in {"journal_entry", "payment_entry", "sales_invoice", "sales_credit_note", "purchase_invoice", "purchase_debit_note", "delivery", "purchase_receipt", "stock_entry", "stock_reconciliation", "asset"}:
        await post_document(db, document, actor)
    document.status = "approved" if document.status == "draft" else document.status
    document.workflow_state = "approved"
    if document.status == "approved":
        document.version += 1
    await record_change(db, actor=actor, topic="erp", aggregate_type=f"erp_{document.document_type}", aggregate_id=document.id, operation="approved", version=document.version, after={"status": document.status})
    await db.commit()
    return document_out(document)


@router.post("/documents/by-id/{document_id}/archive")
async def archive_document(document_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    document = await _document(db, actor, document_id)
    await require_capability(db, actor, document.document_type, "archive")
    if document.archived_at:
        return document_out(document)
    document.archived_at = datetime.now(timezone.utc)
    document.archived_by_account_id = actor.account_id
    document.version += 1
    await record_change(db, actor=actor, topic="erp", aggregate_type=f"erp_{document.document_type}", aggregate_id=document.id, operation="archived", version=document.version, after={"status": document.status})
    await db.commit()
    return document_out(document)


@router.post("/documents/by-id/{document_id}/restore")
async def restore_document(document_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    document = await _document(db, actor, document_id)
    await require_capability(db, actor, document.document_type, "archive")
    if not document.archived_at:
        return document_out(document)
    document.archived_at = None
    document.archived_by_account_id = None
    document.version += 1
    await record_change(db, actor=actor, topic="erp", aggregate_type=f"erp_{document.document_type}", aggregate_id=document.id, operation="restored", version=document.version, after={"status": document.status})
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
    document.workflow_state = "approved"
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
    document.workflow_state = "cancelled"
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
        description=line.description, quantity=line.quantity, rate=line.rate, amount=line.amount, discount_percent=line.discount_percent, discount_amount=line.discount_amount, tax_rate=line.tax_rate, tax_amount=line.tax_amount,
        position=line.position, data=line.data) for line in source_lines])
    await db.commit()
    return document_out(amendment, await _document_lines(db, amendment.id))


@router.post("/documents/by-id/{document_id}/convert/{target_type}", status_code=status.HTTP_201_CREATED)
async def convert_document(document_id: int, target_type: str, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    source = await _document(db, actor, document_id)
    if target_type not in CONVERSION_TARGETS.get(source.document_type, set()):
        raise HTTPException(status_code=422, detail={"code": "erp_invalid_document_conversion", "source": source.document_type, "target": target_type})
    await require_capability(db, actor, target_type, "create")
    if source.status not in {"submitted", "approved"}:
        raise HTTPException(status_code=409, detail={"code": "erp_source_document_not_submitted"})
    await require_phase5_gate(db, actor.organization_id, DOCUMENT_MODULES.get(target_type, ""))
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
        description=line.description, quantity=line.quantity, rate=line.rate, amount=line.amount, discount_percent=line.discount_percent, discount_amount=line.discount_amount, tax_rate=line.tax_rate,
        tax_amount=line.tax_amount, position=line.position, data={**(line.data or {}), "source_line_id": line.id},
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


@router.post("/manufacturing/boms/{document_id}/snapshots", status_code=status.HTTP_201_CREATED)
async def create_bom_snapshot(document_id: int, data: BOMSnapshotInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "bill_of_materials", "approve")
    await require_phase5_gate(db, actor.organization_id, "manufacturing")
    bom = await _document(db, actor, document_id)
    if bom.document_type != "bill_of_materials" or bom.workflow_state != "approved" or bom.status not in {"approved", "submitted"}:
        raise HTTPException(status_code=409, detail={"code": "erp_bom_must_be_approved"})
    item = await db.scalar(select(ERPItem).where(ERPItem.id == data.output_item_id, ERPItem.organization_id == actor.organization_id, ERPItem.is_active.is_(True)))
    if not item:
        raise HTTPException(status_code=422, detail={"code": "erp_invalid_bom_output_item"})
    for line in data.lines:
        if not isinstance(line, dict) or int(line.get("item_id", 0)) <= 0 or Decimal(str(line.get("quantity", 0))) <= 0:
            raise HTTPException(status_code=422, detail={"code": "erp_invalid_bom_component"})
        component = await db.scalar(select(ERPItem.id).where(ERPItem.id == int(line["item_id"]), ERPItem.organization_id == actor.organization_id, ERPItem.is_active.is_(True)))
        if not component:
            raise HTTPException(status_code=422, detail={"code": "erp_invalid_bom_component"})
    latest = await db.scalar(select(func.max(ERPBOMSnapshot.version)).where(ERPBOMSnapshot.organization_id == actor.organization_id, ERPBOMSnapshot.bom_document_id == bom.id))
    snapshot = ERPBOMSnapshot(organization_id=actor.organization_id, bom_document_id=bom.id, version=int(latest or 0) + 1, output_item_id=item.id, output_quantity=data.output_quantity, lines=data.lines, operations=data.operations)
    db.add(snapshot)
    await db.commit()
    return {"id": snapshot.id, "bom_document_id": snapshot.bom_document_id, "version": snapshot.version, "status": snapshot.status, "output_item_id": snapshot.output_item_id, "output_quantity": str(snapshot.output_quantity), "lines": snapshot.lines, "operations": snapshot.operations}


@router.get("/manufacturing/boms/{document_id}/snapshots")
async def list_bom_snapshots(document_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "bill_of_materials", "view")
    rows = (await db.execute(select(ERPBOMSnapshot).where(ERPBOMSnapshot.organization_id == actor.organization_id, ERPBOMSnapshot.bom_document_id == document_id).order_by(ERPBOMSnapshot.version.desc()))).scalars().all()
    return [{"id": row.id, "version": row.version, "status": row.status, "output_item_id": row.output_item_id, "output_quantity": str(row.output_quantity), "lines": row.lines, "operations": row.operations} for row in rows]


@router.post("/manufacturing/work-orders/{document_id}/complete")
async def complete_work_order(document_id: int, data: WorkOrderCompletionInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "work_order", "post")
    await require_phase5_gate(db, actor.organization_id, "manufacturing")
    work_order = await _document(db, actor, document_id)
    if work_order.document_type != "work_order" or work_order.status not in {"submitted", "approved"}:
        raise HTTPException(status_code=409, detail={"code": "erp_work_order_not_approved"})
    snapshot_id = (work_order.payload or {}).get("bom_snapshot_id")
    snapshot = await db.scalar(select(ERPBOMSnapshot).where(ERPBOMSnapshot.id == int(snapshot_id or 0), ERPBOMSnapshot.organization_id == actor.organization_id, ERPBOMSnapshot.status == "approved"))
    item = await db.scalar(select(ERPItem).where(ERPItem.id == data.output_item_id, ERPItem.organization_id == actor.organization_id, ERPItem.is_active.is_(True)))
    warehouse = await db.scalar(select(ERPWarehouse).where(ERPWarehouse.id == data.output_warehouse_id, ERPWarehouse.organization_id == actor.organization_id, ERPWarehouse.is_active.is_(True)))
    if not snapshot or not item or not warehouse:
        raise HTTPException(status_code=422, detail={"code": "erp_work_order_completion_setup_invalid"})
    expected_material_value = Decimal("0")
    for component in snapshot.lines or []:
        component_item = await db.get(ERPItem, int(component.get("item_id", 0)))
        expected_material_value += Decimal(str(component.get("quantity", 0))) * Decimal(str(component_item.standard_cost if component_item else 0))
    actual_material_value = Decimal("0")
    issue_doc = None
    if data.actual_materials:
        issue_doc = ERPDocument(organization_id=actor.organization_id, document_type="stock_entry", number=await next_number(db, actor.organization_id, "stock_entry"), source_document_id=work_order.id, posting_date=date.today(), currency=work_order.currency, payload={"movement_type": "issue", "work_order_id": work_order.id, "bom_snapshot_id": snapshot.id})
        db.add(issue_doc); await db.flush()
        for position, component in enumerate(data.actual_materials):
            component_item_id, component_warehouse_id = int(component.get("item_id", 0)), int(component.get("warehouse_id", 0))
            quantity = Decimal(str(component.get("quantity", 0)))
            component_item = await db.scalar(select(ERPItem).where(ERPItem.id == component_item_id, ERPItem.organization_id == actor.organization_id, ERPItem.is_active.is_(True)))
            component_warehouse = await db.scalar(select(ERPWarehouse).where(ERPWarehouse.id == component_warehouse_id, ERPWarehouse.organization_id == actor.organization_id, ERPWarehouse.is_active.is_(True)))
            if not component_item or not component_warehouse or quantity <= 0:
                raise HTTPException(status_code=422, detail={"code": "erp_invalid_material_issue"})
            rate = Decimal(str(component_item.standard_cost or 0)); actual_material_value += quantity * rate
            db.add(ERPDocumentLine(document_id=issue_doc.id, item_id=component_item.id, warehouse_id=component_warehouse.id, description="Material issue", quantity=quantity, rate=rate, amount=as_money(quantity * rate), position=position, data={"bom_snapshot_id": snapshot.id}))
        await db.flush(); await post_document(db, issue_doc, actor)
    receipt = ERPDocument(organization_id=actor.organization_id, document_type="stock_entry", number=await next_number(db, actor.organization_id, "stock_entry"), source_document_id=work_order.id, posting_date=date.today(), currency=work_order.currency, payload={"movement_type": "receipt", "work_order_id": work_order.id, "bom_snapshot_id": snapshot.id})
    db.add(receipt); await db.flush()
    value = as_money(data.produced_quantity * Decimal(str(item.standard_cost or 0)))
    db.add(ERPDocumentLine(document_id=receipt.id, item_id=item.id, warehouse_id=warehouse.id, description="Finished goods receipt", quantity=data.produced_quantity, rate=item.standard_cost, amount=value, data={"bom_snapshot_id": snapshot.id}, position=0))
    await db.flush(); await post_document(db, receipt, actor)
    variance = as_money(actual_material_value - expected_material_value)
    work_order.status = "completed"; work_order.workflow_state = "approved"; work_order.version += 1
    await record_change(db, actor=actor, topic="erp", aggregate_type="erp_work_order", aggregate_id=work_order.id, operation="completed", after={"receipt_document_id": receipt.id, "material_issue_document_id": issue_doc.id if issue_doc else None, "variance": str(variance)})
    await db.commit()
    return {"work_order_id": work_order.id, "status": work_order.status, "material_issue_document_id": issue_doc.id if issue_doc else None, "receipt_document_id": receipt.id, "produced_quantity": str(data.produced_quantity), "variance": str(variance)}


@router.get("/stock/valuation-layers")
async def list_stock_valuation_layers(item_id: int | None = None, warehouse_id: int | None = None, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "stock", "view")
    statement = select(ERPStockValuationLayer).where(ERPStockValuationLayer.organization_id == actor.organization_id)
    if item_id is not None: statement = statement.where(ERPStockValuationLayer.item_id == item_id)
    if warehouse_id is not None: statement = statement.where(ERPStockValuationLayer.warehouse_id == warehouse_id)
    rows = (await db.execute(statement.order_by(ERPStockValuationLayer.created_at.desc()))).scalars().all()
    return [{"id": row.id, "document_id": row.document_id, "item_id": row.item_id, "warehouse_id": row.warehouse_id, "quantity": str(row.quantity), "remaining_quantity": str(row.remaining_quantity), "unit_cost": str(row.unit_cost), "value": str(row.value), "valuation_method": row.valuation_method} for row in rows]


@router.post("/assets/books", status_code=status.HTTP_201_CREATED)
async def create_asset_book(data: AssetBookInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "asset", "create")
    await require_phase5_gate(db, actor.organization_id, "assets_maintenance")
    if await db.scalar(select(ERPAssetBook.id).where(ERPAssetBook.organization_id == actor.organization_id, ERPAssetBook.code == data.code)):
        raise HTTPException(status_code=409, detail={"code": "erp_asset_book_exists"})
    book_values = data.model_dump(); book_values["currency"] = data.currency.upper()
    book = ERPAssetBook(organization_id=actor.organization_id, **book_values)
    db.add(book); await db.commit()
    return {"id": book.id, "code": book.code, "name": book.name, "currency": book.currency, "depreciation_method": book.depreciation_method, "useful_life_months": book.useful_life_months, "residual_value": str(book.residual_value), "is_active": book.is_active}


@router.get("/assets/books")
async def list_asset_books(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "asset", "view")
    rows = (await db.execute(select(ERPAssetBook).where(ERPAssetBook.organization_id == actor.organization_id).order_by(ERPAssetBook.code))).scalars().all()
    return [{"id": row.id, "code": row.code, "name": row.name, "currency": row.currency, "depreciation_method": row.depreciation_method, "useful_life_months": row.useful_life_months, "residual_value": str(row.residual_value), "is_active": row.is_active} for row in rows]


@router.post("/assets/depreciation-schedules", status_code=status.HTTP_201_CREATED)
async def generate_depreciation_schedule(data: DepreciationScheduleInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "asset", "create")
    await require_phase5_gate(db, actor.organization_id, "assets_maintenance")
    asset = await _document(db, actor, data.asset_document_id)
    book = await db.scalar(select(ERPAssetBook).where(ERPAssetBook.id == data.book_id, ERPAssetBook.organization_id == actor.organization_id, ERPAssetBook.is_active.is_(True)))
    if asset.document_type != "asset" or asset.status not in {"submitted", "approved"} or not book:
        raise HTTPException(status_code=422, detail={"code": "erp_invalid_asset_schedule_source"})
    depreciable = max(Decimal("0"), Decimal(str(asset.grand_total or 0)) - Decimal(str(book.residual_value or 0)))
    monthly = as_money(depreciable / Decimal(book.useful_life_months))
    rows = []
    for index in range(data.periods):
        period = data.start_date.replace(day=1) + timedelta(days=32 * index)
        period = period.replace(day=1)
        amount = monthly if index < book.useful_life_months - 1 else as_money(depreciable - monthly * Decimal(min(index, book.useful_life_months - 1)))
        accumulated = as_money(monthly * Decimal(index + 1))
        row = ERPAssetDepreciationSchedule(organization_id=actor.organization_id, asset_document_id=asset.id, book_id=book.id, period_date=period, depreciation_amount=amount, accumulated_amount=min(accumulated, depreciable))
        db.add(row); rows.append(row)
    await db.commit()
    return [{"id": row.id, "period_date": row.period_date.isoformat(), "depreciation_amount": str(row.depreciation_amount), "accumulated_amount": str(row.accumulated_amount), "status": row.status} for row in rows]


@router.post("/assets/depreciation-schedules/{schedule_id}/post")
async def post_depreciation_schedule(schedule_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "asset", "post")
    await require_phase5_gate(db, actor.organization_id, "assets_maintenance")
    schedule = await db.scalar(select(ERPAssetDepreciationSchedule).where(ERPAssetDepreciationSchedule.id == schedule_id, ERPAssetDepreciationSchedule.organization_id == actor.organization_id).with_for_update())
    if not schedule:
        raise HTTPException(status_code=404, detail="Depreciation schedule not found")
    if schedule.status == "posted" and schedule.journal_document_id:
        return {"id": schedule.id, "status": schedule.status, "journal_document_id": schedule.journal_document_id}
    expense = await db.scalar(select(ERPAccount).where(ERPAccount.organization_id == actor.organization_id, ERPAccount.purpose == "depreciation_expense", ERPAccount.is_active.is_(True), ERPAccount.is_group.is_(False)).order_by(ERPAccount.id).limit(1))
    if not expense:
        raise HTTPException(status_code=422, detail={"code": "erp_missing_depreciation_expense_account"})
    accumulated = await db.scalar(select(ERPAccount).where(ERPAccount.organization_id == actor.organization_id, ERPAccount.purpose == "accumulated_depreciation", ERPAccount.is_active.is_(True), ERPAccount.is_group.is_(False)).order_by(ERPAccount.id).limit(1))
    if not accumulated:
        raise HTTPException(status_code=422, detail={"code": "erp_missing_accumulated_depreciation_account"})
    journal = ERPDocument(organization_id=actor.organization_id, document_type="journal_entry", number=await next_number(db, actor.organization_id, "journal_entry"), posting_date=schedule.period_date, currency="MNT", payload={"source": "asset_depreciation", "schedule_id": schedule.id})
    db.add(journal); await db.flush()
    amount = as_money(schedule.depreciation_amount)
    db.add_all([
        ERPDocumentLine(document_id=journal.id, account_id=expense.id, description="Depreciation expense", quantity=1, rate=amount, amount=amount, data={"debit": str(amount), "credit": "0"}, position=0),
        ERPDocumentLine(document_id=journal.id, account_id=accumulated.id, description="Accumulated depreciation", quantity=1, rate=amount, amount=amount, data={"debit": "0", "credit": str(amount)}, position=1),
    ])
    await db.flush()
    await post_document(db, journal, actor)
    schedule.status, schedule.journal_document_id = "posted", journal.id
    await db.commit()
    return {"id": schedule.id, "status": schedule.status, "journal_document_id": journal.id}


@router.post("/assets/maintenance", status_code=status.HTTP_201_CREATED)
async def create_maintenance_record(data: MaintenanceRecordInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "maintenance_visit", "create")
    await require_phase5_gate(db, actor.organization_id, "assets_maintenance")
    asset = await _document(db, actor, data.asset_document_id)
    if asset.document_type != "asset": raise HTTPException(status_code=422, detail={"code": "erp_invalid_asset"})
    row = ERPAssetMaintenanceRecord(organization_id=actor.organization_id, **data.model_dump())
    db.add(row); await db.commit()
    return {"id": row.id, "asset_document_id": row.asset_document_id, "scheduled_date": row.scheduled_date.isoformat(), "description": row.description, "status": row.status, "cost": str(row.cost)}


@router.get("/assets/maintenance")
async def list_maintenance_records(asset_document_id: int | None = None, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "maintenance_visit", "view")
    statement = select(ERPAssetMaintenanceRecord).where(ERPAssetMaintenanceRecord.organization_id == actor.organization_id)
    if asset_document_id is not None: statement = statement.where(ERPAssetMaintenanceRecord.asset_document_id == asset_document_id)
    rows = (await db.execute(statement.order_by(ERPAssetMaintenanceRecord.scheduled_date))).scalars().all()
    return [{"id": row.id, "asset_document_id": row.asset_document_id, "scheduled_date": row.scheduled_date.isoformat(), "description": row.description, "status": row.status, "cost": str(row.cost), "completed_at": row.completed_at.isoformat() if row.completed_at else None} for row in rows]


@router.post("/assets/maintenance/{record_id}/complete")
async def complete_maintenance_record(record_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "maintenance_visit", "edit")
    await require_phase5_gate(db, actor.organization_id, "assets_maintenance")
    row = await db.scalar(select(ERPAssetMaintenanceRecord).where(ERPAssetMaintenanceRecord.id == record_id, ERPAssetMaintenanceRecord.organization_id == actor.organization_id).with_for_update())
    if not row: raise HTTPException(status_code=404, detail="Maintenance record not found")
    if row.status == "completed": return {"id": row.id, "status": row.status, "completed_at": row.completed_at}
    row.status, row.completed_at = "completed", datetime.now(timezone.utc)
    await db.commit()
    return {"id": row.id, "status": row.status, "completed_at": row.completed_at}


@router.post("/assets/disposals", status_code=status.HTTP_201_CREATED)
async def dispose_asset(data: AssetDisposalInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "asset", "cancel")
    await require_phase5_gate(db, actor.organization_id, "assets_maintenance")
    asset = await db.scalar(select(ERPDocument).where(ERPDocument.id == data.asset_document_id, ERPDocument.organization_id == actor.organization_id).with_for_update())
    if not asset or asset.document_type != "asset" or asset.status not in {"submitted", "approved"}:
        raise HTTPException(status_code=422, detail={"code": "erp_invalid_asset_disposal"})
    if await db.scalar(select(ERPAssetDisposal.id).where(ERPAssetDisposal.asset_document_id == asset.id)):
        raise HTTPException(status_code=409, detail={"code": "erp_asset_already_disposed"})
    row = ERPAssetDisposal(organization_id=actor.organization_id, **data.model_dump())
    db.add(row); await db.flush()
    cost = as_money(asset.grand_total)
    proceeds = as_money(data.proceeds)
    cash = await default_account(db, actor.organization_id, "cash")
    fixed_asset = await default_account(db, actor.organization_id, "fixed_asset")
    lines: list[ERPDocumentLine] = []
    if proceeds:
        lines.append(ERPDocumentLine(account_id=cash.id, description="Asset disposal proceeds", quantity=1, rate=proceeds, amount=proceeds, data={"debit": str(proceeds), "credit": "0"}, position=0))
    if cost > proceeds:
        loss = as_money(cost - proceeds); expense = await default_account(db, actor.organization_id, "expense")
        lines.append(ERPDocumentLine(account_id=expense.id, description="Asset disposal loss", quantity=1, rate=loss, amount=loss, data={"debit": str(loss), "credit": "0"}, position=len(lines)))
    elif proceeds > cost:
        gain = as_money(proceeds - cost); income = await default_account(db, actor.organization_id, "income")
        lines.append(ERPDocumentLine(account_id=income.id, description="Asset disposal gain", quantity=1, rate=gain, amount=gain, data={"debit": "0", "credit": str(gain)}, position=len(lines)))
    if cost:
        lines.append(ERPDocumentLine(account_id=fixed_asset.id, description="Derecognize asset cost", quantity=1, rate=cost, amount=cost, data={"debit": "0", "credit": str(cost)}, position=len(lines)))
    journal = ERPDocument(organization_id=actor.organization_id, document_type="journal_entry", number=await next_number(db, actor.organization_id, "journal_entry"), posting_date=data.disposal_date, currency=asset.currency, payload={"source": "asset_disposal", "disposal_id": row.id})
    db.add(journal); await db.flush()
    for line in lines: line.document_id = journal.id; db.add(line)
    await db.flush(); await post_document(db, journal, actor)
    asset.status = "disposed"; asset.version += 1
    row.journal_document_id = journal.id
    await record_change(db, actor=actor, topic="erp", aggregate_type="erp_asset_disposal", aggregate_id=asset.id, operation="disposed", after={"proceeds": str(data.proceeds), "reason": data.reason})
    await db.commit()
    return {"id": row.id, "asset_document_id": row.asset_document_id, "disposal_date": row.disposal_date.isoformat(), "proceeds": str(row.proceeds), "reason": row.reason, "journal_document_id": row.journal_document_id, "status": asset.status}


@router.post("/assets/disposals/{disposal_id}/reverse")
async def reverse_asset_disposal(disposal_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "asset", "post")
    await require_phase5_gate(db, actor.organization_id, "assets_maintenance")
    disposal = await db.scalar(select(ERPAssetDisposal).where(ERPAssetDisposal.id == disposal_id, ERPAssetDisposal.organization_id == actor.organization_id).with_for_update())
    if not disposal:
        raise HTTPException(status_code=404, detail="Asset disposal not found")
    if disposal.reversal_document_id:
        return {"id": disposal.id, "reversal_document_id": disposal.reversal_document_id}
    asset = await db.scalar(select(ERPDocument).where(ERPDocument.id == disposal.asset_document_id, ERPDocument.organization_id == actor.organization_id).with_for_update())
    if not asset: raise HTTPException(status_code=404, detail="Asset not found")
    journal = ERPDocument(organization_id=actor.organization_id, document_type="journal_entry", number=await next_number(db, actor.organization_id, "journal_entry"), posting_date=disposal.disposal_date, currency=asset.currency, payload={"source": "asset_disposal_reversal", "disposal_id": disposal.id})
    db.add(journal); await db.flush()
    if disposal.proceeds:
        cash = await default_account(db, actor.organization_id, "cash")
        income = await default_account(db, actor.organization_id, "income")
        amount = as_money(disposal.proceeds)
        db.add_all([
            ERPDocumentLine(document_id=journal.id, account_id=cash.id, description="Reverse disposal proceeds", quantity=1, rate=amount, amount=amount, data={"debit": "0", "credit": str(amount)}, position=0),
            ERPDocumentLine(document_id=journal.id, account_id=income.id, description="Reverse disposal gain", quantity=1, rate=amount, amount=amount, data={"debit": str(amount), "credit": "0"}, position=1),
        ])
        await db.flush()
    await post_document(db, journal, actor)
    disposal.reversal_document_id = journal.id
    asset.status = "submitted"
    await db.commit()
    return {"id": disposal.id, "reversal_document_id": journal.id, "asset_document_id": asset.id, "status": asset.status}


@router.get("/reports/dashboard")
async def dashboard(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    await require_capability(db, actor, "erp_dashboard", "view")
    approved_statuses = ["approved", "submitted"]
    async def total_for(document_type: str) -> Decimal:
        value = await db.scalar(select(func.coalesce(func.sum(ERPDocument.grand_total), 0)).where(
            ERPDocument.organization_id == actor.organization_id, ERPDocument.document_type == document_type,
            ERPDocument.status.in_(approved_statuses), ERPDocument.archived_at.is_(None),
        ))
        return as_money(value or 0)
    revenue = await total_for("sales_invoice")
    purchase_expenses = await total_for("purchase_invoice")
    payroll_total = await total_for("payroll_run")
    cash_collected = await total_for("payment_entry")
    inventory_value = await db.scalar(select(func.coalesce(func.sum(ERPInventoryLevel.inventory_value), 0)).where(ERPInventoryLevel.organization_id == actor.organization_id))
    if inventory_value is None:
        inventory_value = await db.scalar(select(func.coalesce(func.sum(ERPStockLedgerEntry.value_delta), 0)).where(ERPStockLedgerEntry.organization_id == actor.organization_id))
    open_support = await db.scalar(select(func.count(ERPDocument.id)).where(
        ERPDocument.organization_id == actor.organization_id, ERPDocument.document_type == "support_ticket",
        ERPDocument.status.not_in(["cancelled", "submitted"]), ERPDocument.archived_at.is_(None),
    )) or 0
    pending_approvals = await db.scalar(select(func.count(ERPDocument.id)).where(
        ERPDocument.organization_id == actor.organization_id, ERPDocument.document_type != "support_ticket",
        ERPDocument.status.not_in(["cancelled", "submitted"]), ERPDocument.workflow_state.not_in(["draft", "approved", "rejected", "cancelled"]),
        ERPDocument.archived_at.is_(None),
    )) or 0
    open_queries = int(open_support) + int(pending_approvals)
    docs = (await db.execute(select(ERPDocument).where(ERPDocument.organization_id == actor.organization_id, ERPDocument.status.in_(approved_statuses), ERPDocument.archived_at.is_(None)))).scalars().all()
    maintenance = sum(1 for doc in docs if doc.document_type == "maintenance_schedule")
    return {"currency": (await _organization(db, actor)).base_currency, "revenue": str(revenue), "expenses": str(purchase_expenses + payroll_total),
        "profit": str(revenue - purchase_expenses - payroll_total), "cash_collected": str(cash_collected),
        "inventory_value": str(as_money(inventory_value or 0)), "open_customer_queries": open_queries, "open_queries": open_queries,
        "open_queries_breakdown": {"support_tickets": int(open_support), "pending_approvals": int(pending_approvals)}, "payroll_total": str(payroll_total),
        "production_cost": str(await total_for("work_order")), "upcoming_maintenance": maintenance}


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


# Dedicated payroll routes own calculation, approval, posting, and exports.
# The generic document workbench remains available for legacy payroll rows but
# cannot create new payroll documents.
router.include_router(payroll_router, prefix="/payroll")
