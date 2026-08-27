"""Pure Decimal payroll calculation primitives.

The module deliberately has no database, clock, HTTP, or ORM dependencies. A
caller resolves and freezes all inputs before invoking :func:`calculate_payslip`.
"""

from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Iterable, Mapping


ZERO = Decimal("0")
MONEY_QUANTUM = Decimal("0.01")


def money(value: Decimal | int | float | str, quantum: Decimal = MONEY_QUANTUM) -> Decimal:
    try:
        return Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"Invalid monetary value: {value!r}") from exc


@dataclass(frozen=True)
class LeaveMonth:
    earnings: Decimal
    worked_days: Decimal
    eligible: bool = True


@dataclass(frozen=True)
class ComponentDefinition:
    code: str
    label: str
    component_kind: str  # earning, deduction, employer_cost
    formula: str
    proration_basis: str = "none"  # none, working_days, calendar_days, hours
    taxable: bool = True
    shi_subject: bool = True
    non_taxable_allowance: bool = False
    leave_average_eligible: bool = True
    only_tax_impact: bool = False
    payer: str = "employee"
    position: int = 0


@dataclass(frozen=True)
class SHIRate:
    payer: str
    insurance_fund: str
    rate: Decimal
    base_floor: Decimal = ZERO
    exemption_code: str | None = None


@dataclass(frozen=True)
class PITBracket:
    lower_bound: Decimal
    upper_bound: Decimal | None
    marginal_rate: Decimal
    base_tax: Decimal = ZERO
    period_basis: str = "annual"


@dataclass(frozen=True)
class ReliefTier:
    eligibility_code: str
    lower_bound: Decimal
    upper_bound: Decimal | None
    fixed_amount: Decimal
    amount_basis: str = "annual"
    formula: str | None = None


@dataclass(frozen=True)
class StatutoryRules:
    minimum_wage: Decimal
    shi_ceiling_multiplier: Decimal
    shi_rates: tuple[SHIRate, ...] = ()
    pit_brackets: tuple[PITBracket, ...] = ()
    relief_tiers: tuple[ReliefTier, ...] = ()
    pit_withholding_method: str = "ytd_cumulative"
    periods_per_year: int = 12
    rounding_quantum: Decimal = MONEY_QUANTUM
    leave_policy: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CalculationInput:
    base_salary: Decimal
    payable_workdays: Decimal = ZERO
    scheduled_workdays: Decimal = ZERO
    payable_calendar_days: Decimal = ZERO
    scheduled_calendar_days: Decimal = ZERO
    payable_hours: Decimal = ZERO
    scheduled_hours: Decimal = ZERO
    context: Mapping[str, Decimal | int | float | str | bool] = field(default_factory=dict)
    components: tuple[ComponentDefinition, ...] = ()
    prior_ytd_gross: Decimal = ZERO
    prior_ytd_taxable: Decimal = ZERO
    prior_ytd_pit: Decimal = ZERO
    prior_ytd_relief: Decimal = ZERO
    prior_month_shi_base: Decimal = ZERO
    current_advance: Decimal = ZERO
    other_tax_deductible: Decimal = ZERO
    other_tax_credit: Decimal = ZERO
    other_deductions: Decimal = ZERO
    relief_eligibilities: frozenset[str] = frozenset()
    leave_months: tuple[LeaveMonth, ...] = ()
    leave_days: Decimal = ZERO
    exemption_codes: frozenset[str] = frozenset()
    allow_negative_net: bool = False
    # Advance runs intentionally defer statutory withholding to the final
    # settlement. They still produce a complete gross trace, but do not
    # consume the SHI cap or YTD PIT accumulator.
    withhold_statutory: bool = True


@dataclass(frozen=True)
class CalculationResult:
    lines: tuple[dict[str, Any], ...]
    gross: Decimal
    taxable_income: Decimal
    shi_subject_gross: Decimal
    shi_base: Decimal
    employee_shi: Decimal
    employer_shi: Decimal
    pit_before_relief: Decimal
    relief: Decimal
    pit: Decimal
    advance_offset: Decimal
    unapplied_advance: Decimal
    other_deductions: Decimal
    net_pay: Decimal
    ytd: Mapping[str, Decimal]
    trace: Mapping[str, Any]


class FormulaError(ValueError):
    pass


