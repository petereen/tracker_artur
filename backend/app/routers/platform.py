"""Superadmin (operator) console API — ``/v1/platform``.

Operators are ``platform_operators`` rows with their own login and tokens
(``kind=platform``, separate signing key and audience): tenant accounts can
never call these endpoints and operator tokens never open a tenant workspace.
``support`` operators are read-only; ``superadmin`` may change state. The
console runs in the system context (no tenant bound) and every mutation is
written to ``platform_audit_logs``.
"""

from __future__ import annotations

import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import create_platform_access_token, decode_platform_access_token, hash_account_password, verify_account_password
from app.core.tenancy import TENANT_FEATURES, _csv, current_tenant_id, normalize_features, tenant_directory
from app.models.models import Organization, RefreshSession, RoleAssignment, UserAccount
from app.models.platform import PlatformAuditLog, PlatformOperator, SubscriptionPlan, TenantDomain, TenantLicense
from app.routers.tenant import license_status, license_view
from app.services import custom_domains, licensing
from app.services.licensing import LicenseError
from app.services.tenant_branding import BrandingInput, merge_branding, public_branding
from app.services.tenant_service import (
    CYCLE_MONTHS,
    SEAT_STATUSES,
    activate_license,
    add_months,
    audit,
    revoke_license,
    seat_clauses,
    seat_usage,
)

router = APIRouter()
platform_bearer = HTTPBearer(auto_error=False)

SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
HOSTNAME_RE = re.compile(r"^(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
BillingCycle = Literal["monthly", "quarterly", "yearly", "custom"]
MAX_FAILED_LOGINS = 5
LOCKOUT = timedelta(minutes=15)


# ── auth ────────────────────────────────────────────────────────────────────
async def get_operator(
    credentials: HTTPAuthorizationCredentials | None = Depends(platform_bearer),
    db: AsyncSession = Depends(get_db),
) -> PlatformOperator:
    if current_tenant_id() is not None:
        raise HTTPException(status_code=403, detail="Operator console is not available inside a tenant workspace")
    claims = decode_platform_access_token(credentials.credentials) if credentials else None
    if not claims:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Operator authentication required")
    operator = await db.get(PlatformOperator, int(claims["sub"]))
    if operator is None or operator.status != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Operator unavailable")
    return operator


async def require_superadmin(operator: PlatformOperator = Depends(get_operator)) -> PlatformOperator:
    if operator.role != "superadmin":
        raise HTTPException(status_code=403, detail="Superadmin role required")
    return operator


def _ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


class OperatorLogin(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        return value.strip().lower()


def operator_view(operator: PlatformOperator) -> dict:
    return {
        "id": operator.id,
        "email": operator.email,
        "display_name": operator.display_name,
        "role": operator.role,
        "status": operator.status,
        "last_login_at": operator.last_login_at,
        "created_at": operator.created_at,
    }


@router.post("/auth/login")
async def operator_login(data: OperatorLogin, request: Request, db: AsyncSession = Depends(get_db)):
    now = datetime.now(timezone.utc)
    operator = await db.scalar(select(PlatformOperator).where(func.lower(PlatformOperator.email) == data.email))
    if operator is None or operator.status != "active":
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if operator.locked_until and operator.locked_until > now:
        raise HTTPException(status_code=423, detail="Account is temporarily locked")
    valid, needs_rehash = verify_account_password(data.password, operator.password_hash)
    if not valid:
        operator.failed_login_count = (operator.failed_login_count or 0) + 1
        if operator.failed_login_count >= MAX_FAILED_LOGINS:
            operator.locked_until = now + LOCKOUT
        audit(db, "operator.login_failed", organization_id=None, operator_id=operator.id, ip_address=_ip(request))
        await db.commit()
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if needs_rehash:
        operator.password_hash = hash_account_password(data.password)
    operator.failed_login_count = 0
    operator.locked_until = None
    operator.last_login_at = now
    audit(db, "operator.login", organization_id=None, operator_id=operator.id, ip_address=_ip(request))
    await db.commit()
    return {
        "access_token": create_platform_access_token(operator.id, operator.role),
        "token_type": "bearer",
        "expires_in": settings.PLATFORM_ACCESS_TOKEN_MINUTES * 60,
        "operator": operator_view(operator),
    }


@router.get("/auth/me")
async def operator_me(operator: PlatformOperator = Depends(get_operator)):
    return operator_view(operator)


# ── catalog: features and plans ─────────────────────────────────────────────
@router.get("/features")
async def feature_catalog(_: PlatformOperator = Depends(get_operator)):
    return [{"code": code, "label": label} for code, label in TENANT_FEATURES.items()]


class PlanInput(BaseModel):
    code: str = Field(min_length=2, max_length=40, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    seat_limit: int | None = Field(default=None, ge=1, le=100000)
    features: list[str] = Field(default_factory=list)
    billing_cycle: BillingCycle = "monthly"
    price_amount: float | None = Field(default=None, ge=0)
    currency: str = Field(default="MNT", min_length=3, max_length=3)
    is_active: bool = True
    sort_order: int = 0


class PlanPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    seat_limit: int | None = Field(default=None, ge=1, le=100000)
    features: list[str] | None = None
    billing_cycle: BillingCycle | None = None
    price_amount: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    is_active: bool | None = None
    sort_order: int | None = None


def plan_view(plan: SubscriptionPlan) -> dict:
    return {
        "id": plan.id,
        "code": plan.code,
        "name": plan.name,
        "description": plan.description,
        "seat_limit": plan.seat_limit,
        "features": list(plan.features or []),
        "billing_cycle": plan.billing_cycle,
        "price_amount": float(plan.price_amount) if plan.price_amount is not None else None,
        "currency": plan.currency,
        "is_active": plan.is_active,
        "sort_order": plan.sort_order,
    }


@router.get("/plans")
async def list_plans(db: AsyncSession = Depends(get_db), _: PlatformOperator = Depends(get_operator)):
    plans = (await db.execute(select(SubscriptionPlan).order_by(SubscriptionPlan.sort_order, SubscriptionPlan.code))).scalars().all()
    return [plan_view(plan) for plan in plans]


@router.post("/plans", status_code=201)
async def create_plan(data: PlanInput, request: Request, db: AsyncSession = Depends(get_db), operator: PlatformOperator = Depends(require_superadmin)):
    if await db.scalar(select(SubscriptionPlan.id).where(SubscriptionPlan.code == data.code)):
        raise HTTPException(status_code=409, detail={"code": "plan_exists", "message": "Plan code already exists"})
    plan = SubscriptionPlan(**{**data.model_dump(), "features": normalize_features(data.features), "currency": data.currency.upper()})
    db.add(plan)
    audit(db, "plan.created", organization_id=None, operator_id=operator.id, target_type="plan", target_id=data.code, details=plan_view(plan), ip_address=_ip(request))
    await db.commit()
    return plan_view(plan)


@router.patch("/plans/{code}")
async def update_plan(code: str, data: PlanPatch, request: Request, db: AsyncSession = Depends(get_db), operator: PlatformOperator = Depends(require_superadmin)):
    plan = await db.scalar(select(SubscriptionPlan).where(SubscriptionPlan.code == code).with_for_update())
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan not found")
    patch = data.model_dump(exclude_unset=True)
    if "features" in patch:
        patch["features"] = normalize_features(patch["features"] or [])
    if patch.get("currency"):
        patch["currency"] = patch["currency"].upper()
    for key, value in patch.items():
        setattr(plan, key, value)
    audit(db, "plan.updated", organization_id=None, operator_id=operator.id, target_type="plan", target_id=code, details=patch, ip_address=_ip(request))
    await db.commit()
    return plan_view(plan)


# ── tenants ─────────────────────────────────────────────────────────────────
class LicenseIssueInput(BaseModel):
    plan_code: str | None = None
    seat_limit: int | None = Field(default=None, ge=1, le=100000)
    features: list[str] | None = None
    billing_cycle: BillingCycle | None = None
    valid_from: datetime | None = None
    expires_at: datetime | None = None
    duration_months: int | None = Field(default=None, ge=1, le=120)
    notes: str | None = Field(default=None, max_length=2000)
    activate: bool = False


class TenantAdminInput(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=10, max_length=128)

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        value = value.strip().lower()
        if any(char.isspace() for char in value):
            raise ValueError("A valid login is required")
        return value


def _slug(value: str) -> str:
    value = value.strip().lower()
    if not SLUG_RE.match(value):
        raise ValueError("Use 1–63 lowercase letters, digits and hyphens")
    if value in _csv(settings.TENANT_RESERVED_SUBDOMAINS):
        raise ValueError("This subdomain is reserved")
    return value


class TenantCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str
    plan_code: str | None = "starter"
    seat_limit: int | None = Field(default=None, ge=1, le=100000)
    features: list[str] | None = None
    billing_cycle: BillingCycle = "monthly"
    contact_email: str | None = Field(default=None, max_length=254)
    timezone: str = Field(default="Asia/Ulaanbaatar", max_length=64)
    base_currency: str = Field(default="MNT", min_length=3, max_length=3)
    admin: TenantAdminInput
    license: LicenseIssueInput | None = None
    branding: BrandingInput | None = None

    @field_validator("slug")
    @classmethod
    def _check_slug(cls, value: str) -> str:
        return _slug(value)


class TenantPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    plan_code: str | None = None
    seat_limit: int | None = Field(default=None, ge=0, le=100000)
    unlimited_seats: bool = False
    features: list[str] | None = None
    billing_cycle: BillingCycle | None = None
    contact_email: str | None = Field(default=None, max_length=254)
    license_required: bool | None = None
    branding: BrandingInput | None = None
    allow_below_usage: bool = False


class StatusChange(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


class TerminateInput(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)
    confirm_slug: str


class DomainInput(BaseModel):
    hostname: str
    # Provision through Cloudflare for SaaS when the platform has it configured.
    use_cloudflare: bool = True

    @field_validator("hostname")
    @classmethod
    def _hostname(cls, value: str) -> str:
        value = value.strip().lower().rstrip(".")
        if not HOSTNAME_RE.match(value):
            raise ValueError("A valid domain name is required")
        return value


async def _seat_counts(db: AsyncSession) -> dict[int, int]:
    rows = await db.execute(
        select(UserAccount.organization_id, func.count(UserAccount.id))
        .where(UserAccount.status.in_(SEAT_STATUSES), func.coalesce(UserAccount.preferences["system_agent"].astext, "") == "")
        .group_by(UserAccount.organization_id)
    )
    return {org_id: count for org_id, count in rows.all()}


def tenant_view(organization: Organization, seats_used: int) -> dict:
    return {
        "id": organization.id,
        "public_id": str(organization.public_id),
        "slug": organization.slug,
        "name": organization.name,
        "status": organization.status,
        "status_reason": organization.status_reason,
        "is_primary": organization.is_primary,
        "plan_code": organization.plan_code,
        "billing_cycle": organization.billing_cycle,
        "seat_limit": organization.seat_limit,
        "seats_used": seats_used,
        "features": normalize_features(organization.features),
        "license": license_status(organization),
        "license_required": organization.license_required,
        "contact_email": organization.contact_email,
        "branding": public_branding(organization),
        "hosts": _tenant_hosts(organization),
        "created_at": organization.created_at,
        "suspended_at": organization.suspended_at,
        "terminated_at": organization.terminated_at,
    }


def _tenant_hosts(organization: Organization) -> list[str]:
    base = settings.TENANT_BASE_DOMAIN.strip().lower().strip(".")
    return [f"{organization.slug}.{base}"] if base else []


async def _tenant(db: AsyncSession, tenant_id: int, *, lock: bool = False) -> Organization:
    organization = await db.get(Organization, tenant_id, with_for_update=lock)
    if organization is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return organization


async def _plan(db: AsyncSession, code: str | None) -> SubscriptionPlan | None:
    if not code:
        return None
    plan = await db.scalar(select(SubscriptionPlan).where(SubscriptionPlan.code == code))
    if plan is None:
        raise HTTPException(status_code=422, detail={"code": "unknown_plan", "message": f"Unknown plan '{code}'"})
    return plan


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _license_http_error(exc: LicenseError) -> HTTPException:
    status_code = 503 if exc.code in {"signing_unavailable", "verification_unavailable"} else 422
    return HTTPException(status_code=status_code, detail={"code": exc.code, "message": exc.message})


async def issue_license(
    db: AsyncSession,
    organization: Organization,
    data: LicenseIssueInput,
    operator: PlatformOperator,
    *,
    supersedes: TenantLicense | None = None,
    ip_address: str | None = None,
) -> TenantLicense:
    now = datetime.now(timezone.utc)
    plan = await _plan(db, data.plan_code or (supersedes.plan_code if supersedes else None) or organization.plan_code)
    seats = data.seat_limit or (supersedes.seat_limit if supersedes else None) or organization.seat_limit or (plan.seat_limit if plan else None)
    if not seats:
        raise HTTPException(status_code=422, detail={"code": "seat_limit_required", "message": "Set the seat count for this license"})
    if data.features is not None:
        features = normalize_features(data.features)
    elif supersedes is not None:
        features = normalize_features(supersedes.features)
    elif organization.features:
        features = normalize_features(organization.features)
    else:
        features = normalize_features(plan.features if plan else [])
    cycle = data.billing_cycle or (supersedes.billing_cycle if supersedes else None) or organization.billing_cycle
    valid_from = _aware(data.valid_from) or now
    if data.expires_at:
        expires_at = _aware(data.expires_at)
    else:
        # A renewal extends the previous term instead of restarting it.
        months = data.duration_months or CYCLE_MONTHS.get(cycle) or 12
        anchor = max(valid_from, supersedes.expires_at) if supersedes is not None else valid_from
        expires_at = add_months(anchor, months)
    if expires_at <= valid_from:
        raise HTTPException(status_code=422, detail={"code": "invalid_window", "message": "Expiry must be after the start date"})
    license_id = uuid.uuid4()
    try:
        token, key_id = licensing.issue_token(
            license_id=str(license_id),
            tenant_public_id=str(organization.public_id),
            tenant_slug=organization.slug,
            seats=seats,
            features=features,
            plan=plan.code if plan else None,
            billing_cycle=cycle,
            valid_from=valid_from,
            expires_at=expires_at,
            now=now,
        )
    except LicenseError as exc:
        raise _license_http_error(exc) from None
    row = TenantLicense(
        public_id=license_id,
        organization_id=organization.id,
        plan_code=plan.code if plan else None,
        seat_limit=seats,
        features=features,
        billing_cycle=cycle,
        valid_from=valid_from,
        expires_at=expires_at,
        status="issued",
        key_id=key_id,
        token=token,
        token_sha256=licensing.token_fingerprint(token),
        supersedes_id=supersedes.id if supersedes else None,
        notes=data.notes,
        issued_by_operator_id=operator.id,
        issued_at=now,
    )
    db.add(row)
    await db.flush()
    audit(db, "license.issued", organization_id=organization.id, operator_id=operator.id, target_type="tenant_license",
          target_id=str(license_id), details={"seats": seats, "features": features, "expires_at": expires_at.isoformat(),
                                              "supersedes": str(supersedes.public_id) if supersedes else None}, ip_address=ip_address)
    if data.activate:
        try:
            await activate_license(db, organization, token, operator_id=operator.id, now=now)
        except LicenseError as exc:
            raise _license_http_error(exc) from None
    return row


def license_admin_view(row: TenantLicense, *, include_token: bool = False) -> dict:
    view = {**license_view(row), "organization_id": row.organization_id, "notes": row.notes, "revoked_reason": row.revoked_reason,
            "supersedes_id": row.supersedes_id, "db_id": row.id}
    if include_token:
        view["token"] = row.token
    return view


@router.get("/tenants")
async def list_tenants(
    status_filter: str | None = Query(default=None, alias="status"),
    q: str | None = Query(default=None, max_length=120),
    db: AsyncSession = Depends(get_db),
    _: PlatformOperator = Depends(get_operator),
):
    query = select(Organization).order_by(Organization.is_primary.desc(), Organization.created_at.desc())
    if status_filter:
        query = query.where(Organization.status == status_filter)
    if q:
        pattern = f"%{q.strip()}%"
        query = query.where(Organization.name.ilike(pattern) | Organization.slug.ilike(pattern))
    organizations = (await db.execute(query)).scalars().all()
    counts = await _seat_counts(db)
    return [tenant_view(org, counts.get(org.id, 0)) for org in organizations]


@router.post("/tenants", status_code=201)
async def create_tenant(data: TenantCreate, request: Request, db: AsyncSession = Depends(get_db), operator: PlatformOperator = Depends(require_superadmin)):
    if await db.scalar(select(Organization.id).where(Organization.slug == data.slug)):
        raise HTTPException(status_code=409, detail={"code": "slug_taken", "message": "This workspace address is already used"})
    if await db.scalar(select(UserAccount.id).where(func.lower(UserAccount.email) == data.admin.email)):
        raise HTTPException(status_code=409, detail={"code": "admin_login_taken", "message": "This admin login already has an account"})
    plan = await _plan(db, data.plan_code)
    seat_limit = data.seat_limit or (plan.seat_limit if plan else None)
    features = normalize_features(data.features if data.features is not None else (plan.features if plan else []))
    branding = merge_branding({"display_name": data.name}, data.branding) if data.branding else {"display_name": data.name}
    organization = Organization(
        name=data.name.strip(),
        slug=data.slug,
        status="pending_activation",
        is_primary=False,
        plan_code=plan.code if plan else None,
        billing_cycle=data.billing_cycle,
        seat_limit=seat_limit,
        features=features,
        license_required=True,
        branding=branding,
        contact_email=data.contact_email,
        timezone=data.timezone,
        base_currency=data.base_currency.upper(),
        settings={},
    )
    db.add(organization)
    await db.flush()
    admin = UserAccount(
        organization_id=organization.id,
        email=data.admin.email,
        password_hash=hash_account_password(data.admin.password),
        status="active",
        locale="mn",
        must_change_password=True,
    )
    db.add(admin)
    await db.flush()
    db.add(RoleAssignment(account_id=admin.id, role="admin"))
    audit(db, "tenant.created", organization_id=organization.id, operator_id=operator.id, target_type="tenant", target_id=organization.id,
          details={"slug": organization.slug, "plan": organization.plan_code, "seat_limit": seat_limit, "features": features, "admin": admin.email},
          ip_address=_ip(request))
    issued = None
    if data.license is not None:
        issued = await issue_license(db, organization, data.license, operator, ip_address=_ip(request))
    await db.commit()
    tenant_directory.invalidate(organization.id)
    return {"tenant": tenant_view(organization, 1), "admin": {"id": admin.id, "email": admin.email},
            "license": license_admin_view(issued, include_token=True) if issued else None}


@router.get("/tenants/{tenant_id}")
async def get_tenant(tenant_id: int, db: AsyncSession = Depends(get_db), _: PlatformOperator = Depends(get_operator)):
    organization = await _tenant(db, tenant_id)
    usage = await seat_usage(db, organization.id)
    licenses = (await db.execute(select(TenantLicense).where(TenantLicense.organization_id == organization.id).order_by(TenantLicense.issued_at.desc()))).scalars().all()
    domains = (await db.execute(select(TenantDomain).where(TenantDomain.organization_id == organization.id).order_by(TenantDomain.hostname))).scalars().all()
    admins = (await db.execute(
        select(UserAccount.id, UserAccount.email, UserAccount.status, UserAccount.last_login_at)
        .join(RoleAssignment, RoleAssignment.account_id == UserAccount.id)
        .where(UserAccount.organization_id == organization.id, RoleAssignment.role == "admin")
        .order_by(UserAccount.email)
    )).all()
    events = (await db.execute(select(PlatformAuditLog).where(PlatformAuditLog.organization_id == organization.id).order_by(PlatformAuditLog.id.desc()).limit(50))).scalars().all()
    return {
        "tenant": tenant_view(organization, usage.used),
        "seats": usage.as_dict(),
        "licenses": [license_admin_view(row) for row in licenses],
        "domains": [{**custom_domains.domain_view(d), "verification_token": d.verification_token} for d in domains],
        "admins": [{"id": row.id, "email": row.email, "status": row.status, "last_login_at": row.last_login_at} for row in admins],
        "audit": [audit_view(event) for event in events],
    }


@router.patch("/tenants/{tenant_id}")
async def update_tenant(tenant_id: int, data: TenantPatch, request: Request, db: AsyncSession = Depends(get_db), operator: PlatformOperator = Depends(require_superadmin)):
    organization = await _tenant(db, tenant_id, lock=True)
    patch = data.model_dump(exclude_unset=True, exclude={"branding", "allow_below_usage", "unlimited_seats"})
    if "plan_code" in patch:
        plan = await _plan(db, patch["plan_code"])
        organization.plan_code = plan.code if plan else None
    if data.unlimited_seats:
        organization.seat_limit = None
    elif "seat_limit" in patch and patch["seat_limit"] is not None:
        usage = await seat_usage(db, organization.id, lock=True)
        if patch["seat_limit"] < usage.used and not data.allow_below_usage:
            raise HTTPException(status_code=409, detail={"code": "seats_below_usage", "message": f"{usage.used} seats are in use", "used": usage.used})
        organization.seat_limit = patch["seat_limit"]
    if "features" in patch and patch["features"] is not None:
        organization.features = normalize_features(patch["features"])
    for key in ("name", "billing_cycle", "contact_email", "license_required"):
        if key in patch and patch[key] is not None:
            setattr(organization, key, patch[key])
    if data.branding is not None:
        organization.branding = merge_branding(organization.branding, data.branding)
    audit(db, "tenant.updated", organization_id=organization.id, operator_id=operator.id, target_type="tenant", target_id=organization.id,
          details={**data.model_dump(exclude_unset=True, mode="json")}, ip_address=_ip(request))
    await db.commit()
    tenant_directory.invalidate(organization.id)
    return tenant_view(organization, (await seat_usage(db, organization.id)).used)


async def _revoke_sessions(db: AsyncSession, organization_id: int) -> None:
    now = datetime.now(timezone.utc)
    account_ids = select(UserAccount.id).where(UserAccount.organization_id == organization_id)
    await db.execute(update(RefreshSession).where(RefreshSession.account_id.in_(account_ids), RefreshSession.revoked_at.is_(None)).values(revoked_at=now))


@router.post("/tenants/{tenant_id}/suspend")
async def suspend_tenant(tenant_id: int, data: StatusChange, request: Request, db: AsyncSession = Depends(get_db), operator: PlatformOperator = Depends(require_superadmin)):
    organization = await _tenant(db, tenant_id, lock=True)
    if organization.status == "terminated":
        raise HTTPException(status_code=409, detail={"code": "tenant_terminated", "message": "Terminated tenants cannot be suspended"})
    organization.status = "suspended"
    organization.status_reason = data.reason
    organization.suspended_at = datetime.now(timezone.utc)
    await _revoke_sessions(db, organization.id)
    audit(db, "tenant.suspended", organization_id=organization.id, operator_id=operator.id, target_type="tenant", target_id=organization.id, details={"reason": data.reason}, ip_address=_ip(request))
    await db.commit()
    tenant_directory.invalidate(organization.id)
    return tenant_view(organization, (await seat_usage(db, organization.id)).used)


@router.post("/tenants/{tenant_id}/reactivate")
async def reactivate_tenant(tenant_id: int, data: StatusChange, request: Request, db: AsyncSession = Depends(get_db), operator: PlatformOperator = Depends(require_superadmin)):
    organization = await _tenant(db, tenant_id, lock=True)
    if organization.status == "terminated":
        raise HTTPException(status_code=409, detail={"code": "tenant_terminated", "message": "Terminated tenants cannot be reactivated"})
    has_license = await db.scalar(select(TenantLicense.id).where(TenantLicense.organization_id == organization.id, TenantLicense.status == "active"))
    organization.status = "active" if (has_license or not organization.license_required) else "pending_activation"
    organization.status_reason = data.reason
    organization.suspended_at = None
    audit(db, "tenant.reactivated", organization_id=organization.id, operator_id=operator.id, target_type="tenant", target_id=organization.id, details={"reason": data.reason}, ip_address=_ip(request))
    await db.commit()
    tenant_directory.invalidate(organization.id)
    return tenant_view(organization, (await seat_usage(db, organization.id)).used)


@router.post("/tenants/{tenant_id}/terminate")
async def terminate_tenant(tenant_id: int, data: TerminateInput, request: Request, db: AsyncSession = Depends(get_db), operator: PlatformOperator = Depends(require_superadmin)):
    organization = await _tenant(db, tenant_id, lock=True)
    if organization.is_primary:
        raise HTTPException(status_code=409, detail={"code": "primary_tenant", "message": "The primary tenant cannot be terminated"})
    if data.confirm_slug.strip().lower() != organization.slug:
        raise HTTPException(status_code=422, detail={"code": "confirmation_mismatch", "message": "Type the tenant slug to confirm"})
    now = datetime.now(timezone.utc)
    organization.status = "terminated"
    organization.status_reason = data.reason
    organization.terminated_at = now
    await db.execute(update(UserAccount).where(UserAccount.organization_id == organization.id, UserAccount.status != "disabled").values(status="disabled"))
    await _revoke_sessions(db, organization.id)
    active = await db.scalar(select(TenantLicense).where(TenantLicense.organization_id == organization.id, TenantLicense.status == "active").with_for_update())
    if active is not None:
        await revoke_license(db, active, operator_id=operator.id, reason=f"tenant terminated: {data.reason}", now=now)
    audit(db, "tenant.terminated", organization_id=organization.id, operator_id=operator.id, target_type="tenant", target_id=organization.id, details={"reason": data.reason}, ip_address=_ip(request))
    await db.commit()
    tenant_directory.invalidate(organization.id)
    return tenant_view(organization, 0)


@router.delete("/tenants/{tenant_id}", status_code=204)
async def purge_tenant(tenant_id: int, request: Request, confirm_slug: str = Query(...), db: AsyncSession = Depends(get_db), operator: PlatformOperator = Depends(require_superadmin)):
    """Permanently delete a terminated tenant and all of its data."""
    organization = await _tenant(db, tenant_id, lock=True)
    if organization.is_primary or organization.status != "terminated":
        raise HTTPException(status_code=409, detail={"code": "purge_not_allowed", "message": "Only a terminated, non-primary tenant can be purged"})
    if confirm_slug.strip().lower() != organization.slug:
        raise HTTPException(status_code=422, detail={"code": "confirmation_mismatch", "message": "Type the tenant slug to confirm"})
    audit(db, "tenant.purged", organization_id=None, operator_id=operator.id, target_type="tenant", target_id=organization.id,
          details={"slug": organization.slug, "name": organization.name}, ip_address=_ip(request))
    await db.delete(organization)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail={"code": "purge_blocked", "message": "Tenant data is still referenced; purge aborted"}) from None
    tenant_directory.invalidate(tenant_id)
    return Response(status_code=204)


# ── domains ─────────────────────────────────────────────────────────────────
@router.post("/tenants/{tenant_id}/domains", status_code=201)
async def add_domain(tenant_id: int, data: DomainInput, request: Request, db: AsyncSession = Depends(get_db), operator: PlatformOperator = Depends(require_superadmin)):
    organization = await _tenant(db, tenant_id)
    if data.hostname in _csv(settings.PLATFORM_ROOT_HOSTS) or data.hostname in _csv(settings.PLATFORM_CONSOLE_HOSTS):
        raise HTTPException(status_code=422, detail={"code": "reserved_host", "message": "This host is used by the platform"})
    if await db.scalar(select(TenantDomain.id).where(TenantDomain.hostname == data.hostname)):
        raise HTTPException(status_code=409, detail={"code": "domain_taken", "message": "Domain already mapped"})
    if data.use_cloudflare and custom_domains.cloudflare_configured():
        try:
            domain = await custom_domains.add_tenant_domain(db, organization.id, data.hostname, account_id=None)
        except custom_domains.DomainError as exc:
            await db.rollback()
            raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from None
    else:
        domain = TenantDomain(organization_id=organization.id, hostname=data.hostname, verification_token=f"oyuns-verify={secrets.token_urlsafe(24)}", dns_records=[])
        db.add(domain)
        await db.flush()
    audit(db, "domain.added", organization_id=organization.id, operator_id=operator.id, target_type="tenant_domain", target_id=data.hostname, ip_address=_ip(request))
    await db.commit()
    await db.refresh(domain)
    return {**custom_domains.domain_view(domain), "verification_token": domain.verification_token,
            "instructions": f"Add a DNS TXT record _oyuns.{domain.hostname} = {domain.verification_token} and CNAME {domain.hostname} to the platform host."}


@router.post("/tenants/{tenant_id}/domains/{domain_id}/verify")
async def verify_domain(tenant_id: int, domain_id: int, request: Request, db: AsyncSession = Depends(get_db), operator: PlatformOperator = Depends(require_superadmin)):
    domain = await db.get(TenantDomain, domain_id, with_for_update=True)
    if domain is None or domain.organization_id != tenant_id:
        raise HTTPException(status_code=404, detail="Domain not found")
    if domain.provider == custom_domains.PROVIDER_CLOUDFLARE:
        # Cloudflare domains are verified by their certificate, not by hand.
        try:
            await custom_domains.refresh_tenant_domain(domain)
        except custom_domains.DomainError as exc:
            raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from None
    else:
        domain.verified_at = datetime.now(timezone.utc)
        domain.status = "active"
    audit(db, "domain.verified", organization_id=tenant_id, operator_id=operator.id, target_type="tenant_domain", target_id=domain.hostname, ip_address=_ip(request))
    await db.commit()
    tenant_directory.invalidate(tenant_id)
    return custom_domains.domain_view(domain)


@router.delete("/tenants/{tenant_id}/domains/{domain_id}", status_code=204)
async def remove_domain(tenant_id: int, domain_id: int, request: Request, db: AsyncSession = Depends(get_db), operator: PlatformOperator = Depends(require_superadmin)):
    domain = await db.get(TenantDomain, domain_id)
    if domain is None or domain.organization_id != tenant_id:
        raise HTTPException(status_code=404, detail="Domain not found")
    audit(db, "domain.removed", organization_id=tenant_id, operator_id=operator.id, target_type="tenant_domain", target_id=domain.hostname, ip_address=_ip(request))
    try:
        await custom_domains.remove_tenant_domain(db, domain)
    except custom_domains.DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from None
    await db.commit()
    tenant_directory.invalidate(tenant_id)
    return Response(status_code=204)


# ── licenses ────────────────────────────────────────────────────────────────
class RevokeInput(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


async def _license(db: AsyncSession, public_id: str, *, lock: bool = False) -> TenantLicense:
    try:
        key = uuid.UUID(public_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="License not found") from None
    query = select(TenantLicense).where(TenantLicense.public_id == key)
    row = await db.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise HTTPException(status_code=404, detail="License not found")
    return row


@router.get("/licenses")
async def list_licenses(tenant_id: int | None = None, db: AsyncSession = Depends(get_db), _: PlatformOperator = Depends(get_operator)):
    query = select(TenantLicense).order_by(TenantLicense.issued_at.desc()).limit(500)
    if tenant_id is not None:
        query = query.where(TenantLicense.organization_id == tenant_id)
    return [license_admin_view(row) for row in (await db.execute(query)).scalars().all()]


@router.post("/tenants/{tenant_id}/licenses", status_code=201)
async def issue_tenant_license(tenant_id: int, data: LicenseIssueInput, request: Request, db: AsyncSession = Depends(get_db), operator: PlatformOperator = Depends(require_superadmin)):
    organization = await _tenant(db, tenant_id, lock=True)
    if organization.status == "terminated":
        raise HTTPException(status_code=409, detail={"code": "tenant_terminated", "message": "Terminated tenants cannot receive licenses"})
    row = await issue_license(db, organization, data, operator, ip_address=_ip(request))
    await db.commit()
    tenant_directory.invalidate(organization.id)
    return license_admin_view(row, include_token=True)


@router.get("/licenses/{public_id}")
async def get_license(public_id: str, db: AsyncSession = Depends(get_db), _: PlatformOperator = Depends(get_operator)):
    return license_admin_view(await _license(db, public_id), include_token=True)


@router.post("/licenses/{public_id}/renew", status_code=201)
async def renew_license(public_id: str, data: LicenseIssueInput, request: Request, db: AsyncSession = Depends(get_db), operator: PlatformOperator = Depends(require_superadmin)):
    """Issue a successor license (renewal, seat upgrade or module change)."""
    previous = await _license(db, public_id)
    if previous.status == "revoked":
        raise HTTPException(status_code=409, detail={"code": "revoked", "message": "A revoked license cannot be renewed"})
    organization = await _tenant(db, previous.organization_id, lock=True)
    row = await issue_license(db, organization, data, operator, supersedes=previous, ip_address=_ip(request))
    await db.commit()
    tenant_directory.invalidate(organization.id)
    return license_admin_view(row, include_token=True)


@router.post("/licenses/{public_id}/activate")
async def operator_activate_license(public_id: str, request: Request, db: AsyncSession = Depends(get_db), operator: PlatformOperator = Depends(require_superadmin)):
    row = await _license(db, public_id)
    organization = await _tenant(db, row.organization_id, lock=True)
    try:
        await activate_license(db, organization, row.token, operator_id=operator.id)
    except LicenseError as exc:
        await db.rollback()
        raise _license_http_error(exc) from None
    await db.commit()
    tenant_directory.invalidate(organization.id)
    return license_admin_view(row)


@router.post("/licenses/{public_id}/revoke")
async def revoke(public_id: str, data: RevokeInput, request: Request, db: AsyncSession = Depends(get_db), operator: PlatformOperator = Depends(require_superadmin)):
    row = await _license(db, public_id, lock=True)
    if row.status == "revoked":
        return license_admin_view(row)
    await revoke_license(db, row, operator_id=operator.id, reason=data.reason)
    await db.commit()
    tenant_directory.invalidate(row.organization_id)
    return license_admin_view(row)


# ── operators ───────────────────────────────────────────────────────────────
class OperatorCreate(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=128)
    display_name: str | None = Field(default=None, max_length=120)
    role: Literal["superadmin", "support"] = "support"

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        return value.strip().lower()


class OperatorPatch(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)
    role: Literal["superadmin", "support"] | None = None
    status: Literal["active", "disabled"] | None = None
    password: str | None = Field(default=None, min_length=12, max_length=128)


@router.get("/operators")
async def list_operators(db: AsyncSession = Depends(get_db), _: PlatformOperator = Depends(require_superadmin)):
    return [operator_view(row) for row in (await db.execute(select(PlatformOperator).order_by(PlatformOperator.email))).scalars().all()]


@router.post("/operators", status_code=201)
async def create_operator(data: OperatorCreate, request: Request, db: AsyncSession = Depends(get_db), operator: PlatformOperator = Depends(require_superadmin)):
    if await db.scalar(select(PlatformOperator.id).where(func.lower(PlatformOperator.email) == data.email)):
        raise HTTPException(status_code=409, detail={"code": "operator_exists", "message": "Operator already exists"})
    row = PlatformOperator(email=data.email, display_name=data.display_name, role=data.role, password_hash=hash_account_password(data.password))
    db.add(row)
    await db.flush()
    audit(db, "operator.created", organization_id=None, operator_id=operator.id, target_type="operator", target_id=row.id, details={"email": row.email, "role": row.role}, ip_address=_ip(request))
    await db.commit()
    return operator_view(row)


@router.patch("/operators/{operator_id}")
async def update_operator(operator_id: int, data: OperatorPatch, request: Request, db: AsyncSession = Depends(get_db), operator: PlatformOperator = Depends(require_superadmin)):
    row = await db.get(PlatformOperator, operator_id, with_for_update=True)
    if row is None:
        raise HTTPException(status_code=404, detail="Operator not found")
    if row.id == operator.id and (data.status == "disabled" or data.role == "support"):
        raise HTTPException(status_code=400, detail="You cannot demote or disable yourself")
    if data.display_name is not None:
        row.display_name = data.display_name
    if data.role is not None:
        row.role = data.role
    if data.status is not None:
        row.status = data.status
    if data.password:
        row.password_hash = hash_account_password(data.password)
        row.failed_login_count = 0
        row.locked_until = None
    audit(db, "operator.updated", organization_id=None, operator_id=operator.id, target_type="operator", target_id=row.id,
          details=data.model_dump(exclude_unset=True, exclude={"password"}), ip_address=_ip(request))
    await db.commit()
    return operator_view(row)


# ── audit and system health ─────────────────────────────────────────────────
def audit_view(event: PlatformAuditLog) -> dict:
    return {
        "id": event.id,
        "action": event.action,
        "operator_id": event.operator_id,
        "account_id": event.account_id,
        "organization_id": event.organization_id,
        "target_type": event.target_type,
        "target_id": event.target_id,
        "details": event.details or {},
        "ip_address": event.ip_address,
        "created_at": event.created_at,
    }


@router.get("/audit")
async def list_audit(tenant_id: int | None = None, limit: int = Query(default=100, ge=1, le=500), db: AsyncSession = Depends(get_db), _: PlatformOperator = Depends(get_operator)):
    query = select(PlatformAuditLog).order_by(PlatformAuditLog.id.desc()).limit(limit)
    if tenant_id is not None:
        query = query.where(PlatformAuditLog.organization_id == tenant_id)
    return [audit_view(event) for event in (await db.execute(query)).scalars().all()]


@router.get("/system")
async def system_status(db: AsyncSession = Depends(get_db), _: PlatformOperator = Depends(get_operator)):
    """Is isolation actually enforced? (RLS is void for superuser/BYPASSRLS roles.)"""
    rls: dict = {"available": False}
    try:
        role = (await db.execute(text("SELECT current_user, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"))).one()
        tables = (await db.execute(text(
            """
            SELECT count(*) FILTER (WHERE c.relrowsecurity AND c.relforcerowsecurity), count(*)
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relkind = 'r' AND n.nspname = current_schema()
              AND (c.relname = 'organizations' OR EXISTS (
                SELECT 1 FROM pg_attribute a WHERE a.attrelid = c.oid AND a.attname = 'organization_id' AND NOT a.attisdropped))
            """
        ))).one()
        strict = await db.scalar(text("SELECT current_setting('app.rls_strict', true)"))
        rls = {
            "available": True,
            "db_role": role[0],
            "superuser": bool(role[1]),
            "bypass_rls": bool(role[2]),
            "protected_tables": int(tables[0]),
            "tenant_tables": int(tables[1]),
            "strict": strict == "on",
            "effective": not role[1] and not role[2] and tables[0] == tables[1] and tables[1] > 0,
        }
    except Exception:  # pragma: no cover - non-PostgreSQL test databases
        rls = {"available": False}
    counts = dict((await db.execute(select(Organization.status, func.count()).group_by(Organization.status))).all())
    return {
        "rls": rls,
        "license_signing": {
            "available": licensing.signing_available(),
            "key_id": settings.LICENSE_SIGNING_KEY_ID,
            "public_key_pem": licensing.public_key_pem(),
            "grace_days": settings.LICENSE_GRACE_DAYS,
        },
        "tenants": counts,
        "routing": {
            "root_hosts": _csv(settings.PLATFORM_ROOT_HOSTS),
            "tenant_base_domain": settings.TENANT_BASE_DOMAIN or None,
            "unknown_host_policy": settings.TENANT_UNKNOWN_HOST_POLICY,
            "console_hosts": _csv(settings.PLATFORM_CONSOLE_HOSTS),
            "custom_domains": {
                "provider": "cloudflare" if custom_domains.cloudflare_configured() else None,
                "cname_target": custom_domains.cname_target() or None,
                "ssl_method": settings.CLOUDFLARE_SSL_METHOD,
                "limit_per_tenant": settings.TENANT_CUSTOM_DOMAIN_LIMIT,
            },
        },
    }


async def seed_platform_operator(db: AsyncSession) -> None:
    """Create the bootstrap superadmin when configured and none exists."""
    email = settings.PLATFORM_BOOTSTRAP_EMAIL.strip().lower()
    if not email or not settings.PLATFORM_BOOTSTRAP_PASSWORD:
        return
    if await db.scalar(select(func.count(PlatformOperator.id))):
        return
    db.add(PlatformOperator(email=email, display_name="Bootstrap superadmin", role="superadmin",
                            password_hash=hash_account_password(settings.PLATFORM_BOOTSTRAP_PASSWORD)))
    await db.commit()
