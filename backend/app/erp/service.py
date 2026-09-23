from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enterprise_deps import ActorContext
from app.models.models import (
    ERPAccessRole,
    ERPAccount,
    ERPAccountingSettings,
    ERPAccountRole,
    ERPCapability,
    ERPCustomField,
    ERPDocument,
    ERPDocumentLine,
    ERPGeneralLedgerEntry,
    ERPApprovalRule,
    ERPFormDefinition,
    ERPMasterRequest,
    ERPTeamRole,
    ERPWorkflowTransition,
    ERPPaymentAllocation,
    ERPPostingPeriod,
    ERPSequence,
    ERPStockLedgerEntry,
    ERPInventoryLevel,
    ERPWarehouse,
    ERPSourceLineAllocation,
    ERPStockValuationLayer,
    ERPBOMSnapshot,
    ERPAssetBook,
    ERPAssetDepreciationSchedule,
    ERPAssetMaintenanceRecord,
    ERPAssetDisposal,
    ERPItem,
    Organization,
    TeamMember,
    UserAccount,
)


ERP_MODULES = {
    "accounting": "Accounting",
    "selling": "Selling",
    "buying": "Buying",
    "stock": "Stock",
    "crm": "CRM",
    "support": "Support",
    "payroll": "Payroll",
    "manufacturing": "Manufacturing",
    "assets_maintenance": "Assets & maintenance",
}
MODULE_SETTINGS_KEY = "erp_modules"
VALID_ACTIONS = frozenset({"view", "view_salary", "edit_setup", "edit_formula", "create", "edit", "calculate", "review", "approve", "approve_payroll_manager", "approve_hr_director", "approve_finance", "post", "pay", "release_slips", "submit", "cancel", "archive", "export", "administer"})
DOCUMENT_MODULES = {
    "journal_entry": "accounting", "payment_entry": "accounting", "budget": "accounting", "fiscal_period": "accounting",
    "quotation": "selling", "sales_order": "selling", "delivery": "selling", "sales_invoice": "selling", "sales_credit_note": "selling",
    "supplier_quotation": "buying", "purchase_order": "buying", "purchase_receipt": "buying", "purchase_invoice": "buying", "purchase_debit_note": "buying",
    "stock_entry": "stock", "stock_reconciliation": "stock",
    "lead": "crm", "opportunity": "crm",
    "support_ticket": "support", "service_level_agreement": "support",
    "salary_structure": "payroll", "payroll_run": "payroll", "salary_slip": "payroll",
    "bill_of_materials": "manufacturing", "work_order": "manufacturing", "job_card": "manufacturing",
    "asset": "assets_maintenance", "maintenance_schedule": "assets_maintenance", "maintenance_visit": "assets_maintenance",
}
DOCUMENT_TYPES = frozenset(DOCUMENT_MODULES)
MASTER_OPERATIONS = frozenset({
    "party", "item", "supplier", "purchase_item", "supplier_price_list", "customer", "sales_catalog_item",
    "customer_discount_tier", "warehouse", "item_sku", "uom", "reorder_rule", "chart_account", "cost_center", "tax_template",
})
MASTER_OPERATION_MODULES = {
    "party": None, "item": None, "supplier": "buying", "purchase_item": "buying", "supplier_price_list": "buying",
    "customer": "selling", "sales_catalog_item": "selling", "customer_discount_tier": "selling", "warehouse": "stock",
    "item_sku": "stock", "uom": "stock", "reorder_rule": "stock", "chart_account": "accounting", "cost_center": "accounting",
    "tax_template": "accounting",
}
OPERATION_TYPES = DOCUMENT_TYPES | MASTER_OPERATIONS
FORM_FIELD_TYPES = frozenset({"text", "long_text", "number", "money", "date", "datetime", "boolean", "select", "multi_select", "reference"})
FORM_SECTIONS = frozenset({"header", "line", "master"})
REFERENCE_TARGETS = frozenset({"party", "item", "warehouse", "account", "project"})
SCOPE_DIMENSIONS = frozenset({"warehouse_ids", "project_ids", "branch_codes"})
MONEY_QUANTUM = Decimal("0.0001")
DEFAULT_ACCOUNTS = (
    ("1000", "Cash", "cash"), ("1010", "Payroll bank", "cash"),
    ("1100", "Accounts receivable", "receivable"), ("1200", "Inventory", "inventory"),
    ("1300", "Fixed assets", "fixed_asset"), ("1301", "Work in progress", "wip"), ("1310", "Accumulated depreciation", "fixed_asset"),
    ("2000", "Accounts payable", "payable"), ("2100", "Sales tax payable", "tax_payable"),
    ("2200", "Purchase tax receivable", "tax_receivable"), ("2300", "Payroll payable", "payroll_payable"),
    ("2310", "Net salary payable", "payroll_payable"), ("2320", "Employee social insurance payable", "payroll_payable"),
    ("2330", "Employer social insurance payable", "payroll_payable"), ("2340", "PIT payable", "tax_payable"),
    ("2350", "Employee advance clearing", "receivable"), ("4000", "Sales income", "income"),
    ("5000", "Operating expenses", "expense"), ("5100", "Salary expense", "payroll_expense"), ("5200", "Depreciation expense", "expense"),
    ("5110", "Employer social insurance expense", "payroll_expense"),
)
ACCOUNT_METADATA = {
    "1000": ("asset", "cash"), "1010": ("asset", "bank"), "1100": ("asset", "receivable"), "1200": ("asset", "inventory"),
    "1300": ("asset", "fixed_asset"), "1301": ("asset", "wip"), "1310": ("asset", "accumulated_depreciation"), "2000": ("liability", "payable"), "2100": ("liability", "tax"),
    "2200": ("asset", "tax"), "2300": ("liability", "payroll_payable"), "2310": ("liability", "net_pay_payable"),
    "2320": ("liability", "employee_shi_payable"), "2330": ("liability", "employer_shi_payable"), "2340": ("liability", "pit_payable"),
    "2350": ("asset", "advance_clearing"), "4000": ("income", "revenue"), "5000": ("expense", "expense"),
    "5100": ("expense", "salary_expense"), "5110": ("expense", "employer_shi_expense"), "5200": ("expense", "depreciation_expense"),
}
ROLE_TEMPLATES = {
    "erp_administrator": ("ERP administrator", [("*", "*")]),
    "erp_accountant": ("Accountant", [("accounts", "*"), ("chart_account", "*"), ("cost_center", "*"), ("tax_template", "*"), ("journal_entry", "*"), ("payment_entry", "*"), ("budget", "*"), ("sales_invoice", "view"), ("purchase_invoice", "view")]),
    "erp_sales": ("Sales", [("parties", "*"), ("customer", "*"), ("customer_discount_tier", "*"), ("items", "view"), ("sales_catalog_item", "*"), ("quotation", "*"), ("sales_order", "*"), ("delivery", "*"), ("sales_invoice", "create"), ("sales_invoice", "view"), ("lead", "*"), ("opportunity", "*")]),
    "erp_purchasing": ("Purchasing", [("parties", "*"), ("supplier", "*"), ("supplier_price_list", "*"), ("purchase_item", "*"), ("items", "view"), ("supplier_quotation", "*"), ("purchase_order", "*"), ("purchase_receipt", "*"), ("purchase_invoice", "create"), ("purchase_invoice", "view")]),
    "erp_stock": ("Stock controller", [("items", "*"), ("item_sku", "*"), ("warehouses", "*"), ("warehouse", "*"), ("uom", "*"), ("reorder_rule", "*"), ("stock", "view"), ("stock_entry", "*"), ("stock_reconciliation", "*")]),
    "erp_hr_payroll": ("Payroll administrator", [("salary_structure", "*"), ("payroll_run", "*"), ("salary_slip", "*"), ("payroll", "*")]),
    "erp_support": ("Support", [("support_ticket", "*"), ("service_level_agreement", "*")]),
    "erp_manufacturing": ("Manufacturing", [("bill_of_materials", "*"), ("work_order", "*"), ("job_card", "*")]),
    "erp_assets": ("Assets and maintenance", [("asset", "*"), ("maintenance_schedule", "*"), ("maintenance_visit", "*")]),
}


