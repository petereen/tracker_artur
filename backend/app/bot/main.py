"""Точка входа бота. Запускается как отдельный процесс."""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from app.bot.handlers import router
from app.bot.scheduler import rebuild_jobs, scheduler
from app.core.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)


async def main():
    if not settings.BOT_TOKEN:
        log.error("BOT_TOKEN не задан — бот не запустится.")
        return

    bot = Bot(token=settings.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    scheduler.start()
    rebuild_jobs()
    log.info("Scheduler started, bot polling...")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
