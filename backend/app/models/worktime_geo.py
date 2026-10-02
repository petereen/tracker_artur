"""Automatic geofence worktime: sites, consent, enrolled devices, event log."""
from __future__ import annotations

import uuid

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, Float, ForeignKey, Index, Integer, String, Text, Time, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import text as sa_text

from app.core.database import Base

GEO_EVENT_KINDS = ("enter", "exit", "state_inside", "state_outside", "sweep")


class WorktimeSite(Base):
    """One office geofence. The oldest site mirrors the legacy single geofence."""

    __tablename__ = "worktime_sites"
    __table_args__ = (
        CheckConstraint("latitude BETWEEN -90 AND 90 AND longitude BETWEEN -180 AND 180", name="ck_worktime_sites_coordinates"),
        CheckConstraint("radius_meters BETWEEN 25 AND 5000", name="ck_worktime_sites_radius"),
        Index("ix_worktime_sites_org_active", "organization_id", "is_active"),
    )

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    public_id = Column(UUID(as_uuid=True), nullable=False, unique=True, default=uuid.uuid4, server_default=sa_text("gen_random_uuid()"))
    name = Column(Text, nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    radius_meters = Column(Integer, nullable=False, server_default="150", default=150)
    is_active = Column(Boolean, nullable=False, server_default=sa_text("true"), default=True)
    # Optional local-time window in which an arrival may start the clock.
    schedule_start = Column(Time)
    schedule_end = Column(Time)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class WorktimeLocationConsent(Base):
    """An employee's acceptance of the location disclaimer. Append-only:
    accepting again is a new row; only ``revoked_at`` is ever set later."""

    __tablename__ = "worktime_location_consents"
    __table_args__ = (Index("ix_worktime_location_consents_account", "account_id", "accepted_at"),)

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False)
    policy_version = Column(String(32), nullable=False)
    text_sha256 = Column(String(64), nullable=False)
    locale = Column(String(8), nullable=False)
    accepted_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    revoked_at = Column(DateTime(timezone=True))
    app_platform = Column(String(16))
    app_version = Column(String(64))


class MobileDevice(Base):
    """A phone enrolled for geofence reporting. Only the SHA-256 of its
    credential is stored; the credential opens the geo endpoints and nothing else."""

    __tablename__ = "mobile_devices"
    __table_args__ = (
        CheckConstraint("platform IN ('ios','android')", name="ck_mobile_devices_platform"),
        Index("ix_mobile_devices_account", "account_id", "revoked_at"),
    )

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False)
    public_id = Column(UUID(as_uuid=True), nullable=False, unique=True, default=uuid.uuid4, server_default=sa_text("gen_random_uuid()"))
    platform = Column(String(16), nullable=False)
    label = Column(Text)
    credential_hash = Column(String(64), nullable=False, unique=True)
    consent_id = Column(Integer, ForeignKey("worktime_location_consents.id", ondelete="SET NULL"))
    geofence_enabled = Column(Boolean, nullable=False, server_default=sa_text("true"), default=True)
    # OS permission snapshot reported by the device.
    location_permission = Column(String(16))  # always | when_in_use | denied
    location_accuracy = Column(String(16))  # precise | approximate
    battery_unrestricted = Column(Boolean)
    app_version = Column(String(64))
    native_version = Column(Integer)
    last_event_at = Column(DateTime(timezone=True))
    last_state_at = Column(DateTime(timezone=True))
    revoked_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class WorktimeGeoEvent(Base):
    """One reported transition (or sweeper action) and what the rules did with it.
    Coordinates are never stored: only the site, the time and the accuracy."""

    __tablename__ = "worktime_geo_events"
    __table_args__ = (
        CheckConstraint("kind IN ('enter','exit','state_inside','state_outside','sweep')", name="ck_worktime_geo_events_kind"),
        UniqueConstraint("device_id", "client_event_id", name="uq_worktime_geo_events_device_client"),
        Index("ix_worktime_geo_events_org_received", "organization_id", "received_at"),
        Index("ix_worktime_geo_events_employee", "employee_id", "occurred_at"),
        Index("ix_worktime_geo_events_pending", "result", "occurred_at"),
    )

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    device_id = Column(Integer, ForeignKey("mobile_devices.id", ondelete="CASCADE"))
    account_id = Column(Integer, ForeignKey("user_accounts.id", ondelete="CASCADE"))
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="CASCADE"))
    site_id = Column(Integer, ForeignKey("worktime_sites.id", ondelete="SET NULL"))
    client_event_id = Column(UUID(as_uuid=True), nullable=False, default=uuid.uuid4)
    kind = Column(String(16), nullable=False)
    occurred_at = Column(DateTime(timezone=True), nullable=False)
    received_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    accuracy_meters = Column(Float)
    is_mock = Column(Boolean, nullable=False, server_default=sa_text("false"), default=False)
    # started | stopped | pending_stop | shadow:<action> | ignored:<reason>
    result = Column(String(64), nullable=False)
    needs_review = Column(Boolean, nullable=False, server_default=sa_text("false"), default=False)
    time_entry_id = Column(Integer, ForeignKey("work_time_entries.id", ondelete="SET NULL"))
