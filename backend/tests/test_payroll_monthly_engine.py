from datetime import date
from decimal import Decimal

import pytest

from app.payroll.monthly_engine import (
    AdvanceBasis,
    CalendarDayType,
    PayrollProfile,
    PayrollRunType,
    SalarySegment,
    calculate_monthly_run,
    classify_work_hours,
    default_2026_rules,
    month_calendar,
    advance_snapshot_warning,
    apply_computed_overrides,
    pay_dates_for_month,
)


D = Decimal


@pytest.mark.parametrize(
    ("gross", "shi", "taxable", "pit_before", "relief", "pit", "net"),
    [
        ("792000", "91080", "700920", "70092", "18000", "52092", "648828"),
        ("1500000", "172500", "1327500", "132750", "16000", "116750", "1210750"),
        ("2500000", "287500", "2212500", "221250", "12000", "209250", "2003250"),
        ("12000000", "910800", "11089200", "1163380", "0", "1163380", "9925820"),
    ],
)
def test_section18_monthly_statutory_examples(gross, shi, taxable, pit_before, relief, pit, net):
    result = calculate_monthly_run(
        PayrollRunType.FINAL,
        PayrollProfile(base_salary=D(gross), tax_relief_eligible=True),
        rules=default_2026_rules(),
        planned_days=21,
        worked_normal_hours=168,
        planned_hours=168,
    )
    assert result.gross == D(gross)
    assert result.employee_shi == D(shi)
    assert result.taxable_income == D(taxable)
    assert result.pit_before_relief == D(pit_before)
    assert result.relief == D(relief)
    assert result.pit == D(pit)
    assert result.net_pay == D(net)


def test_section18_biweekly_percent_advance_and_final_settlement():
    profile = PayrollProfile(
        base_salary=D("1500000"),
        payment_frequency="BIWEEKLY",
        pay_days=(10, 25),
        advance_basis=AdvanceBasis.PERCENT,
        advance_percent=D("40"),
        tax_relief_eligible=True,
        meal_allowance=D("70000"),
        commute_allowance=D("50000"),
    )
    advance = calculate_monthly_run(
        PayrollRunType.ADVANCE, profile, rules=default_2026_rules(), planned_days=21,
        planned_hours=168, worked_normal_hours=80, advance_pay_day=10,
    )
    assert advance.advance == D("600000")
    assert advance.employee_shi == advance.pit == D("0")

    final = calculate_monthly_run(
        PayrollRunType.FINAL, profile, rules=default_2026_rules(), planned_days=21,
        planned_hours=168, worked_normal_hours=168, leave_pay=D("168000"),
        approved_advances=(advance.advance,),
    )
    assert final.gross == D("1788000")
    assert final.employee_shi == D("205620")
    assert final.taxable_income == D("1582380")
    assert final.pit_before_relief == D("158238")
    assert final.relief == D("14000")
    assert final.pit == D("144238")
    assert final.total_deductions == D("949858")
    assert final.net_pay == D("838142")
    assert final.employer_shi == D("223500")


def test_section18_excel_proration_sample_and_whole_tugrik_rounding():
    result = calculate_monthly_run(
        PayrollRunType.FINAL,
        PayrollProfile(base_salary=D("2000000"), salary_type="PRORATION", tax_relief_eligible=True),
        rules=default_2026_rules(), planned_days=21, planned_hours=168,
        worked_normal_hours=147, approved_advances=(D("750000"),),
    )
    assert result.base_pay == result.gross == D("1750000")
    assert result.employee_shi == D("201250")
    assert result.taxable_income == D("1548750")
    assert result.pit == D("140875")
    assert result.total_deductions == D("1092125")
    assert result.net_pay == D("657875")


def test_section18_worked_to_date_subtracts_prior_approved_advances():
    profile = PayrollProfile(base_salary=D("1500000"), salary_type="PRORATION", advance_basis=AdvanceBasis.WORKED_TO_DATE)
    first = calculate_monthly_run(
        PayrollRunType.ADVANCE, profile, rules=default_2026_rules(), planned_days=21,
        planned_hours=168, worked_to_date_hours=80,
    )
    second = calculate_monthly_run(
        PayrollRunType.ADVANCE, profile, rules=default_2026_rules(), planned_days=21,
        planned_hours=168, worked_to_date_hours=120, prior_approved_advances=(first.advance,),
    )
    assert first.advance == D("714286")
    assert second.advance == D("357143")


