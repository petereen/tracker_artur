"""add company plan items

Revision ID: m1n2o3p4q5r6
Revises: l0m1n2o3p4q5
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "m1n2o3p4q5r6"
down_revision: Union[str, Sequence[str], None] = "l0m1n2o3p4q5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "company_plan_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("plan_month", sa.Date(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("horizon", sa.Text(), nullable=False, server_default="short_term"),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.Text(), nullable=False, server_default="approved"),
        sa.Column("source_employee_id", sa.Integer(), nullable=True),
        sa.Column("source_report_id", sa.Integer(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("horizon IN ('long_term','mid_term','short_term')", name="ck_company_plan_items_horizon"),
        sa.CheckConstraint("status IN ('approved')", name="ck_company_plan_items_status"),
        sa.ForeignKeyConstraint(["source_employee_id"], ["employees.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_report_id"], ["work_reports.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_company_plan_items_plan_month", "company_plan_items", ["plan_month"])
    op.create_index("ix_company_plan_items_month_horizon_position", "company_plan_items", ["plan_month", "horizon", "position"])


def downgrade() -> None:
    op.drop_index("ix_company_plan_items_month_horizon_position", table_name="company_plan_items")
    op.drop_index("ix_company_plan_items_plan_month", table_name="company_plan_items")
    op.drop_table("company_plan_items")
