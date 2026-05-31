"""harden nullable columns surfaced as required response fields

Generalises the fix from Sentry issue 28 (employee timezone) to every other
column that a *Out response schema declares as required but that had only a
client-side SQLAlchemy ``default=`` and no ``server_default`` / NOT NULL. Such
columns become NULL on any non-ORM insert (raw seed, singleton row, column
added by an earlier migration without backfill) and then crash FastAPI
response serialization with ResponseValidationError.

Columns hardened (backfill NULLs -> attach server_default -> NOT NULL):
  manager_settings.weekly_summary_day / alerts_enabled / gamification_enabled / soft_mode_weeks
  employees.is_active
  schedules.variant
  questions.options / is_required / sort_order
  tasks.priority

Revision ID: a7b8c9d0e1f2
Revises: e3f4a5b6c7d8
Create Date: 2026-05-31 17:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, Sequence[str], None] = 'e3f4a5b6c7d8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (table, column, existing_type, server_default, backfill_value_sql)
_COLUMNS = [
    ("manager_settings", "weekly_summary_day", sa.Integer(), "5", "5"),
    ("manager_settings", "alerts_enabled", sa.Boolean(), sa.text("true"), "true"),
    ("manager_settings", "gamification_enabled", sa.Boolean(), sa.text("true"), "true"),
    ("manager_settings", "soft_mode_weeks", sa.Integer(), "1", "1"),
    ("employees", "is_active", sa.Boolean(), sa.text("true"), "true"),
    ("schedules", "variant", sa.String(length=1), "A", "'A'"),
    ("questions", "options", postgresql.JSONB(), sa.text("'[]'::jsonb"), "'[]'::jsonb"),
    ("questions", "is_required", sa.Boolean(), sa.text("true"), "true"),
    ("questions", "sort_order", sa.Integer(), "0", "0"),
    ("tasks", "priority", sa.Integer(), "2", "2"),
]


def upgrade() -> None:
    for table, column, existing_type, server_default, backfill in _COLUMNS:
        # 1) backfill existing NULLs so they serialize correctly
        op.execute(f"UPDATE {table} SET {column} = {backfill} WHERE {column} IS NULL")
        # 2) attach server-side default + NOT NULL so raw/seed inserts can't produce NULL
        op.alter_column(
            table,
            column,
            existing_type=existing_type,
            nullable=False,
            server_default=server_default,
        )


def downgrade() -> None:
    for table, column, existing_type, _server_default, _backfill in reversed(_COLUMNS):
        op.alter_column(
            table,
            column,
            existing_type=existing_type,
            nullable=True,
            server_default=None,
        )
