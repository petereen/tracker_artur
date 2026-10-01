"""aiogram middleware — the bot is a companion of one tenant's ERP workspace.

Each tenant has its own bot, so the receiving bot names the tenant
(``bot_tenant_id``). Every update is classified before a handler runs:

* no tenant for the bot → refused (never falls back to the system context);
* the Telegram id is matched against the ERP's worker profiles: a worker of
  this tenant gets ``employee`` plus the roles of the linked ERP account
  (platform roles and custom roles built in Settings), exactly as on the web;
* anyone else (unknown, or a worker of another tenant) gets an information
  message and no handler runs, except the entry points that link an account
  (HR invite, bot handshake) and ``/myid``.

The whole update runs bound to the bot's tenant (ORM guard + ``app.tenant_id``
for row-level security).
"""
import html
import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.bot.db import get_employee_by_tg, is_primary_tenant, link_employee_telegram
from app.bot.menu import sync_chat_menu
from app.core.roles import TELEGRAM_MANAGEMENT_ROLES
from app.core.tenancy import tenant_scope
from app.services.telegram_bots import HANDSHAKE_PREFIX

log = logging.getLogger(__name__)

WORKSPACE_UNAVAILABLE = "⛔️ Байгууллагын эрх идэвхгүй байна (түдгэлзсэн эсвэл лиценз дууссан). Админдаа хандана уу."
BOT_NOT_CONNECTED = "⚠️ Энэ бот OYUNS ERP-ийн аль ч байгууллагад холбогдоогүй байна. Байгууллагынхаа ERP админд хандана уу."
FOREIGN_TENANT = (
    "ℹ️ Таны Telegram бүртгэл өөр байгууллагын OYUNS ERP-д холбогдсон байна.\n\n"
    "Өөрийн байгууллагын ботыг ашиглана уу. Хэрэв танай байгууллага Telegram бот холбоогүй бол ERP админдаа хандана уу."
)
INVITE_PREFIX = "invite_"


def _bot_tenant(data: dict[str, Any]) -> int | None:
    if data.get("bot_tenant_id") is not None:
        return data["bot_tenant_id"]
    bot = data.get("bot")
    if bot is None:
        return None
    from app.services.telegram_bots import registry

    tenant_bot = registry.for_bot_id_sync(bot.id)
    return tenant_bot.organization_id if tenant_bot else None


async def _tenant_operational(tenant_id: int) -> bool:
    from app.core.enterprise_deps import tenant_is_operational

    return await tenant_is_operational(tenant_id)


async def _erp_actor(tg_id: str):
    """The worker's ERP account with its current roles (``None`` without one)."""
    from app.core.database import AsyncSessionLocal
    from app.core.enterprise_deps import actor_from_telegram_id

    async with AsyncSessionLocal() as db:
        return await actor_from_telegram_id(tg_id, db)


async def _tenant_name(tenant_id: int) -> str:
    from app.core.tenancy import tenant_directory

    try:
        state = await tenant_directory.state(tenant_id)
    except Exception:  # noqa: BLE001 - the name only decorates the message
        log.warning("bot.tenant_name_failed tenant=%s", tenant_id, exc_info=True)
        state = None
    return state.name if state else "OYUNS ERP"


def _bot_delivers(data: dict[str, Any]) -> bool:
    bot = data.get("bot")
    if bot is None:
        return True
    from app.services.telegram_bots import registry

    tenant_bot = registry.for_bot_id_sync(bot.id)
    return tenant_bot is None or tenant_bot.delivers


async def _unregistered_text(data: dict[str, Any], tenant_id: int, tg_id: str | None) -> str:
    if data["foreign_tenant"]:
        return FOREIGN_TENANT
    name = html.escape(await _tenant_name(tenant_id))
    if not _bot_delivers(data):
        return (
            f"ℹ️ «{name}» байгууллага Telegram ботоо OYUNS ERP-тэй бүрэн холбож дуусаагүй байна.\n\n"
            "Байгууллагынхаа ERP админд хандана уу."
        )
    identity = f"\n\n🆔 Таны Telegram ID: <code>{tg_id}</code>" if tg_id else ""
    return (
        f"👋 Энэ бол «{name}» байгууллагын OYUNS ERP-ийн туслах бот.\n\n"
        "Ботыг зөвхөн тус байгууллагын ERP-д бүртгэлтэй ажилтнууд ашиглана. "
        "Таны Telegram бүртгэл ямар ч ажилтны профайлд холбогдоогүй байна.\n\n"
        "Хэрэв та энэ байгууллагын ажилтан бол ERP админ эсвэл HR-даа хандаж, "
        f"Telegram ID-гаа профайлдаа холбуулна уу.{identity}"
    )


def _open_to_unregistered(event: TelegramObject) -> bool:
    """Entry points that link an account, plus ``/myid``."""
    if not isinstance(event, Message):
        return False
    parts = (event.text or "").split(maxsplit=1)
    if not parts:
        return False
    command = parts[0].split("@", 1)[0]
    if command == "/myid":
        return True
    payload = parts[1] if len(parts) > 1 else ""
    return command == "/start" and payload.startswith((INVITE_PREFIX, HANDSHAKE_PREFIX))


async def _reply(event: TelegramObject, text: str) -> None:
    if isinstance(event, Message):
        await event.answer(text)
    elif isinstance(event, CallbackQuery):
        await event.answer(text[:200], show_alert=True)


class EmployeeMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tenant_id = _bot_tenant(data)
        if tenant_id is None:
            log.error("bot.update_without_tenant")
            await _reply(event, BOT_NOT_CONNECTED)
            return None
        data["bot_tenant_id"] = tenant_id
        data["foreign_tenant"] = False
        if not await _tenant_operational(tenant_id):
            await _reply(event, WORKSPACE_UNAVAILABLE)
            return None
        user = data.get("event_from_user")
        tg_id = str(user.id) if user is not None else None
        emp = None
        if tg_id is not None:
            emp = get_employee_by_tg(tg_id)
            if emp is not None and emp.organization_id != tenant_id:
                emp = None
                data["foreign_tenant"] = True
            if emp is None and not data["foreign_tenant"] and getattr(user, "username", None):
                emp = link_employee_telegram(user.username, tg_id, tenant_id)
        data["tg_id"] = tg_id
        data["employee"] = emp
        with tenant_scope(tenant_id):
            actor = await _erp_actor(tg_id) if emp is not None else None
            roles = actor.roles if actor else frozenset()
            data["actor"] = actor
            data["roles"] = roles
            data["is_manager"] = bool(roles & TELEGRAM_MANAGEMENT_ROLES)
            if emp is None and not _open_to_unregistered(event):
                await _reply(event, await _unregistered_text(data, tenant_id, tg_id))
                return None
            chat = data.get("event_chat")
            bot = data.get("bot")
            if emp is not None and bot is not None and getattr(chat, "type", None) == "private":
                await sync_chat_menu(bot, chat.id, is_manager=data["is_manager"], primary=is_primary_tenant(tenant_id))
            return await handler(event, data)
