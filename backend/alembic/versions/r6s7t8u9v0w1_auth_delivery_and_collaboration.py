"""auth delivery and collaboration completion

Revision ID: r6s7t8u9v0w1
Revises: q5r6s7t8u9v0
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.models.models import Base


revision: str = "r6s7t8u9v0w1"
down_revision: Union[str, Sequence[str], None] = "q5r6s7t8u9v0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.tables["password_reset_tokens"].create(bind=op.get_bind(), checkfirst=True)
    op.add_column("work_time_entries", sa.Column("exchange_rate_snapshot_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_work_time_entries_exchange_snapshot", "work_time_entries", "exchange_rate_snapshots", ["exchange_rate_snapshot_id"], ["id"], ondelete="SET NULL")
    op.add_column("calendar_connections", sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("calendar_connections", "token_expires_at")
    op.drop_constraint("fk_work_time_entries_exchange_snapshot", "work_time_entries", type_="foreignkey")
    op.drop_column("work_time_entries", "exchange_rate_snapshot_id")
    op.drop_table("password_reset_tokens")
