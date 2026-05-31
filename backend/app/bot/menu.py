"""Ролевое меню команд бота — setup_bot_menus вызывается при старте."""
import logging

from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault

log = logging.getLogger(__name__)

EMPLOYEE_COMMANDS: list[BotCommand] = [
    BotCommand(command="today",   description="Заполнить ежедневный чек-ин"),
    BotCommand(command="mytasks", description="Мои активные задачи"),
    BotCommand(command="done",    description="Отметить задачу выполненной"),
    BotCommand(command="snooze",  description="Перенести срок задачи"),
    BotCommand(command="myid",    description="Мой Telegram ID"),
    BotCommand(command="help",    description="Справка по командам"),
]

MANAGER_COMMANDS: list[BotCommand] = [
    BotCommand(command="today",     description="Заполнить ежедневный чек-ин"),
    BotCommand(command="mytasks",   description="Мои активные задачи"),
    BotCommand(command="done",      description="Отметить задачу выполненной"),
    BotCommand(command="snooze",    description="Перенести срок задачи"),
    BotCommand(command="myid",      description="Мой Telegram ID"),
    BotCommand(command="help",      description="Справка по командам"),
    BotCommand(command="task",      description="Поставить задачу"),
    BotCommand(command="assigned",  description="Задачи, поставленные мной"),
    BotCommand(command="dashboard", description="Сводный дашборд задач"),
    BotCommand(command="summary",   description="Сводка опросов за вчера"),
    BotCommand(command="week",      description="Статистика опросов за 7 дней"),
    BotCommand(command="blockers",  description="Топ блокеров за месяц"),
]


async def setup_bot_menus(bot: Bot, manager_tg: str | int | None = None) -> None:
    """Регистрирует команды в Telegram.

    - Default scope (все пользователи) → EMPLOYEE_COMMANDS.
    - Если manager_tg задан → для этого чата дополнительно → MANAGER_COMMANDS.
    """
    try:
        await bot.set_my_commands(EMPLOYEE_COMMANDS, scope=BotCommandScopeDefault())
        log.info("Меню сотрудника установлено (%d команд)", len(EMPLOYEE_COMMANDS))
    except Exception:
        log.exception("Не удалось установить меню по умолчанию")

    if manager_tg is not None:
        try:
            chat_id = int(manager_tg)
            await bot.set_my_commands(
                MANAGER_COMMANDS,
                scope=BotCommandScopeChat(chat_id=chat_id),
            )
            log.info(
                "Меню руководителя установлено для chat_id=%d (%d команд)",
                chat_id,
                len(MANAGER_COMMANDS),
            )
        except Exception:
            log.exception("Не удалось установить меню руководителя (manager_tg=%r)", manager_tg)
