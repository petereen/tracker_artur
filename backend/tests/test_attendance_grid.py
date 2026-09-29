from datetime import date, datetime, time, timezone
from pathlib import Path
from types import SimpleNamespace

from app.hr.service import derive_attendance

ROOT = Path(__file__).parents[1]
DAY = date(2026, 9, 28)
EMPLOYEE = SimpleNamespace(id=1, organization_id=1, timezone="Asia/Ulaanbaatar")


def entry(start_hour: int, end_hour: int | None, *, mode: str = "in_person", approval: str = "approved", entry_type: str = "work"):
    # 00:00 UTC is 08:00 in Ulaanbaatar.
    return SimpleNamespace(
        entry_type=entry_type,
        approval_status=approval,
        mode=mode,
        started_at=datetime(2026, 9, 28, start_hour, tzinfo=timezone.utc),
        ended_at=datetime(2026, 9, 28, end_hour, tzinfo=timezone.utc) if end_hour is not None else None,
    )


def schedule(hour: int = 9):
    return SimpleNamespace(morning_time=time(hour, 0))


def test_approved_work_suggests_present_with_minutes_and_bounds():
    result = derive_attendance(EMPLOYEE, DAY, [entry(0, 4), entry(5, 9)], None, schedule(), today=date(2026, 9, 29))
    assert result["suggested_status"] == "present"
    assert result["worked_minutes"] == 480
    assert result["first_started_at"].hour == 0
    assert result["last_ended_at"].hour == 9
    assert result["on_leave"] is False and result["leave_type"] is None


def test_only_remote_entries_suggest_remote_and_unapproved_entries_are_ignored():
    entries = [entry(0, 4, mode="remote"), entry(5, 6, approval="pending")]
    assert derive_attendance(EMPLOYEE, DAY, entries, None, None, today=date(2026, 9, 29))["suggested_status"] == "remote"


def test_start_after_schedule_grace_is_late():
    # 03:00 UTC = 11:00 local, well past a 09:00 start.
    assert derive_attendance(EMPLOYEE, DAY, [entry(3, 6)], None, schedule(), today=date(2026, 9, 29))["suggested_status"] == "late"


def test_approved_leave_reports_its_type_without_a_status():
    leave = SimpleNamespace(time_off_type="sick")
    result = derive_attendance(EMPLOYEE, DAY, [], leave, schedule(), today=date(2026, 9, 29))
    assert result["on_leave"] is True
    assert result["leave_type"] == "sick"
    assert result["suggested_status"] is None


def test_past_scheduled_day_without_work_is_absent_but_today_is_undecided():
    assert derive_attendance(EMPLOYEE, DAY, [], None, schedule(), today=date(2026, 9, 29))["suggested_status"] == "absent"
    assert derive_attendance(EMPLOYEE, DAY, [], None, schedule(), today=DAY)["suggested_status"] is None
    assert derive_attendance(EMPLOYEE, DAY, [], None, None, today=date(2026, 9, 29))["suggested_status"] is None


def test_attendance_grid_contract():
    router = (ROOT / "app/hr/router.py").read_text()
    assert '@router.delete("/attendance")' in router
    assert "suggested_attendance_range(db, employees, start, end)" in router
    for field in ('"department_id"', '"department_name"', '"leave_type"'):
        assert field in router
