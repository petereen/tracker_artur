"""Deterministic monthly payroll calculations for the planned run-based flow.

The engine is pure Python: callers resolve worker, calendar, and time data
before calling it. Monetary outputs are rounded per cell to whole tugrik.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from enum import StrEnum
from typing import Mapping, Sequence


ZERO = Decimal("0")
TUGRIK = Decimal("1")
COMPUTED_OVERRIDE_FIELDS = frozenset({"gross", "employee_shi", "employer_shi", "pit", "advance", "other_deductions"})


def amount(value: Decimal | int | float | str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"Invalid payroll amount: {value!r}") from exc


def apply_computed_overrides(
    result: Mapping[str, object],
    overrides: Mapping[str, Decimal | str | int],
    *,
    rules: PayrollRules | None = None,
    tax_relief_eligible: bool = False,
) -> dict[str, object]:
    """Apply audited corrections and recalculate all dependent statutory cells."""
    unknown = set(overrides) - COMPUTED_OVERRIDE_FIELDS
    if unknown:
        raise ValueError(f"Unsupported computed override field: {sorted(unknown)[0]}")
    output = dict(result)
    for key, value in overrides.items():
        override = amount(value)
        if override < ZERO:
            raise ValueError("Computed overrides cannot be negative")
        output[key] = str(override.quantize(TUGRIK, rounding=ROUND_HALF_UP))
    gross = amount(output.get("gross", 0))
    if "gross" in overrides and rules is not None:
        cap = whole_tugrik(rules.minimum_wage * rules.shi_cap_multiplier)
        shi_base = min(gross, cap)
        output["shi_base"] = str(shi_base)
        output["employee_shi"] = str(whole_tugrik(shi_base * sum(rules.employee_shi_rates.values(), ZERO)))
        output["employer_shi"] = str(whole_tugrik(shi_base * sum(rules.employer_shi_rates.values(), ZERO)))
    if "employer_shi" in overrides:
        output["employer_shi"] = str(amount(overrides["employer_shi"]).quantize(TUGRIK, rounding=ROUND_HALF_UP))
    if "employee_shi" in overrides:
        output["employee_shi"] = str(amount(overrides["employee_shi"]).quantize(TUGRIK, rounding=ROUND_HALF_UP))
    employee_shi = amount(output.get("employee_shi", 0))
    taxable_income = max(ZERO, whole_tugrik(gross - employee_shi))
    output["taxable_income"] = str(taxable_income)
    if rules is not None:
        pit_before = _progressive_tax(taxable_income, rules)
        relief = min(pit_before, _relief(taxable_income, rules) if tax_relief_eligible else ZERO)
        output["pit_before_relief"] = str(pit_before)
        output["relief"] = str(relief)
        output["pit"] = str(whole_tugrik(pit_before - relief))
    pit = amount(output.get("pit", 0))
    if "pit" in overrides:
        pit = amount(overrides["pit"]).quantize(TUGRIK, rounding=ROUND_HALF_UP)
        output["pit"] = str(pit)
    advance = amount(output.get("advance", 0))
    other = amount(output.get("other_deductions", 0))
    if "advance" in overrides:
        advance = amount(overrides["advance"]).quantize(TUGRIK, rounding=ROUND_HALF_UP)
    if "other_deductions" in overrides:
        other = amount(overrides["other_deductions"]).quantize(TUGRIK, rounding=ROUND_HALF_UP)
    output["advance"] = str(advance)
    output["other_deductions"] = str(other)
    output["total_deductions"] = str(whole_tugrik(employee_shi + pit + advance + other))
    output["net_pay"] = str(whole_tugrik(gross - amount(output["total_deductions"])) )
    output["computed_overrides"] = sorted(overrides)
    return output


def whole_tugrik(value: Decimal | int | float | str) -> Decimal:
    return amount(value).quantize(TUGRIK, rounding=ROUND_HALF_UP)


class PayrollRunType(StrEnum):
    ADVANCE = "advance"
    FINAL = "final"


class AdvanceBasis(StrEnum):
    FIXED = "FIXED"
    PERCENT = "PERCENT"
    WORKED_TO_DATE = "WORKED-TO-DATE"


class AllowanceBasis(StrEnum):
    """How meal + commute is paid. FIXED and WORKED_DAYS take daily rates."""

    MONTHLY = "MONTHLY"  # legacy snapshots: monthly amounts, hourly workers prorated by hours
    FIXED = "FIXED"  # daily rate × planned workdays of employment in the month
    WORKED_DAYS = "WORKED_DAYS"  # daily rate × days actually worked


class CalendarDayType(StrEnum):
    WORKING = "working"
    WEEKLY_REST = "weekly_rest"
    PUBLIC_HOLIDAY = "public_holiday"


@dataclass(frozen=True)
class SalarySegment:
    monthly_salary: Decimal
    planned_days: int
    worked_normal_hours: Decimal | None = None
    overtime_hours: Mapping[str, Decimal] = field(default_factory=dict)


@dataclass(frozen=True)
class PayrollProfile:
    base_salary: Decimal
    salary_type: str = "PRORATION"
    meal_allowance: Decimal = ZERO
    commute_allowance: Decimal = ZERO
    allowance_basis: AllowanceBasis = AllowanceBasis.MONTHLY
    payment_frequency: str = "MONTHLY"
    pay_days: tuple[int, ...] = (25,)
    advance_basis: AdvanceBasis = AdvanceBasis.FIXED
    advance_amount: Decimal = ZERO
    advance_percent: Decimal = Decimal("40")
    daily_norm_hours: Decimal = Decimal("8")
    insured_type: str = "01001"
    tax_relief_eligible: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.advance_basis, AdvanceBasis):
            object.__setattr__(self, "advance_basis", AdvanceBasis(self.advance_basis))
        if not isinstance(self.allowance_basis, AllowanceBasis):
            object.__setattr__(self, "allowance_basis", AllowanceBasis(self.allowance_basis))
        if self.salary_type not in {"PRORATION", "FIXED"}:
            raise ValueError("salary_type must be PRORATION or FIXED")
        if self.payment_frequency not in {"MONTHLY", "BIWEEKLY", "WEEKLY"}:
            raise ValueError("Unsupported payment frequency")
        required_days = {"MONTHLY": 1, "BIWEEKLY": 2, "WEEKLY": 4}[self.payment_frequency]
        if len(self.pay_days) != required_days or any(day < 1 or day > 31 for day in self.pay_days):
            raise ValueError(f"{self.payment_frequency} requires {required_days} pay day(s), each between 1 and 31")
        if tuple(sorted(set(self.pay_days))) != self.pay_days:
            raise ValueError("Pay days must be unique and in calendar order")
        if self.daily_norm_hours <= ZERO:
            raise ValueError("daily_norm_hours must be positive")


@dataclass(frozen=True)
class PayrollRules:
    minimum_wage: Decimal
    shi_cap_multiplier: Decimal
    employee_shi_rates: Mapping[str, Decimal]
    employer_shi_rates: Mapping[str, Decimal]
    pit_brackets: tuple[tuple[Decimal, Decimal | None, Decimal, Decimal], ...]
    relief_tiers: tuple[tuple[Decimal, Decimal | None, Decimal], ...]
    overtime_multipliers: Mapping[str, Decimal]


def default_2026_rules(*, injury_rate: Decimal = Decimal("0.005")) -> PayrollRules:
    """Return the plan's default 2026 rules (employer rate defaults to 12.5%)."""
    injury_rate = amount(injury_rate)
    if injury_rate < Decimal("0.005") or injury_rate > Decimal("0.025"):
        raise ValueError("Employer injury rate must be between 0.5% and 2.5%")
    return PayrollRules(
        minimum_wage=Decimal("792000"),
        shi_cap_multiplier=Decimal("10"),
        employee_shi_rates={"pension": Decimal("0.085"), "benefit": Decimal("0.008"), "unemployment": Decimal("0.002"), "health": Decimal("0.02")},
        employer_shi_rates={"pension": Decimal("0.085"), "benefit": Decimal("0.01"), "unemployment": Decimal("0.005"), "injury": injury_rate, "health": Decimal("0.02")},
        pit_brackets=(
            (ZERO, Decimal("10000000"), Decimal("0.10"), ZERO),
            (Decimal("10000000"), Decimal("15000000"), Decimal("0.15"), Decimal("1000000")),
            (Decimal("15000000"), None, Decimal("0.20"), Decimal("1750000")),
        ),
        relief_tiers=(
            (ZERO, Decimal("500000"), Decimal("20000")),
            (Decimal("500000"), Decimal("1000000"), Decimal("18000")),
            (Decimal("1000000"), Decimal("1500000"), Decimal("16000")),
            (Decimal("1500000"), Decimal("2000000"), Decimal("14000")),
            (Decimal("2000000"), Decimal("2500000"), Decimal("12000")),
            (Decimal("2500000"), Decimal("3000000"), Decimal("10000")),
        ),
        overtime_multipliers={"weekday": Decimal("1.5"), "rest_day": Decimal("1.5"), "public_holiday": Decimal("2.0")},
    )