class _SafeFormula:
    """Allowlisted expression compiler; never calls Python ``eval``."""

    _allowed_functions = {"min", "max", "abs", "round_money", "if_else"}
    _allowed_nodes = (
        ast.Expression, ast.Constant, ast.Name, ast.BinOp, ast.UnaryOp, ast.Add,
        ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Pow, ast.USub, ast.UAdd,
        ast.Compare, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
        ast.BoolOp, ast.And, ast.Or, ast.Not, ast.UnaryOp, ast.IfExp, ast.Call,
        ast.Load,
    )

    def __init__(self, expression: str):
        if not isinstance(expression, str) or not expression.strip():
            raise FormulaError("Formula must be a non-empty expression")
        try:
            tree = ast.parse(expression, mode="eval")
        except SyntaxError as exc:
            raise FormulaError("Invalid formula syntax") from exc
        self._validate(tree)
        self.tree = tree.body
        self.dependencies = frozenset(
            node.id for node in ast.walk(tree)
            if isinstance(node, ast.Name) and node.id not in self._allowed_functions
        )

    def _validate(self, tree: ast.AST) -> None:
        for node in ast.walk(tree):
            if not isinstance(node, self._allowed_nodes):
                raise FormulaError(f"Formula node is not allowed: {type(node).__name__}")
            if isinstance(node, ast.Constant) and not isinstance(node.value, (int, float, str, bool)):
                raise FormulaError("Only scalar constants are allowed")
            if isinstance(node, ast.Name) and (node.id.startswith("__") or not node.id.replace("_", "").isalnum()):
                raise FormulaError("Invalid formula variable")
            if isinstance(node, ast.Call):
                if not isinstance(node.func, ast.Name) or node.func.id not in self._allowed_functions or node.keywords:
                    raise FormulaError("Only allowlisted positional functions are allowed")

    def evaluate(self, variables: Mapping[str, Any], quantum: Decimal) -> Decimal:
        def visit(node: ast.AST) -> Any:
            if isinstance(node, ast.Constant):
                if isinstance(node.value, bool):
                    return node.value
                if isinstance(node.value, str):
                    return node.value
                return Decimal(str(node.value))
            if isinstance(node, ast.Name):
                if node.id not in variables:
                    raise FormulaError(f"Unknown formula variable: {node.id}")
                return variables[node.id]
            if isinstance(node, ast.UnaryOp):
                value = visit(node.operand)
                if isinstance(node.op, ast.USub): return -value
                if isinstance(node.op, ast.UAdd): return +value
                if isinstance(node.op, ast.Not): return not value
            if isinstance(node, ast.BinOp):
                left, right = visit(node.left), visit(node.right)
                if isinstance(node.op, ast.Add): return left + right
                if isinstance(node.op, ast.Sub): return left - right
                if isinstance(node.op, ast.Mult): return left * right
                if isinstance(node.op, ast.Div):
                    if right == 0: raise FormulaError("Division by zero")
                    return left / right
                if isinstance(node.op, ast.Mod): return left % right
                if isinstance(node.op, ast.Pow):
                    if right != int(right) or abs(right) > 8: raise FormulaError("Unsafe exponent")
                    return left ** int(right)
            if isinstance(node, ast.Compare):
                current = visit(node.left)
                for operator, comparator in zip(node.ops, node.comparators):
                    right = visit(comparator)
                    ok = ((isinstance(operator, ast.Eq) and current == right) or
                          (isinstance(operator, ast.NotEq) and current != right) or
                          (isinstance(operator, ast.Lt) and current < right) or
                          (isinstance(operator, ast.LtE) and current <= right) or
                          (isinstance(operator, ast.Gt) and current > right) or
                          (isinstance(operator, ast.GtE) and current >= right))
                    if not ok: return False
                    current = right
                return True
            if isinstance(node, ast.BoolOp):
                if isinstance(node.op, ast.And):
                    for value in node.values:
                        if not bool(visit(value)):
                            return False
                    return True
                for value in node.values:
                    if bool(visit(value)):
                        return True
                return False
            if isinstance(node, ast.IfExp):
                return visit(node.body) if visit(node.test) else visit(node.orelse)
            if isinstance(node, ast.Call):
                # Keep conditional selection lazy so a guarded branch can
                # safely contain a zero denominator or another invalid value.
                if node.func.id == "if_else":
                    if len(node.args) != 3: raise FormulaError("if_else requires three arguments")
                    return visit(node.args[1]) if visit(node.args[0]) else visit(node.args[2])
                args = [visit(arg) for arg in node.args]
                if node.func.id in {"min", "max"}:
                    if not args: raise FormulaError(f"{node.func.id} requires at least one argument")
                    return min(args) if node.func.id == "min" else max(args)
                if node.func.id in {"abs", "round_money"}:
                    if len(args) != 1: raise FormulaError(f"{node.func.id} requires one argument")
                    return abs(args[0]) if node.func.id == "abs" else money(args[0], quantum)
            raise FormulaError(f"Unsupported formula expression: {type(node).__name__}")

        try:
            result = visit(self.tree)
        except FormulaError:
            raise
        except (TypeError, ZeroDivisionError, InvalidOperation, OverflowError) as exc:
            raise FormulaError("Formula evaluation failed") from exc
        if isinstance(result, bool) or isinstance(result, str):
            raise FormulaError("Formula must return a number")
        try:
            return money(result, quantum)
        except ValueError as exc:
            raise FormulaError("Formula result is not a finite number") from exc


