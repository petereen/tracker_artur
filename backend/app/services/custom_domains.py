"""Tenant custom domains through Cloudflare for SaaS.

    erp.customer.mn ──CNAME──▶ CLOUDFLARE_CNAME_TARGET (proxied, SaaS zone)
                    ──Cloudflare edge (per-hostname certificate)──▶ fallback origin = this VPS

A tenant admin adds a hostname in Settings. The API registers it as a
Cloudflare *custom hostname*, shows the DNS records the customer has to
create, and polls Cloudflare (on demand and from the bot scheduler) until
both the hostname and its certificate are active. Only then ``verified_at``
is set, which is what the tenant middleware routes on (``tenant_domains``).

Operator-added ``manual`` domains keep working as before.
"""

from __future__ import annotations

import logging
import re
import secrets
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import func, select

from app.core.config import settings
from app.core.tenancy import classify_host, system_scope, tenant_directory

log = logging.getLogger(__name__)

CLOUDFLARE_API = "https://api.cloudflare.com/client/v4"
PROVIDER_CLOUDFLARE = "cloudflare"
PROVIDER_MANUAL = "manual"
HOSTNAME_RE = re.compile(r"^(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+(?:[a-z]{2,63}|xn--[a-z0-9-]{1,59})$")
# Cloudflare states after which a hostname no longer serves traffic.
DEAD_HOSTNAME_STATUSES = {"blocked", "moved", "deleted"}
FAILED_SSL_STATUSES = {"validation_timed_out", "issuance_timed_out", "deleted", "expired", "deployment_timed_out"}


class DomainError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def cloudflare_configured() -> bool:
    return bool(settings.CLOUDFLARE_API_TOKEN.strip() and settings.CLOUDFLARE_ZONE_ID.strip() and settings.CLOUDFLARE_CNAME_TARGET.strip())


def cname_target() -> str:
    return settings.CLOUDFLARE_CNAME_TARGET.strip().lower().rstrip(".")


def normalize_hostname(value: str) -> str:
    """Lower-case ASCII (punycode) hostname, or ``DomainError``."""
    value = (value or "").strip().lower()
    value = re.sub(r"^https?://", "", value).split("/")[0].split(":")[0].rstrip(".")
    try:
        value = value.encode("idna").decode("ascii")
    except UnicodeError:
        raise DomainError("invalid_hostname", "Домэйн нэр буруу байна.") from None
    if not HOSTNAME_RE.match(value):
        raise DomainError("invalid_hostname", "Домэйн нэр буруу байна (жишээ: erp.company.mn).")
    kind, _ = classify_host(value)
    if kind != "custom" or value == cname_target():
        raise DomainError("domain_reserved", "Энэ хаяг платформын хаяг тул өөрийн домэйнээр бүртгэх боломжгүй.", 409)
    return value


# ── Cloudflare API ─────────────────────────────────────────────────────────
async def _cloudflare(method: str, path: str, payload: dict | None = None, *, allow_missing: bool = False) -> dict | None:
    if not cloudflare_configured():
        raise DomainError("custom_domains_unavailable", "Өөрийн домэйн холбох үйлчилгээ платформ дээр тохируулагдаагүй байна.", 503)
    url = f"{CLOUDFLARE_API}/zones/{settings.CLOUDFLARE_ZONE_ID.strip()}{path}"
    headers = {"Authorization": f"Bearer {settings.CLOUDFLARE_API_TOKEN.strip()}"}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.request(method, url, json=payload, headers=headers)
    except httpx.HTTPError as exc:
        raise DomainError("cloudflare_unavailable", "Cloudflare-тай холбогдож чадсангүй. Дахин оролдоно уу.", 503) from exc
    if response.status_code == 404 and allow_missing:
        return None
    try:
        body = response.json()
    except ValueError:
        body = {}
    if not body.get("success"):
        errors = body.get("errors") or []
        message = "; ".join(str(error.get("message")) for error in errors if error.get("message")) or f"HTTP {response.status_code}"
        log.warning("cloudflare.request_failed %s %s: %s", method, path, message)
        if any(error.get("code") in {1406, 1414} or "duplicate" in str(error.get("message", "")).lower() for error in errors):
            raise DomainError("domain_taken", "Энэ домэйн Cloudflare дээр аль хэдийн бүртгэлтэй байна.", 409)
        if response.status_code in {400, 409, 422}:
            raise DomainError("cloudflare_rejected", f"Cloudflare хүлээн авсангүй: {message}", 422)
        raise DomainError("cloudflare_unavailable", f"Cloudflare алдаа: {message}", 502)
    return body.get("result") or {}


