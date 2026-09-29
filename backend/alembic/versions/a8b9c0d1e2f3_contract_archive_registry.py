"""Contract data («Гэрээний бүртгэл») on archived contracts

Manually uploaded archive files (existing signed contracts) get the same
registry fields as contract documents: internal code, official number, group,
counterparty, contract date, quantity / unit / price / amount / currency,
penalty %, payment term, note, active flag, links and meta fields. Archived
signed contracts keep their data on the contract document.

Revision ID: a8b9c0d1e2f3
Revises: f7a8b9c0d1e2
Create Date: 2026-09-29 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a8b9c0d1e2f3"
down_revision: Union[str, Sequence[str], None] = "f7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "contract_archive_entries"
COLUMNS = ("code", "contract_number", "group_id", "party_id", "signed_on", "quantity", "unit_id", "unit_price", "amount", "currency",
           "penalty_pct", "payment_term_id", "note", "is_active", "links", "custom_fields")


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("code", sa.String(64)))
    op.add_column(TABLE, sa.Column("contract_number", sa.String(120)))
    op.add_column(TABLE, sa.Column("group_id", sa.Integer(), sa.ForeignKey("contract_groups.id", ondelete="SET NULL", name="fk_contract_archive_entries_group")))
    op.add_column(TABLE, sa.Column("party_id", sa.Integer(), sa.ForeignKey("erp_parties.id", ondelete="SET NULL", name="fk_contract_archive_entries_party")))
    op.add_column(TABLE, sa.Column("signed_on", sa.Date()))
    op.add_column(TABLE, sa.Column("quantity", sa.Numeric(18, 4)))
    op.add_column(TABLE, sa.Column("unit_id", sa.Integer(), sa.ForeignKey("erp_units_of_measure.id", ondelete="SET NULL", name="fk_contract_archive_entries_unit")))
    op.add_column(TABLE, sa.Column("unit_price", sa.Numeric(18, 4)))
    op.add_column(TABLE, sa.Column("amount", sa.Numeric(18, 2)))
    op.add_column(TABLE, sa.Column("currency", sa.String(3), nullable=False, server_default="MNT"))
    op.add_column(TABLE, sa.Column("penalty_pct", sa.Numeric(7, 4)))
    op.add_column(TABLE, sa.Column("payment_term_id", sa.Integer(), sa.ForeignKey("erp_payment_terms.id", ondelete="SET NULL", name="fk_contract_archive_entries_payment_term")))
    op.add_column(TABLE, sa.Column("note", sa.Text()))
    op.add_column(TABLE, sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")))
    op.add_column(TABLE, sa.Column("links", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.add_column(TABLE, sa.Column("custom_fields", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.create_check_constraint("ck_contract_archive_entries_amounts_non_negative", TABLE, "(quantity IS NULL OR quantity >= 0) AND (unit_price IS NULL OR unit_price >= 0) AND (amount IS NULL OR amount >= 0)")
    op.create_check_constraint("ck_contract_archive_entries_penalty_pct", TABLE, "penalty_pct IS NULL OR (penalty_pct >= 0 AND penalty_pct <= 100)")
    op.create_index("uq_contract_archive_entries_org_code", TABLE, ["organization_id", "code"], unique=True, postgresql_where=sa.text("code IS NOT NULL AND deleted_at IS NULL"))


def downgrade() -> None:
    op.drop_index("uq_contract_archive_entries_org_code", table_name=TABLE)
    op.drop_constraint("ck_contract_archive_entries_penalty_pct", TABLE, type_="check")
    op.drop_constraint("ck_contract_archive_entries_amounts_non_negative", TABLE, type_="check")
    for column in reversed(COLUMNS):
        op.drop_column(TABLE, column)
