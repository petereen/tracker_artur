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


bearer = HTTPBearer()


@dataclass(frozen=True)
class ActorContext:
    account_id: int
    organization_id: int
    employee_id: int | None
    email: str
    locale: str
    roles: frozenset[str]

    def has_any_role(self, *roles: str) -> bool:
        return bool(self.roles.intersection(roles))


async def actor_from_token(token: str, db: AsyncSession) -> ActorContext:
    payload = decode_token(token)
    if not payload or payload.get("kind") != "enterprise":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access token")
    account = await db.get(UserAccount, int(payload["sub"]))
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
    return ActorContext(
        account_id=account.id,
        organization_id=account.organization_id,
        employee_id=account.employee_id,
        email=account.email,
        locale=account.locale,
        roles=frozenset(rows),
    )


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
    return ActorContext(account_id=account.id, organization_id=account.organization_id, employee_id=account.employee_id, email=account.email, locale=account.locale, roles=frozenset(roles))


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
