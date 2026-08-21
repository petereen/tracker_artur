"""add Telegram native OIDC authorization states

Revision ID: i1j2k3l4m5n6
Revises: f8g9h0i1j2k3
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "i1j2k3l4m5n6"
down_revision: Union[str, Sequence[str], None] = "f8g9h0i1j2k3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "telegram_oauth_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("nonce_hash", sa.String(length=64), nullable=False),
        sa.Column("encrypted_nonce", sa.Text(), nullable=False),
        sa.Column("encrypted_code_verifier", sa.Text(), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("platform IN ('ios','android')", name="ck_telegram_oauth_platform"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("state_hash", name="uq_telegram_oauth_state_hash"),
        sa.UniqueConstraint("nonce_hash", name="uq_telegram_oauth_nonce_hash"),
    )
    op.create_index("ix_telegram_oauth_states_expiry", "telegram_oauth_states", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_telegram_oauth_states_expiry", table_name="telegram_oauth_states")
    op.drop_table("telegram_oauth_states")
