"""CRM module: customer master enrichment and activity log

Extends ``erp_parties`` into the Dayansoft-style customer master (Харилцагч:
registry/TIN, tax payer flags, head customer, group, payment terms, sales and
purchase defaults) and adds the CRM activity log (Харилцаа холбоо) with
configurable types and per-register statuses. Legacy JSON contacts are copied
into ``erp_party_contacts`` so activities can reference a contact person.

Revision ID: d1e2f3a4b5c6
Revises: c0d1e2f3a4b5
Create Date: 2026-09-25 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, Sequence[str], None] = "c0d1e2f3a4b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ]


def _org() -> sa.Column:
    return sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)


def _flag(name: str, default: bool) -> sa.Column:
    return sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.text("true" if default else "false"))


def upgrade() -> None:
    op.create_table(
        "erp_party_groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        _org(),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("parent_id", sa.Integer(), sa.ForeignKey("erp_party_groups.id", ondelete="SET NULL")),
        _flag("is_default", False),
        _flag("is_foreign", False),
        sa.Column("default_settlement_account_id", sa.Integer(), sa.ForeignKey("erp_accounts.id", ondelete="SET NULL")),
        sa.Column("default_price_list_id", sa.Integer(), sa.ForeignKey("erp_price_lists.id", ondelete="SET NULL")),
        _flag("is_active", True),
        *_timestamps(),
        sa.UniqueConstraint("organization_id", "code", name="uq_erp_party_groups_org_code"),
    )
    op.create_table(
        "erp_payment_terms",
        sa.Column("id", sa.Integer(), primary_key=True),
        _org(),
        sa.Column("code", sa.String(20), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("period_unit", sa.String(8), nullable=False, server_default="day"),
        sa.Column("period_value", sa.Integer(), nullable=False, server_default="0"),
        _flag("is_active", True),
        *_timestamps(),
        sa.UniqueConstraint("organization_id", "code", name="uq_erp_payment_terms_org_code"),
        sa.CheckConstraint("period_unit IN ('day','month')", name="ck_erp_payment_terms_period_unit"),
        sa.CheckConstraint("days >= 0 AND period_value >= 0", name="ck_erp_payment_terms_non_negative"),
    )
    op.create_table(
        "erp_statuses",
        sa.Column("id", sa.Integer(), primary_key=True),
        _org(),
        sa.Column("register", sa.String(40), nullable=False),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("color", sa.String(16), nullable=False, server_default="#64748B"),
        sa.Column("category", sa.String(16), nullable=False, server_default="open"),
        _flag("is_active", True),
        *_timestamps(),
        sa.UniqueConstraint("organization_id", "register", "code", name="uq_erp_statuses_org_register_code"),
        sa.CheckConstraint("category IN ('open','in_progress','waiting','done','cancelled')", name="ck_erp_statuses_category"),
    )
    op.create_index("ix_erp_statuses_org_register", "erp_statuses", ["organization_id", "register", "sort"])
    op.create_table(
        "crm_activity_types",
        sa.Column("id", sa.Integer(), primary_key=True),
        _org(),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
        _flag("is_active", True),
        *_timestamps(),
        sa.UniqueConstraint("organization_id", "code", name="uq_crm_activity_types_org_code"),
    )

    # Customer master enrichment. Booleans land with server defaults so
    # existing rows are valid immediately (backfill → default → NOT NULL).
    op.add_column("erp_parties", sa.Column("name_en", sa.Text()))
    op.add_column("erp_parties", sa.Column("business_name", sa.Text()))
    op.add_column("erp_parties", sa.Column("registry_no", sa.String(20)))
    for name, default in (("is_customer", True), ("is_supplier", False), ("is_individual", False), ("is_foreign", False),
                          ("vat_payer", False), ("city_tax_payer", False), ("settle_via_parent", False)):
        op.add_column("erp_parties", _flag(name, default))
    op.add_column("erp_parties", sa.Column("tax_status_checked_at", sa.DateTime(timezone=True)))
    op.add_column("erp_parties", sa.Column("website", sa.Text()))
    op.add_column("erp_parties", sa.Column("legal_address", sa.Text()))
    op.add_column("erp_parties", sa.Column("location", sa.Text()))
    op.add_column("erp_parties", sa.Column("informal_address", sa.Text()))
    op.add_column("erp_parties", sa.Column("tags", postgresql.ARRAY(sa.Text()), nullable=False, server_default=sa.text("'{}'::text[]")))
    op.add_column("erp_parties", sa.Column("customer_since", sa.Date()))
    op.add_column("erp_parties", sa.Column("inactive_since", sa.Date()))
    op.add_column("erp_parties", sa.Column("responsible_employee_id", sa.Integer(), sa.ForeignKey("employees.id", ondelete="SET NULL")))
    op.add_column("erp_parties", sa.Column("parent_party_id", sa.Integer(), sa.ForeignKey("erp_parties.id", ondelete="SET NULL")))
    op.add_column("erp_parties", sa.Column("group_id", sa.Integer(), sa.ForeignKey("erp_party_groups.id", ondelete="SET NULL")))
    op.add_column("erp_parties", sa.Column("payment_term_id", sa.Integer(), sa.ForeignKey("erp_payment_terms.id", ondelete="SET NULL")))
    op.add_column("erp_parties", sa.Column("price_list_id", sa.Integer(), sa.ForeignKey("erp_price_lists.id", ondelete="SET NULL")))
    op.add_column("erp_parties", sa.Column("settlement_account_id", sa.Integer(), sa.ForeignKey("erp_accounts.id", ondelete="SET NULL")))
    op.add_column("erp_parties", sa.Column("sales_discount_pct", sa.Numeric(9, 4)))
    op.add_column("erp_parties", sa.Column("sales_note", sa.Text()))
    op.add_column("erp_parties", sa.Column("sales_lead_days", sa.Integer()))
    op.add_column("erp_parties", sa.Column("purchase_discount_pct", sa.Numeric(9, 4)))
    op.add_column("erp_parties", sa.Column("purchase_note", sa.Text()))
    op.add_column("erp_parties", sa.Column("purchase_lead_days", sa.Integer()))
    op.add_column("erp_parties", sa.Column("delivery_terms", sa.Text()))
    op.add_column("erp_parties", sa.Column("links", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.add_column("erp_parties", sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
    op.execute("UPDATE erp_parties SET is_supplier = (party_type = 'supplier'), is_customer = (party_type <> 'supplier')")
    op.execute("UPDATE erp_parties SET inactive_since = CURRENT_DATE WHERE status <> 'active' AND inactive_since IS NULL")
    op.create_index("ix_erp_parties_org_registry", "erp_parties", ["organization_id", "registry_no"])
    op.create_index("ix_erp_parties_org_tax_id", "erp_parties", ["organization_id", "tax_id"])
    op.create_index("ix_erp_parties_org_parent", "erp_parties", ["organization_id", "parent_party_id"])

    op.create_table(
        "erp_party_contacts",
        sa.Column("id", sa.Integer(), primary_key=True),
        _org(),
        sa.Column("party_id", sa.Integer(), sa.ForeignKey("erp_parties.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("nickname", sa.Text()),
        sa.Column("position", sa.Text()),
        sa.Column("phone", sa.Text()),
        sa.Column("email", sa.Text()),
        sa.Column("address", sa.Text()),
        sa.Column("note", sa.Text()),
        _flag("is_default", False),
        _flag("is_active", True),
        *_timestamps(),
    )
    op.create_index("ix_erp_party_contacts_party", "erp_party_contacts", ["party_id", "is_active"])
    op.execute(
        """
        INSERT INTO erp_party_contacts (organization_id, party_id, name, position, phone, email, is_default, is_active)
        SELECT p.organization_id, p.id,
               COALESCE(NULLIF(c->>'name', ''), NULLIF(c->>'full_name', ''), p.name),
               NULLIF(c->>'position', ''), NULLIF(c->>'phone', ''), NULLIF(c->>'email', ''),
               t.ord = 1, true
        FROM erp_parties AS p
        CROSS JOIN LATERAL jsonb_array_elements(
            CASE WHEN jsonb_typeof(p.contacts) = 'array' THEN p.contacts ELSE '[]'::jsonb END
        ) WITH ORDINALITY AS t(c, ord)
        WHERE jsonb_typeof(c) = 'object'
        """
    )
    op.create_table(
        "erp_party_bank_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        _org(),
        sa.Column("party_id", sa.Integer(), sa.ForeignKey("erp_parties.id", ondelete="CASCADE"), nullable=False),
        sa.Column("bank_name", sa.Text(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="MNT"),
        sa.Column("iban_prefix", sa.String(40)),
        sa.Column("account_no", sa.String(64), nullable=False),
        sa.Column("account_name", sa.Text()),
        sa.Column("note", sa.Text()),
        _flag("is_default", False),
        _flag("is_active", True),
        *_timestamps(),
    )
    op.create_index("ix_erp_party_bank_accounts_party", "erp_party_bank_accounts", ["party_id", "is_active"])

    op.create_table(
        "crm_activities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True, server_default=sa.text("gen_random_uuid()")),
        _org(),
        sa.Column("number", sa.String(40), nullable=False),
        sa.Column("party_id", sa.Integer(), sa.ForeignKey("erp_parties.id", ondelete="SET NULL")),
        sa.Column("contact_id", sa.Integer(), sa.ForeignKey("erp_party_contacts.id", ondelete="SET NULL")),
        sa.Column("contact_name", sa.Text()),
        sa.Column("contact_phone", sa.Text()),
        sa.Column("contact_email", sa.Text()),
        sa.Column("activity_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("body", sa.Text()),
        sa.Column("type_id", sa.Integer(), sa.ForeignKey("crm_activity_types.id", ondelete="SET NULL")),
        _flag("is_important", False),
        sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.Column("duration_minutes", sa.Integer()),
        sa.Column("responsible_employee_id", sa.Integer(), sa.ForeignKey("employees.id", ondelete="SET NULL")),
        sa.Column("status_id", sa.Integer(), sa.ForeignKey("erp_statuses.id", ondelete="SET NULL")),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("completion_note", sa.Text()),
        sa.Column("reference", sa.Text()),
        sa.Column("contract_id", sa.Integer(), sa.ForeignKey("contract_documents.id", ondelete="SET NULL")),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="SET NULL")),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id", ondelete="SET NULL")),
        _flag("is_closed", False),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("reviewed_by_employee_id", sa.Integer(), sa.ForeignKey("employees.id", ondelete="SET NULL")),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("expected_revenue", sa.Numeric(18, 4)),
        sa.Column("currency", sa.String(3), nullable=False, server_default="MNT"),
        _flag("is_active", True),
        sa.Column("custom", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("created_by_employee_id", sa.Integer(), sa.ForeignKey("employees.id", ondelete="SET NULL")),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        *_timestamps(),
        sa.UniqueConstraint("organization_id", "number", name="uq_crm_activities_org_number"),
        sa.CheckConstraint("duration_minutes IS NULL OR duration_minutes >= 0", name="ck_crm_activities_duration"),
    )
    op.create_index("ix_crm_activities_org_responsible_open", "crm_activities", ["organization_id", "responsible_employee_id", "is_closed", "due_at"])
    op.create_index("ix_crm_activities_org_party", "crm_activities", ["organization_id", "party_id", "activity_at"])
    op.create_index("ix_crm_activities_org_status", "crm_activities", ["organization_id", "status_id"])

    # Existing organizations already have the seeded Sales role; bootstrap only
    # seeds missing roles, so grant the new CRM capabilities here.
    op.execute(
        """
        INSERT INTO erp_capabilities (access_role_id, resource, action)
        SELECT r.id, c.resource, c.action
        FROM erp_access_roles AS r
        CROSS JOIN (VALUES ('crm_activity', '*'), ('crm_settings', 'view')) AS c(resource, action)
        WHERE r.code = 'erp_sales' AND r.is_system
        ON CONFLICT ON CONSTRAINT uq_erp_capability DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM erp_capabilities
        WHERE resource IN ('crm_activity', 'crm_settings')
          AND access_role_id IN (SELECT id FROM erp_access_roles WHERE code = 'erp_sales' AND is_system)
        """
    )
    op.drop_table("crm_activities")
    op.drop_table("erp_party_bank_accounts")
    op.drop_table("erp_party_contacts")
    op.drop_index("ix_erp_parties_org_parent", table_name="erp_parties")
    op.drop_index("ix_erp_parties_org_tax_id", table_name="erp_parties")
    op.drop_index("ix_erp_parties_org_registry", table_name="erp_parties")
    for name in (
        "version", "links", "delivery_terms", "purchase_lead_days", "purchase_note", "purchase_discount_pct",
        "sales_lead_days", "sales_note", "sales_discount_pct", "settlement_account_id", "price_list_id",
        "payment_term_id", "group_id", "parent_party_id", "responsible_employee_id", "inactive_since",
        "customer_since", "tags", "informal_address", "location", "legal_address", "website",
        "tax_status_checked_at", "settle_via_parent", "city_tax_payer", "vat_payer", "is_foreign",
        "is_individual", "is_supplier", "is_customer", "registry_no", "business_name", "name_en",
    ):
        op.drop_column("erp_parties", name)
    op.drop_table("crm_activity_types")
    op.drop_index("ix_erp_statuses_org_register", table_name="erp_statuses")
    op.drop_table("erp_statuses")
    op.drop_table("erp_payment_terms")
    op.drop_table("erp_party_groups")
