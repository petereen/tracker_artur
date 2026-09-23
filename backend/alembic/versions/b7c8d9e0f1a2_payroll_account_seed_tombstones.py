"""Remember deleted organization seed accounts."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c7d8e9f0a1b2"
down_revision: Union[str, Sequence[str], None] = ("s1t2u3v4w5x6", "s2t3u4v5w6x7")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "erp_deleted_seed_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "code", name="uq_erp_deleted_seed_account_org_code"),
    )


def downgrade() -> None:
    op.drop_table("erp_deleted_seed_accounts")
