"""Per-tenant Telegram bots and Cloudflare custom domains

* ``tenant_telegram_bots``: one BotFather bot per tenant (encrypted token,
  handshake state, runner heartbeat). Row-level security like every other
  tenant table.
* ``monthly_report_digests`` is reserved per tenant (``organization_id``),
  so each tenant's managers get their own digest.
* ``tenant_domains`` gains provider state for Cloudflare for SaaS custom
  hostnames (provider id, hostname/SSL status, DNS records to create, last
  check). Domains verified by an operator before this revision stay routed.

Revision ID: d4e8f1a2b3c9
Revises: b3c4d5e6f7a8
Create Date: 2026-09-30 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "d4e8f1a2b3c9"
down_revision: Union[str, Sequence[str], None] = "b3c4d5e6f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tenant_telegram_bots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("bot_id", sa.BigInteger(), nullable=False),
        sa.Column("bot_username", sa.Text()),
        sa.Column("bot_name", sa.Text()),
        sa.Column("token_enc", sa.Text(), nullable=False),
        sa.Column("token_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("handshake_code_enc", sa.Text()),
        sa.Column("handshake_expires_at", sa.DateTime(timezone=True)),
        sa.Column("handshake_completed_at", sa.DateTime(timezone=True)),
        sa.Column("handshake_telegram_id", sa.Text()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column("connected_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('pending','active','error','disabled')", name="ck_tenant_telegram_bots_status"),
        sa.UniqueConstraint("organization_id", name="uq_tenant_telegram_bots_organization_id"),
        sa.UniqueConstraint("bot_id", name="uq_tenant_telegram_bots_bot_id"),
        sa.UniqueConstraint("token_sha256", name="uq_tenant_telegram_bots_token_sha256"),
    )
    bind = op.get_bind()
    has_rls_helper = bind.execute(sa.text("SELECT to_regproc('tenant_row_visible') IS NOT NULL")).scalar()
    if has_rls_helper:
        op.execute('ALTER TABLE "tenant_telegram_bots" ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE "tenant_telegram_bots" FORCE ROW LEVEL SECURITY')
        op.execute(
            'CREATE POLICY tenant_isolation ON "tenant_telegram_bots" '
            "USING (tenant_row_visible(organization_id)) WITH CHECK (tenant_row_visible(organization_id))"
        )

    op.add_column("tenant_domains", sa.Column("provider", sa.Text(), nullable=False, server_default="manual"))
    op.add_column("tenant_domains", sa.Column("provider_hostname_id", sa.Text()))
    op.add_column("tenant_domains", sa.Column("status", sa.Text(), nullable=False, server_default="pending"))
    op.add_column("tenant_domains", sa.Column("ssl_status", sa.Text()))
    op.add_column("tenant_domains", sa.Column("dns_records", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.add_column("tenant_domains", sa.Column("last_error", sa.Text()))
    op.add_column("tenant_domains", sa.Column("last_checked_at", sa.DateTime(timezone=True)))
    op.add_column("tenant_domains", sa.Column("created_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")))
    op.create_unique_constraint("uq_tenant_domains_provider_hostname_id", "tenant_domains", ["provider_hostname_id"])
    op.execute("UPDATE tenant_domains SET status = 'active' WHERE verified_at IS NOT NULL")

    op.add_column("monthly_report_digests", sa.Column("organization_id", sa.Integer()))
    op.execute(
        "UPDATE monthly_report_digests SET organization_id = coalesce("
        "(SELECT id FROM organizations WHERE is_primary LIMIT 1), (SELECT min(id) FROM organizations))"
    )
    op.alter_column("monthly_report_digests", "organization_id", nullable=False)
    op.create_foreign_key("fk_monthly_report_digests_organization", "monthly_report_digests", "organizations", ["organization_id"], ["id"], ondelete="CASCADE")
    op.drop_constraint("uq_monthly_report_digest_period", "monthly_report_digests", type_="unique")
    op.create_unique_constraint("uq_monthly_report_digest_org_period", "monthly_report_digests", ["organization_id", "period_date"])
    if has_rls_helper:
        op.execute('ALTER TABLE "monthly_report_digests" ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE "monthly_report_digests" FORCE ROW LEVEL SECURITY')
        op.execute(
            'CREATE POLICY tenant_isolation ON "monthly_report_digests" '
            "USING (tenant_row_visible(organization_id)) WITH CHECK (tenant_row_visible(organization_id))"
        )


def downgrade() -> None:
    op.execute('DROP POLICY IF EXISTS tenant_isolation ON "monthly_report_digests"')
    op.execute('ALTER TABLE "monthly_report_digests" NO FORCE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "monthly_report_digests" DISABLE ROW LEVEL SECURITY')
    op.drop_constraint("uq_monthly_report_digest_org_period", "monthly_report_digests", type_="unique")
    # Keep one row per period (the primary tenant's) before restoring the old key.
    op.execute(
        "DELETE FROM monthly_report_digests d USING monthly_report_digests keep "
        "WHERE d.period_date = keep.period_date AND d.id > keep.id"
    )
    op.create_unique_constraint("uq_monthly_report_digest_period", "monthly_report_digests", ["period_date"])
    op.drop_constraint("fk_monthly_report_digests_organization", "monthly_report_digests", type_="foreignkey")
    op.drop_column("monthly_report_digests", "organization_id")
    op.drop_constraint("uq_tenant_domains_provider_hostname_id", "tenant_domains", type_="unique")
    for column in ("created_by_account_id", "last_checked_at", "last_error", "dns_records", "ssl_status", "status", "provider_hostname_id", "provider"):
        op.drop_column("tenant_domains", column)
    op.execute('DROP POLICY IF EXISTS tenant_isolation ON "tenant_telegram_bots"')
    op.drop_table("tenant_telegram_bots")
