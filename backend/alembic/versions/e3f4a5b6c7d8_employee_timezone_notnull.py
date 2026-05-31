"""backfill NULL employee timezone and enforce NOT NULL + server default

Fixes Sentry issue 28: ResponseValidationError on GET /employees — legacy rows
(e.g. the seeded manager) had timezone = NULL because the column had only a
client-side SQLAlchemy default and no server_default / NOT NULL constraint.

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-05-31 10:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e3f4a5b6c7d8'
down_revision: Union[str, Sequence[str], None] = 'd2e3f4a5b6c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) backfill existing NULLs so they serialize correctly
    op.execute("UPDATE employees SET timezone = 'Europe/Moscow' WHERE timezone IS NULL")
    # 2) attach a server-side default so direct/raw inserts can't produce NULL
    op.alter_column(
        'employees',
        'timezone',
        existing_type=sa.Text(),
        nullable=False,
        server_default='Europe/Moscow',
    )


def downgrade() -> None:
    op.alter_column(
        'employees',
        'timezone',
        existing_type=sa.Text(),
        nullable=True,
        server_default=None,
    )
