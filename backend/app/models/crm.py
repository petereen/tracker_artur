"""CRM (Харилцагч / Харилцаа холбоо) models.

The customer master itself stays in ``erp_parties`` (see ``ERPParty``); this
module holds the reference data that enriches it (groups, payment terms,
contacts, bank accounts), the per-register configurable statuses, and the CRM
activity log described in Dayansoft ERP d026/d027.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
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
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base


STATUS_CATEGORIES = ("open", "in_progress", "waiting", "done", "cancelled")
FINISHED_STATUS_CATEGORIES = frozenset({"done", "cancelled"})
PAYMENT_TERM_PERIOD_UNITS = ("day", "month")


class ERPPartyGroup(Base):
    """Харилцагчийн бүлэг — hierarchical customer grouping with posting defaults."""

    __tablename__ = "erp_party_groups"
    __table_args__ = (UniqueConstraint("organization_id", "code", name="uq_erp_party_groups_org_code"),)

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    code = Column(String(40), nullable=False)
    name = Column(Text, nullable=False)
    parent_id = Column(Integer, ForeignKey("erp_party_groups.id", ondelete="SET NULL"))
    is_default = Column(Boolean, nullable=False, server_default=sa_text("false"), default=False)
    is_foreign = Column(Boolean, nullable=False, server_default=sa_text("false"), default=False)
    default_settlement_account_id = Column(Integer, ForeignKey("erp_accounts.id", ondelete="SET NULL"))
    default_price_list_id = Column(Integer, ForeignKey("erp_price_lists.id", ondelete="SET NULL"))
    is_active = Column(Boolean, nullable=False, server_default=sa_text("true"), default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class ERPPaymentTerm(Base):
    """Төлбөрийн нөхцөл — settlement terms offered to a party."""

    __tablename__ = "erp_payment_terms"
    __table_args__ = (
        UniqueConstraint("organization_id", "code", name="uq_erp_payment_terms_org_code"),
        CheckConstraint("period_unit IN ('day','month')", name="ck_erp_payment_terms_period_unit"),
        CheckConstraint("days >= 0 AND period_value >= 0", name="ck_erp_payment_terms_non_negative"),
    )

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    code = Column(String(20), nullable=False)
    name = Column(Text, nullable=False)
    days = Column(Integer, nullable=False, server_default="0", default=0)
    period_unit = Column(String(8), nullable=False, server_default="day", default="day")
    period_value = Column(Integer, nullable=False, server_default="0", default=0)
    is_active = Column(Boolean, nullable=False, server_default=sa_text("true"), default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class ERPPartyContact(Base):
    """Холбоо барих хүн — a person at the party the organization deals with."""

    __tablename__ = "erp_party_contacts"
    __table_args__ = (Index("ix_erp_party_contacts_party", "party_id", "is_active"),)

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    party_id = Column(Integer, ForeignKey("erp_parties.id", ondelete="CASCADE"), nullable=False)
    name = Column(Text, nullable=False)
    nickname = Column(Text)
    position = Column(Text)
    phone = Column(Text)
    email = Column(Text)
    address = Column(Text)
    note = Column(Text)
    is_default = Column(Boolean, nullable=False, server_default=sa_text("false"), default=False)
    is_active = Column(Boolean, nullable=False, server_default=sa_text("true"), default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class ERPPartyBankAccount(Base):
    """Харилцагчийн банкны данс."""

    __tablename__ = "erp_party_bank_accounts"
    __table_args__ = (Index("ix_erp_party_bank_accounts_party", "party_id", "is_active"),)

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    party_id = Column(Integer, ForeignKey("erp_parties.id", ondelete="CASCADE"), nullable=False)
    bank_name = Column(Text, nullable=False)
    currency = Column(String(3), nullable=False, server_default="MNT", default="MNT")
    iban_prefix = Column(String(40))
    account_no = Column(String(64), nullable=False)
    account_name = Column(Text)
    note = Column(Text)
    is_default = Column(Boolean, nullable=False, server_default=sa_text("false"), default=False)
    is_active = Column(Boolean, nullable=False, server_default=sa_text("true"), default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class ERPStatus(Base):
    """Төлөв — manually selected statuses configured per register.

    ``category`` is the fixed meaning the application relies on (for example
    whether an activity still counts toward overdue work); the name, order and
    colour stay fully configurable by the organization.
    """

    __tablename__ = "erp_statuses"
    __table_args__ = (
        UniqueConstraint("organization_id", "register", "code", name="uq_erp_statuses_org_register_code"),
        CheckConstraint("category IN ('open','in_progress','waiting','done','cancelled')", name="ck_erp_statuses_category"),
        Index("ix_erp_statuses_org_register", "organization_id", "register", "sort"),
    )

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    register = Column(String(40), nullable=False)
    code = Column(String(40), nullable=False)
    name = Column(Text, nullable=False)
    sort = Column(Integer, nullable=False, server_default="0", default=0)
    color = Column(String(16), nullable=False, server_default="#64748B", default="#64748B")
    category = Column(String(16), nullable=False, server_default="open", default="open")
    is_active = Column(Boolean, nullable=False, server_default=sa_text("true"), default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class CRMActivityType(Base):
    """Харилцаа холбооны төрөл (Уулзалт, Утас, Мэйл, Task, …)."""

    __tablename__ = "crm_activity_types"
    __table_args__ = (UniqueConstraint("organization_id", "code", name="uq_crm_activity_types_org_code"),)

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    code = Column(String(40), nullable=False)
    name = Column(Text, nullable=False)
    sort = Column(Integer, nullable=False, server_default="0", default=0)
    is_active = Column(Boolean, nullable=False, server_default=sa_text("true"), default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class CRMActivity(Base):
    """Харилцаа холбоо — a logged interaction, meeting, call or follow-up."""

    __tablename__ = "crm_activities"
    __table_args__ = (
        UniqueConstraint("organization_id", "number", name="uq_crm_activities_org_number"),
        CheckConstraint("duration_minutes IS NULL OR duration_minutes >= 0", name="ck_crm_activities_duration"),
        Index("ix_crm_activities_org_responsible_open", "organization_id", "responsible_employee_id", "is_closed", "due_at"),
        Index("ix_crm_activities_org_party", "organization_id", "party_id", "activity_at"),
        Index("ix_crm_activities_org_status", "organization_id", "status_id"),
    )

    id = Column(Integer, primary_key=True)
    public_id = Column(UUID(as_uuid=True), nullable=False, unique=True, default=uuid.uuid4, server_default=sa_text("gen_random_uuid()"))
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    number = Column(String(40), nullable=False)
    # 1. Харилцагчийн мэдээлэл — optional: internal activities have no party.
    party_id = Column(Integer, ForeignKey("erp_parties.id", ondelete="SET NULL"))
    contact_id = Column(Integer, ForeignKey("erp_party_contacts.id", ondelete="SET NULL"))
    contact_name = Column(Text)
    contact_phone = Column(Text)
    contact_email = Column(Text)
    # 2. Үндсэн мэдээлэл
    activity_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    subject = Column(Text, nullable=False)
    body = Column(Text)
    type_id = Column(Integer, ForeignKey("crm_activity_types.id", ondelete="SET NULL"))
    is_important = Column(Boolean, nullable=False, server_default=sa_text("false"), default=False)
    # 3. Ажлын хугацаа, хариуцагч
    due_at = Column(DateTime(timezone=True))
    duration_minutes = Column(Integer)
    responsible_employee_id = Column(Integer, ForeignKey("employees.id", ondelete="SET NULL"))
    status_id = Column(Integer, ForeignKey("erp_statuses.id", ondelete="SET NULL"))
    completed_at = Column(DateTime(timezone=True))
    completion_note = Column(Text)
    # 4. Холбогдох бүртгэл
    reference = Column(Text)
    contract_id = Column(Integer, ForeignKey("contract_documents.id", ondelete="SET NULL"))
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="SET NULL"))
    task_id = Column(Integer, ForeignKey("tasks.id", ondelete="SET NULL"))
    # 5. Хаалт болон хяналт
    is_closed = Column(Boolean, nullable=False, server_default=sa_text("false"), default=False)
    closed_at = Column(DateTime(timezone=True))
    reviewed_by_employee_id = Column(Integer, ForeignKey("employees.id", ondelete="SET NULL"))
    reviewed_at = Column(DateTime(timezone=True))
    expected_revenue = Column(Numeric(18, 4))
    currency = Column(String(3), nullable=False, server_default="MNT", default="MNT")
    is_active = Column(Boolean, nullable=False, server_default=sa_text("true"), default=True)
    custom = Column(JSONB, nullable=False, server_default=sa_text("'{}'::jsonb"), default=dict)
    created_by_account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="SET NULL"))
    created_by_employee_id = Column(Integer, ForeignKey("employees.id", ondelete="SET NULL"))
    version = Column(Integer, nullable=False, server_default="1", default=1)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
