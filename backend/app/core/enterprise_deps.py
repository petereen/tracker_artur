from dataclasses import dataclass
from datetime import date
from typing import Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decode_token
from app.models.models import Employee, RoleAssignment, UserAccount
from app.services.file_search_service import FileSearchPrincipal
from app.core.config import settings


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
}


def permissions_for_roles(roles: frozenset[str]) -> frozenset[str]:
    # This deployment serves one internal company. Authenticated workspace
    # accounts may read company assistant data directly; role permissions still
    # remain relevant to non-assistant APIs and mutation-specific checks.
    # Assistant writes continue to require an explicit preview/confirmation
    # flow, while assignment policy is enforced by collaboration_permissions.
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


async def actor_from_account_id(account_id: int, db: AsyncSession) -> ActorContext:
    """Rehydrate current account status and time-bounded roles from storage."""
    account = await db.get(UserAccount, account_id)
    if not account or account.status != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account unavailable")
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
        roles=frozenset(rows),
    )


async def actor_from_token(token: str, db: AsyncSession) -> ActorContext:
    payload = decode_token(token)
    if not payload or payload.get("kind") != "enterprise":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access token")
    actor = await actor_from_account_id(int(payload["sub"]), db)
    if actor.organization_id != int(payload.get("organization_id", -1)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access token")
    return actor


async def actor_from_telegram_id(telegram_id: str, db: AsyncSession) -> ActorContext | None:
    """Resolve Telegram through the same active enterprise account and RBAC path.

    The legacy manager allowlist remains available to old bot commands only; it
    must not grant enterprise-data access without a linked UserAccount.
    """
    employee = await db.scalar(select(Employee).where(Employee.telegram_id == str(telegram_id), Employee.is_active.is_(True)))
    if not employee:
        return None
    account = await db.scalar(select(UserAccount).where(UserAccount.employee_id == employee.id, UserAccount.status == "active"))
    if not account:
        return None
    today = date.today()
    roles = (await db.execute(select(RoleAssignment.role).where(RoleAssignment.account_id == account.id, or_(RoleAssignment.valid_from.is_(None), RoleAssignment.valid_from <= today), or_(RoleAssignment.valid_until.is_(None), RoleAssignment.valid_until >= today)))).scalars().all()
    return build_actor_context(account_id=account.id, organization_id=account.organization_id, employee_id=account.employee_id, email=account.email, locale=account.locale, roles=frozenset(roles), channel="telegram")


async def file_search_principal_from_telegram_id(telegram_id: str, db: AsyncSession) -> FileSearchPrincipal | None:
    """Resolve a verified Telegram employee for constrained company-file reads.

    This intentionally does not manufacture a UserAccount or workspace actor.
    The fixed company tenant is used for discovery, while restricted account
    grants remain unsatisfied unless a real workspace account exists.
    """
    employee = await db.scalar(select(Employee).where(
        Employee.telegram_id == str(telegram_id),
        Employee.is_active.is_(True),
    ))
    if not employee:
        return None
    return FileSearchPrincipal(
        organization_id=settings.DEFAULT_COMPANY_ORGANIZATION_ID,
        employee_id=employee.id,
        channel="telegram",
        locale="mn",
        telegram_id=str(telegram_id),
    )


async def get_actor(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> ActorContext:
    return await actor_from_token(credentials.credentials, db)


def require_roles(*allowed: str) -> Callable:
    async def dependency(actor: ActorContext = Depends(get_actor)) -> ActorContext:
        if not actor.has_any_role(*allowed):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permission")
        return actor

    return dependency
