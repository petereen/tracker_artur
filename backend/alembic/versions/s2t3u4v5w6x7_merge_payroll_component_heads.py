"""Merge payroll component migration heads.

Revision ID: s2t3u4v5w6x7
Revises: r1s2t3u4v5w6, q7r8s9t0u1v2
"""

from typing import Sequence, Union


revision: str = "s2t3u4v5w6x7"
down_revision: Union[str, Sequence[str], None] = (
    "r1s2t3u4v5w6",
    "q7r8s9t0u1v2",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
