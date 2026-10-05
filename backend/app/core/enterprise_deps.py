from dataclasses import dataclass, replace
from datetime import date
from typing import Callable

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decode_token
from app.core.tenancy import TenantBoundaryViolation, bind_tenant, current_tenant_id, tenant_directory
from app.models.models import Employee, ERPAccessRole, ERPAccountRole, ERPTeamRole, RoleAssignment, TeamMember, UserAccount
from app.services.file_search_service import FileSearchPrincipal


bearer = HTTPBearer()


@dataclass(frozen=True)
class ActorContext:
    account_id: int
    organization_id: int
    employee_id: int | None
    email: str
    locale: str
    roles: frozenset[str]
    # These fields are derived by trusted server code.  They are deliberately
    # optional for compatibility with existing dependency/test constructors.
    permissions: frozenset[str] = frozenset()
    detected_language: str = "mn"
    channel: str = "web"
    # Roles actually granted to the account. ``roles`` is narrowed to a
    # personal member scope while a manager works in "member" workspace mode;
    # this keeps the real grants for endpoints that manage the mode itself.
    account_roles: frozenset[str] | None = None
    workspace_mode: str = "manager"

    @property
    def granted_roles(self) -> frozenset[str]:
        return self.account_roles if self.account_roles is not None else self.roles

    def has_any_role(self, *roles: str) -> bool:
        return bool(self.roles.intersection(roles))

    def can(self, permission: str) -> bool:
        return permission in self.permissions


ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "admin": frozenset({"assistant.read", "assistant.preview", "assistant.directory", "assistant.analytics", "assistant.erp"}),
    "manager": frozenset({"assistant.read", "assistant.preview", "assistant.directory", "assistant.analytics", "assistant.erp"}),
    "hr": frozenset({"assistant.read", "assistant.directory", "assistant.analytics"}),
    "team_lead": frozenset({"assistant.read", "assistant.preview", "assistant.analytics"}),
    "member": frozenset({"assistant.read", "assistant.preview"}),
    "contractor": frozenset({"assistant.read"}),
    "client_auditor": frozenset({"assistant.read", "assistant.analytics"}),
    "legal_counsel": frozenset({"assistant.read", "assistant.preview"}),
}


def permissions_for_roles(roles: frozenset[str]) -> frozenset[str]:
    # This deployment serves one internal company. Authenticated workspace
    # accounts may read company assistant data directly; role permissions still
    # remain relevant to non-assistant APIs and mutation-specific checks.
    # Assistant writes continue to require an explicit preview/confirmation
    # flow, while assignment policy is enforced by collaboration_permissions.
    # Keep the read capability for active accounts even during the short window
    # between account creation and role assignment. This makes the curated
    # company knowledge source available to every authenticated Oyuns agent
    # user without granting any management or write capability.
    if not roles:
        return frozenset({"assistant.read"})
    if roles:
        return frozenset({
            "assistant.read",
            "assistant.directory",
            "assistant.analytics",
            "assistant.erp",
            "assistant.preview",
        })
    return frozenset()


def build_actor_context(*, account_id: int, organization_id: int, employee_id: int | None,
                        email: str, locale: str, roles: frozenset[str],
                        detected_language: str = "mn", channel: str = "web") -> ActorContext:
    """Construct an actor only from trusted account/role data."""
    return ActorContext(
        account_id=account_id,
        organization_id=organization_id,
        employee_id=employee_id,
        email=email,
        locale=locale,
        roles=roles,
        permissions=permissions_for_roles(roles),
        detected_language=detected_language,
        channel=channel,
    )


