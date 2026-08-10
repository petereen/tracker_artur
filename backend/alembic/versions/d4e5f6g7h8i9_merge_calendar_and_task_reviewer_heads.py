"""merge calendar and task reviewer migration heads

Revision ID: d4e5f6g7h8i9
Revises: b1c2d3e4f5g6, c1d2e3f4g5h6
"""

from typing import Sequence, Union


revision: str = "d4e5f6g7h8i9"
down_revision: Union[str, Sequence[str], None] = ("b1c2d3e4f5g6", "c1d2e3f4g5h6")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
