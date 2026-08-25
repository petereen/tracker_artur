"""Add authoritative company-file search metadata and index state."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "u0v1w2x3y4z5"
down_revision: Union[str, Sequence[str], None] = "t9u0v1w2x3y4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("company_library_items", sa.Column("title", sa.Text(), nullable=True))
    op.add_column("company_library_items", sa.Column("extension", sa.String(length=32), nullable=True))
    op.add_column(
        "company_library_items",
        sa.Column("searchable_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.add_column("company_library_items", sa.Column("search_key", sa.Text(), nullable=True))
    op.add_column("knowledge_documents", sa.Column("content_available", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column(
        "chat_messages",
        sa.Column("company_file_attachments", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )

    # Backfill without depending on the optional content index or third-party
    # extensions.  Search code applies Unicode NFKC/casefold at query time.
    op.execute(sa.text("""
        UPDATE company_library_items
        SET title = COALESCE(title, regexp_replace(name, '\\.[^./]+$', '')),
            extension = COALESCE(extension, lower(substring(name from '\\.[^./]+$'))),
            search_key = lower(regexp_replace(name, '[^[:alnum:]]', '', 'g'))
        WHERE title IS NULL OR extension IS NULL OR search_key IS NULL
    """))
    op.execute(sa.text("""
        UPDATE company_library_items
        SET searchable_metadata = '{}'::jsonb
        WHERE searchable_metadata IS NULL
    """))
    op.execute(sa.text("""
        UPDATE knowledge_documents AS documents
        SET content_available = EXISTS (
            SELECT 1 FROM knowledge_chunks AS chunks WHERE chunks.document_id = documents.id
        )
        WHERE documents.index_status = 'ready'
    """))
    op.alter_column("company_library_items", "title", existing_type=sa.Text(), nullable=False)
    op.alter_column("company_library_items", "search_key", existing_type=sa.Text(), nullable=False)

    op.create_index("ix_company_library_items_search_key", "company_library_items", ["organization_id", "search_key"])
    op.create_index("ix_company_library_items_title", "company_library_items", ["organization_id", "title"])
    op.create_index("ix_company_library_items_extension", "company_library_items", ["organization_id", "extension"])
    op.create_index("ix_company_library_items_content_type", "company_library_items", ["organization_id", "content_type"])
    op.create_index(
        "ix_company_library_items_searchable_metadata",
        "company_library_items",
        ["searchable_metadata"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_company_library_items_searchable_metadata", table_name="company_library_items")
    op.drop_index("ix_company_library_items_content_type", table_name="company_library_items")
    op.drop_index("ix_company_library_items_extension", table_name="company_library_items")
    op.drop_index("ix_company_library_items_title", table_name="company_library_items")
    op.drop_index("ix_company_library_items_search_key", table_name="company_library_items")
    op.drop_column("knowledge_documents", "content_available")
    op.drop_column("chat_messages", "company_file_attachments")
    op.drop_column("company_library_items", "search_key")
    op.drop_column("company_library_items", "searchable_metadata")
    op.drop_column("company_library_items", "extension")
    op.drop_column("company_library_items", "title")
