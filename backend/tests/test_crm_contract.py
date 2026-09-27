import asyncio
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from app.crm.schemas import ActivityCreate, PartyCreate, PartyPatch, StatusInput
from app.crm.service import (
    activity_is_open,
    activity_is_overdue,
    completion_updates,
    derive_party_type,
    field_changes,
    normalize_tags,
    overdue_days,
    party_flags_for_type,
)
from app.erp.service import ROLE_TEMPLATES
from app.main import app
from app.models.models import Base
from app.services.ebarimt_lookup import TaxpayerLookupError, lookup_taxpayer, parse_info_response, parse_tin_response

UTC = timezone.utc


def test_crm_tables_are_registered_and_tenant_scoped():
    tables = Base.metadata.tables
    for name in ("crm_activities", "crm_activity_types", "erp_statuses", "erp_party_groups", "erp_payment_terms", "erp_party_contacts", "erp_party_bank_accounts"):
        assert name in tables
        assert tables[name].c.organization_id.nullable is False
    parties = tables["erp_parties"].c
    for column in ("registry_no", "is_customer", "is_supplier", "vat_payer", "city_tax_payer", "parent_party_id", "group_id",
                   "payment_term_id", "responsible_employee_id", "customer_since", "inactive_since", "tags", "version"):
        assert column in parties
    # Booleans are NOT NULL with server defaults (PR #3 hardening pattern).
    for column in ("is_customer", "is_supplier", "is_individual", "is_foreign", "vat_payer", "city_tax_payer", "settle_via_parent"):
        assert parties[column].nullable is False and parties[column].server_default is not None
    activities = tables["crm_activities"].c
    assert activities.subject.nullable is False and activities.party_id.nullable is True


def test_crm_routes_are_mounted_under_erp():
    paths = {route.path for route in app.routes}
    for path in (
        "/v1/erp/crm/capabilities", "/v1/erp/crm/lookups", "/v1/erp/crm/summary", "/v1/erp/crm/parties", "/v1/erp/crm/parties/{party_id}",
        "/v1/erp/crm/parties/{party_id}/history", "/v1/erp/crm/parties/lookup-taxpayer", "/v1/erp/crm/parties/import",
        "/v1/erp/crm/activities", "/v1/erp/crm/activities/bulk", "/v1/erp/crm/activities/{activity_id}/clone",
        "/v1/erp/crm/activities/{activity_id}/task", "/v1/erp/crm/settings/statuses", "/v1/erp/crm/settings/party-groups",
    ):
        assert path in paths


def test_static_party_routes_are_declared_before_the_id_route():
    ordered = [route.path for route in app.routes if route.path.startswith("/v1/erp/crm/parties")]
    detail = ordered.index("/v1/erp/crm/parties/{party_id}")
    for static in ("/v1/erp/crm/parties/lookup-taxpayer", "/v1/erp/crm/parties/export.csv", "/v1/erp/crm/parties/import-template.csv", "/v1/erp/crm/parties/import"):
        assert ordered.index(static) < detail


def test_sales_role_template_grants_crm_activities():
    capabilities = set(ROLE_TEMPLATES["erp_sales"][1])
    assert ("crm_activity", "*") in capabilities and ("parties", "*") in capabilities


def test_migration_chains_after_leave_pay_type():
    source = (Path(__file__).parents[1] / "alembic" / "versions" / "d1e2f3a4b5c6_crm_module.py").read_text()
    assert 'down_revision: Union[str, Sequence[str], None] = "c0d1e2f3a4b5"' in source
    assert "erp_party_contacts" in source and "jsonb_array_elements" in source


def test_overdue_days_uses_completion_or_today():
    due = datetime(2026, 9, 10, 12, tzinfo=UTC)
    assert overdue_days(due, None, date(2026, 9, 15)) == 5
    assert overdue_days(due, datetime(2026, 9, 12, 9, tzinfo=UTC), date(2026, 9, 30)) == 2
    assert overdue_days(due, datetime(2026, 9, 9, tzinfo=UTC), date(2026, 9, 30)) == 0
    assert overdue_days(None, None, date(2026, 9, 30)) == 0
    assert overdue_days(due, None, date(2026, 9, 1)) == 0


def test_open_and_overdue_follow_closure_completion_and_status_category():
    now = datetime(2026, 9, 25, 10, tzinfo=UTC)
    past = now - timedelta(hours=1)
    assert activity_is_open(is_closed=False, completed_at=None, status_category="open")
    assert not activity_is_open(is_closed=True, completed_at=None, status_category="open")
    assert not activity_is_open(is_closed=False, completed_at=now, status_category="in_progress")
    assert not activity_is_open(is_closed=False, completed_at=None, status_category="done")
    assert activity_is_overdue(is_closed=False, completed_at=None, status_category="waiting", due_at=past, now=now)
    assert not activity_is_overdue(is_closed=False, completed_at=None, status_category="cancelled", due_at=past, now=now)
    assert not activity_is_overdue(is_closed=False, completed_at=None, status_category=None, due_at=None, now=now)


