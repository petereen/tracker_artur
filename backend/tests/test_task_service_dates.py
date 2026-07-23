from datetime import datetime

import pytz
from sqlalchemy.dialects import postgresql

from app.services import task_service
from app.services.task_service import local_date_bounds


def test_today_uses_employee_timezone_and_half_open_range():
    zone = pytz.timezone("Asia/Ulaanbaatar")
    now = zone.localize(datetime(2026, 7, 23, 15, 30))
    start, end, include_overdue = local_date_bounds(
        "today",
        tz="Asia/Ulaanbaatar",
        now=now,
    )
    assert start.astimezone(zone).strftime("%Y-%m-%d %H:%M") == "2026-07-23 00:00"
    assert end.astimezone(zone).strftime("%Y-%m-%d %H:%M") == "2026-07-24 00:00"
    assert include_overdue is True


def test_this_week_uses_local_monday_through_sunday():
    zone = pytz.timezone("Asia/Ulaanbaatar")
    now = zone.localize(datetime(2026, 7, 23, 15, 30))  # Thursday
    start, end, include_overdue = local_date_bounds(
        "this_week",
        tz="Asia/Ulaanbaatar",
        now=now,
    )
    assert start.astimezone(zone).date().isoformat() == "2026-07-20"
    assert end.astimezone(zone).date().isoformat() == "2026-07-27"
    assert include_overdue is True


def test_invalid_timezone_falls_back_to_ulaanbaatar():
    start, end, _ = local_date_bounds(
        "custom",
        tz="Not/AZone",
        start_date=datetime(2026, 1, 1).date(),
        end_date=datetime(2026, 1, 2).date(),
    )
    zone = pytz.timezone("Asia/Ulaanbaatar")
    assert start.astimezone(zone).date().isoformat() == "2026-01-01"
    assert end.astimezone(zone).date().isoformat() == "2026-01-03"


def test_actor_query_compiles_as_one_deduplicated_select(monkeypatch):
    captured = {}

    class Result:
        def scalars(self):
            return []

    class Session:
        def execute(self, statement):
            captured["sql"] = str(
                statement.compile(
                    dialect=postgresql.dialect(),
                    compile_kwargs={"literal_binds": True},
                )
            )
            return Result()

    class SessionContext:
        def __enter__(self):
            return Session()

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(task_service, "get_session", lambda: SessionContext())
    assert task_service.list_for_actor(
        employee_id=7,
        tg_id="77",
        scope="both",
    ) == []
    assert "tasks.assignee_id = 7" in captured["sql"]
    assert "tasks.created_by_id = 7" in captured["sql"]
    assert "tasks.created_by_tg = '77'" in captured["sql"]
    assert captured["sql"].count("FROM tasks") == 1