@dataclass(frozen=True)
class PayrollRunResult:
    run_type: PayrollRunType
    base_pay: Decimal = ZERO
    overtime_by_bucket: Mapping[str, Decimal] = field(default_factory=dict)
    overtime_pay: Decimal = ZERO
    allowance_days: Decimal = ZERO
    meal_commute: Decimal = ZERO
    gross: Decimal = ZERO
    shi_base: Decimal = ZERO
    employee_shi: Decimal = ZERO
    employer_shi: Decimal = ZERO
    taxable_income: Decimal = ZERO
    pit_before_relief: Decimal = ZERO
    relief: Decimal = ZERO
    pit: Decimal = ZERO
    advance: Decimal = ZERO
    other_deductions: Decimal = ZERO
    total_deductions: Decimal = ZERO
    net_pay: Decimal = ZERO


def _progressive_tax(income: Decimal, rules: PayrollRules) -> Decimal:
    for lower, upper, rate, base_tax in rules.pit_brackets:
        if income >= lower and (upper is None or income <= upper):
            return whole_tugrik(base_tax + (income - lower) * rate)
    if rules.pit_brackets and income > rules.pit_brackets[-1][0]:
        lower, _upper, rate, base_tax = rules.pit_brackets[-1]
        return whole_tugrik(base_tax + (income - lower) * rate)
    return ZERO