def _custom_hostname_payload(hostname: str) -> dict[str, Any]:
    method = settings.CLOUDFLARE_SSL_METHOD.strip().lower() or "http"
    payload: dict[str, Any] = {
        "hostname": hostname,
        "ssl": {"method": method if method in {"http", "txt"} else "http", "type": "dv", "settings": {"min_tls_version": "1.2"}},
    }
    if settings.CLOUDFLARE_CUSTOM_ORIGIN_SERVER.strip():
        payload["custom_origin_server"] = settings.CLOUDFLARE_CUSTOM_ORIGIN_SERVER.strip()
    if settings.CLOUDFLARE_CUSTOM_ORIGIN_SNI.strip():
        payload["custom_origin_sni"] = settings.CLOUDFLARE_CUSTOM_ORIGIN_SNI.strip()
    return payload


async def create_custom_hostname(hostname: str) -> dict:
    return await _cloudflare("POST", "/custom_hostnames", _custom_hostname_payload(hostname)) or {}


async def get_custom_hostname(hostname_id: str) -> dict | None:
    return await _cloudflare("GET", f"/custom_hostnames/{hostname_id}", allow_missing=True)


async def delete_custom_hostname(hostname_id: str) -> None:
    await _cloudflare("DELETE", f"/custom_hostnames/{hostname_id}", allow_missing=True)


# ── State mapping ───────────────────────────────────────────────────────────
def dns_records_for(hostname: str, result: dict) -> list[dict[str, str]]:
    """Records the customer creates at their DNS provider."""
    status = result.get("status")
    ssl = result.get("ssl") or {}
    records = [{"type": "CNAME", "name": hostname, "value": cname_target(), "purpose": "routing"}]
    ownership = result.get("ownership_verification") or {}
    if status != "active" and ownership.get("name") and ownership.get("value"):
        records.append({"type": str(ownership.get("type") or "txt").upper(), "name": ownership["name"], "value": ownership["value"], "purpose": "ownership"})
    if ssl.get("status") != "active":
        for record in ssl.get("validation_records") or []:
            if record.get("txt_name") and record.get("txt_value"):
                records.append({"type": "TXT", "name": record["txt_name"], "value": record["txt_value"], "purpose": "certificate"})
    return records


def apply_cloudflare_state(domain, result: dict | None, now: datetime | None = None) -> None:
    """Mirror a Cloudflare custom hostname onto ``tenant_domains``."""
    now = now or datetime.now(timezone.utc)
    domain.last_checked_at = now
    if result is None:
        # Deleted on Cloudflare: stop routing, keep the row for the admin.
        domain.status = "error"
        domain.ssl_status = None
        domain.verified_at = None
        domain.last_error = "Cloudflare дээр энэ домэйн олдсонгүй. Устгаад дахин нэмнэ үү."
        return
    domain.provider_hostname_id = result.get("id") or domain.provider_hostname_id
    status = result.get("status")
    ssl = result.get("ssl") or {}
    ssl_status = ssl.get("status")
    domain.ssl_status = ssl_status
    domain.dns_records = dns_records_for(domain.hostname, result)
    errors = [str(message) for message in (result.get("verification_errors") or []) if message]
    errors += [str(error.get("message")) for error in (ssl.get("validation_errors") or []) if isinstance(error, dict) and error.get("message")]
    domain.last_error = "; ".join(errors)[:1000] or None
    if status in DEAD_HOSTNAME_STATUSES:
        domain.status = "error"
        domain.verified_at = None
    elif status == "active" and ssl_status == "active":
        domain.status = "active"
        domain.verified_at = domain.verified_at or now
    elif domain.verified_at is not None and status == "active":
        # Certificate renewal in progress: keep serving the tenant.
        domain.status = "active"
    elif ssl_status in FAILED_SSL_STATUSES:
        domain.status = "error"
    else:
        domain.status = "pending"


