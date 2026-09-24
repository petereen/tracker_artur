from copy import deepcopy

import pytest

pytest.importorskip("fastapi")

from app.payroll.monthly_workflow import MonthlyRuleSetInput, _rule_input_default, _rule_validation_issues


def test_default_rule_template_passes_effective_date_source_and_tier_validation():
    payload = MonthlyRuleSetInput(**_rule_input_default())
    assert _rule_validation_issues(payload) == []


def test_rule_validation_requires_source_and_valid_effective_range():
    raw = _rule_input_default()
    raw["source_references"] = ["  "]
    raw["valid_to"] = raw["valid_from"].replace(year=raw["valid_from"].year - 1)
    issues = _rule_validation_issues(MonthlyRuleSetInput(**raw))
    assert "valid_to_before_valid_from" in issues
    assert "source_reference_required" in issues


def test_rule_validation_rejects_non_contiguous_tax_brackets_and_rates_over_one():
    raw = deepcopy(_rule_input_default())
    raw["employee_rates"]["pension"] = "1.01"
    raw["pit_brackets"][1]["lower"] = "10000001"
    issues = _rule_validation_issues(MonthlyRuleSetInput(**raw))
    assert "shi_rate_out_of_range" in issues
    assert "pit_tiers_must_be_contiguous" in issues
