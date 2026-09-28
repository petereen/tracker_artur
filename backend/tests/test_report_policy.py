from datetime import date, timedelta

import pytest

from app.services.report_policy import (
    department_frequencies,
    frequency_for,
    period_for_frequency,
    reminder_window_open,
    report_policy,
    report_type_for,
    validate_policy_input,
    worker_frequencies,
)


def policy_with(**raw):
    return report_policy({"report_policy": raw})


def test_missing_policy_keeps_daily_and_monthly_reports():
    policy = report_policy(None)
    assert policy["worker_frequencies"] == ["daily", "monthly"]
    assert policy["reminder_days"] == 3
    assert policy["departments"] == [] and policy["custom_periods"] == []


def test_explicit_empty_worker_frequencies_disable_personal_reports():
    assert policy_with(worker_frequencies=[])["worker_frequencies"] == []


def test_standard_periods_contain_the_day():
    policy = report_policy(None)
    day = date(2026, 9, 28)  # Monday
    weekly = period_for_frequency(policy, "weekly", date(2026, 10, 1))
    assert (weekly.start, weekly.end) == (date(2026, 9, 28), date(2026, 10, 4))
    monthly = period_for_frequency(policy, "monthly", day)
    assert (monthly.start, monthly.end) == (date(2026, 9, 1), date(2026, 9, 30))
    quarterly = period_for_frequency(policy, "quarterly", day)
    assert (quarterly.start, quarterly.end) == (date(2026, 7, 1), date(2026, 9, 30))
    yearly = period_for_frequency(policy, "yearly", day)
    assert (yearly.start, yearly.end) == (date(2026, 1, 1), date(2026, 12, 31))
    daily = period_for_frequency(policy, "daily", day)
    assert daily.start == daily.end == day and daily.report_type == "daily" and daily.period_key == ""


def test_custom_periods_repeat_from_the_anchor_in_both_directions():
    policy = policy_with(custom_periods=[
        {"id": "sprint", "label": "Спринт", "unit": "week", "interval": 2, "anchor_date": "2026-09-07"},
        {"id": "half", "label": "Хагас жил", "unit": "month", "interval": 6, "anchor_date": "2026-01-15"},
    ])
    sprint = period_for_frequency(policy, "custom:sprint", date(2026, 9, 28))
    assert (sprint.start, sprint.end) == (date(2026, 9, 21), date(2026, 10, 4))
    assert sprint.report_type == "custom" and sprint.period_key == "sprint" and sprint.label == "Спринт"
    before_anchor = period_for_frequency(policy, "custom:sprint", date(2026, 9, 1))
    assert (before_anchor.start, before_anchor.end) == (date(2026, 8, 24), date(2026, 9, 6))
    half = period_for_frequency(policy, "custom:half", date(2026, 9, 28))
    assert (half.start, half.end) == (date(2026, 7, 15), date(2027, 1, 14))
    assert period_for_frequency(policy, "custom:missing", date(2026, 9, 28)) is None


def test_invalid_custom_periods_are_dropped_on_read_and_rejected_on_write():
    policy = policy_with(custom_periods=[{"id": "Bad Id", "unit": "week", "interval": 1, "anchor_date": "2026-01-01"}], worker_frequencies=["custom:Bad Id", "weekly"])
    assert policy["custom_periods"] == [] and policy["worker_frequencies"] == ["weekly"]
    with pytest.raises(ValueError):
        validate_policy_input({"custom_periods": [{"id": "x", "unit": "year", "interval": 1, "anchor_date": "2026-01-01"}]})
    with pytest.raises(ValueError):
        validate_policy_input({"worker_frequencies": ["custom:nope"]})


def test_department_rules_override_workers_and_add_department_reports():
    policy = policy_with(
        worker_frequencies=["daily", "monthly"],
        departments=[
            {"department_id": 3, "worker_frequencies": ["weekly"], "department_frequencies": ["monthly", "yearly", "daily"]},
            {"department_id": 4, "worker_frequencies": None, "department_frequencies": ["quarterly"]},
        ],
    )
    assert worker_frequencies(policy, 3) == ["weekly"]
    assert worker_frequencies(policy, 4) == ["daily", "monthly"]
    assert worker_frequencies(policy, None) == ["daily", "monthly"]
    # Department reports are periodic summaries; a daily department report is dropped.
    assert department_frequencies(policy, 3) == ["monthly", "yearly"]
    assert department_frequencies(policy, 99) == []


def test_reminder_window_covers_the_end_of_each_period():
    policy = report_policy(None)
    monthly = period_for_frequency(policy, "monthly", date(2026, 9, 10))
    assert not reminder_window_open(monthly, date(2026, 9, 27), 3)
    assert all(reminder_window_open(monthly, date(2026, 9, day), 3) for day in (28, 29, 30))
    weekly = period_for_frequency(policy, "weekly", date(2026, 9, 28))
    assert [reminder_window_open(weekly, date(2026, 9, 28) + timedelta(days=offset), 5) for offset in range(7)] == [False, False, False, False, True, True, True]


def test_frequency_ids_round_trip_to_stored_report_types():
    assert report_type_for("custom:sprint") == ("custom", "sprint")
    assert report_type_for("quarterly") == ("quarterly", "")
    assert frequency_for("custom", "sprint") == "custom:sprint"
    assert frequency_for("monthly", "") == "monthly"


def test_due_report_periods_include_led_department_reports():
    from app.bot.scheduler import due_report_periods

    policy = policy_with(worker_frequencies=["daily", "weekly"], departments=[{"department_id": 7, "department_frequencies": ["monthly"]}])
    scope = {"policy": policy, "frequencies": ["daily", "weekly"], "led_departments": {7: ["monthly"]}}
    due = due_report_periods(scope, date(2026, 9, 30))  # Wednesday, last day of month
    assert [(period.report_type, department) for period, department in due] == [("monthly", 7)]
    sunday = due_report_periods(scope, date(2026, 10, 4))
    assert [(period.report_type, department) for period, department in sunday] == [("weekly", None)]