def prorate_amount(amount: Decimal, basis: str, *, payable_workdays: Decimal = ZERO, scheduled_workdays: Decimal = ZERO, payable_calendar_days: Decimal = ZERO, scheduled_calendar_days: Decimal = ZERO, payable_hours: Decimal = ZERO, scheduled_hours: Decimal = ZERO) -> Decimal:
    amount = money(amount)
    if basis in {"none", ""}: return amount
    numer, denom = {
        "working_days": (payable_workdays, scheduled_workdays),
        "calendar_days": (payable_calendar_days, scheduled_calendar_days),
        "hours": (payable_hours, scheduled_hours),
    }.get(basis, (None, None))
    if numer is None: raise ValueError(f"Unknown proration basis: {basis}")
    if denom is None or denom <= 0: raise ValueError(f"Cannot prorate with empty denominator for {basis}")
    return money(amount * numer / denom)


def evaluate_components(components: Iterable[ComponentDefinition], variables: Mapping[str, Any], *, quantum: Decimal = MONEY_QUANTUM, payable_workdays: Decimal = ZERO, scheduled_workdays: Decimal = ZERO, payable_calendar_days: Decimal = ZERO, scheduled_calendar_days: Decimal = ZERO, payable_hours: Decimal = ZERO, scheduled_hours: Decimal = ZERO) -> tuple[dict[str, Any], ...]:
    definitions = sorted(tuple(components), key=lambda item: (item.position, item.code))
    by_code = {item.code: item for item in definitions}
    if len(by_code) != len(definitions): raise FormulaError("Duplicate salary component code")
    compiled = {item.code: _SafeFormula(item.formula) for item in definitions}
    state: dict[str, Decimal] = {}
    visiting: set[str] = set()
    done: set[str] = set()

    def resolve(code: str) -> Decimal:
        if code in done: return state[code]
        if code in visiting: raise FormulaError(f"Circular salary component dependency: {code}")
        visiting.add(code)
        expression = compiled[code]
        for dependency in expression.dependencies:
            if dependency in by_code: resolve(dependency)
        value = expression.evaluate({**variables, **state}, quantum)
        value = prorate_amount(value, by_code[code].proration_basis, payable_workdays=payable_workdays, scheduled_workdays=scheduled_workdays, payable_calendar_days=payable_calendar_days, scheduled_calendar_days=scheduled_calendar_days, payable_hours=payable_hours, scheduled_hours=scheduled_hours)
        state[code] = value
        visiting.remove(code); done.add(code)
        return value

    for item in definitions: resolve(item.code)
    return tuple({"code": item.code, "label": item.label, "component_kind": item.component_kind, "amount": state[item.code], "taxable": item.taxable, "shi_subject": item.shi_subject, "non_taxable_allowance": item.non_taxable_allowance, "leave_average_eligible": item.leave_average_eligible, "only_tax_impact": item.only_tax_impact, "payer": item.payer, "formula": item.formula, "position": item.position} for item in definitions)


def compute_shi(subject_gross: Decimal, rules: StatutoryRules, *, prior_month_base: Decimal = ZERO, exemption_codes: frozenset[str] = frozenset()) -> tuple[Decimal, Decimal, Decimal, dict[str, Decimal]]:
    cap = max(ZERO, money(rules.minimum_wage * rules.shi_ceiling_multiplier, rules.rounding_quantum))
    remaining = max(ZERO, cap - money(prior_month_base, rules.rounding_quantum))
    base = min(max(ZERO, money(subject_gross, rules.rounding_quantum)), remaining)
    employee = ZERO; employer = ZERO; by_fund: dict[str, Decimal] = {}
    for tier in rules.shi_rates:
        if tier.exemption_code and tier.exemption_code in exemption_codes: continue
        tier_base = min(cap, max(base, money(tier.base_floor, rules.rounding_quantum))) if base else ZERO
        amount = money(tier_base * tier.rate, rules.rounding_quantum)
        by_fund[f"{tier.payer}:{tier.insurance_fund}"] = by_fund.get(f"{tier.payer}:{tier.insurance_fund}", ZERO) + amount
        if tier.payer == "employee": employee += amount
        elif tier.payer == "employer": employer += amount
    return money(base, rules.rounding_quantum), money(employee, rules.rounding_quantum), money(employer, rules.rounding_quantum), {key: money(value, rules.rounding_quantum) for key, value in by_fund.items()}


