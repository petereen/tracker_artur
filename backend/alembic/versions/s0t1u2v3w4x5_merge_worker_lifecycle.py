"""Merge payroll lifecycle and organization seed-account migration heads."""

from typing import Sequence, Union


revision: str = "s0t1u2v3w4x5"
down_revision: Union[str, Sequence[str], None] = (
    "c7d8e9f0a1b2",
    "r9s0t1u2v3w4",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
