"""Точка входа бота. Запускается как отдельный процесс.

One process serves every tenant's bot. A supervisor loop reloads the bot
registry (``app.services.telegram_bots``) every few seconds, starts a
long-polling task for each newly connected bot and stops the ones that were
disconnected, so a tenant's handshake works without a restart. Each update
is fed to the shared dispatcher together with the bot's tenant; the
middleware binds that tenant for the whole handler.
"""
import asyncio
import logging
import time

import sentry_sdk
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramConflictError, TelegramUnauthorizedError
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import TelegramMethod
from aiogram.types import ErrorEvent, Update

from app.bot.assistant_handlers import router as assistant_router
from app.bot.handlers import router
from app.bot.handshake_handlers import router as handshake_router
from app.bot.middlewares import EmployeeMiddleware
from app.bot.scheduler import rebuild_jobs, scheduler
from app.bot.tasks_handlers import router as tasks_router
from app.bot.work_report_handlers import router as work_report_router
from app.bot.menu import setup_bot_menus
from app.core.config import settings
from app.observability.sentry import init_from_env
from app.services import telegram_bots
from app.services.telegram_bots import TenantBot

init_from_env(server_name="tracker-artur-bot")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)

POLL_TIMEOUT_SECONDS = 25
SUPERVISE_INTERVAL_SECONDS = 15
# A bot is reported online while its last getUpdates succeeded this recently.
HEALTHY_WITHIN_SECONDS = 90


async def on_error(event: ErrorEvent) -> None:
    log.exception("bot.update_error", exc_info=event.exception)
    sentry_sdk.capture_exception(event.exception)


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    dp.errors.register(on_error)
    dp.message.middleware(EmployeeMiddleware())
    dp.callback_query.middleware(EmployeeMiddleware())
    # The handshake /start must win over the generic /start handler.
    dp.include_router(handshake_router)
    dp.include_router(tasks_router)
    dp.include_router(work_report_router)
    dp.include_router(router)
    dp.include_router(assistant_router)
    return dp


def _manager_chats(organization_id: int) -> list[str]:
    from app.bot.db import get_manager_settings, is_primary_tenant
    from app.services.manager_recipients import manager_telegram_ids

    primary = is_primary_tenant(organization_id)
    chats = manager_telegram_ids(get_manager_settings(organization_id), primary=primary)
    if primary and settings.MANAGER_TG_ID and str(settings.MANAGER_TG_ID) not in chats:
        chats.append(str(settings.MANAGER_TG_ID))
    return chats


