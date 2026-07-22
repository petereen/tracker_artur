"""set Ulaanbaatar as the employee timezone default

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-07-22 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, Sequence[str], None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Keep each existing employee's configured timezone intact.  This only
    # affects employees subsequently created outside the application ORM.
    op.alter_column(
        "employees",
        "timezone",
        existing_type=sa.Text(),
        nullable=False,
        server_default="Asia/Ulaanbaatar",
    )


def downgrade() -> None:
    op.alter_column(
        "employees",
        "timezone",
        existing_type=sa.Text(),
        nullable=False,
        server_default="Europe/Moscow",
    )
