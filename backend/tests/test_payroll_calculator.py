from decimal import Decimal

import pytest

from app.payroll.calculator import (
    CalculationInput,
    ComponentDefinition,
    FormulaError,
    LeaveMonth,
    PITBracket,
    ReliefTier,
    SHIRate,
    StatutoryRules,
    calculate_payslip,
    compute_leave_pay,
    compute_progressive_pit,
    compute_shi,
    prorate_amount,
)


def rules(method="isolated_period"):
    return StatutoryRules(
        minimum_wage=Decimal("792000"),
        shi_ceiling_multiplier=Decimal("10"),
        shi_rates=(SHIRate("employee", "all", Decimal(".115")), SHIRate("employer", "all", Decimal(".125"))),
        pit_brackets=(
            PITBracket(Decimal("0"), Decimal("10000000"), Decimal(".10"), period_basis="monthly"),
            PITBracket(Decimal("10000000"), Decimal("15000000"), Decimal(".15"), period_basis="monthly"),
            PITBracket(Decimal("15000000"), None, Decimal(".20"), period_basis="monthly"),
        ),
        pit_withholding_method=method,
    )


def test_proration_supports_working_and_calendar_days():
    assert prorate_amount(Decimal("1000"), "working_days", payable_workdays=5, scheduled_workdays=20) == Decimal("250.00")
    assert prorate_amount(Decimal("1000"), "calendar_days", payable_calendar_days=15, scheduled_calendar_days=30) == Decimal("500.00")


def test_shi_cap_is_applied_before_rate():
    base, employee, employer, _ = compute_shi(Decimal("10000000"), rules(), prior_month_base=Decimal("7000000"))
    assert base == Decimal("920000.00")
    assert employee == Decimal("105800.00")
    assert employer == Decimal("115000.00")


def test_progressive_brackets_and_ytd_withholding():
    assert compute_progressive_pit(Decimal("12000000"), rules().pit_brackets) == Decimal("1300000.00")
    components = (ComponentDefinition("base", "Base", "earning", "base_salary"),)
    ytd_rules = rules("ytd_cumulative")
    first = calculate_payslip(CalculationInput(base_salary=Decimal("10000000"), components=components), ytd_rules)
    second = calculate_payslip(CalculationInput(base_salary=Decimal("2000000"), components=components, prior_ytd_taxable=first.taxable_income, prior_ytd_pit=first.pit), ytd_rules)
    assert second.pit == Decimal("208000.00")


def test_advance_is_offset_once_and_does_not_change_tax():
    components = (ComponentDefinition("base", "Base", "earning", "base_salary"),)
    no_advance = calculate_payslip(CalculationInput(base_salary=Decimal("1000000"), components=components), rules())
    with_advance = calculate_payslip(CalculationInput(base_salary=Decimal("1000000"), components=components, current_advance=Decimal("200000")), rules())
    assert with_advance.pit == no_advance.pit
    assert with_advance.net_pay == no_advance.net_pay - Decimal("200000.00")


def test_advance_run_defers_statutory_withholding_and_ytd_consumption():
    components = (ComponentDefinition("base", "Base", "earning", "base_salary"),)
    result = calculate_payslip(CalculationInput(base_salary=Decimal("1000000"), components=components, withhold_statutory=False), rules())
    assert result.employee_shi == Decimal("0")
    assert result.pit == Decimal("0")
    assert result.ytd["gross"] == Decimal("0.00")


def test_explicit_non_taxable_allowance_is_excluded_from_pit_base():
    components = (
        ComponentDefinition("base", "Base", "earning", "base_salary"),
        ComponentDefinition("allowance", "Allowance", "earning", "100", taxable=True, non_taxable_allowance=True),
    )
    result = calculate_payslip(CalculationInput(base_salary=Decimal("1000"), components=components), rules())
    assert result.gross == Decimal("1100.00")
    assert result.taxable_income == Decimal("873.50")


def test_relief_cannot_make_pit_negative():
    relief_rules = StatutoryRules(
        minimum_wage=Decimal("0"), shi_ceiling_multiplier=Decimal("0"),
        pit_brackets=(PITBracket(Decimal("0"), None, Decimal(".10")),),
        relief_tiers=(ReliefTier("child", Decimal("0"), None, Decimal("1000000")),),
    )
    result = calculate_payslip(
        CalculationInput(base_salary=Decimal("100"), components=(ComponentDefinition("base", "Base", "earning", "base_salary"),), relief_eligibilities=frozenset({"child"})),
        relief_rules,
    )
    assert result.pit == Decimal("0.00")
    assert result.relief == Decimal("10.00")


def test_dependent_component_uses_prorated_parent_amount():
    components = (
        ComponentDefinition("base", "Base", "earning", "base_salary", proration_basis="working_days", position=0),
        ComponentDefinition("housing", "Housing", "earning", "base * 0.1", position=1),
    )
    result = calculate_payslip(CalculationInput(base_salary=Decimal("1000"), payable_workdays=5, scheduled_workdays=10, components=components), rules())
    assert result.gross == Decimal("550.00")


def test_leave_pay_uses_eligible_average():
    months = tuple(LeaveMonth(Decimal("1000000"), Decimal("20")) for _ in range(12))
    assert compute_leave_pay(months, Decimal("5")) == Decimal("250000.00")


def test_formula_cycles_and_unsafe_nodes_are_rejected():
    cyclic = (ComponentDefinition("a", "A", "earning", "b + 1"), ComponentDefinition("b", "B", "earning", "a + 1"))
    with pytest.raises(FormulaError):
        calculate_payslip(CalculationInput(base_salary=Decimal("1"), components=cyclic), rules())
    unsafe = (ComponentDefinition("a", "A", "earning", "__import__('os').system('x')"),)
    with pytest.raises(FormulaError):
        calculate_payslip(CalculationInput(base_salary=Decimal("1"), components=unsafe), rules())


def test_formula_conditional_selection_is_lazy():
    components = (ComponentDefinition("guarded", "Guarded", "earning", "if_else(base_salary > 0, 100, 1 / 0)"),)
    result = calculate_payslip(CalculationInput(base_salary=Decimal("1"), components=components), rules())
    assert result.gross == Decimal("100.00")


def test_approved_tax_credit_reduces_pit_and_is_traced():
    result = calculate_payslip(
        CalculationInput(
            base_salary=Decimal("1000"),
            components=(ComponentDefinition("base", "Base", "earning", "base_salary", shi_subject=False),),
            other_tax_credit=Decimal("25"),
        ),
        rules(),
    )
    assert result.pit == Decimal("75.00")
    assert result.relief == Decimal("25.00")
    assert result.trace["pit"]["declared_credit"] == "25"


def test_tax_impact_only_benefit_is_taxable_but_not_paid_as_gross():
    result = calculate_payslip(
        CalculationInput(
            base_salary=Decimal("1000"),
            components=(
                ComponentDefinition("base", "Base", "earning", "base_salary", shi_subject=False),
                ComponentDefinition("car", "Company car", "earning", "200", shi_subject=False, only_tax_impact=True),
            ),
        ),
        rules(),
    )
    assert result.gross == Decimal("1000.00")
    assert result.taxable_income == Decimal("1200.00")
    assert result.pit == Decimal("120.00")
