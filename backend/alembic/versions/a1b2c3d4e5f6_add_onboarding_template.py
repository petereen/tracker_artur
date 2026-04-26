"""add onboarding_template to manager_settings

Revision ID: a1b2c3d4e5f6
Revises: 6d63fa35ef86
Create Date: 2026-04-26 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '6d63fa35ef86'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('manager_settings', sa.Column('onboarding_template', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('manager_settings', 'onboarding_template')
