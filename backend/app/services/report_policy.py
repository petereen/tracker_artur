"""Company report policy: which report periods workers and departments submit.

Stored in ``organization.settings["report_policy"]`` and edited by admins in
Settings → Workflows → Reports. The policy decides:

* which periodic reports every worker writes (company default), optionally
  overridden per department;
* which departments write a department-level report (authored by the
  department head) and how often;
* how many days before a period ends reminders start;
* per frequency (``frequency_settings``): where the period starts (week day,
  day of month, first month of the fiscal year/quarter/half), how many days
  before the end reminders start, how many days after the end the report may
  still be submitted (and is reminded about), and the local reminder hour.

Frequencies are the standard ``daily``/``weekly``/``monthly``/``quarterly``/
``half_yearly``/``yearly`` periods plus admin-defined custom periods
(``custom:<id>``) that repeat every N days, weeks or months from an anchor date.

The bot scheduler creates the matching report rows and prompts only for the
enabled periods, and the web report list/creation form follow the same policy.
"""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Iterable

REPORT_POLICY_KEY = "report_policy"
STANDARD_FREQUENCIES = ("daily", "weekly", "monthly", "quarterly", "half_yearly", "yearly")
PERIODIC_REPORT_TYPES = ("weekly", "monthly", "quarterly", "half_yearly", "yearly", "custom")
REVIEWED_REPORT_TYPES = frozenset(PERIODIC_REPORT_TYPES)
CUSTOM_PREFIX = "custom:"
CUSTOM_UNITS = ("day", "week", "month")
DEFAULT_WORKER_FREQUENCIES = ("daily", "monthly")
DEFAULT_REMINDER_DAYS = 3
MAX_REMINDER_DAYS = 14
MAX_CUSTOM_PERIODS = 12
MAX_SCHEDULE_DAYS = 60
FREQUENCY_LABELS = {
    "daily": "Өдрийн тайлан",
    "weekly": "7 хоногийн тайлан",
    "monthly": "Сарын тайлан",
    "quarterly": "Улирлын тайлан",
    "half_yearly": "Хагас жилийн тайлан",
    "yearly": "Жилийн тайлан",
}
# Periods built from whole months starting at the fiscal ``start_month``.
MONTH_SPANS = {"quarterly": 3, "half_yearly": 6, "yearly": 12}
_CUSTOM_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")


@dataclass(frozen=True, slots=True)
class ReportPeriod:
    """One concrete reporting period for a frequency."""

    frequency: str  # "monthly", "custom:<id>", ...
    report_type: str  # stored WorkReport.report_type
    period_key: str  # custom period id, "" for standard periods
    start: date
    end: date
    label: str

    @property
    def length_days(self) -> int:
        return (self.end - self.start).days + 1


def _as_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _custom_periods(raw: Any) -> list[dict]:
    periods: list[dict] = []
    seen: set[str] = set()
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        custom_id = str(item.get("id") or "").strip().lower()
        unit = str(item.get("unit") or "")
        anchor = _as_date(item.get("anchor_date"))
        try:
            interval = int(item.get("interval") or 0)
        except (TypeError, ValueError):
            interval = 0
        if not _CUSTOM_ID.match(custom_id) or custom_id in seen or unit not in CUSTOM_UNITS or anchor is None:
            continue
        max_interval = 366 if unit == "day" else 52 if unit == "week" else 24
        if not 1 <= interval <= max_interval:
            continue
        label = str(item.get("label") or "").strip()[:80] or f"{interval} {unit}"
        periods.append({"id": custom_id, "label": label, "unit": unit, "interval": interval, "anchor_date": anchor.isoformat()})
        seen.add(custom_id)
        if len(periods) >= MAX_CUSTOM_PERIODS:
            break
    return periods


def _bounded_int(value: Any, low: int, high: int) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if low <= number <= high else None


def _reminder_hour(value: Any) -> int | None:
    """``"HH:MM"`` or an hour; reminders run on the hour of the worker's schedule."""
    if value in (None, ""):
        return None
    if isinstance(value, str) and ":" in value:
        value = value.split(":", 1)[0]
    return _bounded_int(value, 0, 23)


def frequency_settings_for(raw: Any, frequency: str) -> dict:
    """Normalized period start and schedule for one frequency.

    ``reminder_days`` ``None`` inherits the company ``reminder_days``;
    ``reminder_hour`` ``None`` keeps the worker's morning check-in time.
    """
    item = raw if isinstance(raw, dict) else {}
    report_type, _ = report_type_for(frequency)
    settings: dict[str, Any] = {
        "reminder_days": _bounded_int(item.get("reminder_days"), 1, MAX_SCHEDULE_DAYS),
        "due_days": _bounded_int(item.get("due_days"), 0, MAX_SCHEDULE_DAYS) or 0,
        "reminder_hour": _reminder_hour(item.get("reminder_hour", item.get("reminder_time"))),
    }
    if report_type == "weekly":
        weekday = _bounded_int(item.get("start_weekday"), 0, 6)
        settings["start_weekday"] = 0 if weekday is None else weekday
    if report_type == "monthly" or report_type in MONTH_SPANS:
        settings["start_day"] = _bounded_int(item.get("start_day"), 1, 28) or 1
    if report_type in MONTH_SPANS:
        settings["start_month"] = _bounded_int(item.get("start_month"), 1, 12) or 1
    return settings