def test_section18_overtime_buckets_use_calendar_multipliers_and_reconcile():
    result = calculate_monthly_run(
        PayrollRunType.FINAL, PayrollProfile(base_salary=D("1500000")),
        rules=default_2026_rules(), planned_days=21, planned_hours=168,
        overtime_hours={"weekday": D("4"), "rest_day": D("8"), "public_holiday": D("8")},
    )
    assert result.overtime_by_bucket == {
        "weekday": D("53571"), "rest_day": D("107143"), "public_holiday": D("142857")
    }
    assert result.overtime_pay == D("303571")
    assert sum(result.overtime_by_bucket.values()) == result.overtime_pay


def test_section18_other_deduction_is_after_tax_and_salary_cost_still_equals_gross():
    result = calculate_monthly_run(
        PayrollRunType.FINAL,
        PayrollProfile(base_salary=D("1500000"), tax_relief_eligible=True, meal_allowance=D("70000"), commute_allowance=D("50000")),
        rules=default_2026_rules(), planned_days=21, planned_hours=168,
        worked_normal_hours=168, leave_pay=D("168000"), approved_advances=(D("600000"),),
        other_deductions=(D("50000"),),
    )
    assert result.employee_shi == D("205620")
    assert result.pit == D("144238")
    assert result.total_deductions == D("999858")
    assert result.net_pay == D("788142")
    assert result.total_deductions + result.net_pay == result.gross == D("1788000")


def test_section18_midmonth_salary_change_splits_fixed_pay_by_workdays():
    segments = (
        SalarySegment(D("1000000"), planned_days=10),
        SalarySegment(D("1500000"), planned_days=11),
    )
    result = calculate_monthly_run(
        PayrollRunType.FINAL,
        PayrollProfile(base_salary=D("1500000"), salary_type="FIXED"),
        rules=default_2026_rules(), planned_days=21, planned_hours=168,
        salary_segments=segments,
    )
    assert result.base_pay == D("1261904")


def test_midmonth_proration_uses_month_hours_for_salary_and_overtime():
    segments = (
        SalarySegment(D("1000000"), 10, D("80"), {"weekday": D("2")}),
        SalarySegment(D("1500000"), 11, D("88"), {"weekday": D("3")}),
    )
    result = calculate_monthly_run(
        PayrollRunType.FINAL,
        PayrollProfile(base_salary=D("1500000"), salary_type="PRORATION"),
        rules=default_2026_rules(), planned_days=21, planned_hours=168,
        worked_normal_hours=168, salary_segments=segments,
    )
    assert result.base_pay == D("1261904")
    assert result.overtime_pay == D("58036")


def test_calendar_defaults_weekends_to_rest_and_allows_transferred_working_day():
    calendar = month_calendar(2026, 8, overrides={date(2026, 8, 8): CalendarDayType.WORKING})
    assert calendar[date(2026, 8, 8)] == CalendarDayType.WORKING
    assert calendar[date(2026, 8, 9)] == CalendarDayType.WEEKLY_REST
    assert calendar[date(2026, 8, 10)] == CalendarDayType.WORKING


def test_section18_work_day_bucketing_and_calendar_holiday():
    regular = classify_work_hours(CalendarDayType.WORKING, D("10"), D("8"))
    rest = classify_work_hours(CalendarDayType.WEEKLY_REST, D("8"), D("8"))
    holiday = classify_work_hours(CalendarDayType.PUBLIC_HOLIDAY, D("8"), D("8"))
    assert regular == (D("8"), {"weekday": D("2"), "rest_day": D("0"), "public_holiday": D("0")})
    assert rest[0] == holiday[0] == D("0")
    assert rest[1]["rest_day"] == holiday[1]["public_holiday"] == D("8")
    assert month_calendar(2026, 8, public_holidays={date(2026, 8, 11): "Holiday"})[date(2026, 8, 11)] == CalendarDayType.PUBLIC_HOLIDAY


def test_section18_final_run_detects_missing_or_changed_advance_snapshot():
    assert advance_snapshot_warning(has_advance_due=True, snapshot_total=None, approved_total=D("0")) == "advance_not_calculated"
    assert advance_snapshot_warning(has_advance_due=True, snapshot_total=D("0"), approved_total=D("600000")) == "advance_changed"
    assert advance_snapshot_warning(has_advance_due=True, snapshot_total=D("600000"), approved_total=D("600000")) is None


