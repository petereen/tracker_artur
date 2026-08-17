from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.erp.service import DEFAULT_ACCOUNTS, DOCUMENT_MODULES, ERP_MODULES, calculate_lines, module_settings, operation_catalog, validate_definition_fields, validate_form_values, validate_workflow
from app.main import app
from app.models.models import Base
from app.services.mcp.catalog import CATALOG


def test_erp_schema_registers_tenant_scoped_configurable_records():
    required = {
        "erp_access_roles", "erp_capabilities", "erp_account_roles", "erp_custom_fields", "erp_sequences",
        "erp_parties", "erp_items", "erp_warehouses", "erp_accounts", "erp_documents", "erp_document_lines",
        "erp_general_ledger_entries", "erp_stock_ledger_entries", "erp_posting_periods", "erp_approval_rules", "erp_payment_allocations", "erp_import_batches",
        "erp_team_roles", "erp_form_definitions", "erp_master_requests", "erp_workflow_transitions",
        "erp_module_configs", "erp_units_of_measure", "erp_price_lists", "erp_price_list_entries", "erp_discount_tiers",
        "erp_reorder_rules", "erp_cost_centers", "erp_tax_templates", "erp_tax_template_rates", "erp_inventory_levels",
    }
    assert required.issubset(Base.metadata.tables)
    assert Base.metadata.tables["erp_documents"].c.organization_id.nullable is False
    assert Base.metadata.tables["erp_general_ledger_entries"].c.document_id.nullable is False


def test_erp_module_visibility_defaults_off_and_ignores_unknown_keys():
    assert module_settings({}) == {module: False for module in ERP_MODULES}
    settings = module_settings({"erp_modules": {"stock": True, "unknown": True}})
    assert settings["stock"] is True
    assert "unknown" not in settings


def test_erp_document_line_totals_are_decimal_and_tax_exclusive():
    lines, net, tax, total = calculate_lines([
        {"description": "Widget", "quantity": "2.5", "rate": "10.125", "tax_rate": "10"},
        {"description": "Service", "quantity": 1, "rate": "5", "tax_rate": 0},
    ])
    assert lines[0]["amount"] == Decimal("25.3125")
    assert net == Decimal("30.3125")
    assert tax == Decimal("2.5313")
    assert total == Decimal("32.8438")


def test_erp_document_line_totals_apply_discount_before_vat():
    lines, net, tax, total = calculate_lines([{
        "description": "Discounted widget", "quantity": "2", "rate": "100", "discount_percent": "10", "tax_rate": "10",
    }])
    assert lines[0]["gross_amount"] == Decimal("200.0000")
    assert lines[0]["discount_amount"] == Decimal("20.0000")
    assert net == Decimal("180.0000")
    assert tax == Decimal("18.0000")
    assert total == Decimal("198.0000")


def test_erp_routes_are_versioned_and_cover_meta_masters_documents_and_reports():
    paths = {route.path for route in app.routes}
    assert {
        "/v1/erp/meta", "/v1/erp/admin/modules", "/v1/erp/masters/parties", "/v1/erp/masters/items",
        "/v1/erp/accounting/accounts", "/v1/erp/documents/{document_type}", "/v1/erp/documents/by-id/{document_id}/submit",
        "/v1/erp/reports/dashboard", "/v1/erp/reports/stock-balance", "/v1/erp/reports/general-ledger", "/v1/erp/reports/trial-balance",
        "/v1/erp/accounting/posting-periods", "/v1/erp/admin/approval-rules", "/v1/erp/stock/policy",
        "/v1/erp/imports/preview", "/v1/erp/imports/csv", "/v1/erp/imports/{batch_id}/commit", "/v1/erp/manufacturing/boms/{document_id}/costing",
        "/v1/erp/catalog", "/v1/erp/admin/forms/{operation}", "/v1/erp/admin/forms/{operation}/publish", "/v1/erp/master-requests/{operation}", "/v1/erp/documents/by-id/{document_id}/transition",
        "/v1/erp/documents/by-id/{document_id}/archive", "/v1/erp/documents/by-id/{document_id}/restore",
    }.issubset(paths)


def test_every_broad_mvp_document_domain_has_an_explicit_module():
    expected = {"journal_entry", "quotation", "purchase_invoice", "stock_entry", "lead", "support_ticket", "payroll_run", "work_order", "maintenance_schedule"}
    assert expected.issubset(DOCUMENT_MODULES)


def test_erp_builder_catalog_is_server_owned_and_covers_documents_and_master_requests():
    catalog = operation_catalog()
    assert {"sales_order", "purchase_order", "stock_entry", "party", "item", "supplier", "customer", "uom", "tax_template"}.issubset(catalog["operations"])
    assert {"reference", "multi_select", "money"}.issubset(catalog["field_types"])
    assert {"warehouse_ids", "project_ids", "branch_codes"}.issubset(catalog["scope_dimensions"])


def test_form_field_validation_separates_document_lines_from_master_requests():
    fields = validate_definition_fields("sales_order", [
        {"key": "customer_note", "label": "Customer note", "field_type": "long_text", "section": "header"},
        {"key": "batch", "label": "Batch", "field_type": "text", "section": "line", "required": True},
    ])
    assert validate_form_values(fields, {"batch": "A-1"}, "line") == {"batch": "A-1"}
    with pytest.raises(HTTPException) as error:
        validate_form_values(fields, {"other": "x"}, "line")
    assert error.value.detail["code"] == "erp_unknown_form_field"
    with pytest.raises(HTTPException) as error:
        validate_definition_fields("item", [{"key": "bad", "label": "Bad", "field_type": "text", "section": "line"}])
    assert error.value.detail["code"] == "erp_invalid_form_field"


def test_workflow_validation_requires_safe_terminal_states_and_role_references():
    workflow = {
        "initial_state": "draft",
        "states": [{"key": "draft"}, {"key": "approved", "terminal": True}, {"key": "rejected", "terminal": True}, {"key": "cancelled", "terminal": True}],
        "transitions": [{"from": "draft", "to": "approved", "label": "Approve", "role_ids": [4]}],
    }
    assert validate_workflow(workflow, {4}, posting_capable=True)["initial_state"] == "draft"
    with pytest.raises(HTTPException) as error:
        validate_workflow(workflow, set(), posting_capable=True)
    assert error.value.detail["code"] == "erp_unknown_workflow_role"


def test_erp_default_chart_supports_invoice_payroll_and_asset_posting():
    types = {account_type for _code, _name, account_type in DEFAULT_ACCOUNTS}
    assert {"receivable", "payable", "income", "expense", "payroll_expense", "payroll_payable", "fixed_asset"}.issubset(types)


def test_mcp_catalog_exposes_read_only_erp_data_without_posting_actions():
    tool = next(item for item in CATALOG if item.name == "oyuns_erp_read")
    assert tool.access_mode == "read"
    assert "never creates" in tool.description
