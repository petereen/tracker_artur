"""Ролевое меню команд бота — setup_bot_menus вызывается при старте."""
import logging

from aiogram import Bot
from aiogram.types import (
    BotCommand,
    BotCommandScopeChat,
    BotCommandScopeDefault,
    MenuButtonCommands,
    MenuButtonWebApp,
    WebAppInfo,
)

log = logging.getLogger(__name__)

EMPLOYEE_COMMANDS: list[BotCommand] = [
    BotCommand(command="app",     description="Даалгаврын самбар нээх"),
    BotCommand(command="today",   description="Өнөөдрийн чек-ин бөглөх"),
    BotCommand(command="mytasks", description="Миний идэвхтэй даалгаврууд"),
    BotCommand(command="done",    description="Даалгаврыг дууссанд тэмдэглэх"),
    BotCommand(command="snooze",  description="Даалгаврын хугацааг хойшлуулах"),
    BotCommand(command="myid",    description="Миний Telegram ID"),
    BotCommand(command="help",    description="Командын тусламж"),
    BotCommand(command="my_stats", description="Миний статистик"),
    BotCommand(command="leaderboard", description="Багийн чансаа"),
]

MANAGER_COMMANDS: list[BotCommand] = [
    BotCommand(command="app",       description="Удирдлагын самбар нээх"),
    BotCommand(command="today",     description="Өнөөдрийн чек-ин бөглөх"),
    BotCommand(command="mytasks",   description="Миний идэвхтэй даалгаврууд"),
    BotCommand(command="done",      description="Даалгаврыг дууссанд тэмдэглэх"),
    BotCommand(command="snooze",    description="Даалгаврын хугацааг хойшлуулах"),
    BotCommand(command="myid",      description="Миний Telegram ID"),
    BotCommand(command="help",      description="Командын тусламж"),
    BotCommand(command="my_stats",  description="Миний статистик"),
    BotCommand(command="leaderboard", description="Багийн чансаа"),
    BotCommand(command="task",      description="Даалгавар үүсгэх"),
    BotCommand(command="assigned",  description="Миний өгсөн даалгаврууд"),
    BotCommand(command="dashboard", description="Даалгаврын хянах самбар"),
    BotCommand(command="summary",   description="Өчигдрийн асуулгын хураангуй"),
    BotCommand(command="week",      description="7 хоногийн асуулгын статистик"),
    BotCommand(command="blockers",  description="Сарын гол саад бэрхшээлүүд"),
]


async def setup_bot_menus(
    bot: Bot, manager_tg: str | int | None = None, mini_app_url: str = ""
) -> None:
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

    # The persistent Telegram menu button gives every registered employee a
    # one-tap entry to /tg. Telegram accepts Web Apps only over HTTPS.
    url = mini_app_url.strip()
    if url:
        try:
            await bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(text="Самбар", web_app=WebAppInfo(url=url))
            )
            log.info("Mini App button configured: %s", url)
        except Exception:
            log.exception("Не удалось установить кнопку Mini App (url=%r)", url)
    else:
        # Avoid leaving a stale Web App button after the environment setting is removed.
        try:
            await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
        except Exception:
            log.exception("Не удалось сбросить кнопку меню")
