"""Budget (Төсөв, гүйцэтгэл) models — Dayansoft ERP d161.

Budget accounts are a management view on top of the chart of accounts: each
budget account groups one or more financial accounts (``erp_accounts``), and a
financial account belongs to at most one budget account so actuals are never
counted twice. Budgets are named scenarios (Base / Optimistic / Conservative)
whose signed entries follow the d161 rule: income positive, costs negative.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text as sa_text,
)
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


BUDGET_KINDS = ("income", "cogs", "expense", "other")
BUDGET_SCENARIOS = ("base", "optimistic", "conservative", "other")
BUDGET_PERIOD_TYPES = ("month", "quarter", "year", "custom")
BUDGET_STATUSES = ("draft", "approved", "archived")


class BudgetAccountGroup(Base):
    """Төсөвт дансны бүлэг — management grouping, independent of the ledger tree."""

    __tablename__ = "budget_account_groups"
    __table_args__ = (
        UniqueConstraint("organization_id", "code", name="uq_budget_account_groups_org_code"),
        CheckConstraint("kind IN ('income','cogs','expense','other')", name="ck_budget_account_groups_kind"),
    )

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    parent_id = Column(Integer, ForeignKey("budget_account_groups.id", ondelete="SET NULL"))
    code = Column(String(40), nullable=False)
    name = Column(Text, nullable=False)
    kind = Column(String(16), nullable=False, server_default="expense", default="expense")
    sort = Column(Integer, nullable=False, server_default="0", default=0)
    is_active = Column(Boolean, nullable=False, server_default=sa_text("true"), default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class BudgetAccount(Base):
    """Төсөвт данс — the line a budget is planned and analysed on."""

    __tablename__ = "budget_accounts"
    __table_args__ = (
        UniqueConstraint("organization_id", "code", name="uq_budget_accounts_org_code"),
        CheckConstraint("kind IN ('income','cogs','expense','other')", name="ck_budget_accounts_kind"),
        Index("ix_budget_accounts_org_group", "organization_id", "group_id"),
    )

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    group_id = Column(Integer, ForeignKey("budget_account_groups.id", ondelete="SET NULL"))
    code = Column(String(40), nullable=False)
    name = Column(Text, nullable=False)
    kind = Column(String(16), nullable=False, server_default="expense", default="expense")
    note = Column(Text)
    sort = Column(Integer, nullable=False, server_default="0", default=0)
    is_active = Column(Boolean, nullable=False, server_default=sa_text("true"), default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class BudgetAccountLink(Base):
    """Financial account → budget account. One budget account per ledger account."""

    __tablename__ = "budget_account_links"
    __table_args__ = (
        UniqueConstraint("organization_id", "erp_account_id", name="uq_budget_account_links_org_erp_account"),
        Index("ix_budget_account_links_budget_account", "budget_account_id"),
    )

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    budget_account_id = Column(Integer, ForeignKey("budget_accounts.id", ondelete="CASCADE"), nullable=False)
    erp_account_id = Column(Integer, ForeignKey("erp_accounts.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Budget(Base):
    """Төсөв — one named scenario over a period, optionally for one project."""

    __tablename__ = "budgets"
    __table_args__ = (
        UniqueConstraint("organization_id", "number", name="uq_budgets_org_number"),
        CheckConstraint("scenario IN ('base','optimistic','conservative','other')", name="ck_budgets_scenario"),
        CheckConstraint("period_type IN ('month','quarter','year','custom')", name="ck_budgets_period_type"),
        CheckConstraint("status IN ('draft','approved','archived')", name="ck_budgets_status"),
        CheckConstraint("start_date <= end_date", name="ck_budgets_period_order"),
        Index("ix_budgets_org_status", "organization_id", "status"),
    )

    id = Column(Integer, primary_key=True)
    public_id = Column(UUID(as_uuid=True), nullable=False, unique=True, default=uuid.uuid4, server_default=sa_text("gen_random_uuid()"))
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    number = Column(String(40), nullable=False)
    name = Column(Text, nullable=False)
    purpose = Column(Text)
    scenario = Column(String(16), nullable=False, server_default="base", default="base")
    period_type = Column(String(16), nullable=False, server_default="month", default="month")
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="SET NULL"))
    currency = Column(String(3), nullable=False, server_default="MNT", default="MNT")
    status = Column(String(16), nullable=False, server_default="draft", default="draft")
    is_primary = Column(Boolean, nullable=False, server_default=sa_text("false"), default=False)
    copied_from_id = Column(Integer, ForeignKey("budgets.id", ondelete="SET NULL"))
    approved_at = Column(DateTime(timezone=True))
    approved_by_account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="SET NULL"))
    created_by_account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="SET NULL"))
    version = Column(Integer, nullable=False, server_default="1", default=1)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class BudgetEntry(Base):
    """One signed planned amount: budget account × project × customer group × period."""

    __tablename__ = "budget_entries"
    __table_args__ = (
        CheckConstraint("period_start <= period_end", name="ck_budget_entries_period_order"),
        Index("ix_budget_entries_budget", "budget_id", "budget_account_id"),
        Index("ix_budget_entries_org_account", "organization_id", "budget_account_id"),
    )

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    budget_id = Column(Integer, ForeignKey("budgets.id", ondelete="CASCADE"), nullable=False)
    budget_account_id = Column(Integer, ForeignKey("budget_accounts.id", ondelete="RESTRICT"), nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="SET NULL"))
    party_group_id = Column(Integer, ForeignKey("erp_party_groups.id", ondelete="SET NULL"))
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    amount = Column(Numeric(18, 2), nullable=False, server_default="0", default=0)
    note = Column(Text)
    position = Column(Integer, nullable=False, server_default="0", default=0)
