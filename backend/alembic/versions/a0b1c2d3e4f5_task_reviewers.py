"""add task reviewers

Revision ID: a0b1c2d3e4f5
Revises: z4a5b6c7d8e9
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a0b1c2d3e4f5"
down_revision: Union[str, Sequence[str], None] = "z4a5b6c7d8e9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("reviewer_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_tasks_reviewer", "tasks", "employees", ["reviewer_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_tasks_reviewer_workflow", "tasks", ["reviewer_id", "workflow_status"])


def downgrade() -> None:
    op.drop_index("ix_tasks_reviewer_workflow", table_name="tasks")
    op.drop_constraint("fk_tasks_reviewer", "tasks", type_="foreignkey")
    op.drop_column("tasks", "reviewer_id")
