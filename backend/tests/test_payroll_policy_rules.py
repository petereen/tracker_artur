import pytest

from app.payroll.calculator import overtime_rule_errors


def test_overtime_policy_accepts_configured_law_floor_values():
    assert overtime_rule_errors({"weekday": "1.5", "rest_day": "2", "public_holiday": "2", "night": "0.2"}) == []


@pytest.mark.parametrize(("code", "value"), [("weekday", "1.49"), ("public_holiday", "1.99"), ("night", "0.19")])
def test_overtime_policy_rejects_values_below_law_floor(code, value):
    errors = overtime_rule_errors({code: value})
    assert errors[0]["code"] == "payroll_overtime_below_legal_minimum"
