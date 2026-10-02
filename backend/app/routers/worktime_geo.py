"""Automatic geofence worktime API (see ``services/worktime_auto.py``).

Three callers:

* the employee's signed-in app: disclaimer, consent, device enrollment;
* the phone's native layer, which may run while the web layer is not loaded:
  ``/mobile/geofences`` and ``/mobile/geo-events`` authenticate with the
  device credential (``Authorization: Device <id>.<secret>``), which opens
  these two endpoints and nothing else;
* administrators: sites, automatic-mode settings, devices and the event log
  (location events are visible to admin and HR only).
"""
from __future__ import annotations

import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, time, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal, get_db
from app.core.enterprise_deps import ActorContext, get_actor, require_roles, tenant_is_operational
from app.core.tenancy import bind_tenant, system_scope
from app.models.models import Employee, Organization, UserAccount
from app.models.worktime_geo import MobileDevice, WorktimeGeoEvent, WorktimeLocationConsent, WorktimeSite
from app.services.enterprise_events import record_change
from app.services.worktime_auto import (
    MAX_SITES_PER_DEVICE,
    POLICY_VERSION,
    GeoEventInput,
    active_sites,
    auto_settings,
    consent_text,
    current_consent,
    device_config,
    employer_ack_current,
    hash_credential,
    process_event,
    revoke_devices,
    site_out,
)
from app.services.worktime_geofence import (
    WORKTIME_GEOFENCE_KEY,
    WORKTIME_GEOFENCE_MAX_RADIUS_METERS,
    WORKTIME_GEOFENCE_MIN_RADIUS_METERS,
    WORKTIME_METHODS_KEY,
)

router = APIRouter()
# Location events are personal data: managers only see the resulting entries.
LOCATION_EVENT_ROLES = ("admin", "hr")
MAX_EVENTS_PER_REQUEST = 50


# ── Device credential ──────────────────────────────────────────────────────
@dataclass(slots=True)
class DeviceContext:
    device: MobileDevice
    account: UserAccount
    employee: Employee
    organization: Organization


def _device_denied(code: str, message: str, status_code: int = status.HTTP_401_UNAUTHORIZED) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


async def get_device(authorization: str | None = Header(default=None), db: AsyncSession = Depends(get_db)) -> DeviceContext:
    scheme, _, value = (authorization or "").partition(" ")
    public_id, _, secret = value.strip().partition(".")
    if scheme.lower() != "device" or not secret:
        raise _device_denied("device_credential_required", "Device credential required")
    try:
        device_uuid = uuid.UUID(public_id)
    except ValueError:
        raise _device_denied("device_revoked", "Device is not enrolled")
    # The credential names its tenant: look it up in the system context, then
    # run the rest of the request inside that tenant.
    with system_scope():
        async with AsyncSessionLocal() as lookup:
            row = (await lookup.execute(
                select(MobileDevice.organization_id, MobileDevice.credential_hash, MobileDevice.revoked_at)
                .where(MobileDevice.public_id == device_uuid)
            )).first()
    if row is None or row.revoked_at is not None or not hmac.compare_digest(row.credential_hash, hash_credential(secret)):
        raise _device_denied("device_revoked", "Device is not enrolled")
    if not await tenant_is_operational(row.organization_id):
        raise _device_denied("tenant_unavailable", "Workspace is not available", status.HTTP_403_FORBIDDEN)
    await bind_tenant(db, row.organization_id)
    device = await db.scalar(select(MobileDevice).where(MobileDevice.public_id == device_uuid))
    account = await db.get(UserAccount, device.account_id) if device else None
    employee = await db.get(Employee, account.employee_id) if account and account.employee_id else None
    if device is None or account is None or account.status != "active" or employee is None or not employee.is_active:
        raise _device_denied("device_revoked", "Device is not enrolled")
    return DeviceContext(device=device, account=account, employee=employee, organization=await db.get(Organization, device.organization_id))


# ── Schemas ────────────────────────────────────────────────────────────────
def _parse_time(value: str | None) -> time | None:
    if value in (None, ""):
        return None
    try:
        hours, minutes = value.split(":")
        return time(int(hours), int(minutes))
    except (ValueError, TypeError):
        raise ValueError("Use HH:MM")


class SiteInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    radius_meters: int = Field(default=150, ge=WORKTIME_GEOFENCE_MIN_RADIUS_METERS, le=WORKTIME_GEOFENCE_MAX_RADIUS_METERS)
    is_active: bool = True
    schedule_start: str | None = None
    schedule_end: str | None = None

    @field_validator("schedule_start", "schedule_end")
    @classmethod
    def validate_time(cls, value: str | None) -> str | None:
        _parse_time(value)
        return value or None


class AutoSettingsInput(BaseModel):
    auto_geofence_mode: Literal["off", "shadow", "on"] | None = None
    exit_grace_minutes: int | None = Field(default=None, ge=0, le=120)
    min_accuracy_meters: int | None = Field(default=None, ge=10, le=1000)
    geo_retention_days: int | None = Field(default=None, ge=7, le=730)
    acknowledge_employer_disclaimer: bool = False


class ConsentInput(BaseModel):
    policy_version: str = Field(max_length=32)
    text_sha256: str = Field(min_length=64, max_length=64)
    locale: str = Field(max_length=8)
    app_platform: Literal["ios", "android", "web"] | None = None
    app_version: str | None = Field(default=None, max_length=64)


class DeviceState(BaseModel):
    location_permission: Literal["always", "when_in_use", "denied"] | None = None
    location_accuracy: Literal["precise", "approximate"] | None = None
    battery_unrestricted: bool | None = None
    app_version: str | None = Field(default=None, max_length=64)
    native_version: int | None = Field(default=None, ge=0, le=100000)


class DeviceEnrollInput(DeviceState):
    platform: Literal["ios", "android"]
    label: str | None = Field(default=None, max_length=120)


class GeoEventIn(BaseModel):
    client_event_id: uuid.UUID
    kind: Literal["enter", "exit", "state_inside", "state_outside"]
    site_id: uuid.UUID | None = None
    occurred_at: datetime
    accuracy_meters: float | None = Field(default=None, ge=0, le=100000)
    is_mock: bool = False
    # Used once to check a snapshot against the site; never stored.
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


class GeoEventsInput(BaseModel):
    events: list[GeoEventIn] = Field(default_factory=list, max_length=MAX_EVENTS_PER_REQUEST)
    state: DeviceState | None = None


# ── Helpers ────────────────────────────────────────────────────────────────
def _apply_state(device: MobileDevice, state: DeviceState | None) -> None:
    if state is None:
        return
    for field, value in state.model_dump(exclude_none=True).items():
        setattr(device, field, value)


def _device_out(device: MobileDevice) -> dict:
    return {
        "id": str(device.public_id), "platform": device.platform, "label": device.label,
        "geofence_enabled": device.geofence_enabled, "location_permission": device.location_permission,
        "location_accuracy": device.location_accuracy, "battery_unrestricted": device.battery_unrestricted,
        "app_version": device.app_version, "native_version": device.native_version,
        "last_event_at": device.last_event_at, "last_state_at": device.last_state_at,
        "revoked_at": device.revoked_at, "created_at": device.created_at,
    }


def _event_out(event: WorktimeGeoEvent, site_name: str | None = None, employee_name: str | None = None) -> dict:
    return {
        "id": event.id, "kind": event.kind, "occurred_at": event.occurred_at, "received_at": event.received_at,
        "accuracy_meters": event.accuracy_meters, "is_mock": event.is_mock, "result": event.result,
        "needs_review": event.needs_review, "time_entry_id": event.time_entry_id,
        "site_name": site_name, "employee_id": event.employee_id, "employee_name": employee_name,
    }


async def _sync_legacy_geofence(db: AsyncSession, organization: Organization) -> None:
    """Keep ``settings["worktime_geofence"]`` (manual and Telegram starts) equal
    to the first active site, so both views of the office stay in step."""
    primary = await db.scalar(select(WorktimeSite).where(
        WorktimeSite.organization_id == organization.id, WorktimeSite.is_active.is_(True)).order_by(WorktimeSite.id).limit(1))
    settings = dict(organization.settings or {})
    if primary is None:
        settings.pop(WORKTIME_GEOFENCE_KEY, None)
    else:
        settings[WORKTIME_GEOFENCE_KEY] = {"latitude": primary.latitude, "longitude": primary.longitude, "radius_meters": primary.radius_meters}
    organization.settings = settings


def _require_employee(actor: ActorContext) -> int:
    if not actor.employee_id:
        raise HTTPException(status_code=409, detail={"code": "employee_unlinked", "message": "Account is not linked to an employee"})
    return actor.employee_id


