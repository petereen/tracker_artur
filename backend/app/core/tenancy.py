"""Tenant context for the OYUNS ERP SaaS (see docs/multi-tenancy.md).

Isolation model: one shared PostgreSQL schema, ``organization_id`` as the
tenant key. A request's tenant lives in a context variable and is enforced in
three independent layers:

1. application queries keep their explicit ``organization_id`` filters;
2. the ORM guard installed here refuses to load or flush a row of another
   tenant (fail loud instead of leaking);
3. every transaction publishes the tenant as ``app.tenant_id`` so PostgreSQL
   row-level security policies (``tenant_row_visible``) filter rows even for
   raw SQL and Core statements.

No tenant in context (bot, scheduler, migrations, the operator console) is the
*system context*: guards stay inactive and RLS stays permissive unless the
database runs with ``app.rls_strict = on``.
"""

from __future__ import annotations

import ipaddress
import logging
import time
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Iterator

from sqlalchemy import event, func, inspect as sa_inspect, select, text as sa_text
from sqlalchemy.orm import Session

from app.core.config import settings

log = logging.getLogger(__name__)

TENANT_SETTING = "app.tenant_id"

# ── Licensed feature modules ──────────────────────────────────────────────
# Everything not listed here is the always-on core workspace (people/HR,
# tasks, calendar, chat, worktime, reports, plans, files, accounting core).
TENANT_FEATURES: dict[str, str] = {
    "crm": "CRM — харилцагч ба харилцаа холбоо",
    "budget": "Төсөв, гүйцэтгэл",
    "payroll": "Цалин",
    "contracts": "Гэрээ ба гэрээний архив",
    "ai_assistant": "OYUNS AI туслах ба дуудлага",
    # Check-in surveys and legacy admin screens read tables that predate the
    # tenant key. They stay available to the primary tenant only.
    "legacy_workspace": "Legacy check-in / Telegram survey tools",
}
PRIMARY_ONLY_FEATURES = frozenset({"legacy_workspace"})

# (path prefix, feature). Matching respects path segment boundaries.
FEATURE_ROUTES: tuple[tuple[str, str], ...] = (
    ("/v1/erp/crm", "crm"),
    ("/v1/erp/budget", "budget"),
    ("/v1/erp/payroll", "payroll"),
    ("/v1/contracts", "contracts"),
    ("/v1/contract-archive", "contracts"),
    ("/v1/assistant", "ai_assistant"),
    ("/v1/settings/ai-agent", "ai_assistant"),
    ("/v1/report-insights/summary", "ai_assistant"),
    ("/questions", "legacy_workspace"),
    ("/schedules", "legacy_workspace"),
    ("/answers", "legacy_workspace"),
    ("/onboarding", "legacy_workspace"),
    ("/dashboard", "legacy_workspace"),
    ("/assistant-learning", "legacy_workspace"),
    ("/work-reports", "legacy_workspace"),
    ("/tasks", "legacy_workspace"),
    ("/auth", "legacy_workspace"),
)

# Reachable while a license is missing or expired, so an admin can activate.
LICENSE_EXEMPT_PREFIXES = ("/v1/auth", "/v1/tenant")
# Reachable even for suspended/terminated tenants (login page chrome only).
SUSPENSION_EXEMPT_PATHS = frozenset({"/v1/tenant/branding", "/v1/auth/capabilities", "/v1/auth/logout"})


def path_matches(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix.rstrip("/") + "/")


def feature_for_path(path: str) -> str | None:
    for prefix, feature in FEATURE_ROUTES:
        if path_matches(path, prefix):
            return feature
    return None


def normalize_features(values: Any) -> list[str]:
    """Keep known feature codes only, sorted and de-duplicated."""
    if not isinstance(values, (list, tuple, set, frozenset)):
        return []
    return sorted({str(value) for value in values if str(value) in TENANT_FEATURES})


# ── Context variable ──────────────────────────────────────────────────────
_current_tenant: ContextVar[int | None] = ContextVar("oyuns_tenant_id", default=None)


class TenantBoundaryViolation(RuntimeError):
    """A row of another tenant reached (or was about to leave) this request."""


def current_tenant_id() -> int | None:
    return _current_tenant.get()


def set_current_tenant(tenant_id: int | None) -> Token:
    return _current_tenant.set(tenant_id)


def reset_current_tenant(token: Token) -> None:
    _current_tenant.reset(token)


