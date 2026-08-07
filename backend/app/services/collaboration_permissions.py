from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Organization


ALL_EMPLOYEE_ROLES = frozenset({"admin", "manager", "team_lead", "member", "contractor", "client_auditor"})
SETTINGS_KEY = "task_assignment_roles"


def configured_assignment_roles(organization: Organization | None) -> frozenset[str]:
    raw = (organization.settings or {}).get(SETTINGS_KEY) if organization else None
    if not isinstance(raw, list):
        return ALL_EMPLOYEE_ROLES
    return frozenset(str(role) for role in raw if role in ALL_EMPLOYEE_ROLES)


async def actor_can_assign_tasks(db: AsyncSession, *, organization_id: int, employee_id: int | None, roles: frozenset[str]) -> bool:
    organization = await db.get(Organization, organization_id)
    # Task delegation is a core collaboration action: every active member can
    # assign work, including an administrator account that is not employee-linked.
    return bool(roles.intersection(ALL_EMPLOYEE_ROLES) or employee_id is not None)


def employee_can_assign_tasks(employee_id: int | None) -> bool:
    # Telegram and web use the same open delegation policy.
    return employee_id is not None
