"""Additive Phase 5 selling, buying, stock, manufacturing, and assets records."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "g2h3i4j5k6l7"
down_revision = "f1g2h3i4j5k6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "erp_source_line_allocations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_document_id", sa.Integer(), sa.ForeignKey("erp_documents.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_line_id", sa.Integer(), sa.ForeignKey("erp_document_lines.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("target_document_id", sa.Integer(), sa.ForeignKey("erp_documents.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("target_line_id", sa.Integer(), sa.ForeignKey("erp_document_lines.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 6), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("target_document_id", "target_line_id", "source_document_id", "source_line_id", name="uq_erp_source_line_allocation"),
    )
    op.create_index("ix_erp_source_line_allocations_source", "erp_source_line_allocations", ["organization_id", "source_document_id", "source_line_id"])

    op.create_table(
        "erp_stock_valuation_layers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("erp_documents.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("item_id", sa.Integer(), sa.ForeignKey("erp_items.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("warehouse_id", sa.Integer(), sa.ForeignKey("erp_warehouses.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 6), nullable=False),
        sa.Column("remaining_quantity", sa.Numeric(18, 6), nullable=False),
        sa.Column("unit_cost", sa.Numeric(18, 4), nullable=False),
        sa.Column("value", sa.Numeric(18, 4), nullable=False),
        sa.Column("valuation_method", sa.String(24), server_default="moving_average", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_erp_stock_valuation_layers_balance", "erp_stock_valuation_layers", ["organization_id", "item_id", "warehouse_id", "created_at"])

    op.create_table(
        "erp_bom_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("bom_document_id", sa.Integer(), sa.ForeignKey("erp_documents.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), server_default="approved", nullable=False),
        sa.Column("output_item_id", sa.Integer(), sa.ForeignKey("erp_items.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("output_quantity", sa.Numeric(18, 6), nullable=False),
        sa.Column("lines", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("operations", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("organization_id", "bom_document_id", "version", name="uq_erp_bom_snapshot_version"),
    )

    op.create_table(
        "erp_asset_books",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("currency", sa.String(3), server_default="MNT", nullable=False),
        sa.Column("depreciation_method", sa.String(24), server_default="straight_line", nullable=False),
        sa.Column("useful_life_months", sa.Integer(), nullable=False),
        sa.Column("residual_value", sa.Numeric(18, 4), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("organization_id", "code", name="uq_erp_asset_book_org_code"),
    )
    op.create_table(
        "erp_asset_depreciation_schedules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("asset_document_id", sa.Integer(), sa.ForeignKey("erp_documents.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("book_id", sa.Integer(), sa.ForeignKey("erp_asset_books.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("period_date", sa.Date(), nullable=False),
        sa.Column("depreciation_amount", sa.Numeric(18, 4), nullable=False),
        sa.Column("accumulated_amount", sa.Numeric(18, 4), nullable=False),
        sa.Column("status", sa.String(24), server_default="scheduled", nullable=False),
        sa.Column("journal_document_id", sa.Integer(), sa.ForeignKey("erp_documents.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("asset_document_id", "book_id", "period_date", name="uq_erp_asset_depreciation_period"),
    )
    op.create_table(
        "erp_asset_maintenance_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("asset_document_id", sa.Integer(), sa.ForeignKey("erp_documents.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("scheduled_date", sa.Date(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(24), server_default="planned", nullable=False),
        sa.Column("cost", sa.Numeric(18, 4), server_default="0", nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_erp_asset_maintenance_org_asset_date", "erp_asset_maintenance_records", ["organization_id", "asset_document_id", "scheduled_date"])
    op.create_table(
        "erp_asset_disposals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("asset_document_id", sa.Integer(), sa.ForeignKey("erp_documents.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("disposal_date", sa.Date(), nullable=False),
        sa.Column("proceeds", sa.Numeric(18, 4), server_default="0", nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("journal_document_id", sa.Integer(), sa.ForeignKey("erp_documents.id", ondelete="SET NULL")),
        sa.Column("reversal_document_id", sa.Integer(), sa.ForeignKey("erp_documents.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("asset_document_id", name="uq_erp_asset_disposal_asset"),
    )
    op.execute("""
    CREATE OR REPLACE FUNCTION erp_phase5_immutable() RETURNS trigger AS $$
    BEGIN
      IF TG_TABLE_NAME = 'erp_asset_depreciation_schedules' AND TG_OP = 'UPDATE' THEN
        IF NEW.asset_document_id IS DISTINCT FROM OLD.asset_document_id OR NEW.book_id IS DISTINCT FROM OLD.book_id OR NEW.period_date IS DISTINCT FROM OLD.period_date OR NEW.depreciation_amount IS DISTINCT FROM OLD.depreciation_amount OR NEW.accumulated_amount IS DISTINCT FROM OLD.accumulated_amount THEN
          RAISE EXCEPTION 'Depreciation schedule amounts and identity are immutable';
        END IF;
        RETURN NEW;
      END IF;
      RAISE EXCEPTION 'Phase 5 ledger and schedule records are immutable';
    END; $$ LANGUAGE plpgsql;
    """)
    for table in ("erp_source_line_allocations", "erp_stock_valuation_layers", "erp_bom_snapshots", "erp_asset_depreciation_schedules"):
        op.execute(f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION erp_phase5_immutable()")


def downgrade() -> None:
    for table in ("erp_asset_depreciation_schedules", "erp_bom_snapshots", "erp_stock_valuation_layers", "erp_source_line_allocations"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_immutable ON {table}")
    op.execute("DROP FUNCTION IF EXISTS erp_phase5_immutable()")
    op.drop_table("erp_asset_disposals")
    op.drop_index("ix_erp_asset_maintenance_org_asset_date", table_name="erp_asset_maintenance_records")
    op.drop_table("erp_asset_maintenance_records")
    op.drop_table("erp_asset_depreciation_schedules")
    op.drop_table("erp_asset_books")
    op.drop_table("erp_bom_snapshots")
    op.drop_index("ix_erp_stock_valuation_layers_balance", table_name="erp_stock_valuation_layers")
    op.drop_table("erp_stock_valuation_layers")
    op.drop_index("ix_erp_source_line_allocations_source", table_name="erp_source_line_allocations")
    op.drop_table("erp_source_line_allocations")
