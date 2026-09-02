import asyncio
from types import SimpleNamespace

from app.bot import work_report_handlers
from app.bot.work_report_handlers import (
    _draft_text,
    _prompt_text,
    checkin_keyboard,
    cmd_monthly_digest,
    draft_keyboard,
    send_daily_prompts,
    send_test_daily_report_prompt,
)


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
    assert [button.callback_data for row in checkin_keyboard(True).inline_keyboard for button in row] == ["checkin:start:test"]


def test_daily_report_prompt_does_not_include_work_time_prompts():
    assert "ажлын тайлан" in _prompt_text("daily", "daily_report")
    assert "эхэлсэн цаг" not in _prompt_text("daily", "daily_report")
    assert "дууссан цаг" not in _prompt_text("daily", "daily_report")


def test_daily_prompt_orchestration_starts_with_checkin_only(monkeypatch):
    sent = []

    async def fake_send_report_prompt(bot, report, *, telegram_chat_id, prompt_type, local_day):
        sent.append(prompt_type)
        return True

    monkeypatch.setattr(work_report_handlers, "send_report_prompt", fake_send_report_prompt)
    report = SimpleNamespace(report_type="daily")
    labels = asyncio.run(send_daily_prompts(None, report, telegram_chat_id="1", local_day=None))

    assert sent == ["daily_checkin"]
    assert labels == ["өдрийн чек-ин"]


def test_test_daily_advances_to_the_report_only_after_checkin(monkeypatch):
    report = SimpleNamespace(id=9, report_type="daily_test")
    captured = {}

    monkeypatch.setattr(work_report_handlers.work_report_service, "get_or_create_report", lambda *_: report)

    async def fake_send_report_prompt(bot, supplied_report, **kwargs):
        captured["report"] = supplied_report
        captured.update(kwargs)
        return True

    monkeypatch.setattr(work_report_handlers, "send_report_prompt", fake_send_report_prompt)

    assert asyncio.run(send_test_daily_report_prompt(None, employee_id=3, telegram_chat_id="1", local_day=None)) is True
    assert captured["report"] is report
    assert captured["prompt_type"] == "test_daily_report"


def test_report_draft_renders_the_worker_raw_text_without_rewriting():
    report = SimpleNamespace(report_type="daily")
    raw_text = "  Борлуулалт <10%> өссөн.  "

    rendered = _draft_text(report, raw_text)

    assert "  Борлуулалт &lt;10%&gt; өссөн.  " in rendered


def test_monthly_digest_is_restricted_to_configured_manager_recipients(monkeypatch):
    answers = []

    async def answer(text):
        answers.append(text)

    message = SimpleNamespace(chat=SimpleNamespace(id="worker-1"), answer=answer)
    monkeypatch.setattr(work_report_handlers, "get_manager_settings", lambda: SimpleNamespace())
    monkeypatch.setattr(work_report_handlers, "manager_telegram_ids", lambda _: ["manager-1"])

    asyncio.run(cmd_monthly_digest(message))

    assert answers == ["❌ Энэ команд зөвхөн telegram_admin_ids-д бүртгэгдсэн удирдлагад зориулсан."]


def test_monthly_digest_sends_on_demand_only_to_configured_recipients(monkeypatch):
    calls = []
    answers = []

    async def answer(text):
        answers.append(text)

    async def fake_send(today, *, recipients, reserve):
        calls.append((today, recipients, reserve))
        return True

    message = SimpleNamespace(chat=SimpleNamespace(id="manager-1"), answer=answer)
    monkeypatch.setattr(work_report_handlers, "get_manager_settings", lambda: SimpleNamespace())
    monkeypatch.setattr(work_report_handlers, "manager_telegram_ids", lambda _: ["manager-1", "manager-2"])
    monkeypatch.setattr(work_report_handlers, "try_send_monthly_report_digest", fake_send)

    asyncio.run(cmd_monthly_digest(message))

    assert len(calls) == 1
    assert calls[0][1:] == (["manager-1", "manager-2"], False)
    assert answers == []