def _frequency_settings(raw: Any, allowed: Iterable[str]) -> dict[str, dict]:
    raw = raw if isinstance(raw, dict) else {}
    return {frequency: frequency_settings_for(raw.get(frequency), frequency) for frequency in allowed if frequency != "daily"}


def _frequencies(raw: Any, allowed: set[str]) -> list[str]:
    values: list[str] = []
    for item in raw if isinstance(raw, list) else []:
        value = str(item)
        if value in allowed and value not in values:
            values.append(value)
    return values


def allowed_frequencies(custom_periods: Iterable[dict]) -> list[str]:
    return [*STANDARD_FREQUENCIES, *(f"{CUSTOM_PREFIX}{item['id']}" for item in custom_periods)]


def report_policy(organization_settings: dict | None) -> dict:
    """Return a normalized policy; missing settings keep today's behavior."""
    raw = (organization_settings or {}).get(REPORT_POLICY_KEY)
    raw = raw if isinstance(raw, dict) else {}
    custom = _custom_periods(raw.get("custom_periods"))
    allowed = set(allowed_frequencies(custom))
    worker = _frequencies(raw.get("worker_frequencies"), allowed) if "worker_frequencies" in raw else list(DEFAULT_WORKER_FREQUENCIES)
    try:
        reminder_days = int(raw.get("reminder_days", DEFAULT_REMINDER_DAYS))
    except (TypeError, ValueError):
        reminder_days = DEFAULT_REMINDER_DAYS
    departments: list[dict] = []
    seen_departments: set[int] = set()
    for item in raw.get("departments") if isinstance(raw.get("departments"), list) else []:
        if not isinstance(item, dict):
            continue
        try:
            department_id = int(item.get("department_id"))
        except (TypeError, ValueError):
            continue
        if department_id in seen_departments:
            continue
        seen_departments.add(department_id)
        inherit = item.get("worker_frequencies") is None
        departments.append({
            "department_id": department_id,
            "worker_frequencies": None if inherit else _frequencies(item.get("worker_frequencies"), allowed),
            "department_frequencies": _frequencies(item.get("department_frequencies"), allowed - {"daily"}),
        })
    return {
        "worker_frequencies": worker,
        "custom_periods": custom,
        "departments": departments,
        "reminder_days": max(1, min(MAX_REMINDER_DAYS, reminder_days)),
        "frequency_settings": _frequency_settings(raw.get("frequency_settings"), allowed_frequencies(custom)),
    }


def settings_for(policy: dict, frequency: str) -> dict:
    return (policy.get("frequency_settings") or {}).get(frequency) or frequency_settings_for(None, frequency)


def _department_rule(policy: dict, department_id: int | None) -> dict | None:
    if department_id is None:
        return None
    return next((item for item in policy["departments"] if item["department_id"] == department_id), None)


def worker_frequencies(policy: dict, department_id: int | None) -> list[str]:
    """Personal report frequencies for a worker in ``department_id``."""
    rule = _department_rule(policy, department_id)
    if rule and rule["worker_frequencies"] is not None:
        return list(rule["worker_frequencies"])
    return list(policy["worker_frequencies"])


def department_frequencies(policy: dict, department_id: int | None) -> list[str]:
    rule = _department_rule(policy, department_id)
    return list(rule["department_frequencies"]) if rule else []


def report_type_for(frequency: str) -> tuple[str, str]:
    """Map a frequency id to the stored ``(report_type, period_key)``."""
    if frequency.startswith(CUSTOM_PREFIX):
        return "custom", frequency[len(CUSTOM_PREFIX):]
    return frequency, ""


def frequency_for(report_type: str, period_key: str | None) -> str:
    return f"{CUSTOM_PREFIX}{period_key}" if report_type == "custom" and period_key else report_type


def frequency_label(policy: dict, frequency: str) -> str:
    if frequency.startswith(CUSTOM_PREFIX):
        custom_id = frequency[len(CUSTOM_PREFIX):]
        custom = next((item for item in policy["custom_periods"] if item["id"] == custom_id), None)
        return custom["label"] if custom else "Тусгай тайлан"
    return FREQUENCY_LABELS.get(frequency, frequency)


def _add_months(day: date, months: int) -> date:
    month_index = day.year * 12 + (day.month - 1) + months
    year, month = divmod(month_index, 12)
    month += 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def _months_between(anchor: date, day: date) -> int:
    months = (day.year - anchor.year) * 12 + (day.month - anchor.month)
    if day < _add_months(anchor, months):
        months -= 1
    return months


