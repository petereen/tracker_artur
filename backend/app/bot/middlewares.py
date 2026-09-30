"""aiogram middleware — инъекция employee + is_manager во все хендлеры.

Не блокирует апдейты: employee может быть None (хендлер /start сам решает,
что ответить незарегистрированному). Убирает дублирование get_employee_by_tg.

Each tenant has its own bot, so the receiving bot names the tenant
(``bot_tenant_id``). A worker of another tenant writing to this bot is not
recognised, and the whole update runs bound to the bot's tenant (ORM guard +
``app.tenant_id`` for row-level security).
"""
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.bot.db import get_employee_by_tg, get_manager_settings, is_primary_tenant, link_employee_telegram
from app.core.config import settings
from app.core.tenancy import tenant_scope
from app.services.manager_recipients import manager_telegram_ids

WORKSPACE_UNAVAILABLE = "⛔️ Байгууллагын эрх идэвхгүй байна (түдгэлзсэн эсвэл лиценз дууссан). Админдаа хандана уу."


def _is_manager(tg_id: str, tenant_id: int | None = None) -> bool:
    primary = is_primary_tenant(tenant_id)
    if primary and tg_id == str(settings.MANAGER_TG_ID):
        return True
    ms = get_manager_settings(tenant_id)
    return tg_id in manager_telegram_ids(ms, primary=primary)


def _bot_tenant(data: dict[str, Any]) -> int | None:
    if data.get("bot_tenant_id") is not None:
        return data["bot_tenant_id"]
    bot = data.get("bot")
    if bot is None:
        return None
    from app.services.telegram_bots import registry

    tenant_bot = registry.for_bot_id_sync(bot.id)
    return tenant_bot.organization_id if tenant_bot else None


async def _tenant_operational(tenant_id: int | None) -> bool:
    if tenant_id is None:
        return True
    from app.core.enterprise_deps import tenant_is_operational

    return await tenant_is_operational(tenant_id)


class EmployeeMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tenant_id = _bot_tenant(data)
        data["bot_tenant_id"] = tenant_id
        data["foreign_tenant"] = False
        if not await _tenant_operational(tenant_id):
            if isinstance(event, Message):
                await event.answer(WORKSPACE_UNAVAILABLE)
            elif isinstance(event, CallbackQuery):
                await event.answer(WORKSPACE_UNAVAILABLE, show_alert=True)
            return None
        user = data.get("event_from_user")
        if user is not None:
            tg_id = str(user.id)
            data["tg_id"] = tg_id
            emp = get_employee_by_tg(tg_id)
            if emp is not None and tenant_id is not None and emp.organization_id != tenant_id:
                emp = None
                data["foreign_tenant"] = True
            if emp is None and not data["foreign_tenant"] and getattr(user, "username", None):
                emp = link_employee_telegram(user.username, tg_id, tenant_id)
            data["employee"] = emp
            data["is_manager"] = _is_manager(tg_id, tenant_id)
        else:
            data["tg_id"] = None
            data["employee"] = None
            data["is_manager"] = False
        with tenant_scope(tenant_id):
            return await handler(event, data)
