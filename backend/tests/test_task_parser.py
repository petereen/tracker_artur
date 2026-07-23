from datetime import datetime

import pytz
import pytest

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


MNG = pytz.timezone("Asia/Ulaanbaatar")
MONGOLIAN_NOW = MNG.localize(datetime(2026, 6, 1, 10, 0))  # Monday


def test_parses_mongolian_relative_deadline_and_priority():
    p = parse_task_text("@bat тайланг маргааш 15 цагт илгээ, яаралтай", now=MONGOLIAN_NOW, tz="Asia/Ulaanbaatar")
    assert p.assignee_username == "bat"
    assert p.priority == PRIORITY_URGENT
    assert p.deadline_at is not None
    assert p.deadline_at.hour == 15
    assert p.deadline_at > MONGOLIAN_NOW
    assert "тайланг" in p.title
    assert "маргааш" not in p.title


def test_parses_mongolian_weekday_and_relative_duration():
    friday = parse_when("дараагийн баасан гарагт 14 цаг", now=MONGOLIAN_NOW, tz="Asia/Ulaanbaatar")
    in_two_days = parse_when("2 хоногийн дараа", now=MONGOLIAN_NOW, tz="Asia/Ulaanbaatar")
    assert friday is not None
    assert friday.weekday() == 4
    assert friday.hour == 14
    assert in_two_days is not None
    assert in_two_days > MONGOLIAN_NOW


def test_parses_mongolian_time_postposition_and_cleans_title():
    p = parse_task_text("тайланг маргааш 15:00-д илгээ", now=MONGOLIAN_NOW, tz="Asia/Ulaanbaatar")
    assert p.deadline_at is not None
    assert p.deadline_at.hour == 15
    assert p.title == "тайланг илгээ"


def test_parses_mongolian_time_from_postposition_as_local_hour():
    p = parse_task_text(
        "Маргааш би 15 цагаас хуралтай",
        now=MONGOLIAN_NOW,
        tz="Asia/Ulaanbaatar",
    )
    assert p.deadline_at is not None
    assert p.deadline_at.date() == MONGOLIAN_NOW.date().replace(day=2)
    assert p.deadline_at.hour == 15
    assert p.deadline_at.utcoffset() == MONGOLIAN_NOW.utcoffset()


def test_recognizes_mongolian_low_priority():
    p = parse_task_text("танилцуулгыг завтай үедээ бэлд", now=MONGOLIAN_NOW, tz="Asia/Ulaanbaatar")
    assert p.priority == PRIORITY_LOW


def test_parses_mongolian_today_and_day_genitive_forms():
    today = parse_when("өнөөдөртөө", now=MONGOLIAN_NOW, tz="Asia/Ulaanbaatar")
    in_two_days = parse_when("2 өдрийн дараа", now=MONGOLIAN_NOW, tz="Asia/Ulaanbaatar")
    assert today is not None
    assert today.date() == MONGOLIAN_NOW.date()
    assert in_two_days is not None
    assert in_two_days.date() == MONGOLIAN_NOW.date().replace(day=3)


@pytest.mark.parametrize("text", ["Хоёр цагийн дараа", "2 цагийн дараа"])
def test_parses_mongolian_relative_hours_written_as_word_or_number(text):
    deadline = parse_when(text, now=MONGOLIAN_NOW, tz="Asia/Ulaanbaatar")
    assert deadline is not None
    assert deadline == MONGOLIAN_NOW.replace(hour=12)