# ── Employee: status, disclaimer, consent ──────────────────────────────────
@router.get("/worktime/auto/status")
async def auto_status(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    organization = await db.get(Organization, actor.organization_id)
    values = auto_settings(organization.settings)
    consent = await current_consent(db, actor.account_id)
    device = await db.scalar(select(MobileDevice).where(
        MobileDevice.account_id == actor.account_id, MobileDevice.revoked_at.is_(None)).order_by(MobileDevice.id.desc()).limit(1))
    sites = await active_sites(db, actor.organization_id)
    recent = (await db.execute(
        select(WorktimeGeoEvent, WorktimeSite.name).outerjoin(WorktimeSite, WorktimeSite.id == WorktimeGeoEvent.site_id)
        .where(WorktimeGeoEvent.account_id == actor.account_id).order_by(WorktimeGeoEvent.occurred_at.desc()).limit(10)
    )).all()
    return {
        "mode": values["auto_geofence_mode"],
        "available": values["auto_geofence_mode"] != "off" and bool(sites) and bool(actor.employee_id),
        "employee_linked": bool(actor.employee_id),
        "policy_version": POLICY_VERSION,
        "consent": {"id": consent.id, "policy_version": consent.policy_version, "accepted_at": consent.accepted_at, "locale": consent.locale} if consent else None,
        "device": _device_out(device) if device else None,
        "site_count": len(sites),
        "geo_retention_days": values["geo_retention_days"],
        "recent_events": [_event_out(event, site_name) for event, site_name in recent],
    }


@router.get("/worktime/auto/consent-text")
async def get_consent_text(locale: str | None = None, actor: ActorContext = Depends(get_actor)):
    return consent_text(locale or actor.locale)


@router.post("/worktime/auto/consent", status_code=status.HTTP_201_CREATED)
async def accept_consent(data: ConsentInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    _require_employee(actor)
    expected = consent_text(data.locale)
    # The acceptance must be of the exact text the server currently serves.
    if data.policy_version != expected["policy_version"] or data.locale != expected["locale"] or not hmac.compare_digest(data.text_sha256, expected["text_sha256"]):
        raise HTTPException(status_code=409, detail={"code": "consent_text_changed", "message": "The disclaimer changed; read it again"})
    consent = WorktimeLocationConsent(
        organization_id=actor.organization_id, account_id=actor.account_id, policy_version=data.policy_version,
        text_sha256=data.text_sha256, locale=data.locale, app_platform=data.app_platform, app_version=data.app_version,
    )
    db.add(consent)
    await db.flush()
    await record_change(db, actor=actor, topic="worktime", aggregate_type="worktime_location_consent", aggregate_id=consent.id, operation="accepted",
                        after={"policy_version": consent.policy_version, "text_sha256": consent.text_sha256, "locale": consent.locale})
    await db.commit()
    return {"id": consent.id, "policy_version": consent.policy_version, "accepted_at": consent.accepted_at, "locale": consent.locale}


@router.delete("/worktime/auto/consent")
async def revoke_consent(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    """Withdraw consent: the phone stops being trusted at once."""
    now = datetime.now(timezone.utc)
    consents = (await db.execute(select(WorktimeLocationConsent).where(
        WorktimeLocationConsent.account_id == actor.account_id, WorktimeLocationConsent.revoked_at.is_(None)).with_for_update())).scalars().all()
    for consent in consents:
        consent.revoked_at = now
    devices = (await db.execute(select(MobileDevice).where(MobileDevice.account_id == actor.account_id, MobileDevice.revoked_at.is_(None)).with_for_update())).scalars().all()
    await revoke_devices(db, devices, now)
    if consents:
        await record_change(db, actor=actor, topic="worktime", aggregate_type="worktime_location_consent", aggregate_id=consents[-1].id, operation="revoked",
                            after={"devices_revoked": len(devices)})
    await db.commit()
    return {"revoked": len(consents), "devices_revoked": len(devices)}


# ── Employee: device enrollment ────────────────────────────────────────────
@router.post("/mobile/devices", status_code=status.HTTP_201_CREATED)
async def enroll_device(data: DeviceEnrollInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    _require_employee(actor)
    organization = await db.get(Organization, actor.organization_id)
    if auto_settings(organization.settings)["auto_geofence_mode"] == "off":
        raise HTTPException(status_code=409, detail={"code": "worktime_auto_disabled", "message": "Automatic work time is switched off"})
    consent = await current_consent(db, actor.account_id)
    if consent is None:
        raise HTTPException(status_code=409, detail={"code": "location_consent_required", "message": "Accept the location disclaimer first"})
    # One reporting phone per account: a second phone left at the office
    # would keep the clock running.
    previous = (await db.execute(select(MobileDevice).where(MobileDevice.account_id == actor.account_id, MobileDevice.revoked_at.is_(None)).with_for_update())).scalars().all()
    await revoke_devices(db, previous)
    secret = secrets.token_urlsafe(32)
    device = MobileDevice(
        organization_id=actor.organization_id, account_id=actor.account_id, platform=data.platform, label=data.label,
        credential_hash=hash_credential(secret), consent_id=consent.id,
    )
    _apply_state(device, data)
    db.add(device)
    await db.flush()
    await record_change(db, actor=actor, topic="worktime", aggregate_type="mobile_device", aggregate_id=device.id, operation="enrolled",
                        after={"platform": device.platform, "replaced": len(previous)})
    await db.commit()
    await db.refresh(device)
    return {
        "device": _device_out(device),
        # Shown once; only its hash is stored.
        "credential": f"{device.public_id}.{secret}",
        "sites": [site_out(site) for site in await active_sites(db, actor.organization_id)],
        "config": device_config(organization.settings),
    }


async def _own_device(db: AsyncSession, actor: ActorContext, device_id: uuid.UUID) -> MobileDevice:
    device = await db.scalar(select(MobileDevice).where(MobileDevice.public_id == device_id, MobileDevice.account_id == actor.account_id).with_for_update())
    if device is None:
        raise HTTPException(status_code=404, detail={"code": "device_not_found", "message": "Device not found"})
    return device


@router.put("/mobile/devices/{device_id}/state")
async def update_device_state(device_id: uuid.UUID, data: DeviceState, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    device = await _own_device(db, actor, device_id)
    _apply_state(device, data)
    await db.commit()
    return _device_out(device)


@router.delete("/mobile/devices/{device_id}")
async def revoke_own_device(device_id: uuid.UUID, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    device = await _own_device(db, actor, device_id)
    await revoke_devices(db, [device])
    await record_change(db, actor=actor, topic="worktime", aggregate_type="mobile_device", aggregate_id=device.id, operation="revoked", after={"by": "owner"})
    await db.commit()
    return _device_out(device)


# ── Native layer (device credential) ───────────────────────────────────────
async def _device_payload(db: AsyncSession, context: DeviceContext) -> dict:
    return {
        "sites": [site_out(site) for site in await active_sites(db, context.organization.id)],
        "config": device_config(context.organization.settings),
        "server_time": datetime.now(timezone.utc),
    }


@router.get("/mobile/geofences")
async def device_geofences(response: Response, db: AsyncSession = Depends(get_db), context: DeviceContext = Depends(get_device)):
    response.headers["Cache-Control"] = "no-store"
    return await _device_payload(db, context)


@router.post("/mobile/geo-events")
async def report_geo_events(data: GeoEventsInput, response: Response, db: AsyncSession = Depends(get_db), context: DeviceContext = Depends(get_device)):
    response.headers["Cache-Control"] = "no-store"
    _apply_state(context.device, data.state)
    results = []
    for item in sorted(data.events, key=lambda event: event.occurred_at):
        event = await process_event(
            db, organization=context.organization, device=context.device, account=context.account, employee=context.employee,
            data=GeoEventInput(
                client_event_id=item.client_event_id, kind=item.kind, site_public_id=item.site_id, occurred_at=item.occurred_at,
                accuracy_meters=item.accuracy_meters, is_mock=item.is_mock, latitude=item.latitude, longitude=item.longitude,
            ),
        )
        results.append({"client_event_id": str(item.client_event_id), "result": event.result})
    await db.commit()
    return {"results": results, **await _device_payload(db, context)}


# ── Administration: settings ───────────────────────────────────────────────
@router.get("/settings/worktime-auto")
async def get_auto_settings(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    organization = await db.get(Organization, actor.organization_id)
    return auto_settings(organization.settings)


@router.put("/settings/worktime-auto")
async def update_auto_settings(data: AutoSettingsInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles("admin"))):
    organization = await db.get(Organization, actor.organization_id, with_for_update=True)
    before = auto_settings(organization.settings)
    methods = dict((organization.settings or {}).get(WORKTIME_METHODS_KEY) or {})
    methods.update(data.model_dump(exclude_none=True, exclude={"acknowledge_employer_disclaimer"}))
    if data.acknowledge_employer_disclaimer:
        methods["employer_disclaimer_ack"] = {
            "account_id": actor.account_id, "email": actor.email,
            "acknowledged_at": datetime.now(timezone.utc).isoformat(), "policy_version": POLICY_VERSION,
        }
    settings = {**(organization.settings or {}), WORKTIME_METHODS_KEY: methods}
    # Tracking location is the employer's decision and responsibility: it
    # cannot be switched on (even in shadow mode) without the acknowledgement.
    if auto_settings(settings)["auto_geofence_mode"] != "off" and not employer_ack_current(settings):
        raise HTTPException(status_code=409, detail={"code": "employer_disclaimer_required", "message": "Acknowledge the employer disclaimer first"})
    organization.settings = settings
    after = auto_settings(organization.settings)
    await record_change(db, actor=actor, topic="settings", aggregate_type="organization_worktime_auto", aggregate_id=organization.id, operation="updated", before=before, after=after)
    await db.commit()
    return after


# ── Administration: sites ──────────────────────────────────────────────────
@router.get("/worktime/sites")
async def list_sites(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles("admin", "manager", "hr", "team_lead"))):
    rows = (await db.execute(select(WorktimeSite).where(WorktimeSite.organization_id == actor.organization_id).order_by(WorktimeSite.id))).scalars().all()
    return [site_out(row) for row in rows]


async def _check_site_limit(db: AsyncSession, organization_id: int, *, excluding: int | None = None) -> None:
    query = select(func.count()).select_from(WorktimeSite).where(WorktimeSite.organization_id == organization_id, WorktimeSite.is_active.is_(True))
    if excluding is not None:
        query = query.where(WorktimeSite.id != excluding)
    if (await db.scalar(query) or 0) >= MAX_SITES_PER_DEVICE:
        raise HTTPException(status_code=409, detail={"code": "worktime_site_limit", "message": f"At most {MAX_SITES_PER_DEVICE} active sites"})


def _apply_site(site: WorktimeSite, data: SiteInput) -> None:
    site.name = data.name.strip()
    site.latitude, site.longitude, site.radius_meters = data.latitude, data.longitude, data.radius_meters
    site.is_active = data.is_active
    site.schedule_start, site.schedule_end = _parse_time(data.schedule_start), _parse_time(data.schedule_end)
    if (site.schedule_start is None) != (site.schedule_end is None):
        raise HTTPException(status_code=422, detail={"code": "worktime_site_schedule", "message": "Set both schedule times or neither"})


@router.post("/worktime/sites", status_code=status.HTTP_201_CREATED)
async def create_site(data: SiteInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles("admin"))):
    organization = await db.get(Organization, actor.organization_id, with_for_update=True)
    if data.is_active:
        await _check_site_limit(db, actor.organization_id)
    site = WorktimeSite(organization_id=actor.organization_id)
    _apply_site(site, data)
    db.add(site)
    await db.flush()
    await _sync_legacy_geofence(db, organization)
    await record_change(db, actor=actor, topic="settings", aggregate_type="worktime_site", aggregate_id=site.id, operation="created", after=site_out(site))
    await db.commit()
    return site_out(site)


async def _site(db: AsyncSession, actor: ActorContext, site_id: uuid.UUID) -> WorktimeSite:
    site = await db.scalar(select(WorktimeSite).where(WorktimeSite.public_id == site_id, WorktimeSite.organization_id == actor.organization_id).with_for_update())
    if site is None:
        raise HTTPException(status_code=404, detail={"code": "worktime_site_not_found", "message": "Site not found"})
    return site


@router.put("/worktime/sites/{site_id}")
async def update_site(site_id: uuid.UUID, data: SiteInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles("admin"))):
    organization = await db.get(Organization, actor.organization_id, with_for_update=True)
    site = await _site(db, actor, site_id)
    before = site_out(site)
    if data.is_active and not site.is_active:
        await _check_site_limit(db, actor.organization_id, excluding=site.id)
    _apply_site(site, data)
    await db.flush()
    await _sync_legacy_geofence(db, organization)
    await record_change(db, actor=actor, topic="settings", aggregate_type="worktime_site", aggregate_id=site.id, operation="updated", before=before, after=site_out(site))
    await db.commit()
    return site_out(site)


@router.delete("/worktime/sites/{site_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_site(site_id: uuid.UUID, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles("admin"))):
    organization = await db.get(Organization, actor.organization_id, with_for_update=True)
    site = await _site(db, actor, site_id)
    await record_change(db, actor=actor, topic="settings", aggregate_type="worktime_site", aggregate_id=site.id, operation="deleted", before=site_out(site))
    await db.delete(site)
    await db.flush()
    await _sync_legacy_geofence(db, organization)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Administration: devices and the event log (admin, HR) ──────────────────
@router.get("/worktime/auto/devices")
async def list_devices(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles(*LOCATION_EVENT_ROLES))):
    rows = (await db.execute(
        select(MobileDevice, UserAccount.email, Employee.name)
        .join(UserAccount, UserAccount.id == MobileDevice.account_id).outerjoin(Employee, Employee.id == UserAccount.employee_id)
        .where(MobileDevice.organization_id == actor.organization_id, MobileDevice.revoked_at.is_(None)).order_by(Employee.name, MobileDevice.id)
    )).all()
    return [{**_device_out(device), "email": email, "employee_name": name} for device, email, name in rows]


@router.delete("/worktime/auto/devices/{device_id}")
async def revoke_device(device_id: uuid.UUID, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles("admin"))):
    device = await db.scalar(select(MobileDevice).where(MobileDevice.public_id == device_id, MobileDevice.organization_id == actor.organization_id).with_for_update())
    if device is None:
        raise HTTPException(status_code=404, detail={"code": "device_not_found", "message": "Device not found"})
    await revoke_devices(db, [device])
    await record_change(db, actor=actor, topic="worktime", aggregate_type="mobile_device", aggregate_id=device.id, operation="revoked", after={"by": "admin"})
    await db.commit()
    return _device_out(device)


@router.get("/worktime/auto/events")
async def list_events(
    needs_review: bool | None = None,
    employee_id: int | None = None,
    cursor: int | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_roles(*LOCATION_EVENT_ROLES)),
):
    query = (
        select(WorktimeGeoEvent, WorktimeSite.name, Employee.name)
        .outerjoin(WorktimeSite, WorktimeSite.id == WorktimeGeoEvent.site_id).outerjoin(Employee, Employee.id == WorktimeGeoEvent.employee_id)
        .where(WorktimeGeoEvent.organization_id == actor.organization_id)
    )
    if needs_review is not None:
        query = query.where(WorktimeGeoEvent.needs_review.is_(needs_review))
    if employee_id is not None:
        query = query.where(WorktimeGeoEvent.employee_id == employee_id)
    if cursor is not None:
        query = query.where(WorktimeGeoEvent.id < cursor)
    rows = (await db.execute(query.order_by(WorktimeGeoEvent.id.desc()).limit(limit + 1))).all()
    page = rows[:limit]
    # Reading other people's location events is itself audited.
    await record_change(db, actor=actor, topic="worktime", aggregate_type="worktime_geo_events", aggregate_id=actor.organization_id, operation="viewed",
                        after={"needs_review": needs_review, "employee_id": employee_id, "count": len(page)})
    await db.commit()
    return {
        "items": [_event_out(event, site_name, employee_name) for event, site_name, employee_name in page],
        "next_cursor": page[-1][0].id if len(rows) > limit and page else None,
    }


@router.post("/worktime/auto/events/{event_id}/reviewed")
async def mark_event_reviewed(event_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles(*LOCATION_EVENT_ROLES))):
    event = await db.scalar(select(WorktimeGeoEvent).where(WorktimeGeoEvent.id == event_id, WorktimeGeoEvent.organization_id == actor.organization_id).with_for_update())
    if event is None:
        raise HTTPException(status_code=404, detail={"code": "geo_event_not_found", "message": "Event not found"})
    event.needs_review = False
    await record_change(db, actor=actor, topic="worktime", aggregate_type="worktime_geo_event", aggregate_id=event.id, operation="reviewed", after={"result": event.result})
    await db.commit()
    return _event_out(event)
