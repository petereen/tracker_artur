"""add admin switch for assistant TTS answers

Revision ID: j8k9l0m1n2o3
Revises: i7j8k9l0m1n2
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "j8k9l0m1n2o3"
down_revision: Union[str, Sequence[str], None] = "i7j8k9l0m1n2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "manager_settings",
        sa.Column("tts_answers_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("manager_settings", "tts_answers_enabled")
