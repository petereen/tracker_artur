"""auth delivery and collaboration completion

Revision ID: r6s7t8u9v0w1
Revises: q5r6s7t8u9v0
"""

from typing import Sequence, Union

from alembic import op

from app.models.models import Base


revision: str = "r6s7t8u9v0w1"
down_revision: Union[str, Sequence[str], None] = "q5r6s7t8u9v0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The foundation migration creates the full calendar/time-entry tables
    # from Base.metadata, including token_expires_at and
    # exchange_rate_snapshot_id.  Keep this follow-up migration compatible
    # with databases that have already applied that schema.  Only the
    # password-reset table is new in this revision.
    Base.metadata.tables["password_reset_tokens"].create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    Base.metadata.tables["password_reset_tokens"].drop(bind=op.get_bind(), checkfirst=True)