def default_workflow() -> dict[str, Any]:
    return {
        "initial_state": "draft",
        "states": [
            {"key": "draft", "label": "Draft", "terminal": False},
            {"key": "submitted", "label": "Submitted", "terminal": False},
            {"key": "approved", "label": "Approved", "terminal": True},
            {"key": "rejected", "label": "Rejected", "terminal": True},
            {"key": "cancelled", "label": "Cancelled", "terminal": True},
        ],
        "transitions": [
            {"from": "draft", "to": "submitted", "label": "Submit", "role_ids": [], "requester_allowed": True},
            {"from": "submitted", "to": "approved", "label": "Approve", "role_ids": [], "requester_allowed": False},
            {"from": "submitted", "to": "rejected", "label": "Reject", "role_ids": [], "requester_allowed": False},
            {"from": "draft", "to": "cancelled", "label": "Cancel", "role_ids": [], "requester_allowed": True},
        ],
    }


def operation_catalog() -> dict[str, Any]:
    operations: dict[str, Any] = {}
    for key, module in DOCUMENT_MODULES.items():
        operations[key] = {"key": key, "kind": "document", "module": module, "label": key.replace("_", " ").title(), "sections": ["header", "line"], "posting_capable": key in {"journal_entry", "payment_entry", "sales_invoice", "sales_credit_note", "purchase_invoice", "purchase_debit_note", "delivery", "purchase_receipt", "stock_entry", "stock_reconciliation", "payroll_run", "salary_slip", "asset"}}
    labels = {
        "party": (None, "Party request"), "item": (None, "Item request"), "supplier": ("buying", "Create supplier / vendor"),
        "purchase_item": ("buying", "Create purchase item"), "supplier_price_list": ("buying", "Create supplier price list"),
        "customer": ("selling", "Create customer"), "sales_catalog_item": ("selling", "Create sales catalog item"),
        "customer_discount_tier": ("selling", "Create customer discount tier"), "warehouse": ("stock", "Create warehouse"),
        "item_sku": ("stock", "Create item / SKU"), "uom": ("stock", "Create unit of measure"), "reorder_rule": ("stock", "Create reorder rule"),
        "chart_account": ("accounting", "Create chart of accounts entry"), "cost_center": ("accounting", "Create cost center"),
        "tax_template": ("accounting", "Create tax template"),
    }
    operations.update({key: {"key": key, "kind": "master_request", "module": module, "label": label, "sections": ["master"], "posting_capable": False} for key, (module, label) in labels.items()})
    return {"operations": operations, "actions": sorted(VALID_ACTIONS), "field_types": sorted(FORM_FIELD_TYPES), "sections": sorted(FORM_SECTIONS), "reference_targets": sorted(REFERENCE_TARGETS), "scope_dimensions": sorted(SCOPE_DIMENSIONS)}


def _field_error(code: str, **details: Any) -> HTTPException:
    return HTTPException(status_code=422, detail={"code": code, **details})


