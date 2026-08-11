"""add enterprise assistant tools and vector retrieval

Revision ID: c2d3e4f5g6h7
Revises: b6c7d8e9f0a1
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "c2d3e4f5g6h7"
down_revision: Union[str, Sequence[str], None] = "b6c7d8e9f0a1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.add_column("company_knowledge", sa.Column("organization_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_company_knowledge_organization", "company_knowledge", "organizations", ["organization_id"], ["id"], ondelete="CASCADE")
    op.create_index("ix_company_knowledge_organization_id", "company_knowledge", ["organization_id"])
    op.execute("UPDATE company_knowledge SET organization_id = 1 WHERE organization_id IS NULL AND EXISTS (SELECT 1 FROM organizations WHERE id = 1) AND (SELECT count(*) FROM organizations) = 1")
    op.create_table("resource_policies", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False), sa.Column("resource_type", sa.String(32), nullable=False), sa.Column("resource_id", sa.Integer(), nullable=False), sa.Column("classification", sa.String(32), nullable=False, server_default="internal"), sa.Column("inherit_from_parent", sa.Boolean(), nullable=False, server_default=sa.text("true")), sa.Column("created_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.UniqueConstraint("organization_id", "resource_type", "resource_id", name="uq_resource_policy_resource"), sa.CheckConstraint("classification IN ('public_link_safe','internal','confidential','restricted')", name="ck_resource_policy_classification"))
    op.create_index("ix_resource_policies_organization_id", "resource_policies", ["organization_id"])
    op.create_table("resource_grants", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("policy_id", sa.Integer(), sa.ForeignKey("resource_policies.id", ondelete="CASCADE"), nullable=False), sa.Column("principal_type", sa.String(16), nullable=False), sa.Column("principal_key", sa.String(128), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.CheckConstraint("principal_type IN ('role','team','project','account')", name="ck_resource_grant_principal"), sa.UniqueConstraint("policy_id", "principal_type", "principal_key", name="uq_resource_grant_principal"))
    op.create_index("ix_resource_grants_policy_id", "resource_grants", ["policy_id"])
    op.create_table("knowledge_documents", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False), sa.Column("source_type", sa.String(32), nullable=False), sa.Column("source_id", sa.Integer(), nullable=False), sa.Column("title", sa.Text(), nullable=False), sa.Column("content_type", sa.Text()), sa.Column("checksum", sa.String(64)), sa.Column("index_status", sa.String(16), nullable=False, server_default="pending"), sa.Column("indexed_at", sa.DateTime(timezone=True)), sa.Column("last_error", sa.Text()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.UniqueConstraint("organization_id", "source_type", "source_id", name="uq_knowledge_document_source"))
    op.create_index("ix_knowledge_documents_index_status", "knowledge_documents", ["organization_id", "index_status"])
    op.create_table("knowledge_chunks", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("document_id", sa.Integer(), sa.ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False), sa.Column("position", sa.Integer(), nullable=False), sa.Column("locator", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")), sa.Column("content", sa.Text(), nullable=False), sa.Column("search_vector", sa.Text()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.execute("ALTER TABLE knowledge_chunks ADD COLUMN embedding vector(1536)")
    op.create_index("ix_knowledge_chunks_document_position", "knowledge_chunks", ["document_id", "position"])
    op.execute("CREATE INDEX ix_knowledge_chunks_embedding_hnsw ON knowledge_chunks USING hnsw (embedding vector_cosine_ops)")
    op.create_table("assistant_tool_audits", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False), sa.Column("account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False), sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("assistant_conversations.id", ondelete="SET NULL")), sa.Column("channel", sa.String(16), nullable=False), sa.Column("tool_name", sa.String(64), nullable=False), sa.Column("status", sa.String(16), nullable=False), sa.Column("resource_refs", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")), sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")), sa.Column("encrypted_payload", sa.Text()), sa.Column("content_expires_at", sa.DateTime(timezone=True), nullable=False), sa.Column("metadata_expires_at", sa.DateTime(timezone=True), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index("ix_assistant_tool_audits_expiry", "assistant_tool_audits", ["content_expires_at"])
    op.create_table("assistant_pending_actions", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("token_hash", sa.String(64), nullable=False), sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False), sa.Column("account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False), sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False), sa.Column("expected_version", sa.Integer(), nullable=False), sa.Column("channel", sa.String(16), nullable=False), sa.Column("payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")), sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False), sa.Column("consumed_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.UniqueConstraint("token_hash"))
    op.create_index("ix_assistant_pending_actions_expiry", "assistant_pending_actions", ["expires_at"])
    op.add_column("assistant_conversations", sa.Column("channel", sa.String(16), nullable=False, server_default="web"))
    op.add_column("assistant_conversations", sa.Column("external_thread_key", sa.String(128), nullable=True))
    op.execute("INSERT INTO resource_policies (organization_id, resource_type, resource_id, classification) SELECT organization_id, 'company_file', id, 'internal' FROM company_library_items")
    op.execute("INSERT INTO resource_policies (organization_id, resource_type, resource_id, classification) SELECT organization_id, 'company_knowledge', id, 'internal' FROM company_knowledge WHERE organization_id IS NOT NULL")


def downgrade() -> None:
    op.drop_column("assistant_conversations", "external_thread_key")
    op.drop_column("assistant_conversations", "channel")
    op.drop_table("assistant_pending_actions")
    op.drop_table("assistant_tool_audits")
    op.drop_table("knowledge_chunks")
    op.drop_table("knowledge_documents")
    op.drop_table("resource_grants")
    op.drop_table("resource_policies")
    op.drop_index("ix_company_knowledge_organization_id", table_name="company_knowledge")
    op.drop_constraint("fk_company_knowledge_organization", "company_knowledge", type_="foreignkey")
    op.drop_column("company_knowledge", "organization_id")
