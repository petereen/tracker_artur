"""Add versioned full-text indexing for unified company knowledge."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import TSVECTOR

revision: str = "m4n5o6p7q8r9"
down_revision: Union[str, Sequence[str], None] = "l2m3n4o5p6q7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    op.add_column("knowledge_documents", sa.Column("index_version", sa.Integer(), nullable=False, server_default="1"))
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        op.add_column(
            "knowledge_chunks",
            sa.Column(
                "search_tsv",
                TSVECTOR(),
                sa.Computed("to_tsvector('simple', coalesce(content, ''))", persisted=True),
                nullable=False,
            ),
        )
        op.create_index("ix_knowledge_chunks_search_tsv", "knowledge_chunks", ["search_tsv"], postgresql_using="gin")
        op.create_index("ix_knowledge_documents_title_trgm", "knowledge_documents", ["title"], postgresql_using="gin", postgresql_ops={"title": "gin_trgm_ops"})
        op.create_index("ix_knowledge_documents_company_file_source", "knowledge_documents", ["organization_id", "source_id"], postgresql_where=sa.text("source_type='company_file'"))
        op.create_index("ix_knowledge_documents_company_knowledge_source", "knowledge_documents", ["organization_id", "source_id"], postgresql_where=sa.text("source_type='company_knowledge'"))
    else:
        # SQLite is used for lightweight contract tests; keep the model shape
        # representable without PostgreSQL generated-vector types.
        op.add_column("knowledge_chunks", sa.Column("search_tsv", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_knowledge_documents_source_type",
        "knowledge_documents",
        "source_type IN ('company_file','company_knowledge')",
    )
    op.create_check_constraint(
        "ck_knowledge_documents_index_status",
        "knowledge_documents",
        "index_status IN ('pending','indexing','ready','partial','failed')",
    )
    # Placeholders are intentionally created in SQL without scheduling jobs;
    # upgraded workers discover version drift on their next scan.
    if bind.dialect.name == "postgresql":
        op.execute(
            """
            INSERT INTO knowledge_documents
                (organization_id, source_type, source_id, title, content_type,
                 checksum, index_status, content_available, index_version)
            SELECT i.organization_id, 'company_file', i.id,
                   COALESCE(i.title, i.name), i.content_type, i.checksum,
                   'pending', false, 1
            FROM company_library_items i
            LEFT JOIN knowledge_documents d
              ON d.organization_id = i.organization_id
             AND d.source_type = 'company_file'
             AND d.source_id = i.id
            WHERE i.kind = 'file' AND i.deleted_at IS NULL AND d.id IS NULL
            """
        )
        op.execute(
            """
            INSERT INTO knowledge_documents
                (organization_id, source_type, source_id, title, content_type,
                 index_status, content_available, index_version)
            SELECT k.organization_id, 'company_knowledge', k.id, k.title,
                   'text/markdown', 'pending', false, 1
            FROM company_knowledge k
            LEFT JOIN knowledge_documents d
              ON d.organization_id = k.organization_id
             AND d.source_type = 'company_knowledge'
             AND d.source_id = k.id
            WHERE k.is_active AND d.id IS NULL
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    op.drop_constraint("ck_knowledge_documents_source_type", "knowledge_documents", type_="check")
    op.drop_constraint("ck_knowledge_documents_index_status", "knowledge_documents", type_="check")
    if bind.dialect.name == "postgresql":
        op.drop_index("ix_knowledge_documents_title_trgm", table_name="knowledge_documents")
        op.drop_index("ix_knowledge_chunks_search_tsv", table_name="knowledge_chunks")
        op.drop_index("ix_knowledge_documents_company_file_source", table_name="knowledge_documents")
        op.drop_index("ix_knowledge_documents_company_knowledge_source", table_name="knowledge_documents")
    op.drop_column("knowledge_chunks", "search_tsv")
    op.drop_column("knowledge_documents", "index_version")