def validate_definition_fields(operation: str, fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if operation not in OPERATION_TYPES:
        raise _field_error("erp_unknown_operation", operation=operation)
    seen: set[str] = set()
    normalised: list[dict[str, Any]] = []
    allowed_sections = {"master"} if operation in MASTER_OPERATIONS else {"header", "line"}
    for position, raw in enumerate(fields):
        key, field_type, section = raw.get("key"), raw.get("field_type"), raw.get("section")
        if not isinstance(key, str) or not key or not key.replace("_", "").isalnum() or key[0].isdigit() or key in seen:
            raise _field_error("erp_invalid_form_field_key", key=key)
        if field_type not in FORM_FIELD_TYPES or section not in allowed_sections:
            raise _field_error("erp_invalid_form_field", key=key)
        if field_type in {"select", "multi_select"} and not isinstance((raw.get("options") or {}).get("choices"), list):
            raise _field_error("erp_form_choices_required", key=key)
        if field_type == "reference" and (raw.get("options") or {}).get("reference_target") not in REFERENCE_TARGETS:
            raise _field_error("erp_form_reference_required", key=key)
        seen.add(key)
        normalised.append({
            "key": key, "label": raw.get("label") or key.replace("_", " ").title(), "help_text": raw.get("help_text"),
            "field_type": field_type, "section": section, "required": bool(raw.get("required", False)),
            "default": raw.get("default"), "options": raw.get("options") or {}, "validation": raw.get("validation") or {},
            "position": int(raw.get("position", position)),
        })
    return sorted(normalised, key=lambda field: (field["section"], field["position"], field["key"]))


def validate_workflow(workflow: dict[str, Any], role_ids: set[int], *, posting_capable: bool) -> dict[str, Any]:
    states = workflow.get("states") or []
    transitions = workflow.get("transitions") or []
    initial = workflow.get("initial_state")
    state_keys = {state.get("key") for state in states if isinstance(state, dict) and state.get("key")}
    if not state_keys or initial not in state_keys or "draft" not in state_keys:
        raise _field_error("erp_invalid_workflow_initial_state")
    if len(state_keys) != len(states):
        raise _field_error("erp_duplicate_workflow_state")
    terminals = {state["key"] for state in states if state.get("terminal")}
    if not {"approved", "rejected", "cancelled"}.issubset(terminals):
        raise _field_error("erp_workflow_terminal_states_required")
    graph: dict[str, set[str]] = {key: set() for key in state_keys}
    for transition in transitions:
        source, target = transition.get("from"), transition.get("to")
        if source not in state_keys or target not in state_keys or source in terminals:
            raise _field_error("erp_invalid_workflow_transition", transition=transition)
        if any(role_id not in role_ids for role_id in (transition.get("role_ids") or [])):
            raise _field_error("erp_unknown_workflow_role")
        graph[source].add(target)
    reachable = {initial}
    frontier = [initial]
    while frontier:
        current = frontier.pop()
        for target in graph[current] - reachable:
            reachable.add(target); frontier.append(target)
    if reachable != state_keys or not terminals.intersection(reachable):
        raise _field_error("erp_workflow_unreachable_state")
    if posting_capable and not any(item.get("to") == "approved" for item in transitions):
        raise _field_error("erp_workflow_safe_finalization_required")
    return {"initial_state": initial, "states": states, "transitions": transitions}


def as_money(value: Decimal | str | int | float) -> Decimal:
    return Decimal(str(value)).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def module_settings(organization_settings: dict[str, Any] | None) -> dict[str, bool]:
    configured = ((organization_settings or {}).get(MODULE_SETTINGS_KEY) or {})
    return {name: bool(configured.get(name, False)) for name in ERP_MODULES}


PHASE5_MODULES = {"selling", "buying", "stock", "manufacturing", "assets_maintenance"}


async def phase5_gate_status(db: AsyncSession, organization_id: int) -> dict[str, Any]:
    organization = await db.get(Organization, organization_id)
    settings = (organization.settings or {}) if organization else {}
    acceptance = settings.get("phase5_payroll_acceptance") or {}
    return {"accepted": bool(acceptance.get("reconciled_period_id")), **acceptance}


async def require_phase5_gate(db: AsyncSession, organization_id: int, module: str) -> None:
    """Require the reconciled payroll acceptance gate for enabled Phase 5 modules."""
    if module not in PHASE5_MODULES:
        return
    organization = await db.get(Organization, organization_id)
    configured = (organization.settings or {}) if organization else {}
    if not bool((configured.get(MODULE_SETTINGS_KEY) or {}).get(module, False)):
        return
    acceptance = configured.get("phase5_payroll_acceptance") or {}
    if not acceptance.get("reconciled_period_id"):
        raise HTTPException(status_code=409, detail={"code": "erp_phase5_payroll_acceptance_required", "module": module})


async def validate_phase5_chain(db: AsyncSession, document: ERPDocument, lines: list[ERPDocumentLine]) -> None:
    """Validate source-document chains and freeze source-line quantities."""
    module = DOCUMENT_MODULES.get(document.document_type)
    await require_phase5_gate(db, document.organization_id, module or "")
    if module not in PHASE5_MODULES:
        return
    expected_sources = {
        "sales_order": {"quotation"}, "delivery": {"sales_order"}, "sales_invoice": {"delivery"}, "sales_credit_note": {"sales_invoice"},
        "purchase_order": {"supplier_quotation"}, "purchase_receipt": {"purchase_order"}, "purchase_invoice": {"purchase_receipt"}, "purchase_debit_note": {"purchase_invoice"},
    }
    source_type_set = expected_sources.get(document.document_type)
    if source_type_set:
        if not document.source_document_id:
            raise HTTPException(status_code=422, detail={"code": "erp_source_document_required", "document_type": document.document_type})
        source = await db.scalar(select(ERPDocument).where(
            ERPDocument.id == document.source_document_id, ERPDocument.organization_id == document.organization_id,
        ).with_for_update())
        if not source or source.document_type not in source_type_set or source.status not in {"submitted", "approved"}:
            raise HTTPException(status_code=422, detail={"code": "erp_invalid_source_document", "document_type": document.document_type})
        source_lines = {line.id: line for line in (await db.execute(select(ERPDocumentLine).where(ERPDocumentLine.document_id == source.id))).scalars().all()}
        if not source_lines and lines:
            raise HTTPException(status_code=422, detail={"code": "erp_source_lines_required"})
        for target_line in lines:
            source_line_id = (target_line.data or {}).get("source_line_id")
            if source_line_id is None:
                raise HTTPException(status_code=422, detail={"code": "erp_source_line_required", "target_line_id": target_line.id})
            try:
                source_line_id = int(source_line_id)
            except (TypeError, ValueError):
                raise HTTPException(status_code=422, detail={"code": "erp_invalid_source_line", "source_line_id": source_line_id})
            source_line = source_lines.get(source_line_id)
            if source_line is None or source_line.item_id != target_line.item_id:
                raise HTTPException(status_code=422, detail={"code": "erp_invalid_source_line", "source_line_id": source_line_id})
            allocated = await db.scalar(select(func.coalesce(func.sum(ERPSourceLineAllocation.quantity), 0)).where(
                ERPSourceLineAllocation.organization_id == document.organization_id,
                ERPSourceLineAllocation.source_line_id == source_line.id,
                ERPSourceLineAllocation.target_document_id != document.id,
            ))
            requested = Decimal(str(target_line.quantity or 0))
            if Decimal(str(allocated or 0)) + requested > Decimal(str(source_line.quantity or 0)):
                raise HTTPException(status_code=409, detail={"code": "erp_source_quantity_overfulfilled", "source_line_id": source_line.id, "available": str(Decimal(str(source_line.quantity or 0)) - Decimal(str(allocated or 0)))})
            db.add(ERPSourceLineAllocation(
                organization_id=document.organization_id, source_document_id=source.id, source_line_id=source_line.id,
                target_document_id=document.id, target_line_id=target_line.id, quantity=requested,
            ))
    if document.document_type in {"bill_of_materials", "work_order"}:
        if document.document_type == "work_order":
            snapshot_id = (document.payload or {}).get("bom_snapshot_id")
            if not snapshot_id:
                raise HTTPException(status_code=422, detail={"code": "erp_approved_bom_snapshot_required"})
            snapshot = await db.scalar(select(ERPBOMSnapshot).where(ERPBOMSnapshot.id == int(snapshot_id), ERPBOMSnapshot.organization_id == document.organization_id, ERPBOMSnapshot.status == "approved"))
            if not snapshot:
                raise HTTPException(status_code=422, detail={"code": "erp_invalid_bom_snapshot"})
    if document.document_type == "asset" and not (document.payload or {}).get("asset_book_id"):
        raise HTTPException(status_code=422, detail={"code": "erp_asset_book_required"})


async def require_capability(db: AsyncSession, actor: ActorContext, resource: str, action: str) -> None:
    if action not in VALID_ACTIONS:
        raise HTTPException(status_code=400, detail="Unknown ERP action")
    # Existing enterprise administrators remain operational while an
    # organization is gradually configured with ERP-specific roles.
    if "admin" in actor.roles:
        return
    # Existing collaboration roles retain a deliberately conservative bridge
    # during ERP rollout.  Payroll and posting/cancellation never flow through
    # this bridge: those require an explicit ERP access role.
    if action in {"view", "create", "edit"} and actor.has_any_role("manager", "team_lead") and resource not in {"payroll_run", "salary_slip", "salary_structure"}:
        return
    allowed = await db.scalar(
        select(ERPCapability.id)
        .join(ERPAccessRole, ERPCapability.access_role_id == ERPAccessRole.id)
        .outerjoin(ERPAccountRole, ERPAccountRole.access_role_id == ERPAccessRole.id)
        .outerjoin(ERPTeamRole, ERPTeamRole.access_role_id == ERPAccessRole.id)
        .outerjoin(TeamMember, TeamMember.team_id == ERPTeamRole.team_id)
        .outerjoin(UserAccount, UserAccount.employee_id == TeamMember.employee_id)
        .where(
            ERPAccessRole.is_active.is_(True),
            or_(ERPAccountRole.account_id == actor.account_id, UserAccount.id == actor.account_id),
            ERPAccessRole.organization_id == actor.organization_id,
            ERPCapability.resource.in_([resource, "*"]),
            ERPCapability.action.in_([action, "*"]),
        )
        .limit(1)
    )
    if not allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Missing ERP capability: {resource}.{action}")


async def capability_scopes(db: AsyncSession, actor: ActorContext, resource: str, action: str) -> dict[str, set[Any]] | None:
    """Return additive explicit scopes. ``None`` represents unrestricted access."""
    if "admin" in actor.roles or (action in {"view", "create", "edit"} and actor.has_any_role("manager", "team_lead")):
        return None
    rows = (await db.execute(
        select(ERPAccountRole.scope, ERPTeamRole.scope)
        .join(ERPAccessRole, ERPAccessRole.id == ERPCapability.access_role_id)
        .outerjoin(ERPAccountRole, ERPAccountRole.access_role_id == ERPAccessRole.id)
        .outerjoin(ERPTeamRole, ERPTeamRole.access_role_id == ERPAccessRole.id)
        .outerjoin(TeamMember, TeamMember.team_id == ERPTeamRole.team_id)
        .outerjoin(UserAccount, UserAccount.employee_id == TeamMember.employee_id)
        .where(
            ERPAccessRole.organization_id == actor.organization_id, ERPAccessRole.is_active.is_(True),
            or_(ERPAccountRole.account_id == actor.account_id, UserAccount.id == actor.account_id),
            ERPCapability.resource.in_([resource, "*"]), ERPCapability.action.in_([action, "*"]),
        )
    )).all()
    result: dict[str, set[Any]] = {key: set() for key in SCOPE_DIMENSIONS}
    unrestricted = False
    for account_scope, team_scope in rows:
        scope = account_scope or team_scope or {}
        if not scope:
            unrestricted = True
        for key in SCOPE_DIMENSIONS:
            result[key].update(scope.get(key) or [])
    return None if unrestricted else result


def scope_allows(scope: dict[str, set[Any]] | None, values: dict[str, Any]) -> bool:
    if scope is None:
        return True
    for key, value in values.items():
        if value is not None and scope.get(key) and value not in scope[key]:
            return False
    return True


async def published_definition(db: AsyncSession, organization_id: int, operation: str) -> ERPFormDefinition | None:
    return await db.scalar(select(ERPFormDefinition).where(
        ERPFormDefinition.organization_id == organization_id,
        ERPFormDefinition.operation == operation,
        ERPFormDefinition.status == "published",
    ).order_by(ERPFormDefinition.version.desc()))


async def ensure_definition(db: AsyncSession, organization_id: int, operation: str, account_id: int | None = None) -> ERPFormDefinition:
    existing = await published_definition(db, organization_id, operation)
    if existing:
        return existing
    resource = operation if operation in MASTER_OPERATIONS else f"document:{operation}"
    legacy_fields = (await db.execute(select(ERPCustomField).where(
        ERPCustomField.organization_id == organization_id, ERPCustomField.resource == resource, ERPCustomField.is_active.is_(True)
    ))).scalars().all()
    fields = [{"key": field.key, "label": field.label, "field_type": "long_text" if field.field_type == "text" else field.field_type,
               "section": "master" if operation in MASTER_OPERATIONS else "header", "required": field.required,
               "default": None, "options": field.options or {}, "validation": {}, "position": index}
              for index, field in enumerate(legacy_fields)]
    definition = ERPFormDefinition(organization_id=organization_id, operation=operation, version=1, status="published", fields=fields,
                                   workflow=default_workflow(), created_by_account_id=account_id, published_at=datetime.now(timezone.utc))
    db.add(definition)
    await db.flush()
    return definition


def validate_form_values(fields: list[dict[str, Any]], values: dict[str, Any], section: str) -> dict[str, Any]:
    definitions = {field["key"]: field for field in fields if field.get("section") == section}
    unknown = set(values).difference(definitions)
    if unknown:
        raise _field_error("erp_unknown_form_field", keys=sorted(unknown))
    result: dict[str, Any] = {}
    for key, definition in definitions.items():
        value = values.get(key, definition.get("default"))
        if value is None:
            if definition.get("required"):
                raise _field_error("erp_required_form_field", key=key)
            continue
        field_type, options, rules = definition["field_type"], definition.get("options") or {}, definition.get("validation") or {}
        valid = ((field_type in {"text", "long_text"} and isinstance(value, str)) or
                 (field_type in {"number", "money"} and isinstance(value, (int, float, str))) or
                 (field_type in {"date", "datetime"} and isinstance(value, str)) or
                 (field_type == "boolean" and isinstance(value, bool)) or
                 (field_type == "select" and value in options.get("choices", [])) or
                 (field_type == "multi_select" and isinstance(value, list) and all(item in options.get("choices", []) for item in value)) or
                 (field_type == "reference" and isinstance(value, (str, int))))
        if not valid:
            raise _field_error("erp_invalid_form_field", key=key)
        if isinstance(value, str):
            if rules.get("min_length") is not None and len(value) < rules["min_length"] or rules.get("max_length") is not None and len(value) > rules["max_length"]:
                raise _field_error("erp_form_field_length", key=key)
        if field_type in {"number", "money"}:
            decimal = Decimal(str(value))
            if rules.get("minimum") is not None and decimal < Decimal(str(rules["minimum"])) or rules.get("maximum") is not None and decimal > Decimal(str(rules["maximum"])):
                raise _field_error("erp_form_field_range", key=key)
        result[key] = value
    return result


async def record_workflow_transition(db: AsyncSession, actor: ActorContext, *, entity_type: str, entity_id: int, operation: str, definition_version: int, from_state: str | None, to_state: str, comment: str | None = None) -> None:
    db.add(ERPWorkflowTransition(
        organization_id=actor.organization_id, entity_type=entity_type, entity_id=entity_id, operation=operation,
        definition_version=definition_version, from_state=from_state, to_state=to_state, comment=comment,
        actor_account_id=actor.account_id,
    ))


async def bootstrap_organization(db: AsyncSession, organization_id: int) -> None:
    """Seed only generic, non-jurisdictional masters and role templates.

    This is idempotent and intentionally does not assign payroll or accounting
    authority to existing users; admins choose those roles explicitly.
    """
    for code, name, account_type in DEFAULT_ACCOUNTS:
        classification, purpose = ACCOUNT_METADATA.get(code, ("asset", "general"))
        exists = await db.scalar(select(ERPAccount.id).where(ERPAccount.organization_id == organization_id, ERPAccount.code == code))
        if not exists:
            db.add(ERPAccount(organization_id=organization_id, code=code, name=name, account_type=account_type, classification=classification, purpose=purpose, currency="MNT"))
        else:
            account = await db.get(ERPAccount, exists)
            if account and account.purpose == "general":
                account.classification, account.purpose, account.currency = classification, purpose, "MNT"
    await db.flush()
    default_center = await db.scalar(select(ERPCostCenter).where(ERPCostCenter.organization_id == organization_id, ERPCostCenter.code == "DEFAULT"))
    if default_center is None:
        default_center = ERPCostCenter(organization_id=organization_id, code="DEFAULT", name="Default cost center", is_active=True)
        db.add(default_center)
        await db.flush()
    settings = await db.scalar(select(ERPAccountingSettings).where(ERPAccountingSettings.organization_id == organization_id))
    if settings is None:
        db.add(ERPAccountingSettings(organization_id=organization_id, base_currency="MNT", fiscal_year_start_month=1, default_cost_center_id=default_center.id))
    elif settings.default_cost_center_id is None:
        settings.default_cost_center_id = default_center.id
    for code, (name, capabilities) in ROLE_TEMPLATES.items():
        role = await db.scalar(select(ERPAccessRole).where(ERPAccessRole.organization_id == organization_id, ERPAccessRole.code == code))
        if role:
            continue
        role = ERPAccessRole(organization_id=organization_id, name=name, code=code, is_system=True)
        db.add(role)
        await db.flush()
        db.add_all([ERPCapability(access_role_id=role.id, resource=resource, action=action) for resource, action in capabilities])


async def validate_custom_fields(
    db: AsyncSession, organization_id: int, resource: str, custom: dict[str, Any], *, posted: bool = False
) -> dict[str, Any]:
    fields = (await db.execute(select(ERPCustomField).where(
        ERPCustomField.organization_id == organization_id,
        ERPCustomField.resource == resource,
        ERPCustomField.is_active.is_(True),
    ))).scalars().all()
    definitions = {field.key: field for field in fields}
    unknown = set(custom).difference(definitions)
    if unknown:
        raise HTTPException(status_code=422, detail={"code": "erp_unknown_custom_field", "keys": sorted(unknown)})
    for key, definition in definitions.items():
        value = custom.get(key)
        if definition.required and value is None:
            raise HTTPException(status_code=422, detail={"code": "erp_required_custom_field", "key": key})
        if value is None:
            continue
        expected = definition.field_type
        valid = (
            (expected == "text" and isinstance(value, str))
            or (expected in {"number", "money"} and isinstance(value, (int, float, str)))
            or (expected in {"date", "datetime"} and isinstance(value, str))
            or (expected == "boolean" and isinstance(value, bool))
            or (expected == "select" and value in (definition.options.get("choices") or []))
            or (expected == "reference" and isinstance(value, (str, int)))
        )
        if not valid:
            raise HTTPException(status_code=422, detail={"code": "erp_invalid_custom_field", "key": key})
        if posted and definition.posting_relevant:
            raise HTTPException(status_code=409, detail={"code": "erp_posted_custom_field_immutable", "key": key})
    return custom


async def next_number(db: AsyncSession, organization_id: int, document_type: str) -> str:
    sequence = await db.scalar(select(ERPSequence).where(
        ERPSequence.organization_id == organization_id, ERPSequence.key == document_type
    ).with_for_update())
    if sequence is None:
        sequence = ERPSequence(organization_id=organization_id, key=document_type, prefix=f"{document_type[:3].upper()}-")
        db.add(sequence)
        await db.flush()
    number = f"{sequence.prefix}{sequence.next_number:0{sequence.padding}d}"
    sequence.next_number += 1
    return number


def calculate_lines(lines: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], Decimal, Decimal, Decimal]:
    result: list[dict[str, Any]] = []
    net = tax = Decimal("0")
    for position, source in enumerate(lines):
        quantity = Decimal(str(source.get("quantity", 1)))
        rate = as_money(source.get("rate", 0))
        tax_rate = Decimal(str(source.get("tax_rate", 0)))
        discount_percent = Decimal(str(source.get("discount_percent", 0)))
        discount_amount_input = as_money(source.get("discount_amount", 0))
        if quantity < 0 or rate < 0 or tax_rate < 0 or tax_rate > 100 or discount_percent < 0 or discount_percent > 100 or discount_amount_input < 0:
            raise ValueError("line values must be non-negative and rates must not exceed 100")
        if discount_percent and discount_amount_input:
            raise ValueError("use either discount_percent or discount_amount")
        gross_amount = as_money(quantity * rate)
        discount_amount = discount_amount_input if discount_amount_input else as_money(gross_amount * discount_percent / Decimal("100"))
        if discount_amount > gross_amount:
            raise ValueError("discount cannot exceed gross amount")
        amount = as_money(gross_amount - discount_amount)
        tax_amount = as_money(amount * tax_rate / Decimal("100"))
        result.append({**source, "quantity": quantity, "rate": rate, "gross_amount": gross_amount, "discount_percent": discount_percent, "discount_amount": discount_amount, "amount": amount, "tax_rate": tax_rate, "tax_amount": tax_amount, "position": position})
        net += amount
        tax += tax_amount
    return result, as_money(net), as_money(tax), as_money(net + tax)


