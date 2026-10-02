"""Inline-клавиатуры бота (вынесены из хендлеров)."""
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def google_calendar_task_url(
    task_id: int,
    *,
    title: str | None = None,
    deadline: datetime | None = None,
    description: str | None = None,
    timezone_name: str | None = None,
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
        tz_name = timezone_name or "UTC"
        try:
            calendar_tz = ZoneInfo(tz_name)
        except Exception:
            calendar_tz = timezone.utc
            tz_name = "UTC"
        start = deadline.astimezone(calendar_tz)
        end = start + timedelta(hours=1)
        # Google Calendar reliably applies ctz to timezone-less local timestamps.
        params["dates"] = f"{start:%Y%m%dT%H%M%S}/{end:%Y%m%dT%H%M%S}"
        params["ctz"] = tz_name
    return "https://calendar.google.com/calendar/render?" + urlencode(params)


def task_reminder_kb(task_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Дууссан", callback_data=f"task:done:{task_id}"),
            ],
            [
                InlineKeyboardButton(text="⏰ 1 цагаар хойшлуулах", callback_data=f"task:snooze:{task_id}:60"),
                InlineKeyboardButton(text="⏰ 1 өдрөөр хойшлуулах", callback_data=f"task:snooze:{task_id}:1440"),
            ],
        ]
    )


def task_actions_kb(
    task_id: int,
    *,
    title: str | None = None,
    deadline: datetime | None = None,
    description: str | None = None,
    timezone_name: str | None = None,
    include_submit_for_review: bool = True,
    task_url: str | None = None,
    language: str = "mn",
) -> InlineKeyboardMarkup:
    labels = {
        "en": ("✅ Done", "🔎 Submit for review", "⏰ Snooze 1 day", "📋 Open task", "📅 Add to Google Calendar"),
        "ru": ("✅ Готово", "🔎 Отправить на проверку", "⏰ Отложить на 1 день", "📋 Открыть задачу", "📅 Добавить в Google Календарь"),
    }.get(language, ("✅ Дууссан", "🔎 Хянахад илгээх", "⏰ 1 өдрөөр хойшлуулах", "📋 Даалгаврыг нээх", "📅 Google Calendar-д нэмэх"))
    actions = [InlineKeyboardButton(text=labels[0], callback_data=f"task:done:{task_id}")]
    if include_submit_for_review:
        actions.append(InlineKeyboardButton(text=labels[1], callback_data=f"task:review:{task_id}"))
    actions.append(InlineKeyboardButton(text=labels[2], callback_data=f"task:snooze:{task_id}:1440"))
    rows = [actions]
    if task_url:
        rows.append([InlineKeyboardButton(text=labels[3], url=task_url)])
    rows.append([InlineKeyboardButton(
                text=labels[4],
                url=google_calendar_task_url(
                    task_id,
                    title=title,
                    deadline=deadline,
                    description=description,
                    timezone_name=timezone_name,
                ),
            )])
    return InlineKeyboardMarkup(inline_keyboard=rows)