def _relief(income: Decimal, rules: PayrollRules) -> Decimal:
    for lower, upper, value in rules.relief_tiers:
        if income >= lower and (upper is None or income <= upper):
            return value
    return ZERO


def _segments(profile: PayrollProfile, planned_days: int, salary_segments: Sequence[SalarySegment] | None) -> tuple[SalarySegment, ...]:
    return tuple(salary_segments or (SalarySegment(profile.base_salary, planned_days),))


def calculate_monthly_run(
    run_type: PayrollRunType | str,
    profile: PayrollProfile,
    *,
    rules: PayrollRules,
    planned_days: int,
    planned_hours: Decimal | int | str,
    worked_normal_hours: Decimal | int | str = ZERO,
    overtime_hours: Mapping[str, Decimal | int | str] | None = None,
    leave_pay: Decimal | int | str = ZERO,
    bonus: Decimal | int | str = ZERO,
    approved_advances: Sequence[Decimal | int | str] = (),
    prior_approved_advances: Sequence[Decimal | int | str] = (),
    other_deductions: Sequence[Decimal | int | str] = (),
    advance_pay_day: int | None = None,
    worked_to_date_hours: Decimal | int | str = ZERO,
    elapsed_planned_days: int = 0,
    salary_segments: Sequence[SalarySegment] | None = None,
    worked_days: Decimal | int | str = ZERO,
    allowance_planned_days: int | None = None,
    worked_days_to_date: Decimal | int | str | None = None,
) -> PayrollRunResult:
    """Calculate an advance or final run from resolved worker and calendar inputs."""
    run_type = PayrollRunType(run_type)
    planned_hours = amount(planned_hours)
    worked_normal_hours = amount(worked_normal_hours)
    segments = _segments(profile, planned_days, salary_segments)
    month_days = sum(segment.planned_days for segment in segments)
    if planned_days <= 0 or planned_hours <= ZERO or month_days <= 0:
        raise ValueError("A payroll month requires positive planned days and hours")

    if run_type is PayrollRunType.ADVANCE:
        if advance_pay_day is not None:
            allowed = profile.pay_days[:-1] if profile.payment_frequency in {"BIWEEKLY", "WEEKLY"} else ()
            if advance_pay_day not in allowed:
                raise ValueError("Worker is not due for an advance on this pay day")
        # FIXED and PERCENT are per-pay-day instalments typed by HR; only
        # WORKED-TO-DATE is cumulative and nets off earlier approved advances.
        if profile.advance_basis is AdvanceBasis.FIXED:
            return PayrollRunResult(run_type=run_type, advance=max(ZERO, whole_tugrik(profile.advance_amount)))
        if profile.advance_basis is AdvanceBasis.PERCENT:
            return PayrollRunResult(run_type=run_type, advance=max(ZERO, whole_tugrik(amount(profile.base_salary) * amount(profile.advance_percent) / Decimal("100"))))
        if profile.salary_type == "PRORATION":
            earned = whole_tugrik(amount(profile.base_salary) / planned_hours * amount(worked_to_date_hours))
        else:
            earned = whole_tugrik(amount(profile.base_salary) * Decimal(elapsed_planned_days) / Decimal(planned_days))
        # Meal + commute are daily rates: (meal + commute) x days of the period so far.
        if profile.allowance_basis is not AllowanceBasis.MONTHLY:
            rate = amount(profile.meal_allowance) + amount(profile.commute_allowance)
            if profile.allowance_basis is AllowanceBasis.WORKED_DAYS and worked_days_to_date is not None:
                days = max(ZERO, amount(worked_days_to_date))
            else:
                days = Decimal(elapsed_planned_days)
            earned += whole_tugrik(rate * days)
        previous = sum((whole_tugrik(value) for value in prior_approved_advances), ZERO)
        return PayrollRunResult(run_type=run_type, advance=max(ZERO, whole_tugrik(earned - previous)))

    base_cells: list[Decimal] = []
    overtime_by_bucket: dict[str, Decimal] = {key: ZERO for key in rules.overtime_multipliers}
    for segment in segments:
        salary = amount(segment.monthly_salary)
        segment_hours = amount(segment.worked_normal_hours if segment.worked_normal_hours is not None else worked_normal_hours)
        if segment.planned_days <= 0:
            raise ValueError("Salary segment must have positive planned hours")
        # A salary segment is still a monthly salary. Proration and overtime
        # use the whole month's planned hours, then split actual hours by the
        # dates in that segment. Dividing by segment hours turns each segment
        # into a full month's salary and overpays mid-month changes.
        if planned_hours <= ZERO:
            raise ValueError("A payroll month requires positive planned hours")
        if profile.salary_type == "PRORATION":
            base_cells.append(whole_tugrik(salary / planned_hours * segment_hours))
        else:
            base_cells.append(whole_tugrik(salary * Decimal(segment.planned_days) / Decimal(month_days)))
        buckets = segment.overtime_hours or (overtime_hours or {})
        for bucket, hours_value in buckets.items():
            if bucket not in rules.overtime_multipliers:
                raise ValueError(f"Unsupported overtime bucket: {bucket}")
            cell = whole_tugrik(salary / planned_hours * amount(hours_value) * rules.overtime_multipliers[bucket])
            overtime_by_bucket[bucket] = whole_tugrik(overtime_by_bucket[bucket] + cell)

    base_pay = sum(base_cells, ZERO)
    overtime_pay = whole_tugrik(sum(overtime_by_bucket.values(), ZERO))
    allowance = amount(profile.meal_allowance) + amount(profile.commute_allowance)
    allowance_days = ZERO
    if profile.allowance_basis is AllowanceBasis.FIXED:
        # Planned workdays inside the employment window, not attendance.
        allowance_days = Decimal(planned_days if allowance_planned_days is None else allowance_planned_days)
        meal_commute = whole_tugrik(allowance * allowance_days)
    elif profile.allowance_basis is AllowanceBasis.WORKED_DAYS:
        allowance_days = max(ZERO, amount(worked_days))
        meal_commute = whole_tugrik(allowance * allowance_days)
    elif profile.salary_type == "PRORATION":
        fraction = min(Decimal("1"), max(ZERO, worked_normal_hours / planned_hours))
        meal_commute = whole_tugrik(allowance * fraction)
    else:
        meal_commute = whole_tugrik(allowance)
    gross = whole_tugrik(base_pay + overtime_pay + whole_tugrik(leave_pay) + meal_commute + whole_tugrik(bonus))
    cap = whole_tugrik(rules.minimum_wage * rules.shi_cap_multiplier)
    shi_base = min(gross, cap)
    employee_shi = whole_tugrik(shi_base * sum(rules.employee_shi_rates.values(), ZERO))
    employer_shi = whole_tugrik(shi_base * sum(rules.employer_shi_rates.values(), ZERO))
    taxable_income = max(ZERO, whole_tugrik(gross - employee_shi))
    pit_before = _progressive_tax(taxable_income, rules)
    relief = min(pit_before, _relief(taxable_income, rules) if profile.tax_relief_eligible else ZERO)
    pit = whole_tugrik(pit_before - relief)
    advance = whole_tugrik(sum((amount(value) for value in approved_advances), ZERO))
    other = whole_tugrik(sum((amount(value) for value in other_deductions), ZERO))
    total_deductions = whole_tugrik(employee_shi + pit + advance + other)
    net = whole_tugrik(gross - total_deductions)
    return PayrollRunResult(
        run_type=run_type, base_pay=base_pay, overtime_by_bucket=overtime_by_bucket,
        overtime_pay=overtime_pay, allowance_days=allowance_days, meal_commute=meal_commute, gross=gross, shi_base=shi_base,
        employee_shi=employee_shi, employer_shi=employer_shi, taxable_income=taxable_income,
        pit_before_relief=pit_before, relief=relief, pit=pit, advance=advance,
        other_deductions=other, total_deductions=total_deductions, net_pay=net,
    )


