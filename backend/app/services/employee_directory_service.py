"""Privacy-safe employee directory context for the OYUNS assistant."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.bot.db import get_manager_settings, get_session
from app.core.config import settings
from app.models.models import Employee

log = logging.getLogger(__name__)


def list_workers(*, include_inactive: bool = True, limit: int = 100) -> list[dict]:
    """Return only operational directory fields; never expose Telegram IDs."""
    try:
        manager_tg_id = str(settings.MANAGER_TG_ID)
        manager_settings = get_manager_settings()
        if manager_settings and manager_settings.telegram_id:
            manager_tg_id = str(manager_settings.telegram_id)

        with get_session() as session:
            query = select(Employee)
            if not include_inactive:
                query = query.where(Employee.is_active.is_(True))
            rows = session.execute(
                query.order_by(Employee.is_active.desc(), Employee.name.asc()).limit(limit)
            ).scalars().all()
            return [
                {
                    "id": employee.id,
                    "name": employee.name,
                    "telegram_username": employee.telegram_username,
                    "timezone": employee.timezone,
                    "is_active": employee.is_active,
                    "is_manager": str(employee.telegram_id) == manager_tg_id,
                }
                for employee in rows
            ]
    except SQLAlchemyError:
        log.exception("employee_directory.list_failed")
        return []