async def custom_role_grants(db: AsyncSession, account_id: int, employee_id: int | None) -> set[str]:
    """Platform roles granted by active custom roles (directly or via a team)."""
    from app.erp.role_catalog import granted_system_roles

    rows = list((await db.execute(
        select(ERPAccessRole.system_roles)
        .join(ERPAccountRole, ERPAccountRole.access_role_id == ERPAccessRole.id)
        .where(ERPAccountRole.account_id == account_id, ERPAccessRole.is_active.is_(True))
    )).scalars().all())
    if employee_id is not None:
        rows += (await db.execute(
            select(ERPAccessRole.system_roles)
            .join(ERPTeamRole, ERPTeamRole.access_role_id == ERPAccessRole.id)
            .join(TeamMember, TeamMember.team_id == ERPTeamRole.team_id)
            .where(TeamMember.employee_id == employee_id, ERPAccessRole.is_active.is_(True))
        )).scalars().all()
    granted: set[str] = set()
    for value in rows:
        granted |= granted_system_roles(value)
    return granted


async def actor_from_account_id(account_id: int, db: AsyncSession) -> ActorContext:
    """Rehydrate current account status and time-bounded roles from storage."""
    try:
        account = await db.get(UserAccount, account_id)
    except TenantBoundaryViolation:
        account = None
    if not account or account.status != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account unavailable")
    try:
        # Pins the request (and RLS for its transactions) to this tenant.
        await bind_tenant(db, account.organization_id)
    except TenantBoundaryViolation:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account unavailable") from None
    if account.employee_id:
        employee = await db.get(Employee, account.employee_id)
        if not employee or not employee.is_active or employee.deleted_at is not None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Worker unavailable")
    today = date.today()
    rows = (
        await db.execute(
            select(RoleAssignment.role).where(
                RoleAssignment.account_id == account.id,
                or_(RoleAssignment.valid_from.is_(None), RoleAssignment.valid_from <= today),
                or_(RoleAssignment.valid_until.is_(None), RoleAssignment.valid_until >= today),
            )
        )
    ).scalars().all()
    return build_actor_context(
        account_id=account.id,
        organization_id=account.organization_id,
        employee_id=account.employee_id,
        email=account.email,
        locale=account.locale,
        roles=frozenset(rows) | await custom_role_grants(db, account.id, account.employee_id),
    )


async def tenant_requires_two_factor(organization_id: int) -> bool:
    state = await tenant_directory.state(organization_id)
    return bool(state and state.two_factor_required)


async def session_actor_from_token(token: str, db: AsyncSession) -> tuple[ActorContext, dict]:
    """Actor and token claims, without the second-factor gate.

    Only for the endpoints a session needs before it passed the second factor
    (``/v1/auth/me``, ``/v1/auth/2fa/*``); everything else uses ``actor_from_token``.
    """
    payload = decode_token(token)
    if not payload or payload.get("kind") != "enterprise":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access token")
    actor = await actor_from_account_id(int(payload["sub"]), db)
    if actor.organization_id != int(payload.get("organization_id", -1)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access token")
    return actor, payload


async def actor_from_token(token: str, db: AsyncSession) -> ActorContext:
    actor, payload = await session_actor_from_token(token, db)
    if not payload.get("mfa") and await tenant_requires_two_factor(actor.organization_id):
        # The tenant enforces 2FA and this session has not passed it yet (also
        # sessions opened before the requirement was switched on).
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "two_factor_required", "message": "Two-factor authentication is required"},
        )
    return actor


async def actor_from_telegram_id(telegram_id: str, db: AsyncSession) -> ActorContext | None:
    """Resolve Telegram through the same active enterprise account and RBAC path.

    The legacy manager allowlist remains available to old bot commands only; it
    must not grant enterprise-data access without a linked UserAccount.
    """
    query = select(Employee).where(Employee.telegram_id == str(telegram_id), Employee.is_active.is_(True), Employee.deleted_at.is_(None))
    if current_tenant_id() is not None:
        # A bot turn is bound to the bot's tenant: another tenant's worker is unknown here.
        query = query.where(Employee.organization_id == current_tenant_id())
    employee = await db.scalar(query)
    if not employee:
        return None
    account = await db.scalar(select(UserAccount).where(UserAccount.employee_id == employee.id, UserAccount.status == "active"))
    if not account:
        return None
    if not await tenant_is_operational(account.organization_id):
        return None
    today = date.today()
    roles = (await db.execute(select(RoleAssignment.role).where(RoleAssignment.account_id == account.id, or_(RoleAssignment.valid_from.is_(None), RoleAssignment.valid_from <= today), or_(RoleAssignment.valid_until.is_(None), RoleAssignment.valid_until >= today)))).scalars().all()
    roles = frozenset(roles) | await custom_role_grants(db, account.id, account.employee_id)
    return build_actor_context(account_id=account.id, organization_id=account.organization_id, employee_id=account.employee_id, email=account.email, locale=account.locale, roles=roles, channel="telegram")


