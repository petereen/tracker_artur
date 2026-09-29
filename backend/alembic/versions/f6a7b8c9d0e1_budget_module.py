"""Budget module (Төсөв, гүйцэтгэл — Dayansoft d161)

Adds budget account groups, budget accounts linked to the chart of accounts,
budget scenarios and their signed period entries. Existing system Accountant
roles (which already hold ``budget:*``) also receive ``budget_settings:*`` so
they can maintain budget accounts.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-09-29 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "e5f6a7b8c9d0"
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


KIND_CHECK = "kind IN ('income','cogs','expense','other')"


def upgrade() -> None:
    op.create_table(
        "budget_account_groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        _org(),
        sa.Column("parent_id", sa.Integer(), sa.ForeignKey("budget_account_groups.id", ondelete="SET NULL")),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False, server_default="expense"),
        sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
        _flag("is_active", True),
        *_timestamps(),
        sa.UniqueConstraint("organization_id", "code", name="uq_budget_account_groups_org_code"),
        sa.CheckConstraint(KIND_CHECK, name="ck_budget_account_groups_kind"),
    )
    op.create_table(
        "budget_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        _org(),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("budget_account_groups.id", ondelete="SET NULL")),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False, server_default="expense"),
        sa.Column("note", sa.Text()),
        sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
        _flag("is_active", True),
        *_timestamps(),
        sa.UniqueConstraint("organization_id", "code", name="uq_budget_accounts_org_code"),
        sa.CheckConstraint(KIND_CHECK, name="ck_budget_accounts_kind"),
    )
    op.create_index("ix_budget_accounts_org_group", "budget_accounts", ["organization_id", "group_id"])
    op.create_table(
        "budget_account_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        _org(),
        sa.Column("budget_account_id", sa.Integer(), sa.ForeignKey("budget_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("erp_account_id", sa.Integer(), sa.ForeignKey("erp_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "erp_account_id", name="uq_budget_account_links_org_erp_account"),
    )
    op.create_index("ix_budget_account_links_budget_account", "budget_account_links", ["budget_account_id"])
    op.create_table(
        "budgets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True, server_default=sa.text("gen_random_uuid()")),
        _org(),
        sa.Column("number", sa.String(40), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("purpose", sa.Text()),
        sa.Column("scenario", sa.String(16), nullable=False, server_default="base"),
        sa.Column("period_type", sa.String(16), nullable=False, server_default="month"),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="SET NULL")),
        sa.Column("currency", sa.String(3), nullable=False, server_default="MNT"),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        _flag("is_primary", False),
        sa.Column("copied_from_id", sa.Integer(), sa.ForeignKey("budgets.id", ondelete="SET NULL")),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("approved_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("created_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        *_timestamps(),
        sa.UniqueConstraint("organization_id", "number", name="uq_budgets_org_number"),
        sa.CheckConstraint("scenario IN ('base','optimistic','conservative','other')", name="ck_budgets_scenario"),
        sa.CheckConstraint("period_type IN ('month','quarter','year','custom')", name="ck_budgets_period_type"),
        sa.CheckConstraint("status IN ('draft','approved','archived')", name="ck_budgets_status"),
        sa.CheckConstraint("start_date <= end_date", name="ck_budgets_period_order"),
    )
    op.create_index("ix_budgets_org_status", "budgets", ["organization_id", "status"])
    op.create_table(
        "budget_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        _org(),
        sa.Column("budget_id", sa.Integer(), sa.ForeignKey("budgets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("budget_account_id", sa.Integer(), sa.ForeignKey("budget_accounts.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="SET NULL")),
        sa.Column("party_group_id", sa.Integer(), sa.ForeignKey("erp_party_groups.id", ondelete="SET NULL")),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("note", sa.Text()),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint("period_start <= period_end", name="ck_budget_entries_period_order"),
    )
    op.create_index("ix_budget_entries_budget", "budget_entries", ["budget_id", "budget_account_id"])
    op.create_index("ix_budget_entries_org_account", "budget_entries", ["organization_id", "budget_account_id"])
    # Actuals are read per account and date; the GL already has that index.
    op.execute("""
        INSERT INTO erp_capabilities (access_role_id, resource, action)
        SELECT r.id, 'budget_settings', '*'
        FROM erp_access_roles r
        WHERE r.code = 'erp_accountant' AND r.is_system
          AND NOT EXISTS (
            SELECT 1 FROM erp_capabilities c WHERE c.access_role_id = r.id AND c.resource = 'budget_settings'
          )
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM erp_capabilities
        WHERE resource = 'budget_settings'
          AND access_role_id IN (SELECT id FROM erp_access_roles WHERE code = 'erp_accountant' AND is_system)
    """)
    op.drop_index("ix_budget_entries_org_account", table_name="budget_entries")
    op.drop_index("ix_budget_entries_budget", table_name="budget_entries")
    op.drop_table("budget_entries")
    op.drop_index("ix_budgets_org_status", table_name="budgets")
    op.drop_table("budgets")
    op.drop_index("ix_budget_account_links_budget_account", table_name="budget_account_links")
    op.drop_table("budget_account_links")
    op.drop_index("ix_budget_accounts_org_group", table_name="budget_accounts")
    op.drop_table("budget_accounts")
    op.drop_table("budget_account_groups")