def compute_progressive_pit(income: Decimal, brackets: Iterable[PITBracket]) -> Decimal:
    income = max(ZERO, income)
    ordered = sorted(tuple(brackets), key=lambda item: item.lower_bound)
    if not ordered: return ZERO
    tax = ZERO
    for bracket in ordered:
        if income <= bracket.lower_bound: continue
        upper = bracket.upper_bound if bracket.upper_bound is not None else income
        slice_income = min(income, upper) - bracket.lower_bound
        if slice_income > 0: tax += slice_income * bracket.marginal_rate
    # base_tax is supported for jurisdictions/profiles that publish fixed bases.
    containing = next((item for item in reversed(ordered) if income > item.lower_bound), None)
    if containing and containing.base_tax:
        tax = max(tax, containing.base_tax + max(ZERO, income - containing.lower_bound) * containing.marginal_rate)
    return money(tax)


def compute_leave_pay(months: Iterable[LeaveMonth], leave_days: Decimal, policy: Mapping[str, Any] | None = None) -> Decimal:
    policy = policy or {}
    eligible = [month for month in months if month.eligible]
    earnings = sum((money(month.earnings) for month in eligible), ZERO)
    days = sum((Decimal(str(month.worked_days)) for month in eligible), ZERO)
    if leave_days <= 0: return ZERO
    if days <= 0:
        fallback = policy.get("missing_history_fallback", "error")
        if fallback == "zero": return ZERO
        if fallback == "base_salary": return ZERO  # caller must supply a base-derived component
        raise ValueError("Vacation pay requires eligible 12-month earnings and worked-day history")
    return money(earnings / days * leave_days)


def _relief_for_income(income: Decimal, eligibilities: frozenset[str], rules: StatutoryRules) -> Decimal:
    amount = ZERO
    for tier in rules.relief_tiers:
        if tier.eligibility_code not in eligibilities or income < tier.lower_bound or (tier.upper_bound is not None and income > tier.upper_bound):
            continue
        candidate = money(tier.fixed_amount, rules.rounding_quantum)
        if tier.formula:
            candidate = _SafeFormula(tier.formula).evaluate({
                "income": income,
                "lower_bound": tier.lower_bound,
                "upper_bound": tier.upper_bound if tier.upper_bound is not None else income,
                "fixed_amount": tier.fixed_amount,
            }, rules.rounding_quantum)
        amount = max(amount, candidate)
    return amount


