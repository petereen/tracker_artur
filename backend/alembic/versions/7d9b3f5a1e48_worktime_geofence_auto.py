"""automatic geofence worktime

``worktime_sites`` (several office geofences; the existing single
``organizations.settings["worktime_geofence"]`` becomes the first site),
``worktime_location_consents`` (append-only employee disclaimer acceptance),
``mobile_devices`` (enrolled phones, hashed geo-only credential) and
``worktime_geo_events`` (transition log and what the rules did). Row-level
security like every other tenant table. ``mobile_update_bundles`` gains
``min_native_version`` so a web bundle is not delivered to a binary too old
for it.

Revision ID: 7d9b3f5a1e48
Revises: 6c8a2e4f0d37
Create Date: 2026-10-02 14:00:00.000000

"""
import math
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "7d9b3f5a1e48"
down_revision: Union[str, Sequence[str], None] = "6c8a2e4f0d37"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ("worktime_sites", "worktime_location_consents", "mobile_devices", "worktime_geo_events")


def _organization_fk() -> sa.Column:
    return sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)


def _legacy_site(settings) -> tuple[float, float, int] | None:
    value = (settings or {}).get("worktime_geofence") if isinstance(settings, dict) else None
    if not isinstance(value, dict):
        return None
    try:
        latitude, longitude = float(value["latitude"]), float(value["longitude"])
        radius = int(value.get("radius_meters", 150))
    except (KeyError, TypeError, ValueError):
        return None
    if not (math.isfinite(latitude) and math.isfinite(longitude) and -90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None
    return latitude, longitude, radius if 25 <= radius <= 5000 else 150


def upgrade() -> None:
    op.create_table(
        "worktime_sites",
        sa.Column("id", sa.Integer(), primary_key=True),
        _organization_fk(),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("radius_meters", sa.Integer(), nullable=False, server_default="150"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("schedule_start", sa.Time()),
        sa.Column("schedule_end", sa.Time()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("public_id", name="uq_worktime_sites_public_id"),
        sa.CheckConstraint("latitude BETWEEN -90 AND 90 AND longitude BETWEEN -180 AND 180", name="ck_worktime_sites_coordinates"),
        sa.CheckConstraint("radius_meters BETWEEN 25 AND 5000", name="ck_worktime_sites_radius"),
    )
    op.create_index("ix_worktime_sites_org_active", "worktime_sites", ["organization_id", "is_active"])

    op.create_table(
        "worktime_location_consents",
        sa.Column("id", sa.Integer(), primary_key=True),
        _organization_fk(),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("policy_version", sa.String(32), nullable=False),
        sa.Column("text_sha256", sa.String(64), nullable=False),
        sa.Column("locale", sa.String(8), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("app_platform", sa.String(16)),
        sa.Column("app_version", sa.String(64)),
    )
    op.create_index("ix_worktime_location_consents_account", "worktime_location_consents", ["account_id", "accepted_at"])

    op.create_table(
        "mobile_devices",
        sa.Column("id", sa.Integer(), primary_key=True),
        _organization_fk(),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("platform", sa.String(16), nullable=False),
        sa.Column("label", sa.Text()),
        sa.Column("credential_hash", sa.String(64), nullable=False),
        sa.Column("consent_id", sa.Integer(), sa.ForeignKey("worktime_location_consents.id", ondelete="SET NULL")),
        sa.Column("geofence_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("location_permission", sa.String(16)),
        sa.Column("location_accuracy", sa.String(16)),
        sa.Column("battery_unrestricted", sa.Boolean()),
        sa.Column("app_version", sa.String(64)),
        sa.Column("native_version", sa.Integer()),
        sa.Column("last_event_at", sa.DateTime(timezone=True)),
        sa.Column("last_state_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("public_id", name="uq_mobile_devices_public_id"),
        sa.UniqueConstraint("credential_hash", name="uq_mobile_devices_credential_hash"),
        sa.CheckConstraint("platform IN ('ios','android')", name="ck_mobile_devices_platform"),
    )
    op.create_index("ix_mobile_devices_account", "mobile_devices", ["account_id", "revoked_at"])

    op.create_table(
        "worktime_geo_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        _organization_fk(),
        sa.Column("device_id", sa.Integer(), sa.ForeignKey("mobile_devices.id", ondelete="CASCADE")),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="CASCADE")),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id", ondelete="CASCADE")),
        sa.Column("site_id", sa.Integer(), sa.ForeignKey("worktime_sites.id", ondelete="SET NULL")),
        sa.Column("client_event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("accuracy_meters", sa.Float()),
        sa.Column("is_mock", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("result", sa.String(64), nullable=False),
        sa.Column("needs_review", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("time_entry_id", sa.Integer(), sa.ForeignKey("work_time_entries.id", ondelete="SET NULL")),
        sa.UniqueConstraint("device_id", "client_event_id", name="uq_worktime_geo_events_device_client"),
        sa.CheckConstraint("kind IN ('enter','exit','state_inside','state_outside','sweep')", name="ck_worktime_geo_events_kind"),
    )
    op.create_index("ix_worktime_geo_events_org_received", "worktime_geo_events", ["organization_id", "received_at"])
    op.create_index("ix_worktime_geo_events_employee", "worktime_geo_events", ["employee_id", "occurred_at"])
    op.create_index("ix_worktime_geo_events_pending", "worktime_geo_events", ["result", "occurred_at"])

    op.add_column("mobile_update_bundles", sa.Column("min_native_version", sa.Integer()))

    bind = op.get_bind()
    # The single office geofence of each organization becomes its first site.
    for organization_id, settings in bind.execute(sa.text("SELECT id, settings FROM organizations ORDER BY id")).all():
        site = _legacy_site(settings)
        if site:
            bind.execute(
                sa.text("INSERT INTO worktime_sites (organization_id, name, latitude, longitude, radius_meters) VALUES (:org, :name, :lat, :lng, :radius)"),
                {"org": organization_id, "name": "Төв оффис", "lat": site[0], "lng": site[1], "radius": site[2]},
            )

    if bind.execute(sa.text("SELECT to_regproc('tenant_row_visible') IS NOT NULL")).scalar():
        for table in TABLES:
            op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
            op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
            op.execute(
                f'CREATE POLICY tenant_isolation ON "{table}" '
                "USING (tenant_row_visible(organization_id)) WITH CHECK (tenant_row_visible(organization_id))"
            )


def downgrade() -> None:
    op.drop_column("mobile_update_bundles", "min_native_version")
    for table in reversed(TABLES):
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
        op.drop_table(table)
