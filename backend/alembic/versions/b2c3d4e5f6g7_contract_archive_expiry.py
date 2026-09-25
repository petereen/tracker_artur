"""Add expiry reminders to archived contract entries."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "b2c3d4e5f6g7"
down_revision: Union[str, None] = "a1c2e3f4g5h6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("contract_archive_entries", sa.Column("expiry_on", sa.Date(), nullable=True))
    op.add_column("contract_archive_entries", sa.Column("expiry_reminder_days", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")))


def downgrade() -> None:
    op.drop_column("contract_archive_entries", "expiry_reminder_days")
    op.drop_column("contract_archive_entries", "expiry_on")