async def default_account(db: AsyncSession, organization_id: int, account_type: str) -> ERPAccount:
    account = await db.scalar(select(ERPAccount).where(
        ERPAccount.organization_id == organization_id, ERPAccount.account_type == account_type,
        ERPAccount.is_active.is_(True), ERPAccount.is_group.is_(False)
    ).order_by(ERPAccount.id).limit(1))
    if not account:
        raise HTTPException(status_code=422, detail={"code": "erp_missing_account", "account_type": account_type})
    return account


async def validate_posting_gate(
    db: AsyncSession,
    organization_id: int,
    posting_date: date,
    lines: list[tuple[int, Decimal, Decimal, int | None, str | None]],
    *,
    currency: str = "MNT",
) -> None:
    """Validate the common accounting invariant before any ledger write."""
    open_periods = (await db.execute(select(ERPPostingPeriod).where(
        ERPPostingPeriod.organization_id == organization_id,
        ERPPostingPeriod.status == "open",
        ERPPostingPeriod.starts_on <= posting_date,
        ERPPostingPeriod.ends_on >= posting_date,
    ).with_for_update())).scalars().all()
    if len(open_periods) != 1:
        closed = await db.scalar(select(ERPPostingPeriod.id).where(
            ERPPostingPeriod.organization_id == organization_id,
            ERPPostingPeriod.starts_on <= posting_date,
            ERPPostingPeriod.ends_on >= posting_date,
            ERPPostingPeriod.status == "closed",
        ).limit(1))
        code = "erp_posting_period_closed" if closed and not open_periods else "erp_posting_period_ambiguous" if open_periods else "erp_posting_period_missing"
        raise HTTPException(status_code=409, detail={"code": code, "posting_date": posting_date.isoformat()})
    settings = await db.scalar(select(ERPAccountingSettings).where(ERPAccountingSettings.organization_id == organization_id))
    account_ids = {account_id for account_id, *_ in lines}
    accounts = {row.id: row for row in (await db.execute(select(ERPAccount).where(
        ERPAccount.organization_id == organization_id, ERPAccount.id.in_(account_ids)
    ))).scalars().all()}
    if len(accounts) != len(account_ids):
        raise HTTPException(status_code=422, detail={"code": "erp_account_tenant_mismatch", "account_ids": sorted(account_ids - set(accounts))})
    for account_id, debit, credit, cost_center_id, _memo in lines:
        account = accounts[account_id]
        if not account.is_active or account.is_group:
            raise HTTPException(status_code=422, detail={"code": "erp_account_not_postable", "account_id": account_id})
        if (account.currency or currency).upper() != currency.upper():
            raise HTTPException(status_code=422, detail={"code": "erp_account_currency_mismatch", "account_id": account_id, "currency": currency})
        effective_cost_center_id = cost_center_id or (settings.default_cost_center_id if settings else None)
        if account.classification in {"expense", "income"} and effective_cost_center_id is None:
            raise HTTPException(status_code=422, detail={"code": "erp_cost_center_required", "account_id": account_id})
        if effective_cost_center_id is not None:
            center = await db.scalar(select(ERPCostCenter).where(
                ERPCostCenter.id == effective_cost_center_id, ERPCostCenter.organization_id == organization_id,
                ERPCostCenter.is_active.is_(True)
            ))
            if not center:
                raise HTTPException(status_code=422, detail={"code": "erp_cost_center_invalid", "cost_center_id": effective_cost_center_id})
        if debit < 0 or credit < 0 or (debit == 0 and credit == 0) or (debit > 0 and credit > 0):
            raise HTTPException(status_code=422, detail={"code": "erp_invalid_ledger_line", "account_id": account_id})
    debit_total = sum((debit for _account, debit, _credit, _cc, _memo in lines), Decimal("0"))
    credit_total = sum((credit for _account, _debit, credit, _cc, _memo in lines), Decimal("0"))
    if debit_total != credit_total:
        raise HTTPException(status_code=422, detail={"code": "erp_unbalanced_journal", "debit": str(debit_total), "credit": str(credit_total)})


