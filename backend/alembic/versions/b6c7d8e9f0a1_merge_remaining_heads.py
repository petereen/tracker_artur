"""merge the remaining global-search and reviewer migration heads

Revision ID: b6c7d8e9f0a1
Revises: d4e5f6g7h8i9, a5b6c7d8e9f0
"""

from typing import Sequence, Union


revision: str = "b6c7d8e9f0a1"
down_revision: Union[str, Sequence[str], None] = (
    "d4e5f6g7h8i9",
    "a5b6c7d8e9f0",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
