"""news & announcements

``announcements``: posts (Markdown body, cover and gallery images) written by
admins, managers and team leads for the «Өнөөдөр» news widget. Row-level
security like every other tenant table.

Revision ID: 4a6e0c2d8b15
Revises: a9b8c7d6e5f4
Create Date: 2026-10-01 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "4a6e0c2d8b15"
down_revision: Union[str, Sequence[str], None] = "a9b8c7d6e5f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "announcements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text()),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("cover_url", sa.Text()),
        sa.Column("image_urls", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("category", sa.Text()),
        sa.Column("is_pinned", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("author_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("author_name", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('draft','published','archived')", name="ck_announcements_status"),
    )
    op.create_index("ix_announcements_org_feed", "announcements", ["organization_id", "status", "is_pinned", "published_at"])
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT to_regproc('tenant_row_visible') IS NOT NULL")).scalar():
        op.execute('ALTER TABLE "announcements" ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE "announcements" FORCE ROW LEVEL SECURITY')
        op.execute(
            'CREATE POLICY tenant_isolation ON "announcements" '
            "USING (tenant_row_visible(organization_id)) WITH CHECK (tenant_row_visible(organization_id))"
        )


def downgrade() -> None:
    op.execute('DROP POLICY IF EXISTS tenant_isolation ON "announcements"')
    op.drop_index("ix_announcements_org_feed", table_name="announcements")
    op.drop_table("announcements")