async def assert_open_posting_period(db: AsyncSession, organization_id: int, posting_date: date) -> None:
    closed = await db.scalar(select(ERPPostingPeriod.id).where(
        ERPPostingPeriod.organization_id == organization_id,
        ERPPostingPeriod.status == "closed",
        ERPPostingPeriod.starts_on <= posting_date,
        ERPPostingPeriod.ends_on >= posting_date,
    ).limit(1))
    if closed:
        raise HTTPException(status_code=409, detail={"code": "erp_posting_period_closed", "posting_date": posting_date.isoformat()})


async def approval_required(db: AsyncSession, document: ERPDocument) -> bool:
    rule = await db.scalar(select(ERPApprovalRule.id).where(
        ERPApprovalRule.organization_id == document.organization_id,
        ERPApprovalRule.resource.in_([document.document_type, "*"]),
        ERPApprovalRule.is_active.is_(True),
        ERPApprovalRule.minimum_amount <= document.grand_total,
    ).order_by(ERPApprovalRule.priority).limit(1))
    return bool(rule)


async def stock_balance_for(db: AsyncSession, organization_id: int, item_id: int, warehouse_id: int) -> Decimal:
    value = await db.scalar(select(func.coalesce(func.sum(ERPStockLedgerEntry.quantity_delta), 0)).where(
        ERPStockLedgerEntry.organization_id == organization_id,
        ERPStockLedgerEntry.item_id == item_id,
        ERPStockLedgerEntry.warehouse_id == warehouse_id,
    ))
    return Decimal(str(value or 0))


