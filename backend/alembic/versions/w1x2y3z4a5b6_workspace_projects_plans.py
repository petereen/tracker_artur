"""add project archival and member plan ideas

Revision ID: w1x2y3z4a5b6
Revises: v0w1x2y3z4a5
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "w1x2y3z4a5b6"
down_revision: Union[str, Sequence[str], None] = "v0w1x2y3z4a5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("archived_at", sa.DateTime(timezone=True)))
    op.add_column("projects", sa.Column("archived_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")))
    op.add_column("company_plan_items", sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE")))
    op.add_column("company_plan_items", sa.Column("due_date", sa.Date()))
    op.add_column("company_plan_items", sa.Column("approved_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")))
    op.drop_constraint("ck_company_plan_items_status", "company_plan_items", type_="check")
    op.create_check_constraint("ck_company_plan_items_status", "company_plan_items", "status IN ('approved','archived')")
    op.execute("""UPDATE company_plan_items AS item SET organization_id = COALESCE(
        (SELECT account.organization_id FROM work_reports AS report JOIN user_accounts AS account ON account.employee_id = report.employee_id WHERE report.id = item.source_report_id LIMIT 1),
        (SELECT id FROM organizations ORDER BY id LIMIT 1)
    ) WHERE item.organization_id IS NULL""")
    op.alter_column("company_plan_items", "organization_id", nullable=False)
    op.create_index("ix_company_plan_items_organization_id", "company_plan_items", ["organization_id"])
    op.create_table(
        "plan_ideas",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("submitted_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("submitted_by_employee_id", sa.Integer(), sa.ForeignKey("employees.id", ondelete="SET NULL")),
        sa.Column("plan_month", sa.Date(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("content", sa.Text()),
        sa.Column("suggested_due_date", sa.Date()),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("reviewed_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("merged_into_plan_item_id", sa.Integer(), sa.ForeignKey("company_plan_items.id", ondelete="SET NULL")),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('pending','approved','rejected','merged')", name="ck_plan_ideas_status"),
    )
    op.create_index("ix_plan_ideas_org_month_status", "plan_ideas", ["organization_id", "plan_month", "status"])


def downgrade() -> None:
    op.drop_table("plan_ideas")
    op.drop_index("ix_company_plan_items_organization_id", table_name="company_plan_items")
    op.drop_constraint("ck_company_plan_items_status", "company_plan_items", type_="check")
    op.create_check_constraint("ck_company_plan_items_status", "company_plan_items", "status IN ('approved')")
    op.drop_column("company_plan_items", "approved_by_account_id")
    op.drop_column("company_plan_items", "due_date")
    op.drop_column("company_plan_items", "organization_id")
    op.drop_column("projects", "archived_by_account_id")
    op.drop_column("projects", "archived_at")
