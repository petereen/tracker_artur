"""Inline-клавиатуры бота (вынесены из хендлеров)."""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


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


def task_actions_kb(task_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Дууссан", callback_data=f"task:done:{task_id}"),
                InlineKeyboardButton(text="⏰ +1 өдөр", callback_data=f"task:snooze:{task_id}:1440"),
            ],
        ]
    )
