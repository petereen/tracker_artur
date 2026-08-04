"""Shared, backwards-compatible management Telegram recipient lookup."""
from __future__ import annotations

from app.core.config import settings


def manager_telegram_ids(manager_settings=None) -> list[str]:
    """Return unique configured management IDs, including the legacy fallback."""
    values = list(getattr(manager_settings, "telegram_admin_ids", None) or [])
    legacy = getattr(manager_settings, "telegram_id", None)
    if legacy:
        values.insert(0, legacy)
    if not values and settings.MANAGER_TG_ID:
        values.append(settings.MANAGER_TG_ID)
    result: list[str] = []
    for value in values:
        value = str(value).strip()
        if value and value not in result:
            result.append(value)
    return result
