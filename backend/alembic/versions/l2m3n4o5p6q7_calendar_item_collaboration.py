"""Add locations and collaborators to calendar entries."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "l2m3n4o5p6q7"
down_revision: Union[str, Sequence[str], None] = "k1l2m3n4o5p6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("calendar_entries", sa.Column("location", sa.Text(), nullable=True))
    op.create_table(
        "calendar_entry_collaborators",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("calendar_entry_id", sa.Integer(), sa.ForeignKey("calendar_entries.id", ondelete="CASCADE"), nullable=False),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("calendar_entry_id", "employee_id", name="uq_calendar_entry_collaborators"),
    )
    op.create_index(
        "ix_calendar_entry_collaborators_org_entry",
        "calendar_entry_collaborators",
        ["organization_id", "calendar_entry_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_calendar_entry_collaborators_org_entry", table_name="calendar_entry_collaborators")
    op.drop_table("calendar_entry_collaborators")
    op.drop_column("calendar_entries", "location")
