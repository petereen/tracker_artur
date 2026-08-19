"""Merge the remaining notification, MCP, and account-preference heads."""

from typing import Sequence, Union


revision: str = "e7f8g9h0i1j2"
down_revision: Union[str, Sequence[str], None] = (
    "a6b7c8d9e0f1",
    "b7c8d9e0f1a2",
    "d6e7f8g9h0i1",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