@contextmanager
def tenant_scope(tenant_id: int | None) -> Iterator[None]:
    """Run a block for one tenant (``None`` = system context)."""
    token = _current_tenant.set(tenant_id)
    try:
        yield
    finally:
        _current_tenant.reset(token)


# Declared system work (operator console, tenant lookups). With
# ``app.rls_strict = on`` only declared system work sees across tenants.
_system_context: ContextVar[bool] = ContextVar("oyuns_system_context", default=False)


@contextmanager
def system_scope() -> Iterator[None]:
    tenant_token = _current_tenant.set(None)
    system_token = _system_context.set(True)
    try:
        yield
    finally:
        _system_context.reset(system_token)
        _current_tenant.reset(tenant_token)


async def bind_tenant(db, tenant_id: int) -> None:
    """Pin the request (and the already-open transaction) to one tenant.

    Raises ``TenantBoundaryViolation`` if a different tenant is already bound:
    a request never switches tenants half-way.
    """
    previous = _current_tenant.get()
    if previous is not None and previous != tenant_id:
        raise TenantBoundaryViolation(f"request bound to tenant {previous}, not {tenant_id}")
    if previous == tenant_id:
        return
    _current_tenant.set(tenant_id)
    bind = getattr(db, "bind", None)
    if bind is not None and bind.dialect.name == "postgresql" and db.in_transaction():
        # ``after_begin`` already ran for this transaction without a tenant.
        await db.execute(select(func.set_config(TENANT_SETTING, str(tenant_id), True)))


# ── Session hooks: RLS setting + ORM guard ─────────────────────────────────
_TENANT_KEYS: dict[type, str | None] = {}


def _tenant_key(cls: type) -> str | None:
    """Column naming the owning tenant: ``organization_id`` or ``id`` (tenant row)."""
    if cls in _TENANT_KEYS:
        return _TENANT_KEYS[cls]
    key: str | None = None
    try:
        mapper = sa_inspect(cls)
        if getattr(mapper, "local_table", None) is not None and mapper.local_table.name == "organizations":
            key = "id"
        elif "organization_id" in mapper.columns:
            key = "organization_id"
    except Exception:  # pragma: no cover - unmapped helper classes
        key = None
    _TENANT_KEYS[cls] = key
    return key


def _apply_tenant_setting(session, transaction, connection) -> None:
    if connection.dialect.name != "postgresql":
        return
    tenant_id = _current_tenant.get()
    if tenant_id is not None:
        connection.execute(sa_text("SELECT set_config('app.tenant_id', :tenant_id, true)"), {"tenant_id": str(tenant_id)})
    elif _system_context.get():
        connection.execute(sa_text("SELECT set_config('app.system_context', 'on', true)"))


def _guard_loaded_instance(target, context) -> None:
    tenant_id = _current_tenant.get()
    if tenant_id is None:
        return
    key = _tenant_key(type(target))
    if key is None:
        return
    owner = target.__dict__.get(key)
    if owner is not None and owner != tenant_id:
        log.error("tenancy.cross_tenant_load model=%s owner=%s tenant=%s", type(target).__name__, owner, tenant_id)
        raise TenantBoundaryViolation(f"{type(target).__name__} of tenant {owner} loaded in tenant {tenant_id}")


def _guard_flush(session, flush_context, instances) -> None:
    tenant_id = _current_tenant.get()
    if tenant_id is None:
        return
    for obj in list(session.new):
        key = _tenant_key(type(obj))
        if key is None:
            continue
        if key == "id":
            raise TenantBoundaryViolation("tenants can only be created in the system context")
        owner = obj.__dict__.get(key)
        if owner is None:
            setattr(obj, key, tenant_id)
        elif owner != tenant_id:
            log.error("tenancy.cross_tenant_insert model=%s owner=%s tenant=%s", type(obj).__name__, owner, tenant_id)
            raise TenantBoundaryViolation(f"{type(obj).__name__} for tenant {owner} written in tenant {tenant_id}")
    for obj in list(session.dirty) + list(session.deleted):
        key = _tenant_key(type(obj))
        if key is None:
            continue
        state = sa_inspect(obj)
        history = state.attrs[key].history
        owners = {value for value in (*history.added, *history.deleted, *history.unchanged) if value is not None}
        if owners - {tenant_id}:
            log.error("tenancy.cross_tenant_write model=%s owners=%s tenant=%s", type(obj).__name__, sorted(owners), tenant_id)
            raise TenantBoundaryViolation(f"{type(obj).__name__} of another tenant modified in tenant {tenant_id}")


