"""Chart of accounts («Данс код», d047) rules shared by payroll, budget and posting."""
import importlib.util
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.erp.chart import PURPOSES, account_usage, catalog, classify_import, descendant_ids, posting_type, validate_purpose
from app.erp.router import AccountInput, _account_values, _normalize_account_values
from app.erp.service import ACCOUNT_METADATA, DEFAULT_ACCOUNTS, LEGACY_DEFAULT_ACCOUNT_NAMES
from app.main import app


def _account(**overrides):
    return AccountInput.model_validate({"code": "1000", "name": "Касс", "classification": "asset", "purpose": "cash", **overrides})


def test_editing_an_account_keeps_its_posting_type():
    # Regression: create/update used to store the bare classification, so an
    # edited «Cash» account was no longer found by default_account("cash").
    assert _account_values(_account())["account_type"] == "cash"
    assert _account_values(_account(code="2340", classification="liability", purpose="pit_payable"))["account_type"] == "tax_payable"
    assert _account_values(_account(code="2200", purpose="tax"))["account_type"] == "tax_receivable"
    assert _account_values(_account(code="9000", classification="equity", purpose="general"))["account_type"] == "equity"


def test_client_supplied_account_type_cannot_override_purpose():
    values = _account_values(_account(account_type="expense"))
    assert (values["classification"], values["purpose"], values["account_type"]) == ("asset", "cash", "cash")


def test_legacy_account_type_only_input_is_classified():
    values = _account_values(AccountInput.model_validate({"code": "4100", "name": "Үйлчилгээний орлого", "account_type": "income"}))
    assert (values["classification"], values["purpose"], values["account_type"]) == ("income", "revenue", "income")


def test_purpose_must_match_classification():
    with pytest.raises(HTTPException) as error:
        _account_values(_account(classification="expense"))
    assert error.value.detail["code"] == "erp_account_classification_invalid"
    assert error.value.detail["allowed"] == ["asset"]
    with pytest.raises(HTTPException) as error:
        _normalize_account_values({"purpose": "salary_expense", "classification": "liability", "currency": "MNT"})
    assert error.value.detail["code"] == "payroll_account_classification_invalid"
    with pytest.raises(HTTPException) as error:
        validate_purpose({"purpose": "made_up", "classification": "asset"})
    assert error.value.detail["code"] == "erp_account_purpose_invalid"


def test_bank_details_are_kept_only_on_cash_and_bank_accounts():
    bank = _account_values(_account(purpose="bank", bank_name=" Хаан банк ", bank_iban="mn12 0005 00", bank_account_number="5012345678"))
    assert bank["bank_name"] == "Хаан банк" and bank["bank_iban"] == "MN12000500" and bank["account_type"] == "cash"
    expense = _account_values(_account(code="5000", classification="expense", purpose="expense", bank_name="Хаан банк"))
    assert expense["bank_name"] is None and expense["bank_iban"] is None


def test_import_types_map_to_classification_and_purpose():
    assert classify_import("Bank") == ("cash", "asset", "bank")
    assert classify_import("Income Account") == ("income", "income", "revenue")
    assert classify_import("tax_payable") == ("tax_payable", "liability", "tax")
    assert classify_import("something odd") == ("asset", "asset", "general")


def test_seeded_chart_is_consistent_with_purpose_rules():
    for code, name, seeded_type in DEFAULT_ACCOUNTS:
        classification, purpose = ACCOUNT_METADATA[code]
        validate_purpose({"purpose": purpose, "classification": classification})
        assert seeded_type == posting_type(purpose, classification), code
        assert name not in LEGACY_DEFAULT_ACCOUNT_NAMES[code], "seed names must be the clear Mongolian ones"
        assert not name.isascii(), code
    assert set(LEGACY_DEFAULT_ACCOUNT_NAMES) == {code for code, _name, _type in DEFAULT_ACCOUNTS}
    # Document posting looks these up by account_type; each must be seeded.
    seeded_types = {seeded_type for _code, _name, seeded_type in DEFAULT_ACCOUNTS}
    assert {"cash", "receivable", "payable", "income", "expense", "tax_payable", "tax_receivable", "inventory", "fixed_asset", "payroll_expense", "payroll_payable"} <= seeded_types


def test_migration_mirrors_the_chart_rules():
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "f7a8b9c0d1e2_chart_of_accounts_clarity.py"
    spec = importlib.util.spec_from_file_location("chart_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.POSTING_TYPES == {purpose: posting_type(purpose, allowed[0]) for purpose, (_label, allowed, _module, kind) in PURPOSES.items() if kind}
    assert {code: name for code, (name, _legacy) in module.RENAMES.items()} == {code: name for code, name, _type in DEFAULT_ACCOUNTS}


def test_catalog_describes_every_purpose():
    data = catalog()
    assert [row["key"] for row in data["purposes"]] == list(PURPOSES)
    assert {row["key"] for row in data["classifications"]} == {"asset", "liability", "equity", "income", "expense"}
    assert next(row for row in data["purposes"] if row["key"] == "bank")["has_bank_details"] is True


def test_descendants_detect_parent_cycles():
    parents = {1: None, 2: 1, 3: 2, 4: None}
    assert descendant_ids(parents, 1) == {2, 3}
    assert descendant_ids(parents, 4) == set()


def test_account_routes_are_registered():
    paths = {route.path for route in app.routes}
    assert {"/v1/erp/accounting/accounts/usage", "/v1/erp/accounting/accounts/catalog"} <= paths
    assert callable(account_usage)
