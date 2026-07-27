from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

from app.bot.keyboards import google_calendar_task_url, task_actions_kb


def test_google_calendar_task_url_prefills_task_details_and_one_hour_event():
    url = google_calendar_task_url(
        42,
        title="Prepare quarterly report & review",
        description="Bring the latest numbers.",
        deadline=datetime(2026, 7, 27, 2, 30, tzinfo=timezone.utc),
        timezone_name="Asia/Ulaanbaatar",
    )
    query = parse_qs(urlparse(url).query)

    assert url.startswith("https://calendar.google.com/calendar/render?")
    assert query["action"] == ["TEMPLATE"]
    assert query["text"] == ["Prepare quarterly report & review"]
    assert query["details"] == ["Task #42\nBring the latest numbers."]
    assert query["dates"] == ["20260727T103000/20260727T113000"]
    assert query["ctz"] == ["Asia/Ulaanbaatar"]


def test_task_actions_keyboard_contains_google_calendar_button():
    keyboard = task_actions_kb(42, title="Prepare report")
    calendar_button = keyboard.inline_keyboard[-1][0]

    assert calendar_button.text == "📅 Google Calendar-д нэмэх"
    assert calendar_button.url.startswith("https://calendar.google.com/calendar/render?")