_guards_installed = False


def install_tenant_guards() -> None:
    """Register the session hooks once per process (idempotent)."""
    global _guards_installed
    if _guards_installed:
        return
    from app.core.database import Base

    event.listen(Session, "after_begin", _apply_tenant_setting)
    event.listen(Session, "before_flush", _guard_flush)
    event.listen(Base, "load", _guard_loaded_instance, propagate=True)
    _guards_installed = True


# ── Tenant runtime state ───────────────────────────────────────────────────
@dataclass(frozen=True)
class TenantState:
    id: int
    public_id: str
    slug: str
    name: str
    status: str
    is_primary: bool
    license_required: bool
    license_expires_at: datetime | None
    seat_limit: int | None
    features: frozenset[str]
    plan_code: str | None = None
    branding: dict = field(default_factory=dict, compare=False, hash=False)
    # Tenant setting: every session must pass a second factor (TOTP).
    two_factor_required: bool = False

    def has_feature(self, feature: str) -> bool:
        if feature in PRIMARY_ONLY_FEATURES and not self.is_primary:
            return False
        return feature in self.features

    def license_state(self, now: datetime | None = None) -> str:
        """``not_required`` | ``valid`` | ``grace`` | ``expired`` | ``missing``."""
        if not self.license_required:
            return "not_required"
        if self.license_expires_at is None:
            return "missing"
        now = now or datetime.now(timezone.utc)
        if now <= self.license_expires_at:
            return "valid"
        if now <= self.license_expires_at + timedelta(days=settings.LICENSE_GRACE_DAYS):
            return "grace"
        return "expired"


@dataclass(frozen=True)
class AccessDenial:
    status_code: int
    code: str
    message: str


def evaluate_tenant_access(state: TenantState, path: str, now: datetime | None = None) -> AccessDenial | None:
    """Decide whether a tenant request may proceed (status, license, feature)."""
    if state.status in {"suspended", "terminated"}:
        if path in SUSPENSION_EXEMPT_PATHS:
            return None
        if state.status == "terminated":
            return AccessDenial(403, "tenant_terminated", "Энэ байгууллагын эрх хаагдсан.")
        return AccessDenial(403, "tenant_suspended", "Байгууллагын эрх түр түдгэлзсэн. Үйлчилгээ үзүүлэгчтэй холбогдоно уу.")
    license_state = state.license_state(now)
    if license_state in {"missing", "expired"} and not any(path_matches(path, prefix) for prefix in LICENSE_EXEMPT_PREFIXES):
        code = "license_required" if license_state == "missing" else "license_expired"
        return AccessDenial(402, code, "Лицензийн түлхүүрээ идэвхжүүлнэ үү (Тохиргоо → Лиценз ба идэвхжүүлэлт).")
    feature = feature_for_path(path)
    if feature and not state.has_feature(feature):
        return AccessDenial(403, "feature_not_licensed", f"«{TENANT_FEATURES[feature]}» модуль таны багцад ороогүй байна.")
    return None


class TenantNotFound(LookupError):
    pass


def _csv(value: str) -> list[str]:
    return [item.strip().lower().strip(".") for item in (value or "").split(",") if item.strip()]


def classify_host(host: str | None) -> tuple[str, str | None]:
    """Return ``("root", None)``, ``("subdomain", slug)`` or ``("custom", hostname)``."""
    hostname = (host or "").strip().lower()
    if hostname.startswith("["):  # IPv6 literal
        hostname = hostname.split("]")[0].lstrip("[")
    else:
        hostname = hostname.split(":")[0]
    hostname = hostname.strip(".")
    if not hostname or hostname in _csv(settings.PLATFORM_ROOT_HOSTS):
        return "root", None
    try:
        ipaddress.ip_address(hostname)
        return "root", None
    except ValueError:
        pass
    base = settings.TENANT_BASE_DOMAIN.strip().lower().strip(".")
    if base:
        if hostname == base:
            return "root", None
        if hostname.endswith("." + base):
            label = hostname[: -len(base) - 1]
            if label in _csv(settings.TENANT_RESERVED_SUBDOMAINS):
                return "root", None
            return "subdomain", label
    return "custom", hostname


