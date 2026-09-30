"""Tenant subscription services: seat accounting and license lifecycle.

Seat rule: an account occupies a seat while its status is ``active``,
``invited`` or ``locked`` (a temporary lockout keeps the seat). Disabled
accounts and system agents (``preferences.system_agent``) are free.

Every path that creates or re-activates an account calls
``ensure_seat_available`` first; it locks the tenant row, so concurrent
invitations cannot both take the last seat. The database trigger
``enforce_tenant_seat_limit`` (migration ``b3c4d5e6f7a8``) is the backstop for
any path that forgets.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.tenancy import normalize_features, tenant_directory
from app.models.models import Organization, UserAccount
from app.models.platform import PlatformAuditLog, TenantLicense
from app.services.licensing import LicenseError, token_fingerprint, verify_token

SEAT_STATUSES = ("active", "invited", "locked")
SEAT_LIMIT_SQLSTATE = "OY001"


@dataclass(frozen=True)
class SeatUsage:
    used: int
    limit: int | None

    @property
    def unlimited(self) -> bool:
        return self.limit is None

    @property
    def available(self) -> int | None:
        return None if self.limit is None else max(self.limit - self.used, 0)

    def as_dict(self) -> dict:
        return {"used": self.used, "limit": self.limit, "available": self.available, "unlimited": self.unlimited}


def seat_clauses(organization_id: int) -> list:
    return [
        UserAccount.organization_id == organization_id,
        UserAccount.status.in_(SEAT_STATUSES),
        func.coalesce(UserAccount.preferences["system_agent"].astext, "") == "",
    ]


def account_consumes_seat(status: str | None, preferences: dict | None) -> bool:
    return status in SEAT_STATUSES and not (preferences or {}).get("system_agent")


def seat_limit_exception(usage: SeatUsage, needed: int = 1) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": "seat_limit_reached",
            "message": (
                f"Лицензийн хэрэглэгчийн хязгаар ({usage.limit}) дүүрсэн байна: {usage.used} идэвхтэй хэрэглэгч. "
                "Шинэ хэрэглэгч нэмэхийн тулд багцаа өргөтгөх эсвэл идэвхгүй хэрэглэгчийг хаана уу."
            ),
            "used": usage.used,
            "limit": usage.limit,
            "needed": needed,
        },
    )


async def seat_usage(db: AsyncSession, organization_id: int, *, lock: bool = False) -> SeatUsage:
    query = select(Organization.seat_limit).where(Organization.id == organization_id)
    limit = await db.scalar(query.with_for_update() if lock else query)
    used = await db.scalar(select(func.count(UserAccount.id)).where(*seat_clauses(organization_id))) or 0
    return SeatUsage(used=int(used), limit=limit)


async def ensure_seat_available(db: AsyncSession, organization_id: int, *, needed: int = 1) -> SeatUsage:
    """Reserve ``needed`` seats in this transaction or raise 409 ``seat_limit_reached``."""
    usage = await seat_usage(db, organization_id, lock=True)
    if usage.limit is not None and usage.used + needed > usage.limit:
        raise seat_limit_exception(usage, needed)
    return usage


def ensure_seat_available_sync(session: Session, organization_id: int, *, needed: int = 1) -> SeatUsage:
    """Synchronous variant for the Telegram bot's session."""
    limit = session.execute(
        select(Organization.seat_limit).where(Organization.id == organization_id).with_for_update()
    ).scalar_one_or_none()
    used = session.execute(select(func.count(UserAccount.id)).where(*seat_clauses(organization_id))).scalar_one() or 0
    usage = SeatUsage(used=int(used), limit=limit)
    if usage.limit is not None and usage.used + needed > usage.limit:
        raise seat_limit_exception(usage, needed)
    return usage


_IDENTITY_PROBE = "platform_identity_in_use(text,text,integer)"
_identity_function_available = False


async def identity_in_use(db: AsyncSession, kind: str, value: str, *, exclude_id: int | None = None) -> bool:
    """Platform-wide uniqueness probe (logins, worker e-mail, Telegram id).

    These identities are unique across *all* tenants, but row-level security
    only shows the caller's own tenant — a plain query would miss a clash and
    the insert would fail later. The SQL helper runs in the system context.
    """
    global _identity_function_available
    bind = getattr(db, "bind", None)
    if bind is not None and bind.dialect.name == "postgresql":
        if not _identity_function_available:
            _identity_function_available = bool(await db.scalar(select(func.to_regprocedure(_IDENTITY_PROBE).is_not(None))))
        if _identity_function_available:
            return bool(await db.scalar(select(func.platform_identity_in_use(kind, value, exclude_id))))
    if kind == "account_email":
        query = select(UserAccount.id).where(func.lower(UserAccount.email) == value.lower())
        model_id = UserAccount.id
    else:
        from app.models.models import Employee

        column = func.lower(Employee.email) if kind == "employee_email" else Employee.telegram_id
        query = select(Employee.id).where(column == (value.lower() if kind == "employee_email" else value))
        model_id = Employee.id
    if exclude_id is not None:
        query = query.where(model_id != exclude_id)
    return (await db.scalar(query.limit(1))) is not None


def is_seat_limit_error(exc: BaseException) -> bool:
    """True for the ``enforce_tenant_seat_limit`` trigger's error."""
    original = getattr(exc, "orig", exc)
    code = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
    return code == SEAT_LIMIT_SQLSTATE or "seat_limit_exceeded" in str(original)


# ── license lifecycle ──────────────────────────────────────────────────────
def add_months(value: datetime, months: int) -> datetime:
    month_index = value.month - 1 + months
    year, month = value.year + month_index // 12, month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


