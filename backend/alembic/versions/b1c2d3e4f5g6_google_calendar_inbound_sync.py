"""add durable Google Calendar inbound synchronization state

Revision ID: b1c2d3e4f5g6
Revises: a0b1c2d3e4f5
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "b1c2d3e4f5g6"
down_revision: Union[str, Sequence[str], None] = "a0b1c2d3e4f5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("calendar_connections")}
    additions = {
        "calendar_id": sa.Column("calendar_id", sa.Text(), nullable=False, server_default="primary"),
        "webhook_channel_id": sa.Column("webhook_channel_id", sa.Text(), nullable=True),
        "webhook_resource_id": sa.Column("webhook_resource_id", sa.Text(), nullable=True),
        "encrypted_channel_token": sa.Column("encrypted_channel_token", sa.Text(), nullable=True),
        "channel_expires_at": sa.Column("channel_expires_at", sa.DateTime(timezone=True), nullable=True),
        "last_webhook_message_number": sa.Column("last_webhook_message_number", sa.String(length=32), nullable=True),
        "sync_failure_count": sa.Column("sync_failure_count", sa.Integer(), nullable=False, server_default="0"),
    }
    for name, column in additions.items():
        if name not in columns:
            op.add_column("calendar_connections", column)
    constraints = {constraint.get("name") for constraint in inspector.get_unique_constraints("calendar_connections")}
    if "uq_calendar_connections_webhook_channel" not in constraints:
        op.create_unique_constraint("uq_calendar_connections_webhook_channel", "calendar_connections", ["webhook_channel_id"])


def downgrade() -> None:
    op.drop_constraint("uq_calendar_connections_webhook_channel", "calendar_connections", type_="unique")
    for column in ("sync_failure_count", "last_webhook_message_number", "channel_expires_at", "encrypted_channel_token", "webhook_resource_id", "webhook_channel_id", "calendar_id"):
        op.drop_column("calendar_connections", column)
