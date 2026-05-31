"""Парсер фразы задачи → структура. Детерминированный (dateparser) как основной
путь; LLM можно подключить позже опционально (без жёсткой зависимости)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import dateparser
from dateparser.search import search_dates

PRIORITY_URGENT = 1
PRIORITY_NORMAL = 2
PRIORITY_LOW = 3

_URGENT_RE = re.compile(r"\b(срочно|asap|очень важно|немедленно|сегодня же)\b", re.IGNORECASE)
_LOW_RE = re.compile(r"\b(не срочно|низкий приоритет|когда будет время|по возможности)\b", re.IGNORECASE)
_USERNAME_RE = re.compile(r"@([A-Za-z0-9_]{3,})")


@dataclass
class ParsedTask:
    title: str
    deadline_at: Optional[datetime]
    priority: int
    assignee_username: Optional[str]


def _detect_priority(text: str) -> int:
    # LOW проверяем раньше: «не срочно» иначе ловится URGENT-паттерном «срочно».
    if _LOW_RE.search(text):
        return PRIORITY_LOW
    if _URGENT_RE.search(text):
        return PRIORITY_URGENT
    return PRIORITY_NORMAL


def parse_task_text(text: str, *, now: datetime, tz: str = "Europe/Moscow") -> ParsedTask:
    """Разбирает свободную фразу на русском в структуру задачи.

    now — таймзоно-осведомлённое «сейчас» в tz пользователя (база для относительных дат).
    """
    raw = (text or "").strip()

    # @username исполнителя
    assignee_username = None
    m = _USERNAME_RE.search(raw)
    if m:
        assignee_username = m.group(1)

    priority = _detect_priority(raw)

    # Поиск даты/времени во фразе
    deadline_at: Optional[datetime] = None
    matched_phrase: Optional[str] = None
    settings = {
        "PREFER_DATES_FROM": "future",
        "RELATIVE_BASE": now.replace(tzinfo=None),
        "TIMEZONE": tz,
        "RETURN_AS_TIMEZONE_AWARE": True,
        "DATE_ORDER": "DMY",
    }
    try:
        found = search_dates(raw, languages=["ru"], settings=settings)
    except Exception:
        found = None
    if found:
        # Берём последнее совпадение — обычно дедлайн в конце фразы
        matched_phrase, deadline_at = found[-1]

    # Чистим title: убираем @username и распознанную дату-фразу
    title = raw
    if assignee_username:
        title = title.replace(f"@{assignee_username}", " ")
    if matched_phrase:
        title = title.replace(matched_phrase, " ")
    title = re.sub(r"\s+", " ", title).strip(" .,–—-")
    if not title:
        title = raw[:60] or "Без названия"

    return ParsedTask(
        title=title[:200],
        deadline_at=deadline_at,
        priority=priority,
        assignee_username=assignee_username,
    )


def parse_when(text: str, *, now: datetime, tz: str = "Europe/Moscow") -> Optional[datetime]:
    """Разбор отдельной фразы времени для /snooze (например «+1 день», «завтра 10:00»)."""
    raw = (text or "").strip()
    settings = {
        "PREFER_DATES_FROM": "future",
        "RELATIVE_BASE": now.replace(tzinfo=None),
        "TIMEZONE": tz,
        "RETURN_AS_TIMEZONE_AWARE": True,
        "DATE_ORDER": "DMY",
    }
    try:
        return dateparser.parse(raw, languages=["ru"], settings=settings)
    except Exception:
        return None
