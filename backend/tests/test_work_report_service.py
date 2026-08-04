from datetime import date

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
