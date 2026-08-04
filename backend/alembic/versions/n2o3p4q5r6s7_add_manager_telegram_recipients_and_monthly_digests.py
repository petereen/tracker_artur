"""add manager Telegram recipients and monthly digest delivery guard

Revision ID: n2o3p4q5r6s7
Revises: i7j8k9l0m1n2
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "n2o3p4q5r6s7"
down_revision: Union[str, Sequence[str], None] = "i7j8k9l0m1n2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "manager_settings",
        sa.Column("telegram_admin_ids", postgresql.JSONB(astext_type=sa.Text()), server_default="'[]'::jsonb", nullable=False),
    )
    op.execute("UPDATE manager_settings SET telegram_admin_ids = jsonb_build_array(telegram_id) WHERE telegram_id IS NOT NULL")
    op.create_table(
        "monthly_report_digests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("period_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("period_date", name="uq_monthly_report_digest_period"),
    )


def downgrade() -> None:
    op.drop_table("monthly_report_digests")
    op.drop_column("manager_settings", "telegram_admin_ids")