def calculate_payslip(data: CalculationInput, rules: StatutoryRules) -> CalculationResult:
    quantum = rules.rounding_quantum
    context = {"base_salary": money(data.base_salary, quantum), "payable_workdays": data.payable_workdays, "scheduled_workdays": data.scheduled_workdays, "payable_calendar_days": data.payable_calendar_days, "scheduled_calendar_days": data.scheduled_calendar_days, "payable_hours": data.payable_hours, "scheduled_hours": data.scheduled_hours, **data.context}
    lines = list(evaluate_components(data.components, context, quantum=quantum, payable_workdays=data.payable_workdays, scheduled_workdays=data.scheduled_workdays, payable_calendar_days=data.payable_calendar_days, scheduled_calendar_days=data.scheduled_calendar_days, payable_hours=data.payable_hours, scheduled_hours=data.scheduled_hours))
    if data.leave_days > 0:
        leave_amount = compute_leave_pay(data.leave_months, data.leave_days, rules.leave_policy)
        lines.append({"code": "vacation_pay", "label": "Vacation pay", "component_kind": "earning", "amount": leave_amount, "taxable": True, "shi_subject": True, "non_taxable_allowance": False, "leave_average_eligible": False, "payer": "employee", "formula": "12_month_average * leave_days", "position": max((line["position"] for line in lines), default=0) + 1})
    gross = money(sum((line["amount"] for line in lines if line["component_kind"] == "earning" and line["payer"] == "employee" and not line.get("only_tax_impact", False)), ZERO), quantum)
    employee_deduction_components = money(sum((line["amount"] for line in lines if line["component_kind"] == "deduction" and line["payer"] == "employee"), ZERO), quantum)
    shi_subject_gross = money(sum((line["amount"] for line in lines if line["component_kind"] == "earning" and line["payer"] == "employee" and line["shi_subject"] and not line.get("only_tax_impact", False)), ZERO), quantum)
    if data.withhold_statutory:
        shi_base, employee_shi, employer_shi, shi_by_fund = compute_shi(shi_subject_gross, rules, prior_month_base=data.prior_month_shi_base, exemption_codes=data.exemption_codes)
    else:
        shi_base, employee_shi, employer_shi, shi_by_fund = ZERO, ZERO, ZERO, {}
    # An allowance may be marked as taxable by a generic component template,
    # but an explicit non-taxable designation always wins.  Keeping this
    # predicate here (rather than asking callers to pre-filter lines) makes
    # the taxable-base contract deterministic for every run type.
    taxable_earnings = money(sum((line["amount"] for line in lines if line["component_kind"] == "earning" and line["payer"] == "employee" and line["taxable"] and not line.get("non_taxable_allowance", False)), ZERO), quantum)
    taxable_income = max(ZERO, money(taxable_earnings - employee_shi - data.other_tax_deductible, quantum)) if data.withhold_statutory else ZERO
    prior_taxable = money(data.prior_ytd_taxable, quantum)
    prior_pit = money(data.prior_ytd_pit, quantum)
    if data.withhold_statutory:
        pit_basis = money(prior_taxable + taxable_income, quantum) if rules.pit_withholding_method == "ytd_cumulative" else taxable_income
        pit_before_relief_cumulative = compute_progressive_pit(pit_basis, rules.pit_brackets)
        relief_cumulative = min(pit_before_relief_cumulative, _relief_for_income(pit_basis, data.relief_eligibilities, rules) + max(ZERO, data.other_tax_credit))
        pit_cumulative = max(ZERO, pit_before_relief_cumulative - relief_cumulative)
        if rules.pit_withholding_method == "ytd_cumulative":
            pit = max(ZERO, money(pit_cumulative - prior_pit, quantum))
            relief = max(ZERO, money(relief_cumulative - data.prior_ytd_relief, quantum))
        else:
            pit_before_relief_cumulative = compute_progressive_pit(taxable_income, rules.pit_brackets)
            relief = min(pit_before_relief_cumulative, _relief_for_income(taxable_income, data.relief_eligibilities, rules) + max(ZERO, data.other_tax_credit))
            pit = max(ZERO, money(pit_before_relief_cumulative - relief, quantum))
    else:
        pit_basis = ZERO
        pit_before_relief_cumulative = relief_cumulative = pit = relief = ZERO
    other_deductions = money(employee_deduction_components + data.other_deductions, quantum)
    net_before_advance = money(gross - employee_shi - pit - other_deductions, quantum)
    requested_advance = max(ZERO, money(data.current_advance, quantum))
    advance_offset = min(requested_advance, max(ZERO, net_before_advance)) if not data.allow_negative_net else requested_advance
    unapplied_advance = max(ZERO, requested_advance - advance_offset)
    net_pay = money(net_before_advance - advance_offset, quantum)
    ytd = {"gross": money(data.prior_ytd_gross + (gross if data.withhold_statutory else ZERO), quantum), "taxable": money(prior_taxable + taxable_income, quantum), "pit": money(prior_pit + pit, quantum), "relief": money(data.prior_ytd_relief + relief, quantum), "shi_base": money(data.prior_month_shi_base + shi_base, quantum)}
    trace = {"formula_context": {key: str(value) for key, value in context.items() if isinstance(value, (Decimal, int, float, str, bool))}, "shi": {"cap": str(money(rules.minimum_wage * rules.shi_ceiling_multiplier, quantum)), "remaining_cap": str(max(ZERO, money(rules.minimum_wage * rules.shi_ceiling_multiplier, quantum) - data.prior_month_shi_base)), "by_fund": {key: str(value) for key, value in shi_by_fund.items()}}, "pit": {"method": rules.pit_withholding_method, "basis": str(pit_basis), "before_relief": str(pit_before_relief_cumulative), "relief": str(relief), "declared_deduction": str(data.other_tax_deductible), "declared_credit": str(data.other_tax_credit), "prior_withheld": str(prior_pit)}, "advance": {"requested": str(requested_advance), "offset": str(advance_offset), "unapplied": str(unapplied_advance)}}
    return CalculationResult(tuple(lines), gross, taxable_income, shi_subject_gross, shi_base, employee_shi, employer_shi, pit_before_relief_cumulative, relief, pit, advance_offset, unapplied_advance, other_deductions, net_pay, ytd, trace)


def snapshot_checksum(value: Mapping[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(payload).hexdigest()
