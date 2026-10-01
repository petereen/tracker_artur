from app.bot.menu import EMPLOYEE_COMMANDS, MANAGER_COMMANDS


def _commands(items):
    return {item.command for item in items}


def test_core_survey_and_help_commands_are_available_to_every_role():
    required = {"today", "help", "leaderboard", "my_stats"}
    assert required <= _commands(EMPLOYEE_COMMANDS)
    assert required <= _commands(MANAGER_COMMANDS)


def test_menus_follow_the_tenant_and_hide_test_commands():
    from app.bot.menu import CHECKIN_COMMANDS, commands_for

    assert not _commands(MANAGER_COMMANDS) & {"test_daily", "test_monthly", "seed_monthly_digest", "test_monthly_digest"}
    assert {"task", "assigned", "dashboard"} <= _commands(commands_for(True, primary=False))
    for is_manager in (True, False):
        assert not _commands(commands_for(is_manager, primary=False)) & CHECKIN_COMMANDS
    assert "dashboard" not in _commands(commands_for(False))


def test_chat_menu_tracks_the_erp_role_and_only_calls_telegram_on_change():
    import asyncio

    from app.bot import menu

    calls = []

    class Bot:
        id = 4242

        async def set_my_commands(self, commands, scope):
            calls.append(("set", scope.chat_id, len(commands)))

        async def delete_my_commands(self, scope):
            calls.append(("reset", scope.chat_id))

    async def run():
        bot = Bot()
        await menu.sync_chat_menu(bot, 7, is_manager=True, primary=True)
        await menu.sync_chat_menu(bot, 7, is_manager=True, primary=True)
        await menu.sync_chat_menu(bot, 7, is_manager=False, primary=True)

    asyncio.run(run())
    assert calls == [("set", 7, len(MANAGER_COMMANDS)), ("reset", 7)]
