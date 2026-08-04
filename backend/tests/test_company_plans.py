from datetime import date

import pytest
from pydantic import ValidationError

from app.routers.company_plans import CompanyPlanItemCreate, CompanyPlanReorder, _month_start


def test_company_plan_month_is_normalized_to_first_day():
    assert _month_start(date(2026, 8, 31)) == date(2026, 8, 1)


def test_company_plan_item_accepts_all_horizons():
    for horizon in ("long_term", "mid_term", "short_term"):
        item = CompanyPlanItemCreate(source_report_id=7, title="Шинэ зүйл", horizon=horizon)
        assert item.horizon == horizon


def test_company_plan_item_rejects_unknown_horizon():
    with pytest.raises(ValidationError):
        CompanyPlanItemCreate(source_report_id=7, title="Шинэ зүйл", horizon="urgent")


def test_reorder_requires_each_horizon_and_unique_item_ids():
    columns = {"long_term": [1], "mid_term": [2], "short_term": [3]}
    assert CompanyPlanReorder(plan_month=date(2026, 8, 1), columns=columns).columns == columns
    with pytest.raises(ValidationError):
        CompanyPlanReorder(plan_month=date(2026, 8, 1), columns={"long_term": [1], "mid_term": [], "short_term": [1]})