async def tenant_is_operational(organization_id: int) -> bool:
    """Active tenant with a usable license (Telegram has no request middleware)."""
    try:
        state = await tenant_directory.state(organization_id)
    except Exception:  # pragma: no cover - a failed lookup must not open access
        return False
    return bool(state and state.status == "active" and state.license_state() not in {"missing", "expired"})


async def file_search_principal_from_telegram_id(telegram_id: str, db: AsyncSession) -> FileSearchPrincipal | None:
    """Resolve a verified Telegram employee for constrained company-file reads.

    This intentionally does not manufacture a UserAccount or workspace actor.
    The employee's own tenant is used for discovery, while restricted account
    grants remain unsatisfied unless a real workspace account exists.
    """
    query = select(Employee).where(
        Employee.telegram_id == str(telegram_id),
        Employee.is_active.is_(True),
    )
    if current_tenant_id() is not None:
        query = query.where(Employee.organization_id == current_tenant_id())
    employee = await db.scalar(query)
    if not employee or not await tenant_is_operational(employee.organization_id):
        return None
    return FileSearchPrincipal(
        organization_id=employee.organization_id,
        employee_id=employee.id,
        channel="telegram",
        locale="mn",
        telegram_id=str(telegram_id),
    )


WORKSPACE_MODE_HEADER = "X-Workspace-Mode"
# Roles that may switch between the company-wide manager view and the
# personal member view. HR alone has no toggle and keeps its grants.
WORKSPACE_MODE_ROLES = frozenset({"admin", "manager", "team_lead"})
# Everything that widens data scope beyond the actor's own records.
SCOPE_WIDENING_ROLES = frozenset({"admin", "manager", "team_lead", "hr", "client_auditor"})


def apply_workspace_mode(actor: ActorContext, mode: str | None) -> ActorContext:
    """Narrow a management actor to a personal scope in member workspace mode.

    The mode can only remove privileges: every existing role check keeps
    working, and in member mode a manager sees exactly what a regular worker
    sees (own reports, tasks, calendar, statistics). Unknown values keep the
    full manager scope.
    """
    requested = mode.strip().lower() if isinstance(mode, str) else ""
    if requested != "member" or not actor.roles.intersection(WORKSPACE_MODE_ROLES):
        return actor
    roles = frozenset((actor.roles - SCOPE_WIDENING_ROLES) | {"member"})
    return replace(
        actor,
        roles=roles,
        permissions=permissions_for_roles(roles),
        account_roles=actor.roles,
        workspace_mode="member",
    )


async def get_account_actor(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> ActorContext:
    """Actor with every granted role, ignoring the workspace mode."""
    return await actor_from_token(credentials.credentials, db)


async def get_actor(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    db: AsyncSession = Depends(get_db),
    workspace_mode: str | None = Header(default=None, alias=WORKSPACE_MODE_HEADER),
) -> ActorContext:
    return apply_workspace_mode(await actor_from_token(credentials.credentials, db), workspace_mode)


async def get_session_actor(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    db: AsyncSession = Depends(get_db),
    workspace_mode: str | None = Header(default=None, alias=WORKSPACE_MODE_HEADER),
) -> tuple[ActorContext, dict]:
    """Actor plus token claims for a session that may still owe the second factor."""
    actor, claims = await session_actor_from_token(credentials.credentials, db)
    return apply_workspace_mode(actor, workspace_mode), claims


def require_roles(*allowed: str) -> Callable:
    async def dependency(actor: ActorContext = Depends(get_actor)) -> ActorContext:
        if not actor.has_any_role(*allowed):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permission")
        return actor

    return dependency