def client_ip_allowed(client_ip: str | None) -> bool:
    cidrs = _csv(settings.PLATFORM_ALLOWED_CIDRS)
    if not cidrs:
        return True
    try:
        address = ipaddress.ip_address((client_ip or "").strip())
    except ValueError:
        return False
    for cidr in cidrs:
        try:
            if address in ipaddress.ip_network(cidr, strict=False):
                return True
        except ValueError:
            log.warning("tenancy.bad_platform_cidr %s", cidr)
    return False


SECURITY_SETTINGS_KEY = "security"


def two_factor_setting(organization_settings) -> bool:
    """``organization.settings["security"]["two_factor_required"]`` (off by default)."""
    security = (organization_settings or {}).get(SECURITY_SETTINGS_KEY) if isinstance(organization_settings, dict) else None
    return bool(isinstance(security, dict) and security.get("two_factor_required"))


def state_from_organization(org) -> TenantState:
    return TenantState(
        id=org.id,
        public_id=str(org.public_id),
        slug=org.slug,
        name=org.name,
        status=org.status,
        is_primary=bool(org.is_primary),
        license_required=bool(org.license_required),
        license_expires_at=org.license_expires_at,
        seat_limit=org.seat_limit,
        features=frozenset(normalize_features(org.features)),
        plan_code=org.plan_code,
        branding=dict(org.branding or {}),
        two_factor_required=two_factor_setting(getattr(org, "settings", None)),
    )


class TenantDirectory:
    """TTL-cached tenant lookups used on every request (system context)."""

    def __init__(self, session_factory: Callable[[], Any] | None = None) -> None:
        self._session_factory = session_factory
        self._states: dict[int, tuple[float, TenantState | None]] = {}
        self._hosts: dict[str, tuple[float, int | None]] = {}
        self._primary: tuple[float, int | None] | None = None

    def _sessions(self):
        if self._session_factory is None:
            from app.core.database import AsyncSessionLocal

            self._session_factory = AsyncSessionLocal
        return self._session_factory()

    @staticmethod
    def _fresh(entry: tuple[float, Any] | None) -> bool:
        return entry is not None and time.monotonic() - entry[0] < settings.TENANT_CACHE_TTL_SECONDS

    async def _query(self, fn: Callable[[Any], Awaitable[Any]]):
        with system_scope():
            async with self._sessions() as db:
                return await fn(db)

    async def state(self, tenant_id: int) -> TenantState | None:
        entry = self._states.get(tenant_id)
        if self._fresh(entry):
            return entry[1]
        from app.models.models import Organization

        async def load(db):
            org = await db.get(Organization, tenant_id)
            return state_from_organization(org) if org else None

        value = await self._query(load)
        self._states[tenant_id] = (time.monotonic(), value)
        return value

    async def primary_id(self) -> int | None:
        if self._fresh(self._primary):
            return self._primary[1]
        from app.models.models import Organization

        async def load(db):
            primary = await db.scalar(select(Organization.id).where(Organization.is_primary.is_(True)))
            if primary is None:
                primary = await db.scalar(select(Organization.id).order_by(Organization.id).limit(1))
            return primary

        value = await self._query(load)
        self._primary = (time.monotonic(), value)
        return value

    async def resolve_host(self, host: str | None) -> int | None:
        """Tenant id for a request host; ``None`` for the shared root hosts."""
        kind, value = classify_host(host)
        if kind == "root" or value is None:
            return None
        cache_key = f"{kind}:{value}"
        entry = self._hosts.get(cache_key)
        if not self._fresh(entry):
            from app.models.models import Organization
            from app.models.platform import TenantDomain

            async def load(db):
                if kind == "subdomain":
                    return await db.scalar(select(Organization.id).where(Organization.slug == value))
                return await db.scalar(
                    select(TenantDomain.organization_id).where(TenantDomain.hostname == value, TenantDomain.verified_at.is_not(None))
                )

            entry = (time.monotonic(), await self._query(load))
            self._hosts[cache_key] = entry
        if entry[1] is None:
            if kind == "custom" and settings.TENANT_UNKNOWN_HOST_POLICY != "reject":
                return None
            raise TenantNotFound(value)
        return entry[1]

    def invalidate(self, tenant_id: int | None = None) -> None:
        if tenant_id is None:
            self._states.clear()
        else:
            self._states.pop(tenant_id, None)
        self._hosts.clear()
        self._primary = None


tenant_directory = TenantDirectory()