async def assert_stock_policy(db: AsyncSession, document: ERPDocument, lines: list[ERPDocumentLine]) -> None:
    movement = str((document.payload or {}).get("movement_type", "receipt"))
    issue = document.document_type == "delivery" or (document.document_type == "stock_entry" and movement in {"issue", "transfer"})
    if not issue:
        return
    organization = await db.get(Organization, document.organization_id)
    allow_negative = bool(((organization.settings or {}).get("erp_stock_policy") or {}).get("allow_negative_stock", False)) if organization else False
    if allow_negative:
        return
    for line in lines:
        if not line.item_id or not line.warehouse_id:
            continue
        available = await stock_balance_for(db, document.organization_id, line.item_id, line.warehouse_id)
        if available - line.quantity < 0:
            raise HTTPException(status_code=409, detail={"code": "erp_negative_stock", "item_id": line.item_id, "warehouse_id": line.warehouse_id, "available": str(available), "requested": str(line.quantity)})


async def apply_payment_allocations(db: AsyncSession, document: ERPDocument) -> None:
    allocations = list((document.payload or {}).get("allocations") or [])
    if not allocations:
        return
    direction = str((document.payload or {}).get("direction", "receive"))
    expected_type = "sales_invoice" if direction == "receive" else "purchase_invoice"
    allocated = Decimal("0")
    for raw in allocations:
        try:
            invoice_id, amount = int(raw["invoice_id"]), as_money(raw["amount"])
        except (KeyError, TypeError, ValueError):
            raise HTTPException(status_code=422, detail={"code": "erp_invalid_payment_allocation"})
        invoice = await db.scalar(select(ERPDocument).where(
            ERPDocument.id == invoice_id, ERPDocument.organization_id == document.organization_id,
        ).with_for_update())
        if not invoice or invoice.document_type != expected_type or invoice.status != "submitted" or invoice.party_id != document.party_id:
            raise HTTPException(status_code=422, detail={"code": "erp_invalid_payment_invoice", "invoice_id": invoice_id})
        if amount <= 0 or amount > invoice.outstanding_amount:
            raise HTTPException(status_code=422, detail={"code": "erp_invalid_payment_amount", "invoice_id": invoice_id})
        invoice.outstanding_amount = as_money(invoice.outstanding_amount - amount)
        db.add(ERPPaymentAllocation(payment_document_id=document.id, invoice_document_id=invoice.id, amount=amount))
        allocated += amount
    if allocated != document.grand_total:
        raise HTTPException(status_code=422, detail={"code": "erp_payment_allocation_mismatch", "allocated": str(allocated), "payment": str(document.grand_total)})


