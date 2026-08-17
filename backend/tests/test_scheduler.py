from datetime import time
from types import SimpleNamespace

import pytz

from app.bot.scheduler import _missed_job_groups, _schedule_weekdays


def test_schedule_weekdays_defaults_to_monday_through_friday():
    assert _schedule_weekdays(None) == (1, 2, 3, 4, 5)
    assert _schedule_weekdays(SimpleNamespace(weekdays=[])) == (1, 2, 3, 4, 5)


def test_schedule_weekdays_preserves_employee_configuration():
    schedule = SimpleNamespace(weekdays=[1, 3, 6])

    assert _schedule_weekdays(schedule) == (1, 3, 6)


def test_worker_digest_weekdays_use_employee_schedule():
    schedule = SimpleNamespace(weekdays=[2, 4, 7])

    weekdays = _schedule_weekdays(schedule)
    digest_dow = ",".join(str(day - 1) for day in weekdays)

    assert digest_dow == "1,3,6"


def test_missed_checkin_jobs_group_employees_with_the_same_deadline():
    timezone = pytz.timezone("Asia/Ulaanbaatar")
    deadline = time(23, 0)
    groups = list(_missed_job_groups([
        (SimpleNamespace(id=1), None, timezone, deadline, (1, 2, 3, 4, 5)),
        (SimpleNamespace(id=2), None, timezone, deadline, (1, 2, 3, 4, 5)),
        (SimpleNamespace(id=3), None, timezone, time(22, 0), (1, 2, 3, 4, 5)),
    ]))

    assert len(groups) == 2
    assert next(group for group in groups if group["deadline"] == deadline)["employee_ids"] == [1, 2]
