"""Tenant workspace endpoints: context, license activation, seats, branding.

Mounted at ``/v1/tenant``. These paths stay reachable while a tenant has no
valid license (see ``LICENSE_EXEMPT_PREFIXES``) so an administrator can paste
a new activation token; ``/v1/tenant/branding`` is public for the login page.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.enterprise_deps import ActorContext, get_account_actor, require_roles
from app.core.tenancy import (
    PRIMARY_ONLY_FEATURES,
    TENANT_FEATURES,
    current_tenant_id,
    state_from_organization,
    tenant_directory,
)
from app.models.models import Organization
from app.models.platform import TenantLicense
from app.services.enterprise_events import record_change
from app.services.licensing import LicenseError, verify_token
from app.services.tenant_branding import BrandingInput, editable_branding, merge_branding, public_branding
from app.services.tenant_service import activate_license, seat_usage

router = APIRouter()


async def require_tenant_admin(actor: ActorContext = Depends(get_account_actor)) -> ActorContext:
    """Tenant admin by granted role: the personal workspace mode must not
    lock an administrator out of license activation."""
    if "admin" not in actor.granted_roles:
        raise HTTPException(status_code=403, detail="Insufficient permission")
    return actor


class LicenseTokenInput(BaseModel):
    token: str = Field(min_length=20, max_length=8192)


def license_error(exc: LicenseError, status_code: int = 422) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": exc.code, "message": exc.message})


def license_view(row: TenantLicense | None) -> dict | None:
    if row is None:
        return None
    return {
        "id": str(row.public_id),
        "status": row.status,
        "plan_code": row.plan_code,
        "seat_limit": row.seat_limit,
        "features": list(row.features or []),
        "billing_cycle": row.billing_cycle,
        "valid_from": row.valid_from,
        "expires_at": row.expires_at,
        "issued_at": row.issued_at,
        "activated_at": row.activated_at,
        "revoked_at": row.revoked_at,
        "key_id": row.key_id,
    }


def license_status(organization: Organization, now: datetime | None = None) -> dict:
    state = state_from_organization(organization)
    now = now or datetime.now(timezone.utc)
    expires = organization.license_expires_at
    return {
        "required": bool(organization.license_required),
        "state": state.license_state(now),
        "expires_at": expires,
        "grace_ends_at": expires + timedelta(days=settings.LICENSE_GRACE_DAYS) if expires else None,
        "days_left": (expires - now).days if expires else None,
    }


def feature_view(organization: Organization) -> list[dict]:
    state = state_from_organization(organization)
    return [
        {"code": code, "label": label, "enabled": state.has_feature(code), "primary_only": code in PRIMARY_ONLY_FEATURES}
        for code, label in TENANT_FEATURES.items()
    ]


async def _organization(db: AsyncSession, organization_id: int, *, lock: bool = False) -> Organization:
    organization = await db.get(Organization, organization_id, with_for_update=lock)
    if organization is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return organization


@router.get("/branding")
async def get_public_branding(request: Request, db: AsyncSession = Depends(get_db)):
    """Branding of the tenant this host/session resolves to (public)."""
    tenant_id = current_tenant_id() or await tenant_directory.primary_id()
    organization = await db.get(Organization, tenant_id) if tenant_id else None
    if organization is None:
        return {"slug": None, "name": "OYUNS ERP", "logo_url": "/favicon.png", "dark_logo_url": "/oyuns-aio-logo.png",
                "favicon_url": "/favicon.png", "primary_color": None, "secondary_color": None}
    return public_branding(organization)


@router.get("/context")
async def get_tenant_context(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_account_actor)):
    organization = await _organization(db, actor.organization_id)
    payload = {
        "slug": organization.slug,
        "name": organization.name,
        "status": organization.status,
        "is_primary": organization.is_primary,
        "plan_code": organization.plan_code,
        "billing_cycle": organization.billing_cycle,
        "features": feature_view(organization),
        "license": license_status(organization),
        "branding": public_branding(organization),
    }
    if "admin" in actor.granted_roles:
        payload["seats"] = (await seat_usage(db, organization.id)).as_dict()
    return payload


@router.get("/license")
async def get_license(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_tenant_admin)):
    organization = await _organization(db, actor.organization_id)
    rows = (await db.execute(
        select(TenantLicense).where(TenantLicense.organization_id == organization.id).order_by(TenantLicense.issued_at.desc()).limit(20)
    )).scalars().all()
    active = next((row for row in rows if row.status == "active"), None)
    return {
        "tenant": {"slug": organization.slug, "name": organization.name, "status": organization.status, "public_id": str(organization.public_id)},
        "license": license_status(organization),
        "active": license_view(active),
        "history": [license_view(row) for row in rows],
        "seats": (await seat_usage(db, organization.id)).as_dict(),
        "features": feature_view(organization),
        "plan_code": organization.plan_code,
        "billing_cycle": organization.billing_cycle,
    }


@router.post("/license/verify")
async def verify_license(data: LicenseTokenInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_tenant_admin)):
    """Check a token without activating it (preview seats, modules, expiry)."""
    organization = await _organization(db, actor.organization_id)
    try:
        claims = verify_token(data.token, expected_tenant=str(organization.public_id))
    except LicenseError as exc:
        raise license_error(exc) from None
    usage = await seat_usage(db, organization.id)
    return {
        "valid": True,
        "claims": claims.as_dict(),
        "seats": usage.as_dict(),
        "fits_current_usage": usage.used <= claims.seats,
        "feature_labels": {code: TENANT_FEATURES[code] for code in claims.features},
    }


@router.post("/license/activate")
async def activate(data: LicenseTokenInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_tenant_admin)):
    organization = await _organization(db, actor.organization_id, lock=True)
    if organization.status in {"suspended", "terminated"}:
        raise HTTPException(status_code=403, detail={"code": f"tenant_{organization.status}", "message": "Workspace is not active"})
    try:
        row = await activate_license(db, organization, data.token, account_id=actor.account_id)
    except LicenseError as exc:
        await db.rollback()
        raise license_error(exc) from None
    await record_change(db, actor=actor, topic="settings", aggregate_type="tenant_license", aggregate_id=organization.id,
                        operation="activated", after={"license_id": str(row.public_id), "seats": row.seat_limit, "expires_at": row.expires_at.isoformat()})
    await db.commit()
    tenant_directory.invalidate(organization.id)
    return {"license": license_status(organization), "active": license_view(row), "seats": (await seat_usage(db, organization.id)).as_dict()}


@router.get("/seats")
async def get_seats(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_tenant_admin)):
    return (await seat_usage(db, actor.organization_id)).as_dict()


@router.get("/branding/settings")
async def get_branding_settings(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles("admin", "manager"))):
    organization = await _organization(db, actor.organization_id)
    return {"branding": editable_branding(organization), "preview": public_branding(organization)}


@router.put("/branding/settings")
async def update_branding_settings(data: BrandingInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_roles("admin"))):
    organization = await _organization(db, actor.organization_id, lock=True)
    organization.branding = merge_branding(organization.branding, data)
    await record_change(db, actor=actor, topic="settings", aggregate_type="organization_branding", aggregate_id=organization.id,
                        operation="updated", after=editable_branding(organization))
    await db.commit()
    tenant_directory.invalidate(organization.id)
    return {"branding": editable_branding(organization), "preview": public_branding(organization)}
