from datetime import datetime

import pytz

from app.services.task_parser import (
    PRIORITY_LOW,
    PRIORITY_NORMAL,
    PRIORITY_URGENT,
    parse_task_text,
    parse_when,
)

MSK = pytz.timezone("Europe/Moscow")
NOW = MSK.localize(datetime(2026, 5, 31, 10, 0))  # воскресенье


def test_extracts_username_priority_and_cleans_title():
    p = parse_task_text("@ivan позвонить клиенту завтра в 15:00, срочно", now=NOW, tz="Europe/Moscow")
    assert p.assignee_username == "ivan"
    assert p.priority == PRIORITY_URGENT
    assert p.deadline_at is not None
    assert "@ivan" not in p.title
    assert "позвонить" in p.title.lower()


def test_low_priority_keyword():
    p = parse_task_text("подготовить отчёт, не срочно", now=NOW)
    assert p.priority == PRIORITY_LOW


def test_default_priority_and_no_username():
    p = parse_task_text("обновить прайс-лист", now=NOW)
    assert p.priority == PRIORITY_NORMAL
    assert p.assignee_username is None
    assert p.title == "обновить прайс-лист"


def test_relative_deadline_is_in_future():
    p = parse_task_text("сделать завтра в 9:00", now=NOW)
    assert p.deadline_at is not None
    assert p.deadline_at > NOW


def test_parse_when_relative():
    dt = parse_when("через 2 дня", now=NOW)
    assert dt is not None
    assert dt > NOW


def test_title_fallback_not_empty():
    p = parse_task_text("@ivan", now=NOW)
    assert p.title  # не пустой даже если остался только username
