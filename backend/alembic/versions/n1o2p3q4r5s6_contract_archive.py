"""Add contract archive folders, entries, access grants, and legal counsel role."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "n1o2p3q4r5s6"
down_revision: Union[str, Sequence[str], None] = "m4n5o6p7q8r9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_role_assignments_role", "role_assignments", type_="check")
    op.create_check_constraint(
        "ck_role_assignments_role",
        "role_assignments",
        "role IN ('admin','manager','team_lead','hr','member','contractor','client_auditor','legal_counsel')",
    )

    op.create_table(
        "contract_archive_folders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parent_id", sa.Integer()),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("created_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.UniqueConstraint("organization_id", "id", name="uq_contract_archive_folders_org_id"),
        sa.ForeignKeyConstraint(
            ["organization_id", "parent_id"],
            ["contract_archive_folders.organization_id", "contract_archive_folders.id"],
            ondelete="CASCADE",
            name="fk_contract_archive_folders_parent_org",
        ),
    )
    op.create_index(
        "uq_contract_archive_folders_active_name",
        "contract_archive_folders",
        ["organization_id", sa.text("coalesce(parent_id, 0)"), sa.text("lower(name)")],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index("ix_contract_archive_folders_parent", "contract_archive_folders", ["organization_id", "parent_id", "deleted_at"])

    op.create_table(
        "contract_archive_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("folder_id", sa.Integer()),
        sa.Column("source", sa.String(24), nullable=False),
        sa.Column("contract_id", sa.Integer(), sa.ForeignKey("contract_documents.id", ondelete="SET NULL")),
        sa.Column("contract_file_id", sa.Integer(), sa.ForeignKey("contract_files.id", ondelete="SET NULL"), unique=True),
        sa.Column("storage_key", sa.Text(), unique=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False, server_default="Бусад"),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("scan_status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("review_status", sa.String(16), nullable=False, server_default="approved"),
        sa.Column("review_reason", sa.Text()),
        sa.Column("created_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("author_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("reviewed_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.CheckConstraint("source IN ('signed_contract','manual_upload')", name="ck_contract_archive_entries_source"),
        sa.CheckConstraint("review_status IN ('pending','approved','rejected')", name="ck_contract_archive_entries_review_status"),
        sa.CheckConstraint(
            "(source = 'signed_contract' AND contract_id IS NOT NULL AND contract_file_id IS NOT NULL AND storage_key IS NULL) OR "
            "(source = 'manual_upload' AND folder_id IS NOT NULL AND contract_id IS NULL AND contract_file_id IS NULL AND storage_key IS NOT NULL)",
            name="ck_contract_archive_entries_storage_source",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "folder_id"],
            ["contract_archive_folders.organization_id", "contract_archive_folders.id"],
            ondelete="SET NULL",
            name="fk_contract_archive_entries_folder_org",
        ),
        sa.UniqueConstraint("public_id", name="uq_contract_archive_entries_public_id"),
    )
    op.create_index("ix_contract_archive_entries_folder", "contract_archive_entries", ["organization_id", "folder_id", "review_status", "deleted_at"])
    op.create_index("ix_contract_archive_entries_search", "contract_archive_entries", ["organization_id", "name", "category"])
    op.create_index(
        "uq_contract_archive_entries_active_contract",
        "contract_archive_entries",
        ["contract_id"],
        unique=True,
        postgresql_where=sa.text("contract_id IS NOT NULL AND review_status IN ('pending','approved') AND deleted_at IS NULL"),
    )
    op.create_index(
        "uq_contract_archive_entries_active_folder_name",
        "contract_archive_entries",
        ["organization_id", "folder_id", sa.text("lower(name)")],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "contract_archive_access",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("folder_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("permission", sa.String(8), nullable=False, server_default="view"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("permission IN ('view','edit')", name="ck_contract_archive_access_permission"),
        sa.ForeignKeyConstraint(
            ["organization_id", "folder_id"],
            ["contract_archive_folders.organization_id", "contract_archive_folders.id"],
            ondelete="CASCADE",
            name="fk_contract_archive_access_folder_org",
        ),
        sa.UniqueConstraint("organization_id", "folder_id", "account_id", name="uq_contract_archive_access_folder_account"),
    )
    op.create_index("ix_contract_archive_access_account", "contract_archive_access", ["organization_id", "account_id", "folder_id"])

    op.execute(
        """
        INSERT INTO contract_archive_entries
            (organization_id, source, contract_id, contract_file_id, name, category,
             content_type, size, checksum, scan_status, review_status, created_by_account_id,
             author_account_id, created_at, updated_at)
        SELECT c.organization_id, 'signed_contract', c.id, f.id, f.filename,
               CASE c.document_type
                   WHEN 'contract' THEN 'Гэрээ'
                   WHEN 'agreement' THEN 'Хэлэлцээр'
                   WHEN 'official_letter' THEN 'Албан бичиг'
                   ELSE 'Бусад'
               END,
               f.content_type, f.size, f.checksum, f.scan_status, 'pending',
               f.uploaded_by_account_id, c.author_account_id, f.created_at, f.created_at
        FROM contract_documents c
        JOIN contract_files f ON f.id = c.signed_final_file_id
        WHERE c.status = 'SIGNED_AND_STAMPED'
          AND NOT EXISTS (
              SELECT 1 FROM contract_archive_entries e
              WHERE e.contract_id = c.id AND e.deleted_at IS NULL
          )
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM contract_archive_entries")
    op.drop_index("ix_contract_archive_access_account", table_name="contract_archive_access")
    op.drop_table("contract_archive_access")
    op.drop_index("uq_contract_archive_entries_active_contract", table_name="contract_archive_entries")
    op.drop_index("uq_contract_archive_entries_active_folder_name", table_name="contract_archive_entries")
    op.drop_index("ix_contract_archive_entries_search", table_name="contract_archive_entries")
    op.drop_index("ix_contract_archive_entries_folder", table_name="contract_archive_entries")
    op.drop_table("contract_archive_entries")
    op.drop_index("ix_contract_archive_folders_parent", table_name="contract_archive_folders")
    op.drop_index("uq_contract_archive_folders_active_name", table_name="contract_archive_folders")
    op.drop_table("contract_archive_folders")
    # The previous role constraint cannot be recreated while legal counsel
    # assignments exist; remove only those assignments as a safe downgrade.
    op.execute("DELETE FROM role_assignments WHERE role = 'legal_counsel'")
    op.drop_constraint("ck_role_assignments_role", "role_assignments", type_="check")
    op.create_check_constraint(
        "ck_role_assignments_role",
        "role_assignments",
        "role IN ('admin','manager','team_lead','hr','member','contractor','client_auditor')",
    )
