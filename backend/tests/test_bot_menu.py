from app.bot.menu import EMPLOYEE_COMMANDS, MANAGER_COMMANDS


def _commands(items):
    return {item.command for item in items}


def test_core_survey_and_help_commands_are_available_to_every_role():
    required = {"today", "help", "leaderboard", "my_stats"}
    assert required <= _commands(EMPLOYEE_COMMANDS)
    assert required <= _commands(MANAGER_COMMANDS)
