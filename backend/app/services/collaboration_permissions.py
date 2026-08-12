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
    allowed_roles = configured_assignment_roles(organization)
    # Assignment authority is derived from current organization settings and
    # server-resolved roles. An employee link alone is never sufficient.
    return bool(roles.intersection(allowed_roles))


def employee_can_assign_tasks(employee_id: int | None) -> bool:
    # Telegram and web use the same open delegation policy.
    return employee_id is not None
