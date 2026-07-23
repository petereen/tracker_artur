"""add file attachment metadata to company knowledge

Revision ID: i7j8k9l0m1n2
Revises: h6i7j8k9l0m1
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "i7j8k9l0m1n2"
down_revision: Union[str, Sequence[str], None] = "h6i7j8k9l0m1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("company_knowledge", sa.Column("attachment_filename", sa.Text(), nullable=True))
    op.add_column("company_knowledge", sa.Column("attachment_stored_name", sa.Text(), nullable=True))
    op.add_column("company_knowledge", sa.Column("attachment_content_type", sa.Text(), nullable=True))
    op.add_column("company_knowledge", sa.Column("attachment_size", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("company_knowledge", "attachment_size")
    op.drop_column("company_knowledge", "attachment_content_type")
    op.drop_column("company_knowledge", "attachment_stored_name")
    op.drop_column("company_knowledge", "attachment_filename")
