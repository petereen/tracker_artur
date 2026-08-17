"""Add normalized ERP core-operation entities and workflow metadata.

Revision ID: a1b2c3d4e5f7
Revises: z4a5b6c7d8e9
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "a1b2c3d4e5f7"
down_revision: Union[str, Sequence[str], None] = "z4a5b6c7d8e9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("erp_master_requests", sa.Column("approved_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")))
    op.add_column("erp_master_requests", sa.Column("approved_at", sa.DateTime(timezone=True)))
    op.add_column("erp_document_lines", sa.Column("discount_percent", sa.Numeric(9, 4), nullable=False, server_default="0"))
    op.add_column("erp_document_lines", sa.Column("discount_amount", sa.Numeric(18, 4), nullable=False, server_default="0"))
    op.add_column("erp_documents", sa.Column("archived_at", sa.DateTime(timezone=True)))
    op.add_column("erp_documents", sa.Column("archived_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")))
    op.create_index("ix_erp_documents_org_archive", "erp_documents", ["organization_id", "archived_at"])

    op.create_table(
        "erp_module_configs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("module", sa.String(40), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("updated_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "module", name="uq_erp_module_config_org_module"),
    )
    op.create_index("ix_erp_module_configs_org_enabled", "erp_module_configs", ["organization_id", "enabled"])
    op.execute("""
        INSERT INTO erp_module_configs (organization_id, module, enabled)
        SELECT o.id, module_name, COALESCE((o.settings->'erp_modules'->>module_name)::boolean, false)
        FROM organizations o
        CROSS JOIN unnest(ARRAY['accounting','selling','buying','stock','crm','support','payroll','manufacturing','assets_maintenance']) AS module_name
        ON CONFLICT (organization_id, module) DO NOTHING
    """)

    op.create_table(
        "erp_units_of_measure",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(32), nullable=False), sa.Column("name", sa.Text(), nullable=False),
        sa.Column("symbol", sa.String(16)), sa.Column("decimal_places", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "code", name="uq_erp_uom_org_code"),
    )
    op.create_table(
        "erp_price_lists",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(64), nullable=False), sa.Column("name", sa.Text(), nullable=False),
        sa.Column("party_id", sa.Integer(), sa.ForeignKey("erp_parties.id", ondelete="SET NULL")),
        sa.Column("price_list_type", sa.String(24), nullable=False, server_default="supplier"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="MNT"),
        sa.Column("valid_from", sa.Date()), sa.Column("valid_to", sa.Date()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "code", name="uq_erp_price_list_org_code"),
    )
    op.create_table(
        "erp_price_list_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("price_list_id", sa.Integer(), sa.ForeignKey("erp_price_lists.id", ondelete="CASCADE"), nullable=False),
        sa.Column("item_id", sa.Integer(), sa.ForeignKey("erp_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("uom_id", sa.Integer(), sa.ForeignKey("erp_units_of_measure.id", ondelete="SET NULL")),
        sa.Column("minimum_quantity", sa.Numeric(18, 6), nullable=False, server_default="1"),
        sa.Column("rate", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.UniqueConstraint("price_list_id", "item_id", name="uq_erp_price_list_entry_item"),
    )
    op.create_table(
        "erp_discount_tiers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(64), nullable=False), sa.Column("name", sa.Text(), nullable=False),
        sa.Column("minimum_spend", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("discount_percent", sa.Numeric(9, 4), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "code", name="uq_erp_discount_tier_org_code"),
    )
    op.create_table(
        "erp_reorder_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("item_id", sa.Integer(), sa.ForeignKey("erp_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("warehouse_id", sa.Integer(), sa.ForeignKey("erp_warehouses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reorder_level", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("reorder_quantity", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("maximum_level", sa.Numeric(18, 6)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.UniqueConstraint("organization_id", "item_id", "warehouse_id", name="uq_erp_reorder_rule_item_warehouse"),
    )
    op.create_table(
        "erp_cost_centers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parent_id", sa.Integer(), sa.ForeignKey("erp_cost_centers.id", ondelete="SET NULL")),
        sa.Column("code", sa.String(64), nullable=False), sa.Column("name", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.UniqueConstraint("organization_id", "code", name="uq_erp_cost_center_org_code"),
    )
    op.create_table(
        "erp_tax_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(64), nullable=False), sa.Column("name", sa.Text(), nullable=False),
        sa.Column("direction", sa.String(16), nullable=False, server_default="sales"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.UniqueConstraint("organization_id", "code", name="uq_erp_tax_template_org_code"),
    )
    op.create_table(
        "erp_tax_template_rates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tax_template_id", sa.Integer(), sa.ForeignKey("erp_tax_templates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False), sa.Column("rate", sa.Numeric(9, 4), nullable=False, server_default="0"),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("erp_accounts.id", ondelete="SET NULL")),
    )
    op.create_table(
        "erp_inventory_levels",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("item_id", sa.Integer(), sa.ForeignKey("erp_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("warehouse_id", sa.Integer(), sa.ForeignKey("erp_warehouses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("valuation_rate", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("inventory_value", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "item_id", "warehouse_id", name="uq_erp_inventory_level_item_warehouse"),
    )
    op.create_index("ix_erp_inventory_levels_org_warehouse", "erp_inventory_levels", ["organization_id", "warehouse_id"])
    op.execute("""
        INSERT INTO erp_inventory_levels (organization_id, item_id, warehouse_id, quantity, valuation_rate, inventory_value)
        SELECT l.organization_id, l.item_id, l.warehouse_id,
               SUM(l.quantity_delta), COALESCE(i.standard_cost, 0),
               SUM(l.quantity_delta) * COALESCE(i.standard_cost, 0)
        FROM erp_stock_ledger_entries l
        JOIN erp_items i ON i.id = l.item_id
        GROUP BY l.organization_id, l.item_id, l.warehouse_id, i.standard_cost
        ON CONFLICT (organization_id, item_id, warehouse_id) DO NOTHING
    """)


def downgrade() -> None:
    op.drop_index("ix_erp_inventory_levels_org_warehouse", table_name="erp_inventory_levels")
    for table in ("erp_inventory_levels", "erp_tax_template_rates", "erp_tax_templates", "erp_cost_centers", "erp_reorder_rules", "erp_discount_tiers", "erp_price_list_entries", "erp_price_lists", "erp_units_of_measure"):
        op.drop_table(table)
    op.drop_index("ix_erp_module_configs_org_enabled", table_name="erp_module_configs")
    op.drop_table("erp_module_configs")
    op.drop_index("ix_erp_documents_org_archive", table_name="erp_documents")
    op.drop_column("erp_documents", "archived_by_account_id")
    op.drop_column("erp_documents", "archived_at")
    op.drop_column("erp_document_lines", "discount_amount")
    op.drop_column("erp_document_lines", "discount_percent")
    op.drop_column("erp_master_requests", "approved_at")
    op.drop_column("erp_master_requests", "approved_by_account_id")
