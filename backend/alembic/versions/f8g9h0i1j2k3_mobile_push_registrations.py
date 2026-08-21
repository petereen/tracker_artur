"""add encrypted mobile push registrations

Revision ID: f8g9h0i1j2k3
Revises: e7f8g9h0i1j2
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f8g9h0i1j2k3"
down_revision: Union[str, Sequence[str], None] = "e7f8g9h0i1j2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mobile_push_registrations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("encrypted_token", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("last_registered_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("platform IN ('ios','android')", name="ck_mobile_push_platform"),
        sa.CheckConstraint("provider IN ('apns','fcm')", name="ck_mobile_push_provider"),
        sa.CheckConstraint("(platform = 'ios' AND provider = 'apns') OR (platform = 'android' AND provider = 'fcm')", name="ck_mobile_push_platform_provider"),
        sa.ForeignKeyConstraint(["account_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_mobile_push_token_hash"),
    )
    op.create_index("ix_mobile_push_account_active", "mobile_push_registrations", ["account_id", "is_active"])


def downgrade() -> None:
    op.drop_index("ix_mobile_push_account_active", table_name="mobile_push_registrations")
    op.drop_table("mobile_push_registrations")
