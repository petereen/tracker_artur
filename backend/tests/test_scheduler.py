from datetime import date, datetime, time
from types import SimpleNamespace

import pytz

from app.bot.scheduler import BIRTHDAY_MESSAGE, _birthday_occurs_on_day, _birthday_schedule_days, _missed_job_groups, _schedule_weekdays, _work_time_reminder_dedup_key
from app.services.digest_service import _digest_allowed_on_day, _is_task_on_day


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


def test_task_digest_skips_configured_non_workday_without_a_task():
    saturday = date(2026, 8, 22)

    assert _digest_allowed_on_day(saturday, {1, 2, 3, 4, 5}, False) is False
    assert _digest_allowed_on_day(saturday, {1, 2, 3, 4, 5}, True) is True


def test_task_deadline_is_checked_in_the_assignee_timezone():
    task = {"deadline_at": pytz.utc.localize(datetime(2026, 8, 21, 16, 30))}

    # 16:30 UTC is Saturday in Ulaanbaatar, so this is a task on Saturday
    # for a local employee even though it is still Friday in UTC.
    assert _is_task_on_day(task, "Asia/Ulaanbaatar", date(2026, 8, 22)) is True
    assert _is_task_on_day(task, "Asia/Ulaanbaatar", date(2026, 8, 21)) is False


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


def test_work_time_end_reminders_have_distinct_daily_notification_slots():
    # The Telegram text is intentionally shared, but the in-app mirror must
    # allow both the 19:00 and 23:00 reminders through.
    first = _work_time_reminder_dedup_key(7, date(2026, 8, 21), "end", 19)
    second = _work_time_reminder_dedup_key(7, date(2026, 8, 21), "end", 23)

    assert first != second


def test_birthday_greeting_matches_calendar_february_29_fallback():
    assert _birthday_occurs_on_day(date(1992, 2, 29), date(2026, 2, 28)) is True
    assert _birthday_occurs_on_day(date(1992, 2, 29), date(2028, 2, 28)) is False
    assert _birthday_occurs_on_day(date(1992, 2, 29), date(2028, 2, 29)) is True


def test_birthday_cron_days_include_leap_day_fallback():
    assert _birthday_schedule_days(date(1990, 1, 10)) == (10,)
    assert _birthday_schedule_days(date(1992, 2, 29)) == (28, 29)


def test_birthday_greeting_sends_exact_text_and_mirrors_platform(monkeypatch):
    from app.bot import scheduler

    employee = SimpleNamespace(
        id=7, name="Бат", birthday=date(1990, 1, 10), timezone="Asia/Ulaanbaatar",
        telegram_id="123", is_active=True,
    )

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, _model, _employee_id):
            return employee

    class FakeBot:
        def __init__(self):
            self.messages = []
            self.session = self

        async def send_message(self, recipient, message):
            self.messages.append((recipient, message))

        async def close(self):
            pass

    bot = FakeBot()
    mirrored = []
    monkeypatch.setattr("app.bot.db.get_session", lambda: FakeSession())
    monkeypatch.setattr(scheduler, "_make_bot", lambda: bot)
    monkeypatch.setattr(scheduler, "_local_today", lambda _timezone: date(2026, 1, 10))
    monkeypatch.setattr("app.services.user_notifications.mirror_existing_telegram_notification", lambda **kwargs: mirrored.append(kwargs))

    import asyncio
    asyncio.run(scheduler.send_birthday_greeting(employee.id))

    assert bot.messages == [("123", BIRTHDAY_MESSAGE)]
    assert mirrored[0]["kind"] == "birthday"
    assert mirrored[0]["body"] == BIRTHDAY_MESSAGE
    assert mirrored[0]["telegram_status"] == "sent"
