"""Add the daily work-report reminder automation switch."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "k1l2m3n4o5p6"
down_revision: Union[str, Sequence[str], None] = "j0k1l2m3n4o5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "manager_settings",
        sa.Column("daily_report_reminders_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("manager_settings", "daily_report_reminders_enabled")
