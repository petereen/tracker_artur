"""Tenant workspace endpoints: context, license activation, seats, branding,
the tenant's Telegram bot and its custom domains.

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
from app.models.platform import TenantDomain, TenantLicense, TenantTelegramBot
from app.services.enterprise_events import record_change
from app.services.licensing import LicenseError, verify_token
from app.services.tenant_branding import BrandingInput, editable_branding, merge_branding, public_branding
from app.services.tenant_service import activate_license, seat_usage
from app.services import custom_domains, telegram_bots

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
    # Worker forms enable the Telegram ID field only when a bot can reach them.
    payload["telegram_bot_connected"] = await telegram_bots.organization_has_bot(db, organization.id)
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


async def require_worker_manager(actor: ActorContext = Depends(get_account_actor)) -> ActorContext:
    """Admins and HR add workers, so both see how many seats remain."""
    if not {"admin", "hr"} & set(actor.granted_roles):
        raise HTTPException(status_code=403, detail="Insufficient permission")
    return actor


@router.get("/seats")
async def get_seats(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_worker_manager)):
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


# ── Telegram bot (per tenant) ────────────────────────────────────────────────
class TelegramBotTokenInput(BaseModel):
    token: str = Field(min_length=20, max_length=200)


def telegram_bot_error(exc: telegram_bots.TelegramBotError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message})


async def telegram_bot_view(db: AsyncSession, organization: Organization) -> dict:
    row = await db.scalar(select(TenantTelegramBot).where(TenantTelegramBot.organization_id == organization.id))
    now = datetime.now(timezone.utc)
    if row is None:
        if organization.is_primary and telegram_bots.platform_bot_token():
            identity = await telegram_bots.platform_bot_identity()
            return {
                "connected": True, "source": "platform", "status": "active",
                "bot_id": telegram_bots.token_bot_id(telegram_bots.platform_bot_token()),
                "bot_username": identity.username if identity else None,
                "bot_name": identity.name if identity else None,
                "handshake_url": None, "handshake_expires_at": None, "handshake_completed_at": None,
                "last_seen_at": None, "online": None, "last_error": None, "connected_at": None,
            }
        return {"connected": False, "source": None, "status": "not_connected"}
    code = telegram_bots.read_handshake_code(row) if row.status == "pending" else None
    return {
        "connected": row.status == "active",
        "source": "tenant",
        "status": row.status,
        "bot_id": row.bot_id,
        "bot_username": row.bot_username,
        "bot_name": row.bot_name,
        "handshake_url": telegram_bots.handshake_url(row.bot_username, code) if code else None,
        "handshake_expires_at": row.handshake_expires_at,
        "handshake_completed_at": row.handshake_completed_at,
        "last_seen_at": row.last_seen_at,
        "online": bool(row.last_seen_at and now - row.last_seen_at < telegram_bots.ONLINE_WINDOW),
        "last_error": row.last_error,
        "connected_at": row.created_at,
    }


@router.get("/telegram-bot")
async def get_telegram_bot(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_tenant_admin)):
    return await telegram_bot_view(db, await _organization(db, actor.organization_id))


@router.put("/telegram-bot")
async def connect_telegram_bot(data: TelegramBotTokenInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_tenant_admin)):
    """Step 1 of the handshake: verify the BotFather token and store it."""
    organization = await _organization(db, actor.organization_id, lock=True)
    try:
        row = await telegram_bots.connect_tenant_bot(db, organization, data.token, account_id=actor.account_id)
    except telegram_bots.TelegramBotError as exc:
        await db.rollback()
        raise telegram_bot_error(exc) from None
    await record_change(db, actor=actor, topic="settings", aggregate_type="telegram_bot", aggregate_id=organization.id,
                        operation="connected", after={"bot_id": row.bot_id, "bot_username": row.bot_username})
    await db.commit()
    return await telegram_bot_view(db, organization)


@router.post("/telegram-bot/handshake")
async def renew_telegram_handshake(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_tenant_admin)):
    """New one-time ``/start`` link while the bot waits for its handshake."""
    organization = await _organization(db, actor.organization_id)
    row = await db.scalar(select(TenantTelegramBot).where(TenantTelegramBot.organization_id == organization.id).with_for_update())
    if row is None or row.status != "pending":
        raise HTTPException(status_code=409, detail={"code": "handshake_not_pending", "message": "Бот холболтын баталгаажуулалт хүлээгээгүй байна."})
    telegram_bots.issue_handshake(row)
    await db.commit()
    return await telegram_bot_view(db, organization)


@router.delete("/telegram-bot")
async def disconnect_telegram_bot(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_tenant_admin)):
    organization = await _organization(db, actor.organization_id)
    row = await db.scalar(select(TenantTelegramBot).where(TenantTelegramBot.organization_id == organization.id))
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "telegram_bot_not_connected", "message": "Telegram бот холбогдоогүй байна."})
    await record_change(db, actor=actor, topic="settings", aggregate_type="telegram_bot", aggregate_id=organization.id,
                        operation="disconnected", before={"bot_id": row.bot_id, "bot_username": row.bot_username})
    await db.delete(row)
    await db.commit()
    telegram_bots.registry.invalidate()
    return await telegram_bot_view(db, organization)


# ── Custom domains (Cloudflare for SaaS) ────────────────────────────────────
class DomainInput(BaseModel):
    hostname: str = Field(min_length=4, max_length=253)


def domain_error(exc: custom_domains.DomainError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message})


async def _tenant_domain(db: AsyncSession, organization_id: int, domain_id: int, *, lock: bool = False) -> TenantDomain:
    query = select(TenantDomain).where(TenantDomain.id == domain_id, TenantDomain.organization_id == organization_id)
    domain = await db.scalar(query.with_for_update() if lock else query)
    if domain is None:
        raise HTTPException(status_code=404, detail={"code": "domain_not_found", "message": "Домэйн олдсонгүй."})
    return domain


async def domains_view(db: AsyncSession, organization: Organization) -> dict:
    rows = (await db.execute(
        select(TenantDomain).where(TenantDomain.organization_id == organization.id).order_by(TenantDomain.created_at, TenantDomain.id)
    )).scalars().all()
    base = settings.TENANT_BASE_DOMAIN.strip().strip(".")
    return {
        "available": custom_domains.cloudflare_configured(),
        "cname_target": custom_domains.cname_target() or None,
        "limit": settings.TENANT_CUSTOM_DOMAIN_LIMIT,
        "platform_url": f"https://{organization.slug}.{base}" if base and not organization.is_primary else settings.PUBLIC_APP_URL.rstrip("/"),
        "domains": [custom_domains.domain_view(row) for row in rows],
    }


@router.get("/domains")
async def list_domains(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_tenant_admin)):
    return await domains_view(db, await _organization(db, actor.organization_id))


@router.post("/domains", status_code=201)
async def add_domain(data: DomainInput, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_tenant_admin)):
    organization = await _organization(db, actor.organization_id, lock=True)
    try:
        domain = await custom_domains.add_tenant_domain(db, organization.id, data.hostname, account_id=actor.account_id)
    except custom_domains.DomainError as exc:
        await db.rollback()
        raise domain_error(exc) from None
    await record_change(db, actor=actor, topic="settings", aggregate_type="tenant_domain", aggregate_id=domain.id,
                        operation="created", after={"hostname": domain.hostname, "provider": domain.provider})
    await db.commit()
    await db.refresh(domain)
    return custom_domains.domain_view(domain)


@router.post("/domains/{domain_id}/refresh")
async def refresh_domain(domain_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_tenant_admin)):
    domain = await _tenant_domain(db, actor.organization_id, domain_id, lock=True)
    try:
        await custom_domains.refresh_tenant_domain(domain)
    except custom_domains.DomainError as exc:
        await db.rollback()
        raise domain_error(exc) from None
    await db.commit()
    return custom_domains.domain_view(domain)


@router.delete("/domains/{domain_id}", status_code=204)
async def delete_domain(domain_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_tenant_admin)):
    domain = await _tenant_domain(db, actor.organization_id, domain_id, lock=True)
    hostname = domain.hostname
    try:
        await custom_domains.remove_tenant_domain(db, domain)
    except custom_domains.DomainError as exc:
        await db.rollback()
        raise domain_error(exc) from None
    await record_change(db, actor=actor, topic="settings", aggregate_type="tenant_domain", aggregate_id=domain_id,
                        operation="deleted", before={"hostname": hostname})
    await db.commit()
