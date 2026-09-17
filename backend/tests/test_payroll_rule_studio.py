from decimal import Decimal

import pytest

from app.payroll.calculator import (
    CalculationInput,
    ComponentDefinition,
    FormulaError,
    PITBracket,
    SHIRate,
    StatutoryRules,
    calculate_payslip,
    compute_progressive_pit,
    compute_shi,
    evaluate_components,
)


def statutory(*, shi_rates=(), pit_mode="marginal_tiers", pit_formula=None):
    return StatutoryRules(
        minimum_wage=Decimal("1000"),
        shi_ceiling_multiplier=Decimal("10"),
        shi_rates=tuple(shi_rates),
        pit_brackets=(PITBracket(Decimal("0"), Decimal("1000"), Decimal(".10")), PITBracket(Decimal("1000"), None, Decimal(".20"))),
        pit_calculation_mode=pit_mode,
        pit_formula=pit_formula,
    )


@pytest.mark.parametrize(
    ("mode", "expected"),
    [("flat_percent", Decimal("150.00")), ("band_rate", Decimal("300.00")), ("marginal_tiers", Decimal("200.00"))],
)
def test_shi_calculation_modes(mode, expected):
    if mode == "flat_percent":
        tiers = (SHIRate("employee", "fund", Decimal(".10"), lower_bound=Decimal("0"), upper_bound=Decimal("1000"), calculation_mode=mode),)
    elif mode == "band_rate":
        tiers = (SHIRate("employee", "fund", Decimal(".20"), lower_bound=Decimal("0"), upper_bound=Decimal("2000"), calculation_mode=mode),)
    else:
        tiers = (SHIRate("employee", "fund", Decimal(".10"), lower_bound=Decimal("0"), upper_bound=Decimal("1000"), calculation_mode=mode), SHIRate("employee", "fund", Decimal(".20"), lower_bound=Decimal("1000"), upper_bound=None, calculation_mode=mode))
    _, employee, _, trace = compute_shi(Decimal("1500"), statutory(shi_rates=tiers))
    assert employee == expected
    assert trace["rules"]


def test_marginal_shi_base_tax_is_applied_once_for_the_containing_tier():
    tiers = (
        SHIRate("employee", "fund", Decimal(".10"), lower_bound=Decimal("0"), upper_bound=Decimal("1000"), calculation_mode="marginal_tiers"),
        SHIRate("employee", "fund", Decimal(".20"), lower_bound=Decimal("1000"), upper_bound=None, base_tax=Decimal("100"), calculation_mode="marginal_tiers"),
    )
    _, employee, _, trace = compute_shi(Decimal("1500"), statutory(shi_rates=tiers))
    assert employee == Decimal("300.00")
    assert trace["by_fund"]["employee:fund"] == Decimal("300.00")


def test_shi_no_cap_policy_uses_full_subject_gross():
    tiers = (SHIRate("employee", "fund", Decimal(".10"), calculation_mode="flat_percent", base_ceiling_policy="none"),)
    base, employee, _, _ = compute_shi(Decimal("20000"), statutory(shi_rates=tiers))
    assert base == Decimal("20000.00")
    assert employee == Decimal("2000.00")


def test_pit_flat_band_and_formula_modes():
    assert compute_progressive_pit(Decimal("1500"), statutory().pit_brackets, mode="flat_percent") == Decimal("150.00")
    assert compute_progressive_pit(Decimal("1500"), statutory().pit_brackets, mode="band_rate") == Decimal("300.00")
    assert compute_progressive_pit(Decimal("1500"), statutory().pit_brackets, mode="formula", formula="income * 0.1") == Decimal("150.00")


def test_component_percentage_dependency_and_cycle_detection():
    lines = evaluate_components((
        ComponentDefinition("base", "Base", "earning", "base_salary"),
        ComponentDefinition("bonus", "Bonus", "earning", "0.1", amount_mode="percentage", percentage_basis="base"),
    ), {"base_salary": Decimal("1000")})
    assert lines[1]["amount"] == Decimal("100.00")
    with pytest.raises(FormulaError, match="Circular"):
        evaluate_components((ComponentDefinition("a", "A", "earning", "b"), ComponentDefinition("b", "B", "earning", "a")), {})


def test_negative_net_is_blocked_and_unsafe_formula_is_rejected():
    with pytest.raises(FormulaError, match="negative amount|deductions exceed"):
        calculate_payslip(CalculationInput(base_salary=Decimal("10"), components=(ComponentDefinition("deduction", "Deduction", "deduction", "100"),)), statutory())
    with pytest.raises(FormulaError):
        evaluate_components((ComponentDefinition("bad", "Bad", "earning", "__import__('os')"),), {})
    with pytest.raises(FormulaError, match="negative amount"):
        evaluate_components((ComponentDefinition("negative", "Negative", "earning", "-1"),), {})
