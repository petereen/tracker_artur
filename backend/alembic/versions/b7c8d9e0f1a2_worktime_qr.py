"""add provisioned dynamic QR worktime kiosks and replay-safe metadata"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "b7c8d9e0f1a2"
down_revision: Union[str, Sequence[str], None] = ("a5b6c7d8e9f0", "c1d2e3f4g5h6")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "worktime_qr_kiosks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("location_id", sa.Text(), nullable=False, server_default="main_office"),
        sa.Column("display_name", sa.Text(), nullable=False, server_default="Main office"),
        sa.Column("credential_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("pairing_code_hash", sa.String(64), unique=True),
        sa.Column("pairing_expires_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("created_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("paired_at", sa.DateTime(timezone=True)),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('active','revoked')", name="ck_worktime_qr_kiosk_status"),
        sa.UniqueConstraint("organization_id", "label", name="uq_worktime_qr_kiosk_org_label"),
    )
    op.create_index("ix_worktime_qr_kiosks_org_status", "worktime_qr_kiosks", ["organization_id", "status"])
    op.add_column("work_time_entries", sa.Column("source_kiosk_id", sa.Integer(), sa.ForeignKey("worktime_qr_kiosks.id", ondelete="SET NULL")))
    op.add_column("work_time_entries", sa.Column("work_location_id", sa.Text()))
    op.create_index("ix_work_time_entries_source_kiosk_id", "work_time_entries", ["source_kiosk_id"])
    op.execute("""
        WITH ranked AS (
            SELECT id, employee_id, started_at,
                   row_number() OVER (PARTITION BY employee_id ORDER BY started_at DESC, id DESC) AS position
            FROM work_time_entries
            WHERE ended_at IS NULL AND employee_id IS NOT NULL
        ), newest AS (
            SELECT employee_id, started_at
            FROM ranked WHERE position = 1
        )
        UPDATE work_time_entries older
        SET ended_at = newest.started_at, version = older.version + 1
        FROM ranked duplicate
        JOIN newest ON newest.employee_id = duplicate.employee_id
        WHERE older.id = duplicate.id
          AND duplicate.position > 1
          AND older.ended_at IS NULL
    """)
    op.create_index("uq_work_time_entries_employee_open", "work_time_entries", ["employee_id"], unique=True, postgresql_where=sa.text("employee_id IS NOT NULL AND ended_at IS NULL"))


def downgrade() -> None:
    op.drop_index("uq_work_time_entries_employee_open", table_name="work_time_entries")
    op.drop_index("ix_work_time_entries_source_kiosk_id", table_name="work_time_entries")
    op.drop_column("work_time_entries", "work_location_id")
    op.drop_column("work_time_entries", "source_kiosk_id")
    op.drop_index("ix_worktime_qr_kiosks_org_status", table_name="worktime_qr_kiosks")
    op.drop_table("worktime_qr_kiosks")
