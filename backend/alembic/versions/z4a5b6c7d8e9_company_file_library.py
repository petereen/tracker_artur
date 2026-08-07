"""add organization company file library

Revision ID: z4a5b6c7d8e9
Revises: y3z4a5b6c7d8
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "z4a5b6c7d8e9"
down_revision: Union[str, Sequence[str], None] = "y3z4a5b6c7d8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "company_library_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parent_id", sa.Integer(), sa.ForeignKey("company_library_items.id", ondelete="CASCADE")),
        sa.Column("kind", sa.String(length=12), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.Text(), unique=True),
        sa.Column("content_type", sa.Text()),
        sa.Column("size", sa.Integer()),
        sa.Column("checksum", sa.String(length=64)),
        sa.Column("uploaded_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.CheckConstraint("kind IN ('folder','file')", name="ck_company_library_items_kind"),
        sa.CheckConstraint(
            "(kind = 'folder' AND storage_key IS NULL AND content_type IS NULL AND size IS NULL AND checksum IS NULL) "
            "OR (kind = 'file' AND storage_key IS NOT NULL AND content_type IS NOT NULL AND size IS NOT NULL AND checksum IS NOT NULL)",
            name="ck_company_library_items_file_metadata",
        ),
    )
    op.create_index("ix_company_library_items_parent", "company_library_items", ["organization_id", "parent_id"])
    op.create_index("ix_company_library_items_deleted", "company_library_items", ["organization_id", "deleted_at"])
    op.create_index(
        "uq_company_library_items_active_sibling_name",
        "company_library_items",
        ["organization_id", sa.text("coalesce(parent_id, 0)"), sa.text("lower(name)")],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_table("company_library_items")
