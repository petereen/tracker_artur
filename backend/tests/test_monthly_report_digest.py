"""End-to-end logic checks for the monthly management report digest.

Run directly with:

    cd backend && python -m pytest -q tests/test_monthly_report_digest.py

The reports below are deliberately dummy, in-memory records.  The test calls
the real digest orchestration, but never writes to the database, calls OpenAI,
or sends a Telegram message.
"""
import asyncio
from datetime import date
from types import SimpleNamespace

from app.services import monthly_report_digest_service as digest


def dummy_reports() -> tuple[list[str], list[tuple[str, str]]]:
    """Create the complete set of approved monthly reports for one period."""
    reports = [
        (
            "Бат",
            "Шинэ борлуулалтын тайлангийн самбар боловсруулж, 12 хэрэглэгчийн санал авсан.",
        ),
        (
            "Саруул",
            "Нөөцийн бүртгэлийг шинэчилж, нийлүүлэлтийн саатлын эрсдэлийг бууруулах төлөвлөгөө гаргасан.",
        ),
    ]
    return [name for name, _ in reports], reports


class FakeBot:
    def __init__(self):
        self.sent: list[tuple[str, str]] = []
        self.session = self

    async def send_message(self, recipient: str, message: str):
        self.sent.append((recipient, message))

    async def close(self):
        pass


def test_monthly_digest_summarizes_dummy_reports_and_sends_once(monkeypatch):
    worker_names, reports = dummy_reports()
    bot = FakeBot()
    reserved: list[date] = []

    monkeypatch.setattr(digest, "_reports_for_period", lambda period, report_type="monthly": (worker_names, reports))
    monkeypatch.setattr(digest, "get_manager_settings", lambda: SimpleNamespace())
    monkeypatch.setattr(digest, "manager_telegram_ids", lambda _: ["manager-1"])
    monkeypatch.setattr(digest, "_reserve", lambda period: reserved.append(period) or True)
    monkeypatch.setattr(digest, "_ai_summary", lambda _: None)

    from app.bot import scheduler

    monkeypatch.setattr(scheduler, "_make_bot", lambda: bot)

    assert asyncio.run(digest.try_send_monthly_report_digest(date(2026, 8, 4))) is True
    assert reserved == [date(2026, 7, 1)]
    assert len(bot.sent) == 1

    recipient, message = bot.sent[0]
    assert recipient == "manager-1"
    assert "2026 оны 07-р сарын AI хураангуй" in message
    assert "Тайлан баталсан: <b>2/2</b> ажилтан" in message
    assert "Бат: Шинэ борлуулалтын тайлангийн самбар" in message
    assert "Саруул: Нөөцийн бүртгэлийг шинэчилж" in message


def test_monthly_digest_waits_until_every_active_worker_has_submitted(monkeypatch):
    monkeypatch.setattr(
        digest,
        "_reports_for_period",
        lambda period, report_type="monthly": (["Бат", "Саруул"], [("Бат", "Зөвхөн нэг тайлан")]),
    )
    reserve_called = False

    def reserve(period):
        nonlocal reserve_called
        reserve_called = True
        return True

    monkeypatch.setattr(digest, "_reserve", reserve)
    monkeypatch.setattr(digest, "get_manager_settings", lambda: SimpleNamespace())
    monkeypatch.setattr(digest, "manager_telegram_ids", lambda _: ["manager-1"])

    assert asyncio.run(digest.try_send_monthly_report_digest(date(2026, 8, 4))) is False
    assert reserve_called is False
