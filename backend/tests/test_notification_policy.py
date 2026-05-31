"""
Тесты для app.services.notification_policy.

Запуск: python -m pytest из backend/ (cwd на sys.path через conftest.py).
"""

from datetime import datetime, time
import pytz
import pytest

from app.services.notification_policy import (
    DEFAULTS,
    QuietPolicy,
    load_policy,
    is_quiet,
    next_allowed,
    working_days_between,
)


# ---------------------------------------------------------------------------
# Вспомогательная фикстура — стандартная политика
# ---------------------------------------------------------------------------

@pytest.fixture
def default_policy() -> QuietPolicy:
    return load_policy(None)


# ---------------------------------------------------------------------------
# load_policy
# ---------------------------------------------------------------------------

class TestLoadPolicy:
    def test_none_returns_defaults(self):
        p = load_policy(None)
        assert p.quiet_start == DEFAULTS["quiet_start"]
        assert p.quiet_end == DEFAULTS["quiet_end"]
        assert p.work_weekdays == DEFAULTS["work_weekdays"]
        assert p.morning_digest == DEFAULTS["morning_digest"]
        assert p.evening_digest == DEFAULTS["evening_digest"]
        assert p.escalation_days == DEFAULTS["escalation_days"]
        assert p.enabled == DEFAULTS["enabled"]

    def test_partial_override(self):
        class FakeSettings:
            quiet_start = time(22, 0)
            quiet_end = None
            work_weekdays = None
            morning_digest = None
            evening_digest = None
            escalation_days = None
            enabled = None

        p = load_policy(FakeSettings())
        assert p.quiet_start == time(22, 0)
        assert p.quiet_end == DEFAULTS["quiet_end"]

    def test_work_weekdays_converted_to_frozenset(self):
        class FakeSettings:
            quiet_start = None
            quiet_end = None
            work_weekdays = [1, 2, 3, 4, 5]
            morning_digest = None
            evening_digest = None
            escalation_days = None
            enabled = None

        p = load_policy(FakeSettings())
        assert isinstance(p.work_weekdays, frozenset)
        assert p.work_weekdays == frozenset({1, 2, 3, 4, 5})


# ---------------------------------------------------------------------------
# is_quiet
# ---------------------------------------------------------------------------

class TestIsQuiet:
    def test_night_is_quiet(self, default_policy):
        # Ночью (22:00 UTC понедельник) — тихо
        dt = pytz.utc.localize(datetime(2024, 1, 8, 22, 0))  # Пн 22:00 UTC
        assert is_quiet(dt, "UTC", default_policy) is True

    def test_morning_before_start_is_quiet(self, default_policy):
        # 08:00 UTC понедельник — ещё не рабочее время
        dt = pytz.utc.localize(datetime(2024, 1, 8, 8, 0))
        assert is_quiet(dt, "UTC", default_policy) is True

    def test_midday_weekday_not_quiet(self, default_policy):
        # 12:00 UTC понедельник — рабочее время
        dt = pytz.utc.localize(datetime(2024, 1, 8, 12, 0))
        assert is_quiet(dt, "UTC", default_policy) is False

    def test_weekend_is_quiet(self, default_policy):
        # Суббота 12:00 UTC
        dt = pytz.utc.localize(datetime(2024, 1, 6, 12, 0))  # Сб
        assert is_quiet(dt, "UTC", default_policy) is True

    def test_sunday_is_quiet(self, default_policy):
        # Воскресенье 15:00 UTC
        dt = pytz.utc.localize(datetime(2024, 1, 7, 15, 0))
        assert is_quiet(dt, "UTC", default_policy) is True

    def test_disabled_policy_never_quiet(self):
        policy = QuietPolicy(
            quiet_start=time(20, 0), quiet_end=time(9, 0),
            work_weekdays=frozenset({1, 2, 3, 4, 5}),
            morning_digest=time(9, 0), evening_digest=time(18, 0),
            escalation_days=1, enabled=False,
        )
        dt = pytz.utc.localize(datetime(2024, 1, 7, 3, 0))  # Воскресенье ночь
        assert is_quiet(dt, "UTC", policy) is False

    def test_naive_dt_treated_as_utc(self, default_policy):
        # Наивный datetime — трактуем как UTC
        dt_naive = datetime(2024, 1, 8, 12, 0)  # Пн 12:00 без tz
        assert is_quiet(dt_naive, "UTC", default_policy) is False

    def test_tz_string_works(self, default_policy):
        # Передаём tz как строку
        dt = pytz.utc.localize(datetime(2024, 1, 8, 12, 0))
        result = is_quiet(dt, "Europe/Moscow", default_policy)
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# next_allowed — основные кейсы
# ---------------------------------------------------------------------------

