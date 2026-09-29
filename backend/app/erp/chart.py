"""Chart of accounts («Данс код», Dayansoft d047) rules shared by every module.

Payroll, budget, assets, settlements and document posting all pick accounts
from the same ``erp_accounts`` table.  The purpose catalog, the posting
``account_type`` derivation and the "where is this account used" answer live
here so each module agrees on what an account is for.
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

CLASSIFICATIONS = ("asset", "liability", "equity", "income", "expense")
CLASSIFICATION_LABELS = {"asset": "Хөрөнгө", "liability": "Өр төлбөр", "equity": "Эздийн өмч", "income": "Орлого", "expense": "Зардал"}
# Normal balance side (d047 «Дебет/Кредит шинж»).
NORMAL_SIDES = {"asset": "debit", "expense": "debit", "liability": "credit", "equity": "credit", "income": "credit"}

# purpose → (label, allowed classifications, module that relies on it, posting account_type)
# ``posting account_type`` is what document posting looks accounts up by
# (``service.default_account``).  It is derived from the purpose and never
# edited directly, otherwise renaming «Касс» would break payment posting.
PURPOSES: dict[str, tuple[str, tuple[str, ...], str, str | None]] = {
    "general": ("Ерөнхий", CLASSIFICATIONS, "general", None),
    "cash": ("Касс", ("asset",), "cash", "cash"),
    "bank": ("Харилцах данс (банк)", ("asset",), "cash", "cash"),
    "receivable": ("Авлага", ("asset",), "settlement", "receivable"),
    "advance_clearing": ("Цалингийн урьдчилгааны тооцоо", ("asset",), "payroll", "advance_clearing"),
    "inventory": ("Бараа материал", ("asset",), "stock", "inventory"),
    "fixed_asset": ("Үндсэн хөрөнгө", ("asset",), "assets", "fixed_asset"),
    "accumulated_depreciation": ("Хуримтлагдсан элэгдэл", ("asset",), "assets", "accumulated_depreciation"),
    "wip": ("Дуусаагүй үйлдвэрлэл", ("asset",), "stock", "wip"),
    "tax": ("НӨАТ / татвар", ("asset", "liability"), "tax", None),
    "payable": ("Өглөг", ("liability",), "settlement", "payable"),
    "payroll_payable": ("Цалингийн өглөг (нийт)", ("liability",), "payroll", "payroll_payable"),
    "net_pay_payable": ("Олгох цалингийн өглөг", ("liability",), "payroll", "payroll_payable"),
    "employee_shi_payable": ("Ажилтны НДШ-ийн өглөг", ("liability",), "payroll", "payroll_payable"),
    "employer_shi_payable": ("Ажил олгогчийн НДШ-ийн өглөг", ("liability",), "payroll", "payroll_payable"),
    "pit_payable": ("ХХОАТ-ын өглөг", ("liability",), "payroll", "tax_payable"),
    "other_deductions_payable": ("Бусад суутгалын өглөг", ("liability",), "payroll", "payroll_payable"),
    "revenue": ("Борлуулалтын орлого", ("income",), "sales", "income"),
    "expense": ("Үйл ажиллагааны зардал", ("expense",), "general", "expense"),
    "salary_expense": ("Цалингийн зардал", ("expense",), "payroll", "payroll_expense"),
    "employer_shi_expense": ("Ажил олгогчийн НДШ-ийн зардал", ("expense",), "payroll", "payroll_expense"),
    "depreciation_expense": ("Элэгдлийн зардал", ("expense",), "assets", "depreciation_expense"),
}
PURPOSE_POSTING_TYPES = {purpose: spec[3] for purpose, spec in PURPOSES.items() if spec[3]}
BANK_FIELDS = ("bank_name", "bank_account_number", "bank_iban", "bank_account_holder")

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

# Table → module whose data references the account (for the usage view).
USAGE_MODULES = {
    "erp_general_ledger_entries": "ledger", "erp_document_lines": "documents",
    "erp_parties": "parties", "erp_party_groups": "parties", "erp_tax_template_rates": "tax",
    "erp_accounting_settings": "settings", "budget_account_links": "budget", "erp_accounts": "children",
}
USAGE_LABELS = {
    "ledger": "Журнал бичилт", "documents": "Баримт", "parties": "Харилцагч", "tax": "Татварын загвар",
    "settings": "Санхүүгийн тохиргоо", "budget": "Төсөв", "payroll": "Цалин", "children": "Дэд данс",
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
    spec = PURPOSES.get(purpose)
    if spec is None:
        raise HTTPException(status_code=422, detail={"code": "erp_account_purpose_invalid", "purpose": purpose})
    if classification not in spec[1]:
        # Payroll keeps its historical error code; the UI maps both to one message.
        code = "payroll_account_classification_invalid" if spec[2] == "payroll" else "erp_account_classification_invalid"
        raise HTTPException(status_code=422, detail={"code": code, "purpose": purpose, "allowed": list(spec[1])})


def catalog() -> dict[str, Any]:
    return {
        "classifications": [{"key": key, "label": CLASSIFICATION_LABELS[key], "normal_side": NORMAL_SIDES[key]} for key in CLASSIFICATIONS],
        "purposes": [{"key": key, "label": label, "classifications": list(allowed), "module": module, "has_bank_details": key in {"bank", "cash"}}
                     for key, (label, allowed, module, _type) in PURPOSES.items()],
        "usage_modules": USAGE_LABELS,
    }


def descendant_ids(parents: dict[int, int | None], root_id: int) -> set[int]:
    """Ids below ``root_id`` in the parent tree (used to reject parent cycles)."""
    children: dict[int, list[int]] = {}
    for child, parent in parents.items():
        if parent is not None:
            children.setdefault(parent, []).append(child)
    found: set[int] = set()
    stack = [root_id]
    while stack:
        for child in children.get(stack.pop(), []):
            if child not in found:
                found.add(child)
                stack.append(child)
    return found


async def account_usage(db: AsyncSession, organization_id: int) -> dict[int, dict[str, int]]:
    """Per account: module → number of rows referencing it, across every module."""
    from app.models.models import Base, ERPAccount, PayrollPostingProfile

    org_accounts = select(ERPAccount.id).where(ERPAccount.organization_id == organization_id).scalar_subquery()
    usage: dict[int, dict[str, int]] = {}
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if not any(foreign_key.column.table.name == "erp_accounts" for foreign_key in column.foreign_keys):
                continue
            module = USAGE_MODULES.get(table.name, "payroll" if table.name.startswith(("payroll_", "monthly_payroll", "salary_", "payslip_")) else "documents")
            rows = await db.execute(select(column, func.count()).where(column.in_(org_accounts)).group_by(column))
            for account_id, count in rows.all():
                bucket = usage.setdefault(int(account_id), {})
                bucket[module] = bucket.get(module, 0) + int(count)
    profiles = (await db.execute(select(PayrollPostingProfile.account_roles).where(PayrollPostingProfile.organization_id == organization_id))).scalars().all()
    for roles in profiles:
        for value in (roles or {}).values():
            if str(value).isdigit():
                bucket = usage.setdefault(int(value), {})
                bucket["payroll"] = bucket.get("payroll", 0) + 1
    return usage
