"""Contract lifecycle models.

The contract domain lives in its own module so the existing enterprise models
remain stable while Alembic still discovers every table through ``app.models``.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text as sa_text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base


CONTRACT_STATUSES = (
    "DRAFT",
    "PENDING_REVIEW",
    "CHANGES_REQUESTED",
    "APPROVED",
    "REJECTED",
    "SIGNED_AND_STAMPED",
)
CONTRACT_DOCUMENT_TYPES = ("contract", "agreement", "official_letter", "other")
CONTRACT_REVIEW_DECISIONS = ("pending", "approved", "changes_requested", "rejected")
CONTRACT_FILE_PURPOSES = ("supporting", "signed_final")
ARCHIVE_SOURCES = ("signed_contract", "manual_upload")
ARCHIVE_REVIEW_STATUSES = ("pending", "approved", "rejected")
ARCHIVE_PERMISSIONS = ("view", "edit")


class ContractDocument(Base):
    __tablename__ = "contract_documents"
    __table_args__ = (
        CheckConstraint("status IN ('DRAFT','PENDING_REVIEW','CHANGES_REQUESTED','APPROVED','REJECTED','SIGNED_AND_STAMPED')", name="ck_contract_documents_status"),
        CheckConstraint("document_type IN ('contract','agreement','official_letter','other')", name="ck_contract_documents_type"),
        CheckConstraint("effective_end_on IS NULL OR effective_start_on IS NULL OR effective_end_on >= effective_start_on", name="ck_contract_documents_effective_range"),
        Index("ix_contract_documents_org_status", "organization_id", "status", "updated_at"),
        Index("ix_contract_documents_author_status", "author_account_id", "status", "updated_at"),
    )

    id = Column(Integer, primary_key=True)
    public_id = Column(UUID(as_uuid=True), nullable=False, unique=True, default=uuid.uuid4, server_default=sa_text("gen_random_uuid()"))
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    author_account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="SET NULL"), nullable=True)
    author_employee_id = Column(Integer, ForeignKey("employees.id", ondelete="SET NULL"))
    title = Column(Text, nullable=False)
    document_type = Column(String(24), nullable=False)
    status = Column(String(24), nullable=False, server_default="DRAFT", default="DRAFT")
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="SET NULL"))
    task_id = Column(Integer, ForeignKey("tasks.id", ondelete="SET NULL"))
    effective_start_on = Column(Date)
    effective_end_on = Column(Date)
    reviewer_account_ids = Column(JSONB, nullable=False, server_default=sa_text("'[]'::jsonb"), default=list)
    current_revision_id = Column(Integer, ForeignKey("contract_revisions.id", ondelete="SET NULL"))
    approved_revision_id = Column(Integer, ForeignKey("contract_revisions.id", ondelete="SET NULL"))
    signed_final_file_id = Column(Integer, ForeignKey("contract_files.id", ondelete="SET NULL"))
    submission_round = Column(Integer, nullable=False, server_default="0", default=0)
    version = Column(Integer, nullable=False, server_default="1", default=1)
    approved_at = Column(DateTime(timezone=True))
    printed_at = Column(DateTime(timezone=True))
    printed_by_account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="SET NULL"))
    signed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class ContractRevision(Base):
    __tablename__ = "contract_revisions"
    __table_args__ = (
        UniqueConstraint("contract_id", "revision_number", name="uq_contract_revisions_number"),
        Index("ix_contract_revisions_contract_created", "contract_id", "created_at"),
    )

    id = Column(Integer, primary_key=True)
    contract_id = Column(Integer, ForeignKey("contract_documents.id", ondelete="CASCADE"), nullable=False)
    revision_number = Column(Integer, nullable=False)
    title = Column(Text, nullable=False)
    document_type = Column(String(24), nullable=False)
    body_json = Column(JSONB, nullable=False, server_default=sa_text("'{}'::jsonb"), default=dict)
    plain_text = Column(Text, nullable=False, server_default="", default="")
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="SET NULL"))
    task_id = Column(Integer, ForeignKey("tasks.id", ondelete="SET NULL"))
    effective_start_on = Column(Date)
    effective_end_on = Column(Date)
    checksum = Column(String(64), nullable=False)
    author_account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ContractReview(Base):
    __tablename__ = "contract_reviews"
    __table_args__ = (
        UniqueConstraint("contract_id", "round_number", "reviewer_account_id", name="uq_contract_reviews_round_reviewer"),
        CheckConstraint("decision IN ('pending','approved','changes_requested','rejected')", name="ck_contract_reviews_decision"),
        Index("ix_contract_reviews_reviewer_pending", "reviewer_account_id", "decision", "contract_id"),
        Index("ix_contract_reviews_contract_round", "contract_id", "round_number"),
    )

    id = Column(Integer, primary_key=True)
    contract_id = Column(Integer, ForeignKey("contract_documents.id", ondelete="CASCADE"), nullable=False)
    round_number = Column(Integer, nullable=False)
    revision_id = Column(Integer, ForeignKey("contract_revisions.id", ondelete="RESTRICT"), nullable=False)
    reviewer_account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="RESTRICT"), nullable=False)
    reviewer_employee_id = Column(Integer, ForeignKey("employees.id", ondelete="SET NULL"))
    reviewer_name_snapshot = Column(Text, nullable=False)
    decision = Column(String(24), nullable=False, server_default="pending", default="pending")
    remark = Column(Text)
    acted_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ContractComment(Base):
    __tablename__ = "contract_comments"
    __table_args__ = (Index("ix_contract_comments_revision_created", "revision_id", "created_at"),)

    id = Column(Integer, primary_key=True)
    contract_id = Column(Integer, ForeignKey("contract_documents.id", ondelete="CASCADE"), nullable=False)
    revision_id = Column(Integer, ForeignKey("contract_revisions.id", ondelete="CASCADE"), nullable=False)
    parent_id = Column(Integer, ForeignKey("contract_comments.id", ondelete="CASCADE"))
    author_account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="SET NULL"))
    anchor = Column(JSONB)
    body = Column(Text, nullable=False)
    is_resolved = Column(Boolean, nullable=False, server_default=sa_text("false"), default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class ContractFile(Base):
    __tablename__ = "contract_files"
    __table_args__ = (
        CheckConstraint("purpose IN ('supporting','signed_final')", name="ck_contract_files_purpose"),
        Index("ix_contract_files_contract_purpose", "contract_id", "purpose", "created_at"),
    )

    id = Column(Integer, primary_key=True)
    contract_id = Column(Integer, ForeignKey("contract_documents.id", ondelete="CASCADE"), nullable=False)
    purpose = Column(String(16), nullable=False)
    storage_key = Column(Text, nullable=False, unique=True)
    filename = Column(Text, nullable=False)
    content_type = Column(Text, nullable=False)
    size = Column(Integer, nullable=False)
    checksum = Column(String(64), nullable=False)
    scan_status = Column(String(16), nullable=False, server_default="pending", default="pending")
    uploaded_by_account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="SET NULL"))
    confirmed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ContractArchiveFolder(Base):
    __tablename__ = "contract_archive_folders"
    __table_args__ = (
        Index(
            "uq_contract_archive_folders_active_name",
            "organization_id",
            sa_text("coalesce(parent_id, 0)"),
            sa_text("lower(name)"),
            unique=True,
            postgresql_where=sa_text("deleted_at IS NULL"),
        ),
        Index("ix_contract_archive_folders_parent", "organization_id", "parent_id", "deleted_at"),
        UniqueConstraint("organization_id", "id", name="uq_contract_archive_folders_org_id"),
        ForeignKeyConstraint(
            ["organization_id", "parent_id"],
            ["contract_archive_folders.organization_id", "contract_archive_folders.id"],
            ondelete="CASCADE",
            name="fk_contract_archive_folders_parent_org",
        ),
    )

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    parent_id = Column(Integer)
    name = Column(Text, nullable=False)
    description = Column(Text)
    created_by_account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="SET NULL"))
    version = Column(Integer, nullable=False, server_default="1", default=1)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    deleted_at = Column(DateTime(timezone=True))
    deleted_by_account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="SET NULL"))


class ContractArchiveEntry(Base):
    __tablename__ = "contract_archive_entries"
    __table_args__ = (
        CheckConstraint("source IN ('signed_contract','manual_upload')", name="ck_contract_archive_entries_source"),
        CheckConstraint("review_status IN ('pending','approved','rejected')", name="ck_contract_archive_entries_review_status"),
        CheckConstraint(
            "(source = 'signed_contract' AND contract_id IS NOT NULL AND contract_file_id IS NOT NULL AND storage_key IS NULL) OR "
            "(source = 'manual_upload' AND folder_id IS NOT NULL AND contract_id IS NULL AND contract_file_id IS NULL AND storage_key IS NOT NULL)",
            name="ck_contract_archive_entries_storage_source",
        ),
        ForeignKeyConstraint(
            ["organization_id", "folder_id"],
            ["contract_archive_folders.organization_id", "contract_archive_folders.id"],
            ondelete="SET NULL",
            name="fk_contract_archive_entries_folder_org",
        ),
        Index("ix_contract_archive_entries_folder", "organization_id", "folder_id", "review_status", "deleted_at"),
        Index("ix_contract_archive_entries_search", "organization_id", "name", "category"),
        Index(
            "uq_contract_archive_entries_active_contract",
            "contract_id",
            unique=True,
            postgresql_where=sa_text("contract_id IS NOT NULL AND review_status IN ('pending','approved') AND deleted_at IS NULL"),
        ),
        Index(
            "uq_contract_archive_entries_active_folder_name",
            "organization_id",
            "folder_id",
            sa_text("lower(name)"),
            unique=True,
            postgresql_where=sa_text("deleted_at IS NULL"),
        ),
    )

    id = Column(Integer, primary_key=True)
    public_id = Column(UUID(as_uuid=True), nullable=False, unique=True, default=uuid.uuid4, server_default=sa_text("gen_random_uuid()"))
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    folder_id = Column(Integer)
    source = Column(String(24), nullable=False)
    contract_id = Column(Integer, ForeignKey("contract_documents.id", ondelete="SET NULL"))
    contract_file_id = Column(Integer, ForeignKey("contract_files.id", ondelete="SET NULL"), unique=True)
    storage_key = Column(Text, unique=True)
    name = Column(Text, nullable=False)
    category = Column(Text, nullable=False, server_default="Бусад", default="Бусад")
    content_type = Column(Text, nullable=False)
    size = Column(Integer, nullable=False)
    checksum = Column(String(64), nullable=False)
    scan_status = Column(String(16), nullable=False, server_default="pending", default="pending")
    review_status = Column(String(16), nullable=False, server_default="approved", default="approved")
    review_reason = Column(Text)
    created_by_account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="SET NULL"))
    author_account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="SET NULL"))
    reviewed_by_account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="SET NULL"))
    reviewed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    deleted_at = Column(DateTime(timezone=True))
    deleted_by_account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="SET NULL"))


class ContractArchiveAccess(Base):
    __tablename__ = "contract_archive_access"
    __table_args__ = (
        CheckConstraint("permission IN ('view','edit')", name="ck_contract_archive_access_permission"),
        ForeignKeyConstraint(
            ["organization_id", "folder_id"],
            ["contract_archive_folders.organization_id", "contract_archive_folders.id"],
            ondelete="CASCADE",
            name="fk_contract_archive_access_folder_org",
        ),
        UniqueConstraint("organization_id", "folder_id", "account_id", name="uq_contract_archive_access_folder_account"),
        Index("ix_contract_archive_access_account", "organization_id", "account_id", "folder_id"),
    )

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    folder_id = Column(Integer, nullable=False)
    account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False)
    permission = Column(String(8), nullable=False, server_default="view", default="view")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