class BotPool:
    """Long-polling tasks keyed by bot id."""

    def __init__(self, dp: Dispatcher) -> None:
        self.dp = dp
        self.running: dict[int, tuple[TenantBot, Bot, asyncio.Task]] = {}
        self.healthy_at: dict[int, float] = {}
        # Tokens Telegram rejected (the platform bot has no row to mark).
        self.revoked_tokens: set[str] = set()

    async def sync(self) -> None:
        telegram_bots.registry.invalidate()
        wanted = {bot.bot_id: bot for bot in await asyncio.to_thread(telegram_bots.registry.load_sync)}
        for bot_id, (tenant_bot, _, task) in list(self.running.items()):
            current = wanted.get(bot_id)
            if current is None or current.token != tenant_bot.token or current.organization_id != tenant_bot.organization_id or task.done():
                await self.stop(bot_id)
        for bot_id, tenant_bot in wanted.items():
            if tenant_bot.token in self.revoked_tokens:
                continue
            if bot_id not in self.running:
                self.start(tenant_bot)
            else:
                # Status changes (pending → active) need no restart.
                _, bot, task = self.running[bot_id]
                self.running[bot_id] = (tenant_bot, bot, task)
        now = time.monotonic()
        healthy = [
            bot_id for bot_id, (tenant_bot, _, _) in self.running.items()
            if tenant_bot.source == "tenant" and now - self.healthy_at.get(bot_id, 0) < HEALTHY_WITHIN_SECONDS
        ]
        await asyncio.to_thread(telegram_bots.record_bot_seen_sync, healthy)

    def start(self, tenant_bot: TenantBot) -> None:
        bot = Bot(token=tenant_bot.token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        task = asyncio.create_task(self._poll(tenant_bot, bot), name=f"bot-poll-{tenant_bot.bot_id}")
        self.running[tenant_bot.bot_id] = (tenant_bot, bot, task)
        log.info("bot.polling_started bot=%s tenant=%s source=%s", tenant_bot.bot_id, tenant_bot.organization_id, tenant_bot.source)

    async def stop(self, bot_id: int) -> None:
        tenant_bot, bot, task = self.running.pop(bot_id)
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        await bot.session.close()
        self.healthy_at.pop(bot_id, None)
        log.info("bot.polling_stopped bot=%s tenant=%s", bot_id, tenant_bot.organization_id)

    async def stop_all(self) -> None:
        for bot_id in list(self.running):
            await self.stop(bot_id)

    async def _setup(self, tenant_bot: TenantBot, bot: Bot) -> None:
        # Polling fails with 409 while a webhook is set on the bot.
        await bot.delete_webhook(drop_pending_updates=False)
        try:
            chats = await asyncio.to_thread(_manager_chats, tenant_bot.organization_id)
            mini_app_url = await asyncio.to_thread(telegram_bots.mini_app_url_sync, tenant_bot.organization_id)
            await setup_bot_menus(bot, chats, mini_app_url)
        except Exception:
            log.exception("bot.menu_setup_failed bot=%s", tenant_bot.bot_id)

    async def _poll(self, tenant_bot: TenantBot, bot: Bot) -> None:
        try:
            await self._setup(tenant_bot, bot)
        except TelegramUnauthorizedError:
            await self._revoked(tenant_bot)
            return
        except Exception:
            log.exception("bot.setup_failed bot=%s", tenant_bot.bot_id)
        allowed_updates = self.dp.resolve_used_update_types()
        offset: int | None = None
        backoff = 1.0
        while True:
            try:
                updates = await bot.get_updates(
                    offset=offset, timeout=POLL_TIMEOUT_SECONDS, allowed_updates=allowed_updates,
                    request_timeout=POLL_TIMEOUT_SECONDS + 15,
                )
            except asyncio.CancelledError:
                raise
            except TelegramUnauthorizedError:
                await self._revoked(tenant_bot)
                return
            except TelegramConflictError as exc:
                if tenant_bot.source == "tenant":
                    await asyncio.to_thread(
                        telegram_bots.record_bot_error_sync, tenant_bot.bot_id,
                        "Энэ ботыг өөр програм давхар ашиглаж байна (getUpdates/webhook conflict).",
                    )
                log.warning("bot.poll_conflict bot=%s: %s", tenant_bot.bot_id, exc)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)
                continue
            except Exception as exc:  # noqa: BLE001 - network hiccups must not stop polling
                log.warning("bot.poll_failed bot=%s: %s: %s", tenant_bot.bot_id, type(exc).__name__, exc)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)
                continue
            backoff = 1.0
            self.healthy_at[tenant_bot.bot_id] = time.monotonic()
            for update in updates:
                offset = update.update_id + 1
                asyncio.create_task(self._feed(bot, tenant_bot, update))

    async def _feed(self, bot: Bot, tenant_bot: TenantBot, update: Update) -> None:
        try:
            response = await self.dp.feed_update(bot, update, bot_tenant_id=tenant_bot.organization_id)
            if isinstance(response, TelegramMethod):
                await bot(response)
        except Exception as exc:  # noqa: BLE001
            log.exception("bot.update_failed bot=%s update=%s", tenant_bot.bot_id, update.update_id)
            sentry_sdk.capture_exception(exc)

    async def _revoked(self, tenant_bot: TenantBot) -> None:
        self.revoked_tokens.add(tenant_bot.token)
        log.error("bot.token_revoked bot=%s tenant=%s", tenant_bot.bot_id, tenant_bot.organization_id)
        if tenant_bot.source == "tenant":
            await asyncio.to_thread(
                telegram_bots.record_bot_error_sync, tenant_bot.bot_id,
                "Telegram токеныг хүчингүй болгосон байна. BotFather-аас шинэ токен авч дахин холбоно уу.",
                disable=True,
            )


async def main():
    dp = build_dispatcher()
    scheduler.start()
    rebuild_jobs()
    try:
        # Warm the OpenAI key cache so sync availability checks (voice, task
        # AI) also see a key configured only in platform settings.
        from app.services.ai_gateway.runtime import openai_api_key

        await openai_api_key()
    except Exception:
        log.warning("bot.ai_runtime_warmup_failed", exc_info=True)

    pool = BotPool(dp)
    log.info("Scheduler started, supervising tenant bots...")
    try:
        while True:
            try:
                await pool.sync()
            except Exception:
                log.exception("bot.supervise_failed")
            await asyncio.sleep(SUPERVISE_INTERVAL_SECONDS)
    finally:
        await pool.stop_all()


if __name__ == "__main__":
    asyncio.run(main())
