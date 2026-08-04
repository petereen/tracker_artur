from datetime import date, datetime, timezone
from types import SimpleNamespace

from app.services import work_report_service
from app.services.work_report_service import is_last_three_days, period_for


def test_monthly_report_period_is_first_day_of_current_month():
    assert period_for("monthly", date(2026, 8, 31)) == date(2026, 8, 1)


def test_next_month_plan_period_rolls_over_year():
    assert period_for("next_month_plan", date(2026, 12, 30)) == date(2027, 1, 1)
    assert period_for("next_month_plan_test", date(2026, 12, 30)) == date(2027, 1, 1)


def test_last_three_days_support_short_and_leap_months():
    assert is_last_three_days(date(2026, 2, 25)) is False
    assert is_last_three_days(date(2026, 2, 26)) is True
    assert is_last_three_days(date(2026, 2, 28)) is True
    assert is_last_three_days(date(2024, 2, 26)) is False
    assert is_last_three_days(date(2024, 2, 27)) is True
    assert is_last_three_days(date(2024, 2, 29)) is True


def test_work_time_keeps_the_first_selected_value(monkeypatch):
    report = SimpleNamespace(report_type="daily", started_at=None, ended_at=None)

    class FakeSession:
        commits = 0

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def get(self, _, report_id):
            return report if report_id == 7 else None

        def commit(self):
            self.commits += 1

    session = FakeSession()
    monkeypatch.setattr(work_report_service, "get_session", lambda: session)
    first = datetime(2026, 8, 4, 1, 0, tzinfo=timezone.utc)
    second = datetime(2026, 8, 4, 2, 0, tzinfo=timezone.utc)

    assert work_report_service.set_work_time(7, "started_at", first) == first
    assert work_report_service.set_work_time(7, "started_at", second) == first
    assert report.started_at == first
    assert session.commits == 1
