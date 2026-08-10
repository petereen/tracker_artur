from types import SimpleNamespace

from app.bot.scheduler import _schedule_weekdays


def test_schedule_weekdays_defaults_to_monday_through_friday():
    assert _schedule_weekdays(None) == (1, 2, 3, 4, 5)
    assert _schedule_weekdays(SimpleNamespace(weekdays=[])) == (1, 2, 3, 4, 5)


def test_schedule_weekdays_preserves_employee_configuration():
    schedule = SimpleNamespace(weekdays=[1, 3, 6])

    assert _schedule_weekdays(schedule) == (1, 3, 6)
