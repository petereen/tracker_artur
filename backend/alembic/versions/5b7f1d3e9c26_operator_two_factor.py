"""operator console two-factor login

TOTP enrolment for ``platform_operators``: encrypted secret, enabled-at
timestamp, last accepted time step (replay guard) and hashed recovery codes.
Existing operators enrol on their next login.

Revision ID: 5b7f1d3e9c26
Revises: 4a6e0c2d8b15
Create Date: 2026-10-01 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "5b7f1d3e9c26"
down_revision: Union[str, Sequence[str], None] = "4a6e0c2d8b15"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("platform_operators", sa.Column("totp_secret_enc", sa.Text()))
    op.add_column("platform_operators", sa.Column("totp_enabled_at", sa.DateTime(timezone=True)))
    op.add_column("platform_operators", sa.Column("totp_last_step", sa.BigInteger()))
    op.add_column("platform_operators", sa.Column(
        "totp_recovery_codes", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")))


def downgrade() -> None:
    op.drop_column("platform_operators", "totp_recovery_codes")
    op.drop_column("platform_operators", "totp_last_step")
    op.drop_column("platform_operators", "totp_enabled_at")
    op.drop_column("platform_operators", "totp_secret_enc")
