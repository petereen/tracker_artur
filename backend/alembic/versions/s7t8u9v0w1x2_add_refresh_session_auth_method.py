"""record refresh-session authentication method

Revision ID: s7t8u9v0w1x2
Revises: r6s7t8u9v0w1
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "s7t8u9v0w1x2"
down_revision: Union[str, Sequence[str], None] = "r6s7t8u9v0w1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "refresh_sessions",
        sa.Column("auth_method", sa.Text(), nullable=False, server_default="password"),
    )


def downgrade() -> None:
    op.drop_column("refresh_sessions", "auth_method")
