"""allow browser Telegram OIDC transactions

Revision ID: j2k3l4m5n6o7
Revises: a6b7c8d9e0f2
"""

from typing import Union

from alembic import op


revision: str = "j2k3l4m5n6o7"
down_revision: Union[str, None] = "a6b7c8d9e0f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_telegram_oauth_platform", "telegram_oauth_states", type_="check")
    op.create_check_constraint(
        "ck_telegram_oauth_platform",
        "telegram_oauth_states",
        "platform IN ('ios','android','web')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_telegram_oauth_platform", "telegram_oauth_states", type_="check")
    op.create_check_constraint(
        "ck_telegram_oauth_platform",
        "telegram_oauth_states",
        "platform IN ('ios','android')",
    )
