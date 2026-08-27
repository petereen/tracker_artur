import pytest
from pydantic import ValidationError

from app.main import app
from app.models.models import Base
from app.payroll.schemas import PayrollRunInput, VariablePayInput


def test_payroll_run_persists_sequence_audit_state():
    table = Base.metadata.tables["payroll_runs"]
    assert {"reconciliation_snapshot", "approval_workflow", "approved_at", "payslips_published_at"}.issubset(table.c.keys())


def test_payroll_sequence_routes_are_exposed_through_the_dedicated_module():
    paths = {route.path for route in app.routes}
    assert {
        "/v1/erp/payroll/runs/{run_id}/reconciliation",
        "/v1/erp/payroll/runs/{run_id}/reconciliation/resolve",
        "/v1/erp/payroll/runs/{run_id}/approve",
        "/v1/erp/payroll/runs/{run_id}/cash-vouchers",
        "/v1/erp/payroll/runs/{run_id}/publish-payslips",
        "/v1/erp/payroll/me/payslips/{payslip_id}/protected-download",
    }.issubset(paths)


def test_variable_pay_inputs_are_typed_and_frozen_with_the_run_contract():
    variable = VariablePayInput(employee_id=7, code="sales_bonus", label="Sales bonus", amount="125000", component_kind="earning", source="bonus")
    run = PayrollRunInput(run_type="single", period_start="2026-08-01", period_end="2026-08-31", tax_point_date="2026-08-31", variable_inputs=[variable])
    assert run.variable_inputs[0].amount.as_tuple().exponent == 0
    with pytest.raises(ValidationError):
        VariablePayInput(employee_id=7, code="Bad code", label="Invalid", amount="0", component_kind="earning")
