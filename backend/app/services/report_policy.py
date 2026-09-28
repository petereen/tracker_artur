"""Company report policy: which report periods workers and departments submit.

Stored in ``organization.settings["report_policy"]`` and edited by admins in
Settings → Workflows → Reports. The policy decides:

* which periodic reports every worker writes (company default), optionally
  overridden per department;
* which departments write a department-level report (authored by the
  department head) and how often;
* how many days before a period ends reminders start.

Frequencies are the standard ``daily``/``weekly``/``monthly``/``quarterly``/
``yearly`` periods plus admin-defined custom periods (``custom:<id>``) that
repeat every N days, weeks or months from an anchor date.

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
STANDARD_FREQUENCIES = ("daily", "weekly", "monthly", "quarterly", "yearly")
PERIODIC_REPORT_TYPES = ("weekly", "monthly", "quarterly", "yearly", "custom")
REVIEWED_REPORT_TYPES = frozenset(PERIODIC_REPORT_TYPES)
CUSTOM_PREFIX = "custom:"
CUSTOM_UNITS = ("day", "week", "month")
DEFAULT_WORKER_FREQUENCIES = ("daily", "monthly")
DEFAULT_REMINDER_DAYS = 3
MAX_REMINDER_DAYS = 14
MAX_CUSTOM_PERIODS = 12
FREQUENCY_LABELS = {
    "daily": "Өдрийн тайлан",
    "weekly": "7 хоногийн тайлан",
    "monthly": "Сарын тайлан",
    "quarterly": "Улирлын тайлан",
    "yearly": "Жилийн тайлан",
}
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
    }


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
        start = day - timedelta(days=day.weekday())
        end = start + timedelta(days=6)
    elif report_type == "monthly":
        start = day.replace(day=1)
        end = day.replace(day=calendar.monthrange(day.year, day.month)[1])
    elif report_type == "quarterly":
        first_month = 3 * ((day.month - 1) // 3) + 1
        start = date(day.year, first_month, 1)
        end = _add_months(start, 3) - timedelta(days=1)
    elif report_type == "yearly":
        start, end = date(day.year, 1, 1), date(day.year, 12, 31)
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
    normalized = report_policy({REPORT_POLICY_KEY: data})
    return normalized
