"""aiogram middleware — инъекция employee + is_manager во все хендлеры.

Не блокирует апдейты: employee может быть None (хендлер /start сам решает,
что ответить незарегистрированному). Убирает дублирование get_employee_by_tg.
"""
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from app.bot.db import get_employee_by_tg, get_manager_settings, link_employee_telegram
from app.core.config import settings


def _is_manager(tg_id: str) -> bool:
    if tg_id == str(settings.MANAGER_TG_ID):
        return True
    ms = get_manager_settings()
    return bool(ms and ms.telegram_id and str(ms.telegram_id) == tg_id)


class EmployeeMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is not None:
            tg_id = str(user.id)
            data["tg_id"] = tg_id
            emp = get_employee_by_tg(tg_id)
            if emp is None and getattr(user, "username", None):
                emp = link_employee_telegram(user.username, tg_id)
            data["employee"] = emp
            data["is_manager"] = _is_manager(tg_id)
        else:
            data["tg_id"] = None
            data["employee"] = None
            data["is_manager"] = False
        return await handler(event, data)