CYCLE_MONTHS = {"monthly": 1, "quarterly": 3, "yearly": 12}


def default_expiry(valid_from: datetime, billing_cycle: str) -> datetime | None:
    months = CYCLE_MONTHS.get(billing_cycle)
    return add_months(valid_from, months) if months else None


def apply_license(organization: Organization, license_row: TenantLicense) -> None:
    """Mirror the active license onto the tenant row used by gating/triggers."""
    organization.seat_limit = license_row.seat_limit
    organization.features = normalize_features(license_row.features)
    organization.license_expires_at = license_row.expires_at
    organization.plan_code = license_row.plan_code or organization.plan_code
    organization.billing_cycle = license_row.billing_cycle or organization.billing_cycle
    if organization.status == "pending_activation":
        organization.status = "active"


def audit(db: AsyncSession, action: str, *, organization_id: int | None, operator_id: int | None = None,
          account_id: int | None = None, target_type: str | None = None, target_id: str | int | None = None,
          details: dict | None = None, ip_address: str | None = None) -> None:
    db.add(PlatformAuditLog(
        operator_id=operator_id,
        account_id=account_id,
        organization_id=organization_id,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        details=details or {},
        ip_address=ip_address,
    ))


async def activate_license(
    db: AsyncSession,
    organization: Organization,
    token: str,
    *,
    account_id: int | None = None,
    operator_id: int | None = None,
    now: datetime | None = None,
) -> TenantLicense:
    """Verify ``token`` for ``organization`` and make it the active license.

    Raises ``LicenseError`` with a stable ``code`` for the UI. The caller
    commits; the tenant cache is invalidated here.
    """
    now = now or datetime.now(timezone.utc)
    claims = verify_token(token, now=now, expected_tenant=str(organization.public_id))
    license_row = await db.scalar(
        select(TenantLicense).where(TenantLicense.public_id == claims.license_id).with_for_update()
    )
    if license_row is None or license_row.organization_id != organization.id:
        raise LicenseError("unknown_license", "Энэ лиценз бүртгэлд олдсонгүй. Үйлчилгээ үзүүлэгчээс шинэ түлхүүр авна уу.")
    if license_row.token_sha256 != token_fingerprint(token):
        raise LicenseError("token_mismatch", "Лицензийн түлхүүр бүртгэлтэй таарахгүй байна.")
    if license_row.status == "revoked":
        raise LicenseError("revoked", "Энэ лицензийг цуцалсан байна.")
    if license_row.status == "superseded":
        raise LicenseError("superseded", "Энэ лицензийг шинэ лицензээр сольсон байна.")
    if license_row.status == "active":
        return license_row

    current = await db.scalar(
        select(TenantLicense)
        .where(TenantLicense.organization_id == organization.id, TenantLicense.status == "active")
        .with_for_update()
    )
    if current is not None and current.issued_at and license_row.issued_at and current.issued_at > license_row.issued_at:
        raise LicenseError("superseded", "Идэвхтэй лиценз энэ түлхүүрээс шинэ байна.")

    # Lock the tenant row so seat accounting and activation serialize.
    await db.execute(select(Organization.id).where(Organization.id == organization.id).with_for_update())
    usage = await seat_usage(db, organization.id)
    if usage.used > license_row.seat_limit:
        raise LicenseError(
            "seats_below_usage",
            f"Лиценз {license_row.seat_limit} хэрэглэгчийн эрхтэй, одоо {usage.used} идэвхтэй хэрэглэгч байна. "
            "Эхлээд илүү хэрэглэгчдийг идэвхгүй болгоно уу.",
        )

    if current is not None:
        # Flush first: at most one ``active`` row per tenant (partial index).
        current.status = "superseded"
        await db.flush()
    license_row.status = "active"
    license_row.activated_at = now
    license_row.activated_by_account_id = account_id
    license_row.activated_by_operator_id = operator_id
    await db.flush()
    apply_license(organization, license_row)
    audit(
        db,
        "license.activated",
        organization_id=organization.id,
        operator_id=operator_id,
        account_id=account_id,
        target_type="tenant_license",
        target_id=str(license_row.public_id),
        details={"seats": license_row.seat_limit, "features": list(license_row.features or []), "expires_at": license_row.expires_at.isoformat(), "superseded": str(current.public_id) if current else None},
    )
    tenant_directory.invalidate(organization.id)
    return license_row


async def revoke_license(db: AsyncSession, license_row: TenantLicense, *, operator_id: int | None, reason: str | None,
                         now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    was_active = license_row.status == "active"
    license_row.status = "revoked"
    license_row.revoked_at = now
    license_row.revoked_reason = (reason or "").strip() or None
    license_row.revoked_by_operator_id = operator_id
    if was_active:
        organization = await db.get(Organization, license_row.organization_id, with_for_update=True)
        if organization is not None:
            # Seats/features stay recorded; without a valid license the tenant
            # is limited to the activation screens until a new key is applied.
            organization.license_expires_at = None
    audit(db, "license.revoked", organization_id=license_row.organization_id, operator_id=operator_id,
          target_type="tenant_license", target_id=str(license_row.public_id), details={"reason": license_row.revoked_reason, "was_active": was_active})
    tenant_directory.invalidate(license_row.organization_id)


def translate_db_error(exc: DBAPIError) -> HTTPException | None:
    if is_seat_limit_error(exc):
        return HTTPException(status_code=409, detail={"code": "seat_limit_reached", "message": "Лицензийн хэрэглэгчийн хязгаар дүүрсэн байна."})
    return None
