"""add read and edit levels to resource grants"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f2a3b4c5d6e7"
down_revision: Union[str, Sequence[str], None] = "e7f8g9h0i1j2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "resource_grants",
        sa.Column("access_level", sa.String(length=8), nullable=False, server_default="read"),
    )
    op.create_check_constraint(
        "ck_resource_grant_access_level",
        "resource_grants",
        "access_level IN ('read','edit')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_resource_grant_access_level", "resource_grants", type_="check")
    op.drop_column("resource_grants", "access_level")