def month_calendar(
    year: int,
    month: int,
    *,
    overrides: Mapping[date, CalendarDayType | str] | None = None,
    public_holidays: Mapping[date, str] | None = None,
) -> dict[date, CalendarDayType]:
    """Build a month calendar: weekdays work, weekends rest, explicit edits win."""
    if month < 1 or month > 12:
        raise ValueError("month must be between 1 and 12")
    overrides = overrides or {}
    public_holidays = public_holidays or {}
    days = calendar.monthrange(year, month)[1]
    result: dict[date, CalendarDayType] = {}
    for day in range(1, days + 1):
        current = date(year, month, day)
        if current in overrides:
            result[current] = CalendarDayType(overrides[current])
        elif current in public_holidays:
            result[current] = CalendarDayType.PUBLIC_HOLIDAY
        else:
            result[current] = CalendarDayType.WEEKLY_REST if current.weekday() >= 5 else CalendarDayType.WORKING
    return result


def pay_dates_for_month(profile: PayrollProfile, year: int, month: int) -> tuple[date, ...]:
    """Resolve typed pay-day numbers, clamping days beyond month end."""
    last_day = calendar.monthrange(year, month)[1]
    return tuple(date(year, month, min(day, last_day)) for day in profile.pay_days)


def classify_work_hours(
    day_type: CalendarDayType | str,
    total_hours: Decimal | int | str,
    daily_norm_hours: Decimal | int | str,
) -> tuple[Decimal, dict[str, Decimal]]:
    """Split one day's worked hours into normal time and legal overtime buckets."""
    day_type = CalendarDayType(day_type)
    total_hours = amount(total_hours)
    norm = amount(daily_norm_hours)
    if total_hours < ZERO or norm <= ZERO:
        raise ValueError("Hours must be nonnegative and the daily norm must be positive")
    buckets = {"weekday": ZERO, "rest_day": ZERO, "public_holiday": ZERO}
    if day_type is CalendarDayType.PUBLIC_HOLIDAY:
        buckets["public_holiday"] = total_hours
        return ZERO, buckets
    if day_type is CalendarDayType.WEEKLY_REST:
        buckets["rest_day"] = total_hours
        return ZERO, buckets
    normal = min(total_hours, norm)
    buckets["weekday"] = max(ZERO, total_hours - norm)
    return normal, buckets


