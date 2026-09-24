"""merge heads

Revision ID: 92b736716ad1
Revises: f2a3b4c5d6e7, w2x3y4z5a6b7
Create Date: 2026-09-24 17:02:05.844297

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '92b736716ad1'
down_revision: Union[str, Sequence[str], None] = ('f2a3b4c5d6e7', 'w2x3y4z5a6b7')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
