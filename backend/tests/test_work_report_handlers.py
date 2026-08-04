from app.bot.work_report_handlers import daily_prompt_keyboard, draft_keyboard, work_time_keyboard, _prompt_text


def test_daily_prompt_has_one_click_start_and_end_actions():
    buttons = [button.callback_data for row in daily_prompt_keyboard(42).inline_keyboard for button in row]
    assert buttons == ["wrtime:42:start", "wrtime:42:end"]


def test_draft_prompt_has_all_lifecycle_actions():
    buttons = [button.callback_data for row in draft_keyboard(7).inline_keyboard for button in row]
    assert buttons == ["wrdraft:7:approve", "wrdraft:7:edit", "wrdraft:7:delete"]


def test_daily_checkin_and_report_are_separate_prompts():
    checkin = _prompt_text("daily", "daily_checkin")
    report = _prompt_text("daily", "daily_report")
    assert "чек-ин" in checkin
    assert "/today" in checkin
    assert "ажлын тайлан" in report
    assert "/today" not in report


def test_work_time_prompts_have_one_action_each():
    start = [button.callback_data for row in work_time_keyboard(42, "start").inline_keyboard for button in row]
    end = [button.callback_data for row in work_time_keyboard(42, "end").inline_keyboard for button in row]
    assert start == ["wrtime:42:start"]
    assert end == ["wrtime:42:end"]
