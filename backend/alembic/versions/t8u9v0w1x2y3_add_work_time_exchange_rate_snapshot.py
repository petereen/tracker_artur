"""add exchange-rate snapshot linkage to work-time entries

Revision ID: t8u9v0w1x2y3
Revises: s7t8u9v0w1x2
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "t8u9v0w1x2y3"
down_revision: Union[str, Sequence[str], None] = "s7t8u9v0w1x2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "work_time_entries",
        sa.Column("exchange_rate_snapshot_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_work_time_entries_exchange_rate_snapshot",
        "work_time_entries",
        "exchange_rate_snapshots",
        ["exchange_rate_snapshot_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_work_time_entries_exchange_rate_snapshot",
        "work_time_entries",
        type_="foreignkey",
    )
    op.drop_column("work_time_entries", "exchange_rate_snapshot_id")
