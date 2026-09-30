"""Shared, backwards-compatible management Telegram recipient lookup.

``manager_settings`` holds one row per tenant. The ``MANAGER_TG_ID`` env
fallback predates tenancy and belongs to the primary tenant only.
"""
from __future__ import annotations

from sqlalchemy import select

from app.core.config import settings


def manager_telegram_ids(manager_settings=None, *, primary: bool = True) -> list[str]:
    """Return unique configured management IDs, including the legacy fallback."""
    values = list(getattr(manager_settings, "telegram_admin_ids", None) or [])
    legacy = getattr(manager_settings, "telegram_id", None)
    if legacy:
        values.insert(0, legacy)
    if not values and primary and settings.MANAGER_TG_ID:
        values.append(settings.MANAGER_TG_ID)
    result: list[str] = []
    for value in values:
        value = str(value).strip()
        if value and value not in result:
            result.append(value)
    return result


async def manager_settings_for(db, organization_id: int | None):
    """The tenant's settings row (``None`` until an admin saves one)."""
    from app.models.models import ManagerSettings

    if organization_id is None:
        return None
    return (
        await db.execute(
            select(ManagerSettings).where(ManagerSettings.organization_id == organization_id).order_by(ManagerSettings.id).limit(1)
        )
    ).scalar_one_or_none()