async def post_document(db: AsyncSession, document: ERPDocument, actor: ActorContext) -> None:
    """Create append-only financial and stock movements in the same transaction."""
    if document.document_type in {"salary_structure", "payroll_run", "salary_slip"}:
        # Legacy payroll documents remain readable for migration/audit purposes,
        # but all new calculation and posting is owned by app.payroll.
        raise HTTPException(status_code=410, detail={"code": "payroll_use_dedicated_api", "path": "/v1/erp/payroll"})
    await assert_open_posting_period(db, document.organization_id, document.posting_date)
    already_posted = await db.scalar(select(ERPGeneralLedgerEntry.id).where(ERPGeneralLedgerEntry.document_id == document.id).limit(1))
    if not already_posted:
        already_posted = await db.scalar(select(ERPStockLedgerEntry.id).where(ERPStockLedgerEntry.document_id == document.id).limit(1))
    if already_posted:
        document.status = "submitted"
        return
    lines = (await db.execute(select(ERPDocumentLine).where(ERPDocumentLine.document_id == document.id))).scalars().all()
    await validate_phase5_chain(db, document, lines)
    await assert_stock_policy(db, document, lines)
    gl: list[tuple[int, Decimal, Decimal, str | None]] = []
    if document.document_type == "journal_entry":
        for line in lines:
            if not line.account_id:
                raise HTTPException(status_code=422, detail="Journal lines require an account")
            debit = as_money((line.data or {}).get("debit", 0))
            credit = as_money((line.data or {}).get("credit", 0))
            if bool(debit) == bool(credit):
                raise HTTPException(status_code=422, detail="Journal line needs exactly one debit or credit")
            gl.append((line.account_id, debit, credit, line.description))
    elif document.document_type == "sales_invoice":
        receivable, income = await default_account(db, document.organization_id, "receivable"), await default_account(db, document.organization_id, "income")
        gl = [(receivable.id, document.grand_total, Decimal("0"), "Customer receivable"), (income.id, Decimal("0"), document.net_total, "Sales income")]
        if document.tax_total:
            tax = await default_account(db, document.organization_id, "tax_payable")
            gl.append((tax.id, Decimal("0"), document.tax_total, "Sales tax"))
    elif document.document_type == "sales_credit_note":
        receivable, income = await default_account(db, document.organization_id, "receivable"), await default_account(db, document.organization_id, "income")
        gl = [(income.id, document.net_total, Decimal("0"), "Sales credit note"), (receivable.id, Decimal("0"), document.grand_total, "Customer credit")]
        if document.tax_total:
            tax = await default_account(db, document.organization_id, "tax_payable")
            gl.append((tax.id, document.tax_total, Decimal("0"), "Sales tax reversal"))
    elif document.document_type == "purchase_invoice":
        expense, payable = await default_account(db, document.organization_id, "expense"), await default_account(db, document.organization_id, "payable")
        gl = [(expense.id, document.net_total, Decimal("0"), "Purchase expense"), (payable.id, Decimal("0"), document.grand_total, "Supplier payable")]
        if document.tax_total:
            tax = await default_account(db, document.organization_id, "tax_receivable")
            gl.append((tax.id, document.tax_total, Decimal("0"), "Purchase tax"))
    elif document.document_type == "purchase_debit_note":
        expense, payable = await default_account(db, document.organization_id, "expense"), await default_account(db, document.organization_id, "payable")
        gl = [(payable.id, document.grand_total, Decimal("0"), "Supplier debit note"), (expense.id, Decimal("0"), document.net_total, "Purchase expense reversal")]
        if document.tax_total:
            tax = await default_account(db, document.organization_id, "tax_receivable")
            gl.append((tax.id, Decimal("0"), document.tax_total, "Purchase tax reversal"))
    elif document.document_type == "payment_entry":
        direction = str((document.payload or {}).get("direction", "receive"))
        cash = await default_account(db, document.organization_id, "cash")
        counter = await default_account(db, document.organization_id, "receivable" if direction == "receive" else "payable")
        if direction == "receive":
            gl = [(cash.id, document.grand_total, Decimal("0"), "Payment received"), (counter.id, Decimal("0"), document.grand_total, "Customer settlement")]
        else:
            gl = [(counter.id, document.grand_total, Decimal("0"), "Supplier settlement"), (cash.id, Decimal("0"), document.grand_total, "Payment made")]
    elif document.document_type == "payroll_run":
        expense, payable = await default_account(db, document.organization_id, "payroll_expense"), await default_account(db, document.organization_id, "payroll_payable")
        gl = [(expense.id, document.grand_total, Decimal("0"), "Payroll accrual"), (payable.id, Decimal("0"), document.grand_total, "Payroll payable")]
    elif document.document_type == "asset":
        asset, payable = await default_account(db, document.organization_id, "fixed_asset"), await default_account(db, document.organization_id, "payable")
        gl = [(asset.id, document.grand_total, Decimal("0"), "Asset capitalization"), (payable.id, Decimal("0"), document.grand_total, "Asset payable")]
    elif document.document_type in {"stock_entry", "purchase_receipt", "delivery", "work_order"}:
        total_value = as_money(sum((Decimal(str(line.amount or 0)) for line in lines), Decimal("0")))
        if total_value:
            movement = str((document.payload or {}).get("movement_type", "receipt"))
            issue = document.document_type == "delivery" or (document.document_type == "stock_entry" and movement == "issue")
            inventory = await default_account(db, document.organization_id, "inventory")
            contra = await default_account(db, document.organization_id, "expense" if issue else "payable")
            if movement == "transfer":
                gl = [(inventory.id, total_value, Decimal("0"), "Inventory transfer out"), (inventory.id, Decimal("0"), total_value, "Inventory transfer in")]
            else:
                gl = [(contra.id, total_value, Decimal("0"), "Stock issue" if issue else "Stock receipt"), (inventory.id, Decimal("0"), total_value, "Inventory movement")] if issue else [(inventory.id, total_value, Decimal("0"), "Inventory receipt"), (contra.id, Decimal("0"), total_value, "Stock receipt")]
    elif document.document_type == "stock_reconciliation":
        adjustment = Decimal("0")
        for line in lines:
            if not line.item_id or not line.warehouse_id or (line.data or {}).get("actual_quantity") is None:
                continue
            current = await stock_balance_for(db, document.organization_id, line.item_id, line.warehouse_id)
            item = await db.get(ERPItem, line.item_id)
            adjustment += (Decimal(str((line.data or {}).get("actual_quantity"))) - current) * Decimal(str(item.standard_cost if item else line.rate))
        if adjustment:
            inventory = await default_account(db, document.organization_id, "inventory")
            contra = await default_account(db, document.organization_id, "expense")
            amount = as_money(abs(adjustment))
            gl = [(inventory.id, amount, Decimal("0"), "Inventory reconciliation adjustment"), (contra.id, Decimal("0"), amount, "Inventory reconciliation adjustment")] if adjustment > 0 else [(contra.id, amount, Decimal("0"), "Inventory reconciliation loss"), (inventory.id, Decimal("0"), amount, "Inventory reconciliation loss")]
    await validate_posting_gate(
        db, document.organization_id, document.posting_date,
        [(account_id, debit_amount, credit_amount, (document.payload or {}).get("cost_center_id"), memo)
         for account_id, debit_amount, credit_amount, memo in gl],
        currency=document.currency,
    )
    if gl:
        db.add_all([ERPGeneralLedgerEntry(
            organization_id=document.organization_id, document_id=document.id, account_id=account_id, party_id=document.party_id,
            posting_date=document.posting_date, debit=debit_amount, credit=credit_amount, memo=memo,
        ) for account_id, debit_amount, credit_amount, memo in gl])
    if document.document_type in {"stock_entry", "stock_reconciliation", "purchase_receipt", "delivery", "work_order"}:
        for line in lines:
            if not line.item_id or not line.warehouse_id:
                continue
            movement = str((document.payload or {}).get("movement_type", "receipt"))
            if document.document_type == "stock_reconciliation":
                actual_raw = (line.data or {}).get("actual_quantity")
                if actual_raw is None:
                    raise HTTPException(status_code=422, detail={"code": "erp_reconciliation_actual_quantity_required", "line_id": line.id})
                if Decimal(str(actual_raw)) < 0:
                    raise HTTPException(status_code=422, detail={"code": "erp_reconciliation_quantity_negative", "line_id": line.id})
                current = await stock_balance_for(db, document.organization_id, line.item_id, line.warehouse_id)
                quantity = Decimal(str(actual_raw)) - current
                direction = 1
            else:
                direction = -1 if document.document_type == "delivery" or (document.document_type == "stock_entry" and movement in {"issue", "transfer"}) else 1
                quantity = line.quantity * direction
            item = await db.get(ERPItem, line.item_id)
            level = await db.scalar(select(ERPInventoryLevel).where(
                ERPInventoryLevel.organization_id == document.organization_id, ERPInventoryLevel.item_id == line.item_id,
                ERPInventoryLevel.warehouse_id == line.warehouse_id,
            ).with_for_update())
            if level is None:
                level = ERPInventoryLevel(organization_id=document.organization_id, item_id=line.item_id, warehouse_id=line.warehouse_id)
                db.add(level)
            issue = quantity < 0
            valuation_rate = as_money((level.valuation_rate if issue and level.valuation_rate else (item.standard_cost if item else line.rate)))
            movement_value = as_money(abs(quantity) * valuation_rate)
            db.add(ERPStockLedgerEntry(
                organization_id=document.organization_id, document_id=document.id, item_id=line.item_id, warehouse_id=line.warehouse_id,
                posting_date=document.posting_date, quantity_delta=quantity, value_delta=as_money(movement_value * (-1 if quantity < 0 else 1)), valuation_rate=valuation_rate,
            ))
            level.quantity = level.quantity + quantity
            level.valuation_rate = valuation_rate
            level.inventory_value = as_money(level.quantity * valuation_rate)
            db.add(ERPStockValuationLayer(
                organization_id=document.organization_id, document_id=document.id, item_id=line.item_id, warehouse_id=line.warehouse_id,
                quantity=quantity, remaining_quantity=max(quantity, Decimal("0")), unit_cost=valuation_rate,
                value=as_money(movement_value * (-1 if quantity < 0 else 1)), valuation_method=(item.valuation_method if item else "moving_average"),
            ))
            target_warehouse_id = (line.data or {}).get("target_warehouse_id") if movement == "transfer" else None
            if target_warehouse_id and int(target_warehouse_id) != line.warehouse_id:
                target = await db.scalar(select(ERPWarehouse).where(ERPWarehouse.id == int(target_warehouse_id), ERPWarehouse.organization_id == document.organization_id, ERPWarehouse.is_active.is_(True)).with_for_update())
                if not target:
                    raise HTTPException(status_code=422, detail={"code": "erp_invalid_transfer_warehouse"})
                db.add(ERPStockLedgerEntry(
                    organization_id=document.organization_id, document_id=document.id, item_id=line.item_id, warehouse_id=target.id,
                    posting_date=document.posting_date, quantity_delta=line.quantity, value_delta=as_money(line.amount), valuation_rate=valuation_rate,
                ))
                target_level = await db.scalar(select(ERPInventoryLevel).where(
                    ERPInventoryLevel.organization_id == document.organization_id, ERPInventoryLevel.item_id == line.item_id,
                    ERPInventoryLevel.warehouse_id == target.id,
                ).with_for_update())
                if target_level is None:
                    target_level = ERPInventoryLevel(organization_id=document.organization_id, item_id=line.item_id, warehouse_id=target.id)
                    db.add(target_level)
                target_level.quantity += line.quantity
                target_level.valuation_rate = valuation_rate
                target_level.inventory_value = as_money(target_level.quantity * valuation_rate)
                db.add(ERPStockValuationLayer(
                    organization_id=document.organization_id, document_id=document.id, item_id=line.item_id, warehouse_id=target.id,
                    quantity=line.quantity, remaining_quantity=line.quantity, unit_cost=valuation_rate,
                    value=as_money(line.amount), valuation_method=(item.valuation_method if item else "moving_average"),
                ))
    if document.document_type == "payment_entry":
        await apply_payment_allocations(db, document)
    document.status = "submitted"
    document.submitted_at = datetime.now(timezone.utc)
    document.submitted_by_account_id = actor.account_id
    document.version += 1


