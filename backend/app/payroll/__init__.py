"""Configurable, snapshot-friendly payroll domain."""

from .calculator import (
    CalculationInput,
    CalculationResult,
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
    evaluate_components,
    prorate_amount,
)

__all__ = [
    "CalculationInput", "CalculationResult", "ComponentDefinition", "FormulaError", "LeaveMonth", "PITBracket",
    "ReliefTier", "SHIRate", "StatutoryRules", "calculate_payslip", "compute_leave_pay",
    "compute_progressive_pit", "compute_shi", "evaluate_components", "prorate_amount",
]
