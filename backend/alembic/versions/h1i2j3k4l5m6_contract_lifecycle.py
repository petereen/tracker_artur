"""Add the Гэрээ contract lifecycle domain."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "h1i2j3k4l5m6"
down_revision: Union[str, None] = "g1h2i3j4k5l6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "contract_documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("author_account_id", sa.Integer(), nullable=True),
        sa.Column("author_employee_id", sa.Integer()),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("document_type", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="DRAFT"),
        sa.Column("project_id", sa.Integer()),
        sa.Column("task_id", sa.Integer()),
        sa.Column("effective_start_on", sa.Date()),
        sa.Column("effective_end_on", sa.Date()),
        sa.Column("reviewer_account_ids", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("current_revision_id", sa.Integer()),
        sa.Column("approved_revision_id", sa.Integer()),
        sa.Column("signed_final_file_id", sa.Integer()),
        sa.Column("submission_round", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("printed_at", sa.DateTime(timezone=True)),
        sa.Column("printed_by_account_id", sa.Integer()),
        sa.Column("signed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["author_account_id"], ["user_accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["author_employee_id"], ["employees.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["printed_by_account_id"], ["user_accounts.id"], ondelete="SET NULL"),
        sa.CheckConstraint("status IN ('DRAFT','PENDING_REVIEW','CHANGES_REQUESTED','APPROVED','REJECTED','SIGNED_AND_STAMPED')", name="ck_contract_documents_status"),
        sa.CheckConstraint("document_type IN ('contract','agreement','official_letter','other')", name="ck_contract_documents_type"),
        sa.CheckConstraint("effective_end_on IS NULL OR effective_start_on IS NULL OR effective_end_on >= effective_start_on", name="ck_contract_documents_effective_range"),
    )
    op.create_index("ix_contract_documents_public_id", "contract_documents", ["public_id"], unique=True)
    op.create_index("ix_contract_documents_org_status", "contract_documents", ["organization_id", "status", "updated_at"])
    op.create_index("ix_contract_documents_author_status", "contract_documents", ["author_account_id", "status", "updated_at"])

    op.create_table(
        "contract_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("contract_id", sa.Integer(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("document_type", sa.String(length=24), nullable=False),
        sa.Column("body_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("plain_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("project_id", sa.Integer()),
        sa.Column("task_id", sa.Integer()),
        sa.Column("effective_start_on", sa.Date()),
        sa.Column("effective_end_on", sa.Date()),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("author_account_id", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["contract_id"], ["contract_documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["author_account_id"], ["user_accounts.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("contract_id", "revision_number", name="uq_contract_revisions_number"),
    )
    op.create_index("ix_contract_revisions_contract_created", "contract_revisions", ["contract_id", "created_at"])

    op.create_table(
        "contract_files",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("contract_id", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.String(length=16), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("scan_status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("uploaded_by_account_id", sa.Integer()),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["contract_id"], ["contract_documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_by_account_id"], ["user_accounts.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("storage_key"),
        sa.CheckConstraint("purpose IN ('supporting','signed_final')", name="ck_contract_files_purpose"),
    )
    op.create_index("ix_contract_files_contract_purpose", "contract_files", ["contract_id", "purpose", "created_at"])

    op.create_table(
        "contract_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("contract_id", sa.Integer(), nullable=False),
        sa.Column("round_number", sa.Integer(), nullable=False),
        sa.Column("revision_id", sa.Integer(), nullable=False),
        sa.Column("reviewer_account_id", sa.Integer(), nullable=False),
        sa.Column("reviewer_employee_id", sa.Integer()),
        sa.Column("reviewer_name_snapshot", sa.Text(), nullable=False),
        sa.Column("decision", sa.String(length=24), nullable=False, server_default="pending"),
        sa.Column("remark", sa.Text()),
        sa.Column("acted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["contract_id"], ["contract_documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["revision_id"], ["contract_revisions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reviewer_account_id"], ["user_accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reviewer_employee_id"], ["employees.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("contract_id", "round_number", "reviewer_account_id", name="uq_contract_reviews_round_reviewer"),
        sa.CheckConstraint("decision IN ('pending','approved','changes_requested','rejected')", name="ck_contract_reviews_decision"),
    )
    op.create_index("ix_contract_reviews_reviewer_pending", "contract_reviews", ["reviewer_account_id", "decision", "contract_id"])
    op.create_index("ix_contract_reviews_contract_round", "contract_reviews", ["contract_id", "round_number"])

    op.create_table(
        "contract_comments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("contract_id", sa.Integer(), nullable=False),
        sa.Column("revision_id", sa.Integer(), nullable=False),
        sa.Column("parent_id", sa.Integer()),
        sa.Column("author_account_id", sa.Integer()),
        sa.Column("anchor", postgresql.JSONB()),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_resolved", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["contract_id"], ["contract_documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["revision_id"], ["contract_revisions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_id"], ["contract_comments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["author_account_id"], ["user_accounts.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_contract_comments_revision_created", "contract_comments", ["revision_id", "created_at"])
    op.create_foreign_key("fk_contract_documents_current_revision", "contract_documents", "contract_revisions", ["current_revision_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_contract_documents_approved_revision", "contract_documents", "contract_revisions", ["approved_revision_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_contract_documents_signed_file", "contract_documents", "contract_files", ["signed_final_file_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    op.drop_constraint("fk_contract_documents_signed_file", "contract_documents", type_="foreignkey")
    op.drop_constraint("fk_contract_documents_approved_revision", "contract_documents", type_="foreignkey")
    op.drop_constraint("fk_contract_documents_current_revision", "contract_documents", type_="foreignkey")
    op.drop_index("ix_contract_comments_revision_created", table_name="contract_comments")
    op.drop_table("contract_comments")
    op.drop_index("ix_contract_reviews_contract_round", table_name="contract_reviews")
    op.drop_index("ix_contract_reviews_reviewer_pending", table_name="contract_reviews")
    op.drop_table("contract_reviews")
    op.drop_index("ix_contract_files_contract_purpose", table_name="contract_files")
    op.drop_table("contract_files")
    op.drop_index("ix_contract_revisions_contract_created", table_name="contract_revisions")
    op.drop_table("contract_revisions")
    op.drop_index("ix_contract_documents_author_status", table_name="contract_documents")
    op.drop_index("ix_contract_documents_org_status", table_name="contract_documents")
    op.drop_index("ix_contract_documents_public_id", table_name="contract_documents")
    op.drop_table("contract_documents")
