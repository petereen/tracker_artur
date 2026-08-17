"""complete Google Calendar two-way sync storage

Revision ID: g1h2i3j4k5l6
Revises: f7g8h9i0j1k2
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "g1h2i3j4k5l6"
down_revision: Union[str, Sequence[str], None] = "f7g8h9i0j1k2"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _add(table: str, column: sa.Column) -> None:
    if column.name not in _columns(table):
        op.add_column(table, column)


def upgrade() -> None:
    _add("tasks", sa.Column("is_all_day", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    _add("calendar_entries", sa.Column("is_all_day", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    _add("calendar_entries", sa.Column("recurrence_rule", sa.Text(), nullable=True))
    _add("calendar_entries", sa.Column("recurrence_exceptions", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")))
    _add("calendar_connections", sa.Column("google_account_email", sa.Text(), nullable=True))
    _add("calendar_connections", sa.Column("calendar_name", sa.Text(), nullable=True))
    _add("calendar_connections", sa.Column("calendar_timezone", sa.Text(), nullable=True))

    mapping_columns = _columns("calendar_event_links")
    additions = {
        "calendar_entry_id": sa.Column("calendar_entry_id", sa.Integer(), sa.ForeignKey("calendar_entries.id", ondelete="CASCADE"), nullable=True),
        "external_recurring_event_id": sa.Column("external_recurring_event_id", sa.Text(), nullable=True),
        "external_updated_at": sa.Column("external_updated_at", sa.DateTime(timezone=True), nullable=True),
        "source": sa.Column("source", sa.Text(), nullable=False, server_default="platform"),
        "platform_version": sa.Column("platform_version", sa.Integer(), nullable=True),
        "platform_fingerprint": sa.Column("platform_fingerprint", sa.String(length=64), nullable=True),
        "conflict_state": sa.Column("conflict_state", sa.Text(), nullable=False, server_default="none"),
    }
    for name, column in additions.items():
        if name not in mapping_columns:
            op.add_column("calendar_event_links", column)

    inspector = sa.inspect(op.get_bind())
    constraints = {item.get("name") for item in inspector.get_unique_constraints("calendar_event_links")}
    if "uq_calendar_event_links_entry" not in constraints:
        op.create_unique_constraint("uq_calendar_event_links_entry", "calendar_event_links", ["connection_id", "calendar_entry_id"])
    checks = {item.get("name") for item in inspector.get_check_constraints("calendar_event_links")}
    if "ck_calendar_event_links_entity" not in checks:
        op.create_check_constraint("ck_calendar_event_links_entity", "calendar_event_links", "task_id IS NOT NULL OR calendar_entry_id IS NOT NULL")
    op.alter_column("calendar_event_links", "task_id", nullable=True)

    op.create_table(
        "google_calendar_oauth_states",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("nonce_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("encrypted_code_verifier", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_google_calendar_oauth_states_expiry", "google_calendar_oauth_states", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_google_calendar_oauth_states_expiry", table_name="google_calendar_oauth_states")
    op.drop_table("google_calendar_oauth_states")
    op.drop_constraint("ck_calendar_event_links_entity", "calendar_event_links", type_="check")
    op.drop_constraint("uq_calendar_event_links_entry", "calendar_event_links", type_="unique")
    op.drop_column("calendar_event_links", "conflict_state")
    op.drop_column("calendar_event_links", "platform_fingerprint")
    op.drop_column("calendar_event_links", "platform_version")
    op.drop_column("calendar_event_links", "source")
    op.drop_column("calendar_event_links", "external_updated_at")
    op.drop_column("calendar_event_links", "external_recurring_event_id")
    op.drop_column("calendar_event_links", "calendar_entry_id")
    op.drop_column("calendar_connections", "calendar_timezone")
    op.drop_column("calendar_connections", "calendar_name")
    op.drop_column("calendar_connections", "google_account_email")
    op.drop_column("calendar_entries", "recurrence_exceptions")
    op.drop_column("calendar_entries", "recurrence_rule")
    op.drop_column("calendar_entries", "is_all_day")
    op.drop_column("tasks", "is_all_day")
