from app.bot.work_report_handlers import daily_prompt_keyboard, draft_keyboard


def test_daily_prompt_has_one_click_start_and_end_actions():
    buttons = [button.callback_data for row in daily_prompt_keyboard(42).inline_keyboard for button in row]
    assert buttons == ["wrtime:42:start", "wrtime:42:end"]


def test_draft_prompt_has_all_lifecycle_actions():
    buttons = [button.callback_data for row in draft_keyboard(7).inline_keyboard for button in row]
    assert buttons == ["wrdraft:7:approve", "wrdraft:7:edit", "wrdraft:7:delete"]
