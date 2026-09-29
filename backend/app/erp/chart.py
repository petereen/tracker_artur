"""Chart of accounts («Данс код», Dayansoft d047) rules shared by every module.

Payroll, budget, assets and settlements all pick accounts from the same
``erp_accounts`` table, so the purpose ↔ classification contract and the
"where is this account used" answer live here instead of in each module.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Base, ERPAccount, PayrollPostingProfile

CLASSIFICATIONS = ("asset", "liability", "equity", "income", "expense")

# Purpose → classifications it may carry. ``general`` fits any classification.
# ``tax`` covers both VAT payable (liability) and VAT receivable (asset).
PURPOSE_CLASSIFICATIONS: dict[str, frozenset[str]] = {
    "general": frozenset(CLASSIFICATIONS),
    "cash": frozenset({"asset"}), "bank": frozenset({"asset"}), "receivable": frozenset({"asset"}),
    "inventory": frozenset({"asset"}), "fixed_asset": frozenset({"asset"}), "wip": frozenset({"asset"}),
    "accumulated_depreciation": frozenset({"asset"}), "advance_clearing": frozenset({"asset"}),
    "tax": frozenset({"asset", "liability"}),
    "payable": frozenset({"liability"}), "payroll_payable": frozenset({"liability"}),
    "net_pay_payable": frozenset({"liability"}), "employee_shi_payable": frozenset({"liability"}),
    "employer_shi_payable": frozenset({"liability"}), "pit_payable": frozenset({"liability"}),
    "other_deductions_payable": frozenset({"liability"}),
    "revenue": frozenset({"income"}),
    "expense": frozenset({"expense"}), "salary_expense": frozenset({"expense"}),
    "employer_shi_expense": frozenset({"expense"}), "depreciation_expense": frozenset({"expense"}),
}
PAYROLL_PURPOSES = frozenset({
    "salary_expense", "employer_shi_expense", "employee_shi_payable", "employer_shi_payable",
    "pit_payable", "net_pay_payable", "bank", "advance_clearing", "other_deductions_payable",
})
BANK_FIELDS = ("bank_name", "bank_iban", "bank_account_number", "bank_account_holder")

# Monthly payroll «Дүн» sheet accounts: field → required classification.
MONTHLY_PAYROLL_ACCOUNT_CLASSIFICATIONS = {
    "salary_expense_account_id": ("expense", "Цалингийн зардлын данс"),
    "employer_shi_account_id": ("expense", "Ажил олгогчийн НДШ-ийн зардлын данс"),
    "advance_clearing_account_id": ("asset", "Урьдчилгааны тооцооны данс"),
}
CLASSIFICATION_LABELS = {"asset": "Хөрөнгө", "liability": "Өр төлбөр", "equity": "Эздийн өмч", "income": "Орлого", "expense": "Зардал"}

# Where an account is referenced, in the words of the page that references it.
USAGE_LABELS: dict[tuple[str, str], tuple[str, str]] = {
    ("erp_general_ledger_entries", "account_id"): ("accounting", "Ерөнхий дэвтрийн гүйлгээ"),
    ("erp_document_lines", "account_id"): ("accounting", "Баримтын мөр"),
    ("erp_accounts", "parent_id"): ("accounting", "Дэд данс"),
    ("erp_accounting_settings", "default_bank_account_id"): ("accounting", "Үндсэн харилцах данс"),
    ("erp_tax_template_rates", "account_id"): ("accounting", "Татварын загвар"),
    ("erp_parties", "settlement_account_id"): ("crm", "Харилцагчийн тооцооны данс"),
    ("erp_party_groups", "default_settlement_account_id"): ("crm", "Харилцагчийн бүлгийн тооцооны данс"),
    ("budget_account_links", "erp_account_id"): ("budget", "Төсөвт данс"),
    ("monthly_payroll_company_settings", "salary_expense_account_id"): ("payroll", "Цалингийн зардлын данс"),
    ("monthly_payroll_company_settings", "employer_shi_account_id"): ("payroll", "Ажил олгогчийн НДШ-ийн данс"),
    ("monthly_payroll_company_settings", "advance_clearing_account_id"): ("payroll", "Урьдчилгааны тооцооны данс"),
    ("payroll_account_tags", "account_id"): ("payroll", "Цалингийн дансны тэмдэглэгээ"),
    ("payroll_runs", "payment_account_id"): ("payroll", "Цалингийн төлбөрийн данс"),
    ("payroll_payment_batches", "payment_account_id"): ("payroll", "Цалингийн төлбөрийн багц"),
    ("payroll_payment_batches", "payable_account_id"): ("payroll", "Цалингийн өглөгийн багц"),
    ("payroll_bank_entries", "payment_account_id"): ("payroll", "Цалингийн банкны гүйлгээ"),
    ("payroll_statement_imports", "payment_account_id"): ("payroll", "Банкны хуулгын импорт"),
    ("salary_components", "account_id"): ("payroll", "Цалингийн бүрэлдэхүүн"),
    ("payroll_salary_component_masters", "account_id"): ("payroll", "Цалингийн бүрэлдэхүүн"),
    ("payslip_line_items", "account_id"): ("payroll", "Цалингийн хуудасны мөр"),
}


# ``account_type`` is what document posting looks accounts up by
# (``service.default_account``), so it is derived from the purpose and never
# edited directly — otherwise renaming «Касс» would break payment posting.
PURPOSE_POSTING_TYPES = {
    "cash": "cash", "bank": "cash", "receivable": "receivable", "advance_clearing": "receivable",
    "inventory": "inventory", "fixed_asset": "fixed_asset", "accumulated_depreciation": "fixed_asset", "wip": "wip",
    "payable": "payable", "payroll_payable": "payroll_payable", "net_pay_payable": "payroll_payable",
    "employee_shi_payable": "payroll_payable", "employer_shi_payable": "payroll_payable", "other_deductions_payable": "payroll_payable",
    "pit_payable": "tax_payable", "revenue": "income", "expense": "expense", "depreciation_expense": "expense",
    "salary_expense": "payroll_expense", "employer_shi_expense": "payroll_expense",
}
# Imported ``account_type`` (generic CSV or ERPNext root/account type) → (classification, purpose).
IMPORT_TYPES = {
    "asset": ("asset", "general"), "cash": ("asset", "cash"), "bank": ("asset", "bank"), "receivable": ("asset", "receivable"),
    "inventory": ("asset", "inventory"), "stock": ("asset", "inventory"), "fixed_asset": ("asset", "fixed_asset"),
    "accumulated_depreciation": ("asset", "accumulated_depreciation"), "wip": ("asset", "wip"), "tax_receivable": ("asset", "tax"),
    "liability": ("liability", "general"), "payable": ("liability", "payable"), "tax_payable": ("liability", "tax"), "tax": ("liability", "tax"),
    "payroll_payable": ("liability", "payroll_payable"), "equity": ("equity", "general"),
    "income": ("income", "revenue"), "income_account": ("income", "revenue"),
    "expense": ("expense", "expense"), "expense_account": ("expense", "expense"), "payroll_expense": ("expense", "salary_expense"),
    "depreciation": ("expense", "depreciation_expense"), "cost_of_goods_sold": ("expense", "expense"),
}


def posting_type(purpose: str, classification: str) -> str:
    if purpose == "tax":
        return "tax_receivable" if classification == "asset" else "tax_payable"
    return PURPOSE_POSTING_TYPES.get(purpose, classification)


def classify_import(raw_type: str) -> tuple[str, str, str]:
    """(account_type, classification, purpose) for an imported account row."""
    key = raw_type.casefold().strip().replace(" ", "_")
    classification, purpose = IMPORT_TYPES.get(key, ("asset", "general"))
    return posting_type(purpose, classification), classification, purpose


def validate_purpose(values: dict[str, Any]) -> None:
    purpose, classification = values["purpose"], values["classification"]
    allowed = PURPOSE_CLASSIFICATIONS.get(purpose)
    if allowed is None:
        raise HTTPException(status_code=422, detail={"code": "erp_account_purpose_unknown", "purpose": purpose})
    if classification not in allowed:
        code = "payroll_account_classification_invalid" if purpose in PAYROLL_PURPOSES else "erp_account_purpose_classification_invalid"
        raise HTTPException(status_code=422, detail={"code": code, "purpose": purpose, "allowed": sorted(allowed)})


def _account_fk_columns() -> list[tuple[Any, Any]]:
    return [(table, column) for table in Base.metadata.tables.values() for column in table.columns
            if any(foreign_key.column.table.name == "erp_accounts" for foreign_key in column.foreign_keys)]


async def account_usage(db: AsyncSession, organization_id: int) -> dict[int, list[dict[str, Any]]]:
    """Per account: every place it is referenced, with a reference count."""
    org_accounts = select(ERPAccount.id).where(ERPAccount.organization_id == organization_id)
    usage: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for table, column in _account_fk_columns():
        rows = (await db.execute(select(column, func.count()).where(column.in_(org_accounts)).group_by(column))).all()
        module, label = USAGE_LABELS.get((table.name, column.name), ("other", table.name.replace("_", " ")))
        for account_id, count in rows:
            usage[account_id].append({"module": module, "label": label, "count": int(count)})
    profiles = (await db.execute(select(PayrollPostingProfile).where(PayrollPostingProfile.organization_id == organization_id))).scalars().all()
    for profile in profiles:
        for role, value in (profile.account_roles or {}).items():
            if str(value).isdigit():
                usage[int(value)].append({"module": "payroll", "label": f"Цалингийн бичилтийн үүрэг · {role}", "count": 1})
    return dict(usage)


async def descendant_ids(db: AsyncSession, organization_id: int, account_id: int) -> set[int]:
    rows = (await db.execute(select(ERPAccount.id, ERPAccount.parent_id).where(ERPAccount.organization_id == organization_id))).all()
    children: dict[int, list[int]] = defaultdict(list)
    for child_id, parent_id in rows:
        if parent_id:
            children[parent_id].append(child_id)
    found: set[int] = set()
    stack = [account_id]
    while stack:
        for child in children.get(stack.pop(), []):
            if child not in found:
                found.add(child)
                stack.append(child)
    return found