async def cancel_document(db: AsyncSession, document: ERPDocument) -> None:
    entries = (await db.execute(select(ERPGeneralLedgerEntry).where(ERPGeneralLedgerEntry.document_id == document.id))).scalars().all()
    stock_entries = (await db.execute(select(ERPStockLedgerEntry).where(ERPStockLedgerEntry.document_id == document.id))).scalars().all()
    db.add_all([ERPGeneralLedgerEntry(
        organization_id=row.organization_id, document_id=document.id, account_id=row.account_id, party_id=row.party_id,
        posting_date=document.posting_date, debit=row.credit, credit=row.debit, memo=f"Reversal of {row.id}", reversal_of_id=row.id,
    ) for row in entries])
    db.add_all([ERPStockLedgerEntry(
        organization_id=row.organization_id, document_id=document.id, item_id=row.item_id, warehouse_id=row.warehouse_id,
        posting_date=document.posting_date, quantity_delta=-row.quantity_delta, value_delta=-row.value_delta, valuation_rate=row.valuation_rate,
    ) for row in stock_entries])
    for row in stock_entries:
        level = await db.scalar(select(ERPInventoryLevel).where(
            ERPInventoryLevel.organization_id == row.organization_id, ERPInventoryLevel.item_id == row.item_id,
            ERPInventoryLevel.warehouse_id == row.warehouse_id,
        ).with_for_update())
        if level:
            level.quantity = level.quantity - row.quantity_delta
            level.inventory_value = as_money(level.quantity * level.valuation_rate)
    allocations = (await db.execute(select(ERPPaymentAllocation).where(ERPPaymentAllocation.payment_document_id == document.id))).scalars().all()
    for allocation in allocations:
        invoice = await db.scalar(select(ERPDocument).where(ERPDocument.id == allocation.invoice_document_id).with_for_update())
        if invoice:
            invoice.outstanding_amount = as_money(invoice.outstanding_amount + allocation.amount)
    document.status = "cancelled"
    document.cancelled_at = datetime.now(timezone.utc)
    document.version += 1


def document_out(document: ERPDocument, lines: list[ERPDocumentLine] | None = None) -> dict[str, Any]:
    result = {
        "id": document.id, "public_id": str(document.public_id), "document_type": document.document_type, "number": document.number,
        "status": document.status, "party_id": document.party_id, "project_id": document.project_id, "source_document_id": document.source_document_id,
        "amended_from_id": document.amended_from_id, "currency": document.currency, "exchange_rate": str(document.exchange_rate),
        "posting_date": document.posting_date.isoformat(), "due_date": document.due_date.isoformat() if document.due_date else None,
        "net_total": str(document.net_total), "tax_total": str(document.tax_total), "grand_total": str(document.grand_total),
        "outstanding_amount": str(document.outstanding_amount), "payload": document.payload, "custom": document.custom,
        "definition_version": document.definition_version, "workflow_state": document.workflow_state, "version": document.version,
        "archived_at": document.archived_at.isoformat() if document.archived_at else None,
    }
    if lines is not None:
        result["lines"] = [{"id": line.id, "item_id": line.item_id, "warehouse_id": line.warehouse_id, "account_id": line.account_id,
            "description": line.description, "quantity": str(line.quantity), "rate": str(line.rate), "amount": str(line.amount),
            "discount_percent": str(line.discount_percent), "discount_amount": str(line.discount_amount),
            "tax_rate": str(line.tax_rate), "tax_amount": str(line.tax_amount), "data": line.data} for line in lines]
    return result
