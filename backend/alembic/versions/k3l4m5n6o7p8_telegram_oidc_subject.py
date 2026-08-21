"""persist Telegram OIDC subjects on user accounts

Revision ID: k3l4m5n6o7p8
Revises: j2k3l4m5n6o7
"""

from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = "k3l4m5n6o7p8"
down_revision: Union[str, None] = "j2k3l4m5n6o7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user_accounts", sa.Column("telegram_oidc_subject", sa.Text(), nullable=True))
    op.create_unique_constraint("uq_user_accounts_telegram_oidc_subject", "user_accounts", ["telegram_oidc_subject"])


def downgrade() -> None:
    op.drop_constraint("uq_user_accounts_telegram_oidc_subject", "user_accounts", type_="unique")
    op.drop_column("user_accounts", "telegram_oidc_subject")
