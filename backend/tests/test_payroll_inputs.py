from datetime import date
from decimal import Decimal

from app.payroll.inputs import payment_days


def test_confirmed_full_day_without_measured_minutes_does_not_invent_worked_hours():
    result = payment_days(
        date(2026, 9, 7), date(2026, 9, 7),
        attendance={date(2026, 9, 7): {"status": "present", "minutes": None}},
        validate_attendance=True,
    )
    assert Decimal(result["payable_workdays"]) == Decimal("1")
    assert Decimal(result["scheduled_hours"]) == Decimal("8")
    assert Decimal(result["payable_hours"]) == Decimal("0")


def test_measured_attendance_minutes_feed_actual_worked_hours():
    result = payment_days(
        date(2026, 9, 7), date(2026, 9, 7),
        attendance={date(2026, 9, 7): {"status": "present", "minutes": 420}},
        validate_attendance=True,
    )
    assert Decimal(result["payable_hours"]) == Decimal("7")
