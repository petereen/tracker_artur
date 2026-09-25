"""merge payroll allowance basis and contract expiry reminders

Revision ID: m6n7o8p9q0r1
Revises: x3y4z5a6b7c8, a1c2e3f4g5h6
Create Date: 2026-09-25 11:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "m6n7o8p9q0r1"
down_revision: Union[str, Sequence[str], None] = ("x3y4z5a6b7c8", "a1c2e3f4g5h6")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
