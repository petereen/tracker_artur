"""Inline-клавиатуры бота (вынесены из хендлеров)."""
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def google_calendar_task_url(
    task_id: int,
    *,
    title: str | None = None,
    deadline: datetime | None = None,
    description: str | None = None,
) -> str:
    """Build a Google Calendar event template URL for a task."""
    details = description.strip() if description else ""
    task_line = f"Task #{task_id}"
    details = f"{task_line}\n{details}" if details else task_line
    params = {
        "action": "TEMPLATE",
        "text": title or task_line,
        "details": details,
    }
    if deadline:
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        start = deadline.astimezone(timezone.utc)
        end = start + timedelta(hours=1)
        params["dates"] = f"{start:%Y%m%dT%H%M%SZ}/{end:%Y%m%dT%H%M%SZ}"
    return "https://calendar.google.com/calendar/render?" + urlencode(params)


def task_reminder_kb(task_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Дууссан", callback_data=f"task:done:{task_id}"),
            ],
            [
                InlineKeyboardButton(text="⏰ +1 цаг", callback_data=f"task:snooze:{task_id}:60"),
                InlineKeyboardButton(text="⏰ +1 өдөр", callback_data=f"task:snooze:{task_id}:1440"),
            ],
        ]
    )


def task_actions_kb(
    task_id: int,
    *,
    title: str | None = None,
    deadline: datetime | None = None,
    description: str | None = None,
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Дууссан", callback_data=f"task:done:{task_id}"),
                InlineKeyboardButton(text="⏰ +1 өдөр", callback_data=f"task:snooze:{task_id}:1440"),
            ],
            [InlineKeyboardButton(
                text="📅 Google Calendar-д нэмэх",
                url=google_calendar_task_url(
                    task_id, title=title, deadline=deadline, description=description
                ),
            )],
        ]
    )
