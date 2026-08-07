from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Organization, RoleAssignment, UserAccount


ALL_EMPLOYEE_ROLES = frozenset({"admin", "manager", "team_lead", "member", "contractor", "client_auditor"})
SETTINGS_KEY = "task_assignment_roles"


def configured_assignment_roles(organization: Organization | None) -> frozenset[str]:
    raw = (organization.settings or {}).get(SETTINGS_KEY) if organization else None
    if not isinstance(raw, list):
        return ALL_EMPLOYEE_ROLES
    return frozenset(str(role) for role in raw if role in ALL_EMPLOYEE_ROLES)


async def actor_can_assign_tasks(db: AsyncSession, *, organization_id: int, employee_id: int | None, roles: frozenset[str]) -> bool:
    if employee_id is None:
        return False
    organization = await db.get(Organization, organization_id)
    return bool(roles.intersection(configured_assignment_roles(organization)))


def employee_can_assign_tasks(employee_id: int | None) -> bool:
    if employee_id is None:
        return False
    from app.bot.db import get_session

    with get_session() as db:
        account = db.execute(select(UserAccount).where(UserAccount.employee_id == employee_id, UserAccount.status == "active")).scalar_one_or_none()
        if account is None:
            # Active Telegram-only workers follow the default-open policy until
            # an account exists and an administrator explicitly restricts roles.
            organization = db.execute(select(Organization).order_by(Organization.id)).scalars().first()
            return configured_assignment_roles(organization) == ALL_EMPLOYEE_ROLES
        roles = frozenset(db.execute(select(RoleAssignment.role).where(RoleAssignment.account_id == account.id)).scalars().all())
        organization = db.get(Organization, account.organization_id)
        return bool(roles.intersection(configured_assignment_roles(organization)))
