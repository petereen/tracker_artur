import asyncio
from types import SimpleNamespace

from app.bot import work_report_handlers
from app.bot.work_report_handlers import _draft_text, _prompt_text, checkin_keyboard, draft_keyboard, send_daily_prompts, work_time_keyboard


def test_draft_prompt_has_all_lifecycle_actions():
    buttons = [button.callback_data for row in draft_keyboard(7).inline_keyboard for button in row]
    assert buttons == ["wrdraft:7:approve", "wrdraft:7:edit", "wrdraft:7:delete"]


def test_daily_checkin_and_report_are_separate_prompts():
    checkin = _prompt_text("daily", "daily_checkin")
    report = _prompt_text("daily", "daily_report")
    assert "чек-ин" in checkin
    assert "товч" in checkin
    assert "ажлын тайлан" in report
    assert [button.callback_data for row in checkin_keyboard().inline_keyboard for button in row] == ["checkin:start"]


def test_work_time_prompts_have_one_action_each():
    start = [button.callback_data for row in work_time_keyboard(42, "start").inline_keyboard for button in row]
    end = [button.callback_data for row in work_time_keyboard(42, "end").inline_keyboard for button in row]
    assert len(start) == len(end) == 35
    assert start[0] == "wrtime:42:start:0600"
    assert start[-1] == "wrtime:42:start:2300"
    assert end[0] == "wrtime:42:end:0600"
    assert end[-1] == "wrtime:42:end:2300"


def test_daily_time_prompt_texts_are_distinct_from_report_text():
    assert "эхэлсэн" in _prompt_text("daily", "daily_start")
    assert "дууссан" in _prompt_text("daily", "daily_end")
    assert "ажлын тайлан" in _prompt_text("daily", "daily_report")


def test_daily_prompt_orchestration_has_the_required_order(monkeypatch):
    sent = []

    async def fake_send_report_prompt(bot, report, *, telegram_chat_id, prompt_type, local_day):
        sent.append(prompt_type)
        return True

    monkeypatch.setattr(work_report_handlers, "send_report_prompt", fake_send_report_prompt)
    report = SimpleNamespace(report_type="daily_test")
    labels = asyncio.run(send_daily_prompts(None, report, telegram_chat_id="1", local_day=None))

    assert sent == ["test_daily_checkin", "test_daily_report", "test_daily_start", "test_daily_end"]
    assert labels == ["өдрийн чек-ин", "өдрийн тайлан", "ажил эхэлсэн цаг", "ажил дууссан цаг"]


def test_report_draft_renders_the_worker_raw_text_without_rewriting():
    report = SimpleNamespace(report_type="daily")
    raw_text = "  Борлуулалт <10%> өссөн.  "

    rendered = _draft_text(report, raw_text)

    assert "  Борлуулалт &lt;10%&gt; өссөн.  " in rendered
