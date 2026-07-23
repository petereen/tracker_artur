"""Чөлөөт текстээс даалгаврын бүтэц гаргах детерминист парсер."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import dateparser
from dateparser.search import search_dates

PRIORITY_URGENT = 1
PRIORITY_NORMAL = 2
PRIORITY_LOW = 3

_URGENT_RE = re.compile(
    r"\b(срочно|asap|очень важно|немедленно|сегодня же|яаралтай|нэн яаралтай|маш чухал|нэн даруй|өнөөдөртөө)\b",
    re.IGNORECASE,
)
_LOW_RE = re.compile(
    r"\b(не срочно|низкий приоритет|когда будет время|по возможности|яаралгүй|бага ач холбогдолтой|завтай үедээ|боломжтой бол)\b",
    re.IGNORECASE,
)
_USERNAME_RE = re.compile(r"@([A-Za-z0-9_]{3,})")

_MONGOLIAN_DAYS = {
    "даваа": "понедельник", "мягмар": "вторник", "лхагва": "среда",
    "пүрэв": "четверг", "баасан": "пятница", "бямба": "суббота", "ням": "воскресенье",
}
_MONGOLIAN_RELATIVE_TIME_RE = re.compile(
    r"\b(өнөөдөр(?:төө)?|маргааш|нөгөөдөр)(?:ын|ийн)?\b.*?"
    r"\b([01]?\d|2[0-3])(?::([0-5]\d))?\s*цаг(?:аас|т)?\b",
    re.IGNORECASE,
)
_MONGOLIAN_NUMBER_WORDS = {
    "нэг": "1",
    "хоёр": "2",
    "гурван": "3",
    "дөрвөн": "4",
    "таван": "5",
    "зургаан": "6",
    "долоон": "7",
    "найман": "8",
    "есөн": "9",
    "арван": "10",
}
_MONGOLIAN_HOURS_AFTER_RE = re.compile(
    r"\b(?P<count>\d+|" + "|".join(_MONGOLIAN_NUMBER_WORDS) + r")\s*цаг(?:ийн)?\s+дараа\b",
    re.IGNORECASE,
)


def _explicit_mongolian_deadline(
    text_value: str,
    *,
    now: datetime,
    timezone_name: str,
) -> Optional[datetime]:
    """Parse relative Mongolian day/time without relying on dateparser heuristics."""
    match = _MONGOLIAN_RELATIVE_TIME_RE.search(text_value or "")
    if not match:
        return None
    day_word = match.group(1).casefold()
    days_ahead = 0 if day_word.startswith("өнөөдөр") else 1 if day_word == "маргааш" else 2
    target_date = (now + timedelta(days=days_ahead)).date()
    target_time = time(hour=int(match.group(2)), minute=int(match.group(3) or 0))
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        zone = now.tzinfo
    return datetime.combine(target_date, target_time, tzinfo=zone)


def _normalize_mongolian_dates(text: str) -> str:
    """Convert common Mongolian time phrases into forms dateparser understands.

    dateparser 1.2 does not provide a Mongolian locale, so this keeps the
    deterministic fallback usable without relying on the optional LLM path.
    """
    normalized = text
    replacements = {
        "нөгөөдөр": "послезавтра",
        "маргааш": "завтра",
        "өнөөдөртөө": "сегодня",
        "өнөөдөр": "сегодня",
    }
    for source, target in replacements.items():
        normalized = re.sub(rf"\b{source}(?:ын|ийн)?\b", target, normalized, flags=re.IGNORECASE)
    for source, target in _MONGOLIAN_DAYS.items():
        day = rf"{source}(?:\s+гараг)?(?:т|д)?"
        # dateparser recognises Russian weekday names but not reliably the
        # inflected "next weekday" forms.  With PREFER_DATES_FROM=future, the
        # bare weekday correctly resolves to the next occurrence.
        normalized = re.sub(rf"\b(?:дараагийн|ирэх)\s+{day}\b", target, normalized, flags=re.IGNORECASE)
        normalized = re.sub(rf"\bэнэ\s+{day}\b", target, normalized, flags=re.IGNORECASE)
        normalized = re.sub(rf"\b{day}\b", target, normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\b(\d+)\s*(?:минут(?:ын)?|мин)\s+дараа\b", r"через \1 минут", normalized, flags=re.IGNORECASE)

    def _replace_mongolian_hours(match: re.Match[str]) -> str:
        count = match.group("count")
        return f"через {_MONGOLIAN_NUMBER_WORDS.get(count.casefold(), count)} часов"

    normalized = _MONGOLIAN_HOURS_AFTER_RE.sub(_replace_mongolian_hours, normalized)
    normalized = re.sub(r"\b(\d+)\s*(?:хоног(?:ийн)?|өдөр(?:ийн)?|өдрийн)\s+дараа\b", r"через \1 дней", normalized, flags=re.IGNORECASE)
    # "маргааш 10 цагт" and "баасан гарагт 15 цаг" are common in task text.
    normalized = re.sub(r"\b(\d{1,2}):(\d{2})\s+цаг(?:аас|т)?\b", r"\1:\2", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\b(\d{1,2})\s+цаг(?:аас|т)?\b", r"\1:00", normalized, flags=re.IGNORECASE)
    # Mongolian postpositions often follow a numeric time: "15:00-д".
    normalized = re.sub(r"\b(\d{1,2}:\d{2})(?:-?[дт])(?=\s|$|[,.])", r"\1", normalized, flags=re.IGNORECASE)
    return normalized


@dataclass
class ParsedTask:
    title: str
    deadline_at: Optional[datetime]
    priority: int
    assignee_username: Optional[str]


def _detect_priority(text: str) -> int:
    # Check low priority first because the Russian legacy phrase contains "срочно".
    if _LOW_RE.search(text):
        return PRIORITY_LOW
    if _URGENT_RE.search(text):
        return PRIORITY_URGENT
    return PRIORITY_NORMAL


def parse_task_text(text: str, *, now: datetime, tz: str = "Asia/Ulaanbaatar") -> ParsedTask:
    """Монгол (мөн хуучин орос) чөлөөт текстийг даалгавар болгон задлана.

    ``now`` нь хэрэглэгчийн цагийн бүсэд байгаа timezone-aware утга байна.
    """
    original = (text or "").strip()
    raw = _normalize_mongolian_dates(original)

    # @username гүйцэтгэгч
    assignee_username = None
    m = _USERNAME_RE.search(raw)
    if m:
        assignee_username = m.group(1)

    priority = _detect_priority(raw)

    # Өгүүлбэр доторх огноо, цагийг хайна.
    deadline_at = _explicit_mongolian_deadline(original, now=now, timezone_name=tz)
    matched_phrase: Optional[str] = None
    settings = {
        "PREFER_DATES_FROM": "future",
        "RELATIVE_BASE": now.replace(tzinfo=None),
        "TIMEZONE": tz,
        "RETURN_AS_TIMEZONE_AWARE": True,
        "DATE_ORDER": "DMY",
    }
    try:
        found = search_dates(raw, languages=["ru", "en"], settings=settings)
    except Exception:
        found = None
    if found:
        # Ихэвчлэн хугацаа өгүүлбэрийн төгсгөлд байдаг тул сүүлийнхийг авна.
        matched_phrase, searched_deadline = found[-1]
        if deadline_at is None:
            deadline_at = searched_deadline

    # Гарчгаас @username болон танигдсан хугацааг авна.
    title = raw
    if assignee_username:
        title = title.replace(f"@{assignee_username}", " ")
    if matched_phrase:
        title = title.replace(matched_phrase, " ")
    title = re.sub(r"\s+", " ", title).strip(" .,–—-")
    if not title:
        title = raw[:60] or "Гарчиггүй"

    return ParsedTask(
        title=title[:200],
        deadline_at=deadline_at,
        priority=priority,
        assignee_username=assignee_username,
    )


def parse_when(text: str, *, now: datetime, tz: str = "Asia/Ulaanbaatar") -> Optional[datetime]:
    """/snooze-д зориулж хугацааны тусдаа хэллэгийг задлана."""
    raw = _normalize_mongolian_dates((text or "").strip())
    settings = {
        "PREFER_DATES_FROM": "future",
        "RELATIVE_BASE": now.replace(tzinfo=None),
        "TIMEZONE": tz,
        "RETURN_AS_TIMEZONE_AWARE": True,
        "DATE_ORDER": "DMY",
    }
    try:
        return dateparser.parse(raw, languages=["ru", "en"], settings=settings)
    except Exception:
        return None
