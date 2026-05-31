"""
Модуль политики уведомлений: тихие часы, рабочее окно, выходные.

Чистый модуль — только stdlib + pytz. Без импортов БД / планировщика / aiogram.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, date

import pytz

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULTS = dict(
    quiet_start=time(20, 0),
    quiet_end=time(9, 0),
    work_weekdays=frozenset({1, 2, 3, 4, 5}),  # ISO: 1=Пн … 7=Вс
    morning_digest=time(9, 0),
    evening_digest=time(18, 0),
    escalation_days=1,
    enabled=True,
)


# ---------------------------------------------------------------------------
# Policy dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class QuietPolicy:
    quiet_start: time          # начало тихих часов (конец рабочего окна)
    quiet_end: time            # конец тихих часов  (начало рабочего окна)
    work_weekdays: frozenset   # ISO-weekday 1=Пн … 7=Вс
    morning_digest: time
    evening_digest: time
    escalation_days: int
    enabled: bool


# ---------------------------------------------------------------------------
# load_policy
# ---------------------------------------------------------------------------

def load_policy(ms) -> QuietPolicy:
    """Создать QuietPolicy из объекта ManagerSettings (или None).

    Атрибуты берём через getattr с fallback на DEFAULTS.
    Поле work_weekdays принимает любой iterable и конвертируется в frozenset.
    """
    def _get(attr):
        val = getattr(ms, attr, None)
        return DEFAULTS[attr] if val is None else val

    work_weekdays = _get("work_weekdays")
    if not isinstance(work_weekdays, frozenset):
        work_weekdays = frozenset(work_weekdays)

    return QuietPolicy(
        quiet_start=_get("quiet_start"),
        quiet_end=_get("quiet_end"),
        work_weekdays=work_weekdays,
        morning_digest=_get("morning_digest"),
        evening_digest=_get("evening_digest"),
        escalation_days=_get("escalation_days"),
        enabled=_get("enabled"),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalize_tz(tz) -> pytz.BaseTzInfo:
    """Вернуть tzinfo; принимает строку IANA или tzinfo."""
    if isinstance(tz, str):
        return pytz.timezone(tz)
    return tz


def _to_aware(dt: datetime, zone: pytz.BaseTzInfo) -> datetime:
    """Если dt наивный — трактуем как UTC и локализуем в UTC; иначе оставляем."""
    if dt.tzinfo is None:
        dt = pytz.utc.localize(dt)
    return dt


def _localize_naive_safe(zone: pytz.BaseTzInfo, naive_dt: datetime) -> datetime:
    """Локализовать наивный datetime, обработав DST-конфликты:
    - NonExistentTimeError  → сдвигаем на +1 час и повторяем (переход вперёд)
    - AmbiguousTimeError    → берём is_dst=False (осенний переход, второй вариант)
    """
    try:
        return zone.localize(naive_dt, is_dst=None)
    except pytz.exceptions.NonExistentTimeError:
        return zone.localize(naive_dt + timedelta(hours=1), is_dst=None)
    except pytz.exceptions.AmbiguousTimeError:
        return zone.localize(naive_dt, is_dst=False)


def _is_working_time(local_dt: datetime, policy: QuietPolicy) -> bool:
    """Проверить, попадает ли local_dt в рабочее окно рабочего дня.

    Рабочее окно: [quiet_end, quiet_start) в локальном времени.
    Поддерживает два случая:
      - дневное окно: quiet_end < quiet_start  (напр. 09:00 – 20:00)
      - ночное окно:  quiet_end > quiet_start  (напр. 22:00 – 06:00, т.е. через полночь)
    """
    weekday = local_dt.isoweekday()
    if weekday not in policy.work_weekdays:
        return False

    t = local_dt.time()
    qs = policy.quiet_start
    qe = policy.quiet_end

    if qe < qs:
        # Дневное рабочее окно: [qe, qs)
        return qe <= t < qs
    else:
        # Ночное/через-полночь рабочее окно: [qe, 24) ∪ [0, qs)
        return t >= qe or t < qs


# ---------------------------------------------------------------------------
# is_quiet
# ---------------------------------------------------------------------------

def is_quiet(dt: datetime, tz, policy: QuietPolicy) -> bool:
    """Вернуть True, если сейчас «тихое время» (не рабочее окно или выходной).

    Если policy.enabled=False — никогда не тихо (всегда False).
    """
    if not policy.enabled:
        return False

    zone = _normalize_tz(tz)
    dt = _to_aware(dt, zone)
    local_dt = dt.astimezone(zone)
    return not _is_working_time(local_dt, policy)


# ---------------------------------------------------------------------------
# next_allowed
# ---------------------------------------------------------------------------

def next_allowed(dt: datetime, tz, policy: QuietPolicy) -> datetime:
    """Вернуть ближайший момент, когда разрешена отправка.

    - Если policy.enabled=False → вернуть dt.
    - Если dt уже в рабочем окне рабочего дня → вернуть dt.
    - Иначе сдвинуться на ближайшее quiet_end ближайшего рабочего дня.
    Bounded loop ≤ 8 итераций; fallback — dt.
    """
    if not policy.enabled:
        return dt

    zone = _normalize_tz(tz)
    dt = _to_aware(dt, zone)
    local_dt = dt.astimezone(zone)

    if _is_working_time(local_dt, policy):
        return dt

    # Ищем следующее разрешённое окно
    candidate_date = local_dt.date()
    qe = policy.quiet_end

    for _ in range(8):
        # Попробуем quiet_end на candidate_date
        naive_candidate = datetime.combine(candidate_date, qe)
        try:
            aware_candidate = _localize_naive_safe(zone, naive_candidate)
        except Exception:
            # Крайний fallback при совсем экзотических DST-ошибках
            candidate_date += timedelta(days=1)
            continue

        # Если это рабочий день и кандидат в будущем относительно dt
        if (candidate_date.isoweekday() in policy.work_weekdays
                and aware_candidate > dt):
            return aware_candidate

        # Если сегодня рабочий день, но quiet_end уже прошёл — пробуем следующий день
        candidate_date += timedelta(days=1)

    # Fallback
    return dt


# ---------------------------------------------------------------------------
# working_days_between
# ---------------------------------------------------------------------------

def working_days_between(d1: datetime, d2: datetime, policy: QuietPolicy) -> int:
    """Число рабочих дат (ISO-weekday ∈ work_weekdays) в полуинтервале (d1.date, d2.date].

    Даты берём как UTC-date (naive date по UTC достаточно).
    """
    start: date = d1.date() if hasattr(d1, "date") else d1
    end: date = d2.date() if hasattr(d2, "date") else d2

    count = 0
    current = start + timedelta(days=1)  # открытый левый конец
    while current <= end:
        if current.isoweekday() in policy.work_weekdays:
            count += 1
        current += timedelta(days=1)
    return count