class TestNextAllowed:
    """Основные кейсы next_allowed."""

    def test_weekday_22_to_next_day_09(self, default_policy):
        """Будний день 22:00 UTC → следующий день 09:00 UTC."""
        # Понедельник 2024-01-08 22:00 UTC
        dt = pytz.utc.localize(datetime(2024, 1, 8, 22, 0))
        result = next_allowed(dt, "UTC", default_policy)
        assert result.hour == 9
        assert result.minute == 0
        # Следующий день — вторник 2024-01-09
        result_utc = result.astimezone(pytz.utc)
        assert result_utc.date() == datetime(2024, 1, 9).date()

    def test_friday_22_to_monday_09(self, default_policy):
        """Пятница 22:00 UTC → понедельник 09:00 UTC."""
        # Пятница 2024-01-12 22:00 UTC
        dt = pytz.utc.localize(datetime(2024, 1, 12, 22, 0))
        result = next_allowed(dt, "UTC", default_policy)
        result_local = result.astimezone(pytz.utc)
        assert result_local.isoweekday() == 1  # Понедельник
        assert result_local.hour == 9
        assert result_local.minute == 0
        assert result_local.date() == datetime(2024, 1, 15).date()

    def test_saturday_noon_to_monday_09(self, default_policy):
        """Суббота 12:00 UTC → понедельник 09:00 UTC."""
        # Суббота 2024-01-13 12:00 UTC
        dt = pytz.utc.localize(datetime(2024, 1, 13, 12, 0))
        result = next_allowed(dt, "UTC", default_policy)
        result_utc = result.astimezone(pytz.utc)
        assert result_utc.isoweekday() == 1  # Понедельник
        assert result_utc.hour == 9
        assert result_utc.minute == 0
        assert result_utc.date() == datetime(2024, 1, 15).date()

    def test_weekday_11_in_window_unchanged(self, default_policy):
        """Будний день 11:00 (в рабочем окне) → dt без изменений."""
        # Понедельник 2024-01-08 11:00 UTC
        dt = pytz.utc.localize(datetime(2024, 1, 8, 11, 0))
        result = next_allowed(dt, "UTC", default_policy)
        assert result == dt

    def test_disabled_policy_returns_dt(self, default_policy):
        """policy.enabled=False → возвращаем dt как есть."""
        policy = QuietPolicy(
            quiet_start=time(20, 0), quiet_end=time(9, 0),
            work_weekdays=frozenset({1, 2, 3, 4, 5}),
            morning_digest=time(9, 0), evening_digest=time(18, 0),
            escalation_days=1, enabled=False,
        )
        dt = pytz.utc.localize(datetime(2024, 1, 13, 12, 0))  # Суббота
        assert next_allowed(dt, "UTC", policy) == dt

    def test_result_is_aware(self, default_policy):
        """Результат всегда aware datetime."""
        dt = pytz.utc.localize(datetime(2024, 1, 8, 22, 0))
        result = next_allowed(dt, "UTC", default_policy)
        assert result.tzinfo is not None

    def test_naive_input_handled(self, default_policy):
        """Наивный input обрабатывается без исключения."""
        dt_naive = datetime(2024, 1, 8, 22, 0)  # Пн 22:00 naive → UTC
        result = next_allowed(dt_naive, "UTC", default_policy)
        assert result.tzinfo is not None


# ---------------------------------------------------------------------------
# next_allowed — DST кейсы
# ---------------------------------------------------------------------------

