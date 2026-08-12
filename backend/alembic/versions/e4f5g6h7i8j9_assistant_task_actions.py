"""allow assistant pending actions to create tasks

Revision ID: e4f5g6h7i8j9
Revises: c3d4e5f6g7h8
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e4f5g6h7i8j9"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6g7h8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "assistant_pending_actions",
        sa.Column("action_type", sa.String(length=32), nullable=False, server_default="update_task"),
    )
    op.alter_column("assistant_pending_actions", "task_id", existing_type=sa.Integer(), nullable=True)
    op.alter_column("assistant_pending_actions", "expected_version", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    op.alter_column("assistant_pending_actions", "expected_version", existing_type=sa.Integer(), nullable=False)
    op.alter_column("assistant_pending_actions", "task_id", existing_type=sa.Integer(), nullable=False)
    op.drop_column("assistant_pending_actions", "action_type")
