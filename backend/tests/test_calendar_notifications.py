from pathlib import Path

from app.services.reminder_service import _render_outbox


def test_calendar_collaborator_creation_explicitly_delivers_to_both_channels():
    source = (Path(__file__).parents[1] / "app/routers/enterprise.py").read_text()
    helper = source[source.index("async def _notify_calendar_collaborators"):source.index("def _holiday_provider_rows")]

    assert "await create_notifications(" in helper
    assert "employee_ids=collaborator_ids" in helper
    assert "deliver_telegram=True" in helper
    assert "_notify_calendar_collaborators(" in source[source.index("async def create_calendar_entry"):]


def test_calendar_collaborator_telegram_message_contains_item_details_and_link():
    text, keyboard = _render_outbox({
        "kind": "event",
        "task_id": None,
        "payload": {
            "title": "Багийн уулзалт",
            "body": "Таныг “Багийн уулзалт”-д оролцогчоор нэмлээ.",
            "starts_at": "2026-09-02T03:00:00+00:00",
            "location": "Оффис 2",
            "target_url": "/calendar",
        },
    })

    assert "Багийн уулзалт" in text
    assert "Оффис 2" in text
    assert "Календарь нээх" in text
    assert "/calendar" in text
    assert keyboard is None
