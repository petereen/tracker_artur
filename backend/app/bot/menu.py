"""Ролевое меню команд бота: меню по умолчанию — при старте, меню руководителя — по ERP-ролям."""
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
    BotCommand(command="daystart", description="Ажил эхэлсэн цаг бүртгэх"),
    BotCommand(command="dayend",   description="Ажил дууссан цаг бүртгэх"),
    BotCommand(command="remotestart", description="Remote ажил эхэлсэн цаг бүртгэх"),
    BotCommand(command="remoteend",   description="Remote ажил дууссан цаг бүртгэх"),
    BotCommand(command="daypause", description="Ажлын цаг түр зогсоох"),
    BotCommand(command="worktime", description="Өнөөдрийн ажлын цаг харах"),
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
    BotCommand(command="daystart",  description="Ажил эхэлсэн цаг бүртгэх"),
    BotCommand(command="dayend",    description="Ажил дууссан цаг бүртгэх"),
    BotCommand(command="remotestart", description="Remote ажил эхэлсэн цаг бүртгэх"),
    BotCommand(command="remoteend",   description="Remote ажил дууссан цаг бүртгэх"),
    BotCommand(command="daypause", description="Ажлын цаг түр зогсоох"),
    BotCommand(command="worktime", description="Өнөөдрийн ажлын цаг харах"),
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
    BotCommand(command="monthly_digest", description="Сарын тайлангийн хураангуй авах"),
]


# Check-in surveys predate tenancy and exist for the primary tenant only.
CHECKIN_COMMANDS = frozenset({"today", "my_stats", "leaderboard", "summary", "week", "blockers"})

# Last menu pushed to a private chat by this process: (manager, primary).
_chat_menus: dict[tuple[int, int], tuple[bool, bool]] = {}


def commands_for(is_manager: bool, primary: bool = True) -> list[BotCommand]:
    """Menu for a role inside a tenant (management = ERP roles, see middleware)."""
    commands = MANAGER_COMMANDS if is_manager else EMPLOYEE_COMMANDS
    return commands if primary else [item for item in commands if item.command not in CHECKIN_COMMANDS]


async def sync_chat_menu(bot: Bot, chat_id: int, *, is_manager: bool, primary: bool) -> None:
    """Keep a worker's private-chat menu in step with their current ERP role.

    Called on every update; Telegram is only contacted when the role changed
    (or once after a restart), so a promotion or demotion in the ERP shows up
    on the worker's next message."""
    key, wanted = (bot.id, chat_id), (is_manager, primary)
    if _chat_menus.get(key) == wanted:
        return
    try:
        scope = BotCommandScopeChat(chat_id=chat_id)
        if is_manager:
            await bot.set_my_commands(commands_for(True, primary), scope=scope)
        else:
            # Back to the bot's default (employee) menu.
            await bot.delete_my_commands(scope=scope)
        _chat_menus[key] = wanted
    except Exception:
        log.exception("bot.chat_menu_failed chat=%s", chat_id)


async def setup_bot_menus(bot: Bot, mini_app_url: str = "", *, primary: bool = True) -> None:
    """Registers the default (employee) menu and the Mini App button.

    Management menus are per chat and follow ERP roles: see ``sync_chat_menu``."""
    try:
        await bot.set_my_commands(commands_for(False, primary), scope=BotCommandScopeDefault())
    except Exception:
        log.exception("Не удалось установить меню по умолчанию")

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
