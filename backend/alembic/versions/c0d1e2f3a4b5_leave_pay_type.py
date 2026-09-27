"""leave request pay type (paid / unpaid)

Revision ID: c0d1e2f3a4b5
Revises: b9c0d1e2f3a4
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c0d1e2f3a4b5"
down_revision: Union[str, Sequence[str], None] = "b9c0d1e2f3a4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The enterprise foundation migration builds leave_requests from the
    # current model metadata, which already includes these columns on fresh
    # databases. Keep this revision safe for both schema histories.
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("leave_requests")}
    if "requested_pay_type" not in columns:
        op.add_column("leave_requests", sa.Column("requested_pay_type", sa.Text(), nullable=False, server_default="paid"))
    if "approved_pay_type" not in columns:
        op.add_column("leave_requests", sa.Column("approved_pay_type", sa.Text(), nullable=True))
    # Existing approved requests keep their meaning: unpaid leave type stays unpaid, everything else paid.
    op.execute("UPDATE leave_requests SET requested_pay_type = 'unpaid' WHERE time_off_type = 'unpaid'")
    op.execute("UPDATE leave_requests SET approved_pay_type = requested_pay_type WHERE status = 'approved'")


def downgrade() -> None:
    op.drop_column("leave_requests", "approved_pay_type")
    op.drop_column("leave_requests", "requested_pay_type")
