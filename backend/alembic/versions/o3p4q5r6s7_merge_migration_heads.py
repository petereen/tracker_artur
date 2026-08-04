"""merge the TTS/work-report and manager-recipient migration branches

Revision ID: o3p4q5r6s7
Revises: m1n2o3p4q5r6, n2o3p4q5r6s7
"""

from typing import Sequence, Union


revision: str = "o3p4q5r6s7"
down_revision: Union[str, Sequence[str], None] = (
    "m1n2o3p4q5r6",
    "n2o3p4q5r6s7",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