def test_completion_updates_fill_dates_without_overwriting_user_input():
    now = datetime(2026, 9, 25, tzinfo=UTC)
    typed = datetime(2026, 9, 20, tzinfo=UTC)
    assert completion_updates(is_closed=True, was_closed=False, completed_at=None, status_category="open", now=now) == {"completed_at": now, "closed_at": now}
    assert completion_updates(is_closed=False, was_closed=False, completed_at=typed, status_category="done", now=now) == {}
    assert completion_updates(is_closed=False, was_closed=False, completed_at=None, status_category="done", now=now) == {"completed_at": now}
    assert completion_updates(is_closed=False, was_closed=True, completed_at=typed, status_category="open", now=now) == {"closed_at": None}
    assert completion_updates(is_closed=False, was_closed=False, completed_at=None, status_category="in_progress", now=now) == {}


def test_party_type_and_flags_are_consistent():
    assert derive_party_type(is_customer=True, is_supplier=False) == "customer"
    assert derive_party_type(is_customer=False, is_supplier=True) == "supplier"
    assert derive_party_type(is_customer=True, is_supplier=True) == "customer"
    assert derive_party_type(is_customer=True, is_supplier=False, requested="prospect") == "prospect"
    assert derive_party_type(is_customer=False, is_supplier=False) == "prospect"
    assert party_flags_for_type("supplier") == {"is_customer": False, "is_supplier": True}
    assert party_flags_for_type("prospect") == {"is_customer": True, "is_supplier": False}


def test_tags_are_trimmed_deduplicated_and_bounded():
    assert normalize_tags([" VIP ", "vip", "Бөөний  худалдаа", "", "  "]) == ["VIP", "Бөөний худалдаа"]
    assert len(normalize_tags([f"t{i}" for i in range(50)])) == 30


def test_field_changes_reports_only_real_differences():
    before = {"name": "А", "credit_limit": Decimal("100.0000"), "customer_since": date(2026, 1, 1), "group_id": 1}
    after = {"name": "Б", "credit_limit": Decimal("100"), "customer_since": date(2026, 1, 1), "group_id": None}
    assert field_changes(before, after, before.keys()) == {"name": {"from": "А", "to": "Б"}, "group_id": {"from": 1, "to": None}}


def test_party_schema_cleans_blank_values_and_validates_codes():
    party = PartyCreate(name="  Даянсофт ", registry_no="ab1234567", email="", code="10001")
    assert party.name == "Даянсофт" and party.registry_no == "AB1234567" and party.email is None
    with pytest.raises(ValidationError):
        PartyCreate(name="X", code="bad code!")
    with pytest.raises(ValidationError):
        PartyCreate(name="X", email="not-an-email")
    # A blank patch field is an explicit “clear”, not an omitted field.
    assert PartyPatch(tax_id="").model_dump(exclude_unset=True) == {"tax_id": None}


def test_status_schema_requires_hex_colour_and_known_category():
    assert StatusInput(name="Шинэ", color="#aabbcc").color == "#AABBCC"
    with pytest.raises(ValidationError):
        StatusInput(name="Шинэ", color="red")
    with pytest.raises(ValidationError):
        StatusInput(name="Шинэ", category="archived")


def test_activity_schema_treats_naive_times_as_ulaanbaatar():
    activity = ActivityCreate(subject="Уулзалт", due_at="2026-09-25T09:00")
    assert activity.due_at.utcoffset() == timedelta(hours=8)
    assert ActivityCreate(subject="Утас", due_at="2026-09-25T09:00:00+00:00").due_at.utcoffset() == timedelta(0)
    with pytest.raises(ValidationError):
        ActivityCreate(subject="")


def test_ebarimt_response_parsing_is_tolerant():
    assert parse_tin_response({"status": 200, "data": 34101374585}) == "34101374585"
    assert parse_tin_response({"data": None}) is None
    info = parse_info_response({"data": {"name": "ДАЯНСОФТ ХХК", "vatPayer": True, "cityPayer": False, "found": True}}, tin="1", registry_no="5922364")
    assert (info.name, info.vat_payer, info.city_tax_payer, info.found) == ("ДАЯНСОФТ ХХК", True, False, True)


def test_ebarimt_lookup_resolves_registry_then_tin_and_reports_outages():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("getTinInfo"):
            assert request.url.params["regNo"] == "5922364"
            return httpx.Response(200, json={"status": 200, "data": 34101374585})
        assert request.url.params["tin"] == "34101374585"
        return httpx.Response(200, json={"data": {"name": "Даянсофт", "vatPayer": True, "cityPayer": True, "found": True}})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            info = await lookup_taxpayer(registry_no="5922364", client=client)
        assert info.tin == "34101374585" and info.vat_payer and info.city_tax_payer
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(502))) as client:
            with pytest.raises(TaxpayerLookupError) as failure:
                await lookup_taxpayer(tin="1", client=client)
        assert failure.value.code == "ebarimt_unavailable"
        with pytest.raises(TaxpayerLookupError):
            await lookup_taxpayer()

    asyncio.run(run())