def domain_view(domain) -> dict[str, Any]:
    return {
        "id": domain.id,
        "hostname": domain.hostname,
        "provider": domain.provider,
        "status": domain.status,
        "ssl_status": domain.ssl_status,
        "verified_at": domain.verified_at,
        "dns_records": list(domain.dns_records or []),
        "last_error": domain.last_error,
        "last_checked_at": domain.last_checked_at,
        "created_at": domain.created_at,
        "url": f"https://{domain.hostname}",
    }


# ── Tenant operations ───────────────────────────────────────────────────────
async def _hostname_owner(hostname: str) -> int | None:
    """Tenant already using ``hostname`` (row-level security hides others)."""
    from app.core.database import AsyncSessionLocal
    from app.models.platform import TenantDomain

    with system_scope():
        async with AsyncSessionLocal() as db:
            return await db.scalar(select(TenantDomain.organization_id).where(TenantDomain.hostname == hostname))


async def add_tenant_domain(db, organization_id: int, hostname: str, *, account_id: int | None):
    from app.models.platform import TenantDomain

    hostname = normalize_hostname(hostname)
    if not cloudflare_configured():
        raise DomainError("custom_domains_unavailable", "Өөрийн домэйн холбох үйлчилгээ платформ дээр тохируулагдаагүй байна.", 503)
    owner = await _hostname_owner(hostname)
    if owner is not None:
        raise DomainError("domain_taken", "Энэ домэйн аль хэдийн бүртгэлтэй байна.", 409)
    count = await db.scalar(select(func.count(TenantDomain.id)).where(TenantDomain.organization_id == organization_id))
    if count >= settings.TENANT_CUSTOM_DOMAIN_LIMIT:
        raise DomainError("domain_limit", f"Нэг байгууллага {settings.TENANT_CUSTOM_DOMAIN_LIMIT} хүртэл домэйн холбоно.", 409)
    result = await create_custom_hostname(hostname)
    domain = TenantDomain(
        organization_id=organization_id,
        hostname=hostname,
        verification_token=f"oyuns-verify={secrets.token_urlsafe(24)}",
        provider=PROVIDER_CLOUDFLARE,
        created_by_account_id=account_id,
        dns_records=[],
    )
    apply_cloudflare_state(domain, result)
    db.add(domain)
    try:
        await db.flush()
    except Exception:
        # Keep Cloudflare in step with the database.
        if domain.provider_hostname_id:
            try:
                await delete_custom_hostname(domain.provider_hostname_id)
            except DomainError:
                log.warning("cloudflare.cleanup_failed %s", hostname)
        raise
    tenant_directory.invalidate(organization_id)
    return domain


async def refresh_tenant_domain(domain) -> None:
    if domain.provider != PROVIDER_CLOUDFLARE or not domain.provider_hostname_id:
        return
    was_verified = domain.verified_at is not None
    apply_cloudflare_state(domain, await get_custom_hostname(domain.provider_hostname_id))
    if was_verified != (domain.verified_at is not None):
        tenant_directory.invalidate(domain.organization_id)


async def remove_tenant_domain(db, domain) -> None:
    if domain.provider == PROVIDER_CLOUDFLARE and domain.provider_hostname_id:
        await delete_custom_hostname(domain.provider_hostname_id)
    organization_id = domain.organization_id
    await db.delete(domain)
    tenant_directory.invalidate(organization_id)


async def refresh_pending_domains() -> None:
    """Scheduler job: advance Cloudflare domains that wait for DNS/certificates."""
    if not cloudflare_configured():
        return
    from app.core.database import AsyncSessionLocal
    from app.models.platform import TenantDomain

    with system_scope():
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(
                select(TenantDomain).where(TenantDomain.provider == PROVIDER_CLOUDFLARE, TenantDomain.status == "pending").limit(50)
            )).scalars().all()
            for domain in rows:
                try:
                    await refresh_tenant_domain(domain)
                except DomainError as exc:
                    log.warning("custom_domains.refresh_failed %s: %s", domain.hostname, exc.message)
            await db.commit()