def period_for_frequency(policy: dict, frequency: str, day: date) -> ReportPeriod | None:
    """The period of ``frequency`` that contains ``day``."""
    report_type, period_key = report_type_for(frequency)
    label = frequency_label(policy, frequency)
    if report_type == "daily":
        start = end = day
    elif report_type == "weekly":
        start_weekday = settings_for(policy, frequency).get("start_weekday", 0)
        start = day - timedelta(days=(day.weekday() - start_weekday) % 7)
        end = start + timedelta(days=6)
    elif report_type == "monthly" or report_type in MONTH_SPANS:
        # A company month may run e.g. from the 26th to the 25th, and a fiscal
        # year (with its quarters and halves) may start in any month.
        config = settings_for(policy, frequency)
        span = MONTH_SPANS.get(report_type, 1)
        anchor = date(2000, config.get("start_month", 1), config.get("start_day", 1))
        index = _months_between(anchor, day) // span
        start = _add_months(anchor, index * span)
        end = _add_months(anchor, (index + 1) * span) - timedelta(days=1)
    elif report_type == "custom":
        custom = next((item for item in policy["custom_periods"] if item["id"] == period_key), None)
        if custom is None:
            return None
        anchor = date.fromisoformat(custom["anchor_date"])
        interval = int(custom["interval"])
        if custom["unit"] == "month":
            index = _months_between(anchor, day) // interval
            start = _add_months(anchor, index * interval)
            end = _add_months(anchor, (index + 1) * interval) - timedelta(days=1)
        else:
            length = interval * (7 if custom["unit"] == "week" else 1)
            index = (day - anchor).days // length
            start = anchor + timedelta(days=index * length)
            end = start + timedelta(days=length - 1)
    else:
        return None
    return ReportPeriod(frequency=frequency, report_type=report_type, period_key=period_key, start=start, end=end, label=label)


def reminder_window_open(period: ReportPeriod, day: date, reminder_days: int) -> bool:
    """Whether ``day`` falls in the reminder window at the end of ``period``.

    The window is the last ``reminder_days`` days, but never more than half
    of a short period (a weekly report is not nagged about all week).
    """
    if period.report_type == "daily":
        return period.start == day
    window = max(1, min(reminder_days, period.length_days // 2 or 1))
    return period.end - timedelta(days=window - 1) <= day <= period.end


def previous_period(policy: dict, period: ReportPeriod) -> ReportPeriod | None:
    return period_for_frequency(policy, period.frequency, period.start - timedelta(days=1))


def open_report_periods(policy: dict, frequency: str, day: date) -> list[tuple[ReportPeriod, str]]:
    """Periods of ``frequency`` a worker is reminded about on ``day``.

    ``("closing", period)``: the current period is in its reminder window
    (``reminder_days`` before the end); ``("overdue", period)``: the previous
    period ended less than ``due_days`` ago and may still be submitted.
    """
    current = period_for_frequency(policy, frequency, day)
    if current is None:
        return []
    config = settings_for(policy, frequency)
    result: list[tuple[ReportPeriod, str]] = []
    due_days = int(config.get("due_days") or 0)
    if due_days and current.report_type != "daily":
        previous = previous_period(policy, current)
        if previous and day <= previous.end + timedelta(days=due_days):
            result.append((previous, "overdue"))
    explicit = config.get("reminder_days")
    if explicit and current.report_type != "daily":
        # An explicit lead time may cover the whole period (e.g. 30 days
        # before a yearly report is due); the default stays capped.
        window = max(1, min(int(explicit), current.length_days))
        if current.end - timedelta(days=window - 1) <= day <= current.end:
            result.append((current, "closing"))
    elif reminder_window_open(current, day, policy["reminder_days"]):
        result.append((current, "closing"))
    return result


def submission_deadline(policy: dict, period: ReportPeriod) -> date:
    return period.end + timedelta(days=int(settings_for(policy, period.frequency).get("due_days") or 0))


def validate_policy_input(data: dict) -> dict:
    """Normalize admin input, rejecting references to unknown frequencies."""
    custom = _custom_periods(data.get("custom_periods"))
    requested_custom = data.get("custom_periods") or []
    if len(custom) != len(requested_custom):
        raise ValueError("invalid_custom_period")
    allowed = set(allowed_frequencies(custom))
    for value in data.get("worker_frequencies") or []:
        if value not in allowed:
            raise ValueError(f"unknown_frequency:{value}")
    for rule in data.get("departments") or []:
        for value in [*(rule.get("worker_frequencies") or []), *(rule.get("department_frequencies") or [])]:
            if value not in allowed:
                raise ValueError(f"unknown_frequency:{value}")
    for value in (data.get("frequency_settings") or {}):
        if value not in allowed:
            raise ValueError(f"unknown_frequency:{value}")
    normalized = report_policy({REPORT_POLICY_KEY: data})
    return normalized
