"""Точка входа бота. Запускается как отдельный процесс."""
import asyncio
import logging

import sentry_sdk
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ErrorEvent

from app.bot.handlers import router
from app.bot.middlewares import EmployeeMiddleware
from app.bot.scheduler import rebuild_jobs, scheduler
from app.bot.tasks_handlers import router as tasks_router
from app.bot.menu import setup_bot_menus
from app.core.config import settings
from app.observability.sentry import init_from_env

init_from_env(server_name="tracker-artur-bot")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)


async def on_error(event: ErrorEvent) -> None:
    log.exception("bot.update_error", exc_info=event.exception)
    sentry_sdk.capture_exception(event.exception)


async def main():
    if not settings.BOT_TOKEN:
        log.error("BOT_TOKEN не задан — бот не запустится.")
        return

    bot = Bot(token=settings.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.errors.register(on_error)
    dp.message.middleware(EmployeeMiddleware())
    dp.callback_query.middleware(EmployeeMiddleware())
    dp.include_router(tasks_router)
    dp.include_router(router)

    scheduler.start()
    rebuild_jobs()
    await setup_bot_menus(bot, settings.MANAGER_TG_ID, settings.MINI_APP_URL)
    log.info("Scheduler started, bot polling...")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
