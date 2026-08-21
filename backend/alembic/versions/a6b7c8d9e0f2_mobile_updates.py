"""Add self-hosted mobile web update bundles and channels.

Revision ID: a6b7c8d9e0f2
Revises: i1j2k3l4m5n6
"""

from alembic import op
import sqlalchemy as sa


revision = "a6b7c8d9e0f2"
down_revision = "i1j2k3l4m5n6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mobile_update_bundles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("app_id", sa.String(length=128), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("app_id", "version", name="uq_mobile_update_bundle_app_version"),
        sa.UniqueConstraint("storage_key", name="uq_mobile_update_bundles_storage_key"),
    )
    op.create_index(
        "ix_mobile_update_bundles_app_created",
        "mobile_update_bundles",
        ["app_id", "created_at"],
    )

    op.create_table(
        "mobile_update_channels",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("app_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column(
            "active_bundle_id",
            sa.Integer(),
            sa.ForeignKey("mobile_update_bundles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "previous_bundle_id",
            sa.Integer(),
            sa.ForeignKey("mobile_update_bundles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("app_id", "name", name="uq_mobile_update_channel_app_name"),
    )


def downgrade() -> None:
    op.drop_table("mobile_update_channels")
    op.drop_index("ix_mobile_update_bundles_app_created", table_name="mobile_update_bundles")
    op.drop_table("mobile_update_bundles")
