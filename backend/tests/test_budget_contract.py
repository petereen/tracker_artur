from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.budget.excel import build_budget_workbook, parse_budget_workbook
from app.budget.schemas import BudgetCreate, GroupInput, LineRow
from app.budget.service import (
    BudgetError,
    adjusted_amount,
    assert_unique_rows,
    column_label,
    measures,
    performance_pct,
    period_columns,
    prorate,
    shift_years,
    sign_ok,
    split_by_bucket,
    variance_status,
)
from app.erp.service import ERP_MODULES, ROLE_TEMPLATES
from app.main import app
from app.models.models import Base

D = Decimal


def test_budget_tables_are_registered_and_tenant_scoped():
    tables = Base.metadata.tables
    for name in ("budget_account_groups", "budget_accounts", "budget_account_links", "budgets", "budget_entries"):
        assert name in tables
        assert tables[name].c.organization_id.nullable is False
    links = tables["budget_account_links"]
    # One budget account per ledger account, so actuals are never double counted.
    assert any({column.name for column in constraint.columns} == {"organization_id", "erp_account_id"}
               for constraint in links.constraints if constraint.__class__.__name__ == "UniqueConstraint")
    for column in ("is_primary", "status", "scenario", "period_type", "version"):
        assert tables["budgets"].c[column].nullable is False and tables["budgets"].c[column].server_default is not None


def test_budget_routes_are_mounted_under_erp():
    paths = {route.path for route in app.routes}
    for path in (
        "/v1/erp/budget/capabilities", "/v1/erp/budget/lookups", "/v1/erp/budget/groups", "/v1/erp/budget/accounts", "/v1/erp/budget/accounts/generate",
        "/v1/erp/budget/budgets", "/v1/erp/budget/budgets/{budget_id}", "/v1/erp/budget/budgets/{budget_id}/lines",
        "/v1/erp/budget/budgets/{budget_id}/approve", "/v1/erp/budget/budgets/{budget_id}/copy", "/v1/erp/budget/budgets/{budget_id}/import",
        "/v1/erp/budget/analysis", "/v1/erp/budget/analysis/transactions", "/v1/erp/budget/analysis/export",
    ):
        assert path in paths, path


def test_budget_is_an_erp_module_and_accountants_manage_it():
    assert "budget" in ERP_MODULES
    capabilities = set(ROLE_TEMPLATES["erp_accountant"][1])
    assert ("budget", "*") in capabilities and ("budget_settings", "*") in capabilities


def test_period_columns_clip_to_budget_dates():
    months = period_columns("month", date(2026, 1, 15), date(2026, 3, 10))
    assert months == [(date(2026, 1, 15), date(2026, 1, 31)), (date(2026, 2, 1), date(2026, 2, 28)), (date(2026, 3, 1), date(2026, 3, 10))]
    assert len(period_columns("month", date(2026, 1, 1), date(2026, 12, 31))) == 12
    quarters = period_columns("quarter", date(2026, 1, 1), date(2026, 12, 31))
    assert quarters[1] == (date(2026, 4, 1), date(2026, 6, 30)) and len(quarters) == 4
    assert period_columns("year", date(2025, 7, 1), date(2026, 6, 30)) == [(date(2025, 7, 1), date(2025, 12, 31)), (date(2026, 1, 1), date(2026, 6, 30))]
    assert period_columns("custom", date(2026, 1, 1), date(2026, 8, 31)) == [(date(2026, 1, 1), date(2026, 8, 31))]
    assert column_label("quarter", date(2026, 4, 1), date(2026, 6, 30)) == "2026 Q2"
    assert column_label("month", date(2026, 2, 1), date(2026, 2, 28)) == "2026.02"


def test_prorate_is_linear_by_day():
    # d161: 1.2 тэрбум жилийн төсөв, 6 сар өнгөрсөн → ≈ 600 сая байх ёстой.
    expected = prorate(D("1200000000"), date(2026, 1, 1), date(2026, 12, 31), date(2026, 1, 1), date(2026, 6, 30))
    assert abs(expected - D("1200000000") * 181 / 365) < 1
    assert prorate(D("310"), date(2026, 1, 1), date(2026, 1, 31), date(2026, 1, 1), date(2026, 1, 10)) == D("100")
    assert prorate(D("100"), date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1), date(2026, 2, 28)) == 0
    assert prorate(D("100"), date(2026, 1, 1), date(2026, 1, 31), date(2025, 1, 1), date(2027, 1, 1)) == D("100")


