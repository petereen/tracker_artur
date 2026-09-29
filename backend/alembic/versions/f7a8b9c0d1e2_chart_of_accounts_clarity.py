"""Chart of accounts clarity («Данс код», Dayansoft d047)

Adds bank details to cash/bank accounts and renames seeded accounts that still
carry their original English names to Mongolian. Accounts an organization has
already renamed are left untouched.

Also restores ``account_type`` (what document posting looks accounts up by)
from the account purpose: editing an account used to overwrite it with the
bare classification, so e.g. an edited «Cash» account stopped being found as
the cash account for payments. Accounts still on purpose ``general`` whose
``account_type`` names a posting role (CSV imports, older API writes) get the
matching purpose/classification, so purpose is the single source of truth.

Revision ID: f7a8b9c0d1e2
Revises: f6a7b8c9d0e1
Create Date: 2026-09-29 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f7a8b9c0d1e2"
down_revision: Union[str, Sequence[str], None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# code → (new name, names it may still carry from the English seed)
RENAMES = {
    "1000": ("Касс дахь мөнгө", ("Cash",)),
    "1010": ("Харилцах данс (цалин)", ("Payroll bank",)),
    "1100": ("Дансны авлага", ("Accounts receivable",)),
    "1200": ("Бараа материал", ("Inventory",)),
    "1300": ("Үндсэн хөрөнгө", ("Fixed assets",)),
    "1301": ("Дуусаагүй үйлдвэрлэл", ("Work in progress",)),
    "1310": ("Хуримтлагдсан элэгдэл", ("Accumulated depreciation",)),
    "2000": ("Дансны өглөг", ("Accounts payable",)),
    "2100": ("НӨАТ-ын өглөг", ("Sales tax payable",)),
    "2200": ("НӨАТ-ын авлага", ("Purchase tax receivable",)),
    "2300": ("Цалингийн өглөг (нийт)", ("Payroll payable",)),
    "2310": ("Олгох цалингийн өглөг", ("Net salary payable",)),
    "2320": ("Ажилтны НДШ-ийн өглөг", ("Employee social insurance payable",)),
    "2330": ("Ажил олгогчийн НДШ-ийн өглөг", ("Employer social insurance payable",)),
    "2340": ("ХХОАТ-ын өглөг", ("PIT payable",)),
    "2350": ("Цалингийн урьдчилгааны тооцоо", ("Employee advance clearing",)),
    "4000": ("Борлуулалтын орлого", ("Sales income",)),
    "5000": ("Үйл ажиллагааны зардал", ("Operating expenses",)),
    "5100": ("Цалингийн зардал", ("Salary expense", "Payroll expense")),
    "5110": ("Ажил олгогчийн НДШ-ийн зардал", ("Employer social insurance expense",)),
    "5200": ("Элэгдлийн зардал", ("Depreciation expense",)),
}

# purpose → posting account_type; mirrors app.erp.chart.PURPOSES (frozen here).
POSTING_TYPES = {
    "cash": "cash", "bank": "cash", "receivable": "receivable", "advance_clearing": "advance_clearing",
    "inventory": "inventory", "fixed_asset": "fixed_asset", "accumulated_depreciation": "accumulated_depreciation", "wip": "wip",
    "payable": "payable", "payroll_payable": "payroll_payable", "net_pay_payable": "payroll_payable",
    "employee_shi_payable": "payroll_payable", "employer_shi_payable": "payroll_payable", "other_deductions_payable": "payroll_payable",
    "pit_payable": "tax_payable", "revenue": "income", "expense": "expense", "depreciation_expense": "depreciation_expense",
    "salary_expense": "payroll_expense", "employer_shi_expense": "payroll_expense",
}

# Legacy posting account_type on a ``general`` account → (classification, purpose).
LEGACY_TYPES = {
    "cash": ("asset", "cash"), "bank": ("asset", "bank"), "receivable": ("asset", "receivable"), "inventory": ("asset", "inventory"),
    "stock": ("asset", "inventory"), "fixed_asset": ("asset", "fixed_asset"), "wip": ("asset", "wip"), "tax_receivable": ("asset", "tax"),
    "payable": ("liability", "payable"), "tax_payable": ("liability", "tax"), "payroll_payable": ("liability", "payroll_payable"),
    "income": ("income", "revenue"), "income_account": ("income", "revenue"), "expense": ("expense", "expense"),
    "expense_account": ("expense", "expense"), "payroll_expense": ("expense", "salary_expense"),
    "liability": ("liability", "general"), "equity": ("equity", "general"),
}


def upgrade() -> None:
    op.add_column("erp_accounts", sa.Column("bank_name", sa.String(length=120), nullable=True))
    op.add_column("erp_accounts", sa.Column("bank_account_number", sa.String(length=64), nullable=True))
    op.add_column("erp_accounts", sa.Column("bank_iban", sa.String(length=34), nullable=True))
    op.add_column("erp_accounts", sa.Column("bank_account_holder", sa.String(length=200), nullable=True))

    rename = sa.text("UPDATE erp_accounts SET name = :name WHERE code = :code AND name = ANY(:legacy)")
    for code, (name, legacy) in RENAMES.items():
        op.execute(rename.bindparams(name=name, code=code, legacy=list(legacy)))

    adopt = sa.text(
        "UPDATE erp_accounts SET classification = :classification, purpose = :purpose "
        "WHERE purpose = 'general' AND account_type = :account_type"
    )
    for account_type, (classification, purpose) in LEGACY_TYPES.items():
        op.execute(adopt.bindparams(classification=classification, purpose=purpose, account_type=account_type))

    repair = sa.text("UPDATE erp_accounts SET account_type = :account_type WHERE purpose = :purpose AND account_type <> :account_type")
    for purpose, account_type in POSTING_TYPES.items():
        op.execute(repair.bindparams(purpose=purpose, account_type=account_type))
    op.execute(sa.text(
        "UPDATE erp_accounts SET account_type = CASE WHEN classification = 'asset' THEN 'tax_receivable' ELSE 'tax_payable' END "
        "WHERE purpose = 'tax'"
    ))
    op.execute(sa.text("UPDATE erp_accounts SET account_type = classification WHERE purpose = 'general' AND account_type <> classification"))


def downgrade() -> None:
    op.drop_column("erp_accounts", "bank_account_holder")
    op.drop_column("erp_accounts", "bank_iban")
    op.drop_column("erp_accounts", "bank_account_number")
    op.drop_column("erp_accounts", "bank_name")