def overtime_day_lines(
    *,
    day_lines: Sequence[Mapping[str, object]],
    aggregate_hours: Mapping[str, Decimal | int | str],
    bucket_totals: Mapping[str, Decimal | int | str],
    salary_segments: Sequence[Mapping[str, object]],
    base_salary: Decimal | int | str,
    planned_hours: Decimal | int | str,
    multipliers: Mapping[str, Decimal | int | str],
) -> list[dict[str, object]]:
    """Explain each overtime cell as dated lines whose amounts sum to the cell.

    Rates follow the engine: the salary in force on that date divided by the
    whole month's planned hours. When the accountant edited aggregate hours
    so the dated lines no longer reconcile, one manual line per bucket is
    returned instead. Per-line rounding differences are absorbed by the
    largest line so every bucket total equals the engine's cell exactly.
    """
    planned = amount(planned_hours)
    default_rate = amount(base_salary) / planned if planned > ZERO else ZERO
    aggregate = {bucket: amount(hours) for bucket, hours in aggregate_hours.items() if amount(hours) > ZERO}
    dated: dict[str, Decimal] = {}
    for line in day_lines:
        for bucket, hours in (line.get("overtime_hours") or {}).items():  # type: ignore[union-attr]
            dated[bucket] = dated.get(bucket, ZERO) + amount(hours)
    dated = {bucket: hours for bucket, hours in dated.items() if hours > ZERO}

    def rate_on(day: date | None) -> Decimal:
        if day is None:
            return default_rate
        for segment in salary_segments:
            if date.fromisoformat(str(segment["valid_from"])) <= day <= date.fromisoformat(str(segment["valid_to"])):
                return amount(segment["monthly_salary"]) / planned if planned > ZERO else ZERO  # type: ignore[arg-type]
        return default_rate

    raw: list[dict[str, object]] = []
    if dated and dated == aggregate:
        for line in sorted(day_lines, key=lambda item: str(item.get("date"))):
            day = date.fromisoformat(str(line["date"]))
            for bucket, hours in (line.get("overtime_hours") or {}).items():  # type: ignore[union-attr]
                hours_value = amount(hours)
                if hours_value <= ZERO:
                    continue
                multiplier = amount(multipliers.get(bucket, 1))
                rate = rate_on(day)
                raw.append({
                    "date": day.isoformat(), "weekday": day.weekday(), "day_type": line.get("day_type"),
                    "bucket": bucket, "hours": hours_value, "multiplier": multiplier,
                    "rate": rate, "exact": hours_value * multiplier * rate, "source": line.get("source") or "time",
                })
    else:
        for bucket, hours_value in aggregate.items():
            multiplier = amount(multipliers.get(bucket, 1))
            raw.append({
                "date": None, "weekday": None, "day_type": None, "bucket": bucket, "hours": hours_value,
                "multiplier": multiplier, "rate": default_rate,
                "exact": hours_value * multiplier * default_rate, "source": "manual",
            })
    for line in raw:
        line["amount"] = whole_tugrik(line.pop("exact"))  # type: ignore[arg-type]
    for bucket in {str(line["bucket"]) for line in raw}:
        lines = [line for line in raw if line["bucket"] == bucket]
        difference = whole_tugrik(bucket_totals.get(bucket, 0)) - sum((amount(line["amount"]) for line in lines), ZERO)  # type: ignore[arg-type]
        if difference:
            largest = max(lines, key=lambda line: amount(line["amount"]))  # type: ignore[arg-type]
            largest["amount"] = amount(largest["amount"]) + difference  # type: ignore[arg-type]
    return [
        {**line, "hours": str(line["hours"]), "multiplier": str(line["multiplier"]),
         "rate": str(amount(line["rate"]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)), "amount": str(line["amount"])}  # type: ignore[arg-type]
        for line in raw
    ]


def advance_snapshot_warning(
    *,
    has_advance_due: bool,
    snapshot_total: Decimal | int | str | None,
    approved_total: Decimal | int | str,
) -> str | None:
    """Return the section 18 warning state for a final run's advance snapshot."""
    if not has_advance_due:
        return None
    if snapshot_total is None:
        return "advance_not_calculated"
    snapshot = whole_tugrik(snapshot_total)
    current = whole_tugrik(approved_total)
    if snapshot != current:
        return "advance_changed"
    if current == ZERO:
        return "advance_not_calculated"
    return None