def test_pay_frequency_resolves_a_day_beyond_month_end_to_the_last_day():
    profile = PayrollProfile(base_salary=D("1000000"), payment_frequency="BIWEEKLY", pay_days=(15, 31))
    assert pay_dates_for_month(profile, 2026, 2) == (date(2026, 2, 15), date(2026, 2, 28))
    with pytest.raises(ValueError, match="unique and in calendar order"):
        PayrollProfile(base_salary=D("1000000"), payment_frequency="BIWEEKLY", pay_days=(25, 10))


def test_weekly_profile_allows_only_each_scheduled_advance_day():
    profile = PayrollProfile(base_salary=D("1500000"), payment_frequency="WEEKLY", pay_days=(10, 17, 24, 31), advance_basis=AdvanceBasis.PERCENT, advance_percent=D("40"))
    for pay_day in profile.pay_days[:-1]:
        result = calculate_monthly_run(PayrollRunType.ADVANCE, profile, rules=default_2026_rules(), planned_days=21, planned_hours=168, advance_pay_day=pay_day)
        assert result.advance == D("600000")
    with pytest.raises(ValueError, match="not due"):
        calculate_monthly_run(PayrollRunType.ADVANCE, profile, rules=default_2026_rules(), planned_days=21, planned_hours=168, advance_pay_day=12)


def test_statutory_contribution_cap_and_injury_rate_boundary():
    rules = default_2026_rules()
    at_cap = calculate_monthly_run(PayrollRunType.FINAL, PayrollProfile(base_salary=D("7920000")), rules=rules, planned_days=21, planned_hours=168, worked_normal_hours=168)
    above_cap = calculate_monthly_run(PayrollRunType.FINAL, PayrollProfile(base_salary=D("9000000")), rules=rules, planned_days=21, planned_hours=168, worked_normal_hours=168)
    assert at_cap.shi_base == above_cap.shi_base == D("7920000")
    assert at_cap.employee_shi == above_cap.employee_shi == D("910800")
    with pytest.raises(ValueError, match="between 0.5% and 2.5%"):
        default_2026_rules(injury_rate=D("0.0049"))


def test_computed_overrides_round_and_rebuild_gross_to_net_equation():
    result = apply_computed_overrides({"gross": "100000", "employee_shi": "10000", "pit": "5000", "advance": "20000", "other_deductions": "0"}, {"pit": D("5500.5"), "other_deductions": D("1000")})
    assert result["pit"] == "5501"
    assert result["total_deductions"] == "36501"
    assert result["net_pay"] == "63499"
    assert D(str(result["total_deductions"])) + D(str(result["net_pay"])) == D(str(result["gross"]))
    with pytest.raises(ValueError, match="Unsupported computed override"):
        apply_computed_overrides({"gross": "100000"}, {"net_pay": D("1")})


def test_gross_override_recalculates_shi_tax_and_net():
    result = apply_computed_overrides(
        {"gross": "100000", "shi_base": "100000", "employee_shi": "11500", "employer_shi": "10700", "taxable_income": "88500", "pit_before_relief": "8850", "relief": "0", "pit": "8850", "advance": "10000", "other_deductions": "0"},
        {"gross": D("200000.4"), "advance": D("15000")},
        rules=default_2026_rules(),
    )
    assert result["gross"] == "200000"
    assert result["shi_base"] == "200000"
    assert result["employee_shi"] == "23000"
    assert result["employer_shi"] == "25000"
    assert result["taxable_income"] == "177000"
    assert result["pit"] == "17700"
    assert result["advance"] == "15000"
    assert result["total_deductions"] == "55700"
    assert result["net_pay"] == "144300"


def test_manual_contribution_override_recalculates_taxable_income_and_pit():
    result = apply_computed_overrides(
        {"gross": "200000", "employee_shi": "23000", "employer_shi": "21400", "taxable_income": "177000", "pit_before_relief": "17700", "relief": "0", "pit": "17700", "advance": "0", "other_deductions": "0"},
        {"employee_shi": D("50000")},
        rules=default_2026_rules(),
    )
    assert result["taxable_income"] == "150000"
    assert result["pit"] == "15000"
    assert result["net_pay"] == "135000"