def test_split_by_bucket_spreads_a_quarter_into_months():
    parts = split_by_bucket(D("900"), date(2026, 1, 1), date(2026, 3, 31), date(2026, 1, 1), date(2026, 12, 31), "month")
    assert [bucket[0] for bucket, _ in parts] == [date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 1)]
    assert sum(value for _, value in parts) == D("900")
    assert parts[1][1] == D("900") * 28 / 90


def test_sign_rule_income_positive_costs_negative():
    assert sign_ok("income", D("500")) and not sign_ok("income", D("-1"))
    assert sign_ok("expense", D("-100")) and not sign_ok("expense", D("100"))
    assert sign_ok("cogs", D("-5")) and not sign_ok("cogs", D("5"))
    assert sign_ok("other", D("5")) and sign_ok("other", D("-5"))
    assert sign_ok("expense", D("0"))


def test_variance_reads_the_same_way_for_income_and_expense():
    # d161 worked example: (budget, should-be, actual, performance).
    sales = measures(D("1200"), D("600"), D("650"))
    salary = measures(D("-300"), D("-150"), D("-160"))
    rent = measures(D("-120"), D("-60"), D("-60"))
    marketing = measures(D("-80"), D("-40"), D("-55"))
    assert (sales["performance_pct"], sales["status"]) == ("108.3", "favorable")
    assert (salary["performance_pct"], salary["status"]) == ("106.7", "unfavorable")
    assert (rent["performance_pct"], rent["status"]) == ("100.0", "on_track")
    assert (marketing["performance_pct"], marketing["status"]) == ("137.5", "unfavorable")
    assert salary["variance"] == "-10.00" and sales["variance"] == "50.00"
    assert variance_status(D("-100"), D("-80")) == "favorable"  # spent less than planned
    assert variance_status(D("0"), D("5")) == "unplanned" and variance_status(D("0"), D("0")) == "no_activity"
    assert performance_pct(D("5"), D("0")) is None


def test_profit_is_income_plus_expense():
    income, expense = D("500000000"), D("-350000000")
    assert income + expense == D("150000000")


def test_scenario_copy_scales_and_shifts():
    assert adjusted_amount(D("-100"), D("10")) == D("-110.00")
    assert adjusted_amount(D("200"), D("-15")) == D("170.00")
    assert shift_years(date(2024, 2, 29), 1) == date(2025, 2, 28)


def test_duplicate_rows_are_rejected():
    assert_unique_rows([(1, None, None), (1, 2, None), (1, None, 3)])
    with pytest.raises(BudgetError):
        assert_unique_rows([(1, None, None), (1, None, None)])


def test_schemas_validate_period_and_amounts():
    with pytest.raises(ValidationError):
        BudgetCreate(name="2026", start_date=date(2026, 12, 31), end_date=date(2026, 1, 1))
    with pytest.raises(ValidationError):
        BudgetCreate(name="Too long", start_date=date(2020, 1, 1), end_date=date(2026, 1, 1))
    with pytest.raises(ValidationError):
        LineRow(budget_account_id=1, amounts={date(2026, 1, 1): D("NaN")})
    with pytest.raises(ValidationError):
        GroupInput(code="bad code", name="x")
    assert GroupInput(code="ЗАРДАЛ-1", name=" Зардал ").name == "Зардал"


def test_excel_round_trip():
    columns = [{"start": date(2026, 1, 1), "label": "2026.01"}, {"start": date(2026, 2, 1), "label": "2026.02"}]
    content = build_budget_workbook(title="BUD-0001", columns=columns, rows=[
        {"account_code": "4000", "account_name": "Борлуулалт", "project_code": None, "party_group_code": "CUSTOMERS", "note": "Жилийн зорилт",
         "amounts": {date(2026, 1, 1): D("80000000"), date(2026, 2, 1): D("85000000")}},
        {"account_code": "5100", "account_name": "Цалин", "project_code": "P-1", "party_group_code": None, "note": None,
         "amounts": {date(2026, 1, 1): D("-25000000")}},
    ])
    parsed = parse_budget_workbook(content, [date(2026, 1, 1), date(2026, 2, 1)])
    assert parsed.errors == []
    assert [row.account_code for row in parsed.rows] == ["4000", "5100"]
    assert parsed.rows[0].amounts == {date(2026, 1, 1): D("80000000"), date(2026, 2, 1): D("85000000")}
    assert parsed.rows[0].party_group_code == "CUSTOMERS" and parsed.rows[1].project_code == "P-1"
    # A workbook from a different period is flagged instead of silently dropped.
    mismatched = parse_budget_workbook(content, [date(2026, 1, 1)])
    assert mismatched.errors and "2026-02-01" in mismatched.errors[0]["message"]
    with pytest.raises(ValueError):
        parse_budget_workbook(b"not a workbook", [date(2026, 1, 1)])
