"""Contract registry metadata («Гэрээ бүртгэх», Dayansoft d028)

Adds the registry fields Dayansoft keeps on every contract: internal code
(auto-continued), official number, contract group (hierarchical), counterparty
from the CRM customer master, contract date, quantity / unit / unit price /
amount / currency, penalty %, payment term, note, active flag, file links and
free-form meta fields. Existing contracts get sequential ``CT-0001`` codes per
organization.

Revision ID: c2d3e4f5a6b7
Revises: a1c2e3g4i5k6
Create Date: 2026-09-29 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c2d3e4f5a6b7"
down_revision: Union[str, Sequence[str], None] = "a1c2e3g4i5k6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "contract_groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("parent_id", sa.Integer(), sa.ForeignKey("contract_groups.id", ondelete="SET NULL")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "code", name="uq_contract_groups_org_code"),
    )

    op.add_column("contract_documents", sa.Column("code", sa.String(64)))
    op.add_column("contract_documents", sa.Column("contract_number", sa.String(120)))
    op.add_column("contract_documents", sa.Column("group_id", sa.Integer(), sa.ForeignKey("contract_groups.id", ondelete="SET NULL", name="fk_contract_documents_group")))
    op.add_column("contract_documents", sa.Column("party_id", sa.Integer(), sa.ForeignKey("erp_parties.id", ondelete="SET NULL", name="fk_contract_documents_party")))
    op.add_column("contract_documents", sa.Column("signed_on", sa.Date()))
    op.add_column("contract_documents", sa.Column("quantity", sa.Numeric(18, 4)))
    op.add_column("contract_documents", sa.Column("unit_id", sa.Integer(), sa.ForeignKey("erp_units_of_measure.id", ondelete="SET NULL", name="fk_contract_documents_unit")))
    op.add_column("contract_documents", sa.Column("unit_price", sa.Numeric(18, 4)))
    op.add_column("contract_documents", sa.Column("amount", sa.Numeric(18, 2)))
    op.add_column("contract_documents", sa.Column("currency", sa.String(3), nullable=False, server_default="MNT"))
    op.add_column("contract_documents", sa.Column("penalty_pct", sa.Numeric(7, 4)))
    op.add_column("contract_documents", sa.Column("payment_term_id", sa.Integer(), sa.ForeignKey("erp_payment_terms.id", ondelete="SET NULL", name="fk_contract_documents_payment_term")))
    op.add_column("contract_documents", sa.Column("note", sa.Text()))
    op.add_column("contract_documents", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")))
    op.add_column("contract_documents", sa.Column("links", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.add_column("contract_documents", sa.Column("custom_fields", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.create_check_constraint("ck_contract_documents_amounts_non_negative", "contract_documents", "(quantity IS NULL OR quantity >= 0) AND (unit_price IS NULL OR unit_price >= 0) AND (amount IS NULL OR amount >= 0)")
    op.create_check_constraint("ck_contract_documents_penalty_pct", "contract_documents", "penalty_pct IS NULL OR (penalty_pct >= 0 AND penalty_pct <= 100)")

    op.execute(
        """
        UPDATE contract_documents AS doc
        SET code = 'CT-' || lpad(numbered.n::text, 4, '0')
        FROM (
            SELECT id, row_number() OVER (PARTITION BY organization_id ORDER BY created_at, id) AS n
            FROM contract_documents
        ) AS numbered
        WHERE numbered.id = doc.id AND doc.code IS NULL
        """
    )
    op.create_index("uq_contract_documents_org_code", "contract_documents", ["organization_id", "code"], unique=True, postgresql_where=sa.text("code IS NOT NULL"))
    op.create_index("ix_contract_documents_org_party", "contract_documents", ["organization_id", "party_id"])
    op.create_index("ix_contract_documents_org_group", "contract_documents", ["organization_id", "group_id"])


def downgrade() -> None:
    op.drop_index("ix_contract_documents_org_group", table_name="contract_documents")
    op.drop_index("ix_contract_documents_org_party", table_name="contract_documents")
    op.drop_index("uq_contract_documents_org_code", table_name="contract_documents")
    op.drop_constraint("ck_contract_documents_penalty_pct", "contract_documents", type_="check")
    op.drop_constraint("ck_contract_documents_amounts_non_negative", "contract_documents", type_="check")
    for column in ("custom_fields", "links", "is_active", "note", "payment_term_id", "penalty_pct", "currency", "amount", "unit_price", "unit_id", "quantity", "signed_on", "party_id", "group_id", "contract_number", "code"):
        op.drop_column("contract_documents", column)
    op.drop_table("contract_groups")
