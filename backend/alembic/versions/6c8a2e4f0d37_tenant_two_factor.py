"""tenant account two-factor login

TOTP enrolment for ``user_accounts`` (encrypted secret, enabled-at timestamp,
last accepted time step, hashed recovery codes) and the session flag that
records a passed second factor. The requirement itself is a tenant setting
(``organizations.settings["security"]``), off by default.

Revision ID: 6c8a2e4f0d37
Revises: 5b7f1d3e9c26
Create Date: 2026-10-02 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "6c8a2e4f0d37"
down_revision: Union[str, Sequence[str], None] = "5b7f1d3e9c26"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("user_accounts", sa.Column("totp_secret_enc", sa.Text()))
    op.add_column("user_accounts", sa.Column("totp_enabled_at", sa.DateTime(timezone=True)))
    op.add_column("user_accounts", sa.Column("totp_last_step", sa.BigInteger()))
    op.add_column("user_accounts", sa.Column(
        "totp_recovery_codes", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.add_column("refresh_sessions", sa.Column("mfa_verified_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("refresh_sessions", "mfa_verified_at")
    op.drop_column("user_accounts", "totp_recovery_codes")
    op.drop_column("user_accounts", "totp_last_step")
    op.drop_column("user_accounts", "totp_enabled_at")
    op.drop_column("user_accounts", "totp_secret_enc")