class TestNextAllowedDST:
    """DST-кейсы для next_allowed."""

    def test_london_dst_spring_forward_no_exception(self):
        """Europe/London переход вперёд 2025-03-30 01:00 → 02:00.

        01:30 локального не существует. Убедиться, что next_allowed
        не кидает исключение и возвращает валидный aware datetime.
        """
        zone = pytz.timezone("Europe/London")
        # 2025-03-30 01:30 UTC (когда Лондон переходит на BST, 01:00 UTC)
        # Это воскресенье — тихий день, next_allowed должен дать понедельник 09:00
        dt_utc = pytz.utc.localize(datetime(2025, 3, 30, 1, 30))

        policy = load_policy(None)
        result = next_allowed(dt_utc, zone, policy)

        assert result is not None
        assert result.tzinfo is not None
        # Воскресенье → следующий рабочий день понедельник 2025-03-31
        result_local = result.astimezone(zone)
        assert result_local.isoweekday() == 1  # Понедельник
        assert result_local.date() == datetime(2025, 3, 31).date()

    def test_london_dst_autumn_fallback_no_exception(self):
        """Europe/London переход назад 2025-10-26 01:00 → 00:00 (повтор часа).

        Убедиться, что next_allowed не кидает исключение.
        """
        zone = pytz.timezone("Europe/London")
        # Воскресенье 2025-10-26 00:30 UTC
        dt_utc = pytz.utc.localize(datetime(2025, 10, 26, 0, 30))

        policy = load_policy(None)
        result = next_allowed(dt_utc, zone, policy)

        assert result is not None
        assert result.tzinfo is not None

    def test_moscow_no_dst_stable(self):
        """Europe/Moscow не имеет DST с 2014 — результат стабилен."""
        zone = pytz.timezone("Europe/Moscow")
        # Понедельник 2024-01-08 20:00 MSK = 17:00 UTC (тихий час)
        dt_utc = pytz.utc.localize(datetime(2024, 1, 8, 17, 0))

        policy = load_policy(None)
        result = next_allowed(dt_utc, zone, policy)

        result_local = result.astimezone(zone)
        assert result_local.isoweekday() in {2}  # Вторник
        assert result_local.hour == 9


# ---------------------------------------------------------------------------
# working_days_between
# ---------------------------------------------------------------------------

class TestWorkingDaysBetween:
    """Тесты working_days_between."""

    def test_friday_to_monday_is_one(self, default_policy):
        """Пятница → понедельник: 1 рабочий день (только сам понедельник в интервале).

        Полуинтервал (d1.date, d2.date]: сб, вс, пн → пн рабочий → 1.
        """
        fri = pytz.utc.localize(datetime(2024, 1, 12))  # Пятница
        mon = pytz.utc.localize(datetime(2024, 1, 15))  # Понедельник
        assert working_days_between(fri, mon, default_policy) == 1

    def test_monday_to_friday_is_four(self, default_policy):
        """Понедельник → пятница: 4 рабочих дня (вт, ср, чт, пт)."""
        mon = pytz.utc.localize(datetime(2024, 1, 8))   # Пн
        fri = pytz.utc.localize(datetime(2024, 1, 12))  # Пт
        assert working_days_between(mon, fri, default_policy) == 4

    def test_same_day_is_zero(self, default_policy):
        """Один и тот же день → 0."""
        mon = pytz.utc.localize(datetime(2024, 1, 8))
        assert working_days_between(mon, mon, default_policy) == 0

    def test_friday_to_friday_next_week_is_five(self, default_policy):
        """Пятница → следующая пятница: 5 рабочих дней (сб,вс,пн,вт,ср,чт,пт → 5)."""
        fri1 = pytz.utc.localize(datetime(2024, 1, 12))  # Пт
        fri2 = pytz.utc.localize(datetime(2024, 1, 19))  # Пт следующей недели
        assert working_days_between(fri1, fri2, default_policy) == 5

    def test_monday_to_wednesday_same_week(self, default_policy):
        """Пн → Ср: 2 рабочих дня (вт, ср)."""
        mon = pytz.utc.localize(datetime(2024, 1, 8))
        wed = pytz.utc.localize(datetime(2024, 1, 10))
        assert working_days_between(mon, wed, default_policy) == 2

    def test_saturday_to_sunday_is_zero(self, default_policy):
        """Сб → Вс: 0 рабочих дней."""
        sat = pytz.utc.localize(datetime(2024, 1, 6))
        sun = pytz.utc.localize(datetime(2024, 1, 7))
        assert working_days_between(sat, sun, default_policy) == 0

    def test_weekend_only_policy(self):
        """Политика только с выходными днями."""
        policy = QuietPolicy(
            quiet_start=time(20, 0), quiet_end=time(9, 0),
            work_weekdays=frozenset({6, 7}),  # сб + вс
            morning_digest=time(9, 0), evening_digest=time(18, 0),
            escalation_days=1, enabled=True,
        )
        fri = pytz.utc.localize(datetime(2024, 1, 12))  # Пт
        mon = pytz.utc.localize(datetime(2024, 1, 15))  # Пн
        # В интервале (пт, пн]: сб=6, вс=7, пн=1 → 2 рабочих (сб+вс)
        assert working_days_between(fri, mon, policy) == 2
