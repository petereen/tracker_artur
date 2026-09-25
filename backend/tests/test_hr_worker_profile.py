import asyncio
from datetime import date
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.hr.identity import normalize_registration_number, parse_registration_number
from app.hr.schemas import DepartmentInput, EmployeeCreate, EmployeePatch


# ─── Регистрын дугаар ────────────────────────────────────────────────────────

def test_registration_number_decodes_20th_century_birthday_and_gender():
    assert parse_registration_number("УБ99011512") == {"birthday": date(1999, 1, 15), "gender": "male"}


def test_registration_number_month_offset_marks_2000s_births():
    # Month 23 = March, born 2001; second-to-last digit 2 is even -> female.
    assert parse_registration_number("ТА01231524") == {"birthday": date(2001, 3, 15), "gender": "female"}


@pytest.mark.parametrize("value", ["UB99011512", "УБ9901151", "УБ990115123", "У99011512", "УБ99131512", "УБ99023012"])
def test_registration_number_rejects_bad_format_or_date(value):
    with pytest.raises(ValueError):
        parse_registration_number(value)


def test_registration_number_normalisation():
    assert normalize_registration_number(" уб 9901-1512 ") == "УБ99011512"
    assert normalize_registration_number("   ") is None
    assert normalize_registration_number(None) is None


# ─── Worker schemas ─────────────────────────────────────────────────────────

def test_create_derives_display_name_and_normalises_identity():
    data = EmployeeCreate(first_name="Бат", last_name="Дорж", registration_number="уб99011512", email=" Bat@Example.MN ", phone_number="+976 9911 2233")
    assert data.name == "Бат Дорж"
    assert data.registration_number == "УБ99011512"
    assert data.email == "bat@example.mn"
    assert data.employment_status == "active"


def test_create_requires_some_name():
    with pytest.raises(ValidationError):
        EmployeeCreate(first_name="  ", registration_number="УБ99011512")


@pytest.mark.parametrize("field,value", [("registration_number", "12345"), ("phone_number", "call me"), ("email", "not-an-email")])
def test_create_rejects_invalid_contact_fields(field, value):
    with pytest.raises(ValidationError):
        EmployeeCreate(name="Бат", **{field: value})


def test_create_rejects_leaving_before_joining():
    with pytest.raises(ValidationError):
        EmployeeCreate(name="Бат", start_date=date(2026, 5, 1), end_date=date(2026, 4, 30))


def test_create_only_allows_working_statuses():
    assert EmployeeCreate(name="Бат", employment_status="probation").employment_status == "probation"
    with pytest.raises(ValidationError):
        EmployeeCreate(name="Бат", employment_status="terminated")


def test_patch_keeps_explicit_nulls_to_clear_fields():
    patch = EmployeePatch(registration_number="", department_id=None, employment_status="on_leave")
    assert patch.model_dump(exclude_unset=True) == {"registration_number": None, "department_id": None, "employment_status": "on_leave"}


def test_department_code_is_optional_but_validated():
    assert DepartmentInput(name=" Санхүү ", code=" ").model_dump() == {"code": None, "name": "Санхүү", "description": None, "manager_employee_id": None}
    with pytest.raises(ValidationError):
        DepartmentInput(name="Санхүү", code="санхүү")


# ─── Status / active alignment ──────────────────────────────────────────────

class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _FakeDB:
    def __init__(self, details, accounts):
        self.details = details
        self.accounts = accounts

    async def scalar(self, _query):
        return self.details

    async def execute(self, _query):
        return _Rows(self.accounts)


def _worker(status="active", is_active=True, account_status="active"):
    from app.hr import service

    employee = SimpleNamespace(id=7, organization_id=1, is_active=is_active, deleted_at=None, deleted_by_account_id=None)
    details = SimpleNamespace(employment_status=status)
    account = SimpleNamespace(status=account_status)
    return service, employee, details, account


def test_precise_status_is_stored_and_disables_login():
    service, employee, details, account = _worker()
    asyncio.run(service.set_worker_active(_FakeDB(details, [account]), employee, False, status="on_leave"))
    assert (employee.is_active, details.employment_status, account.status) == (False, "on_leave", "disabled")


def test_plain_toggle_keeps_compatible_status():
    service, employee, details, account = _worker(status="probation")
    asyncio.run(service.set_worker_active(_FakeDB(details, [account]), employee, True))
    assert details.employment_status == "probation"


def test_reactivation_leaves_account_state_to_admins():
    service, employee, details, account = _worker(status="inactive", is_active=False, account_status="disabled")
    asyncio.run(service.set_worker_active(_FakeDB(details, [account]), employee, True))
    assert (employee.is_active, details.employment_status, account.status) == (True, "active", "disabled")


def test_status_must_match_active_flag():
    service, employee, details, account = _worker()
    with pytest.raises(ValueError):
        asyncio.run(service.set_worker_active(_FakeDB(details, [account]), employee, True, status="terminated"))


# ─── Router helpers ─────────────────────────────────────────────────────────

def test_event_payload_never_carries_private_values():
    from app.hr.router import _event_payload

    payload = _event_payload(7, {"registration_number": "УБ99011512", "address": "Хан-Уул", "birthday": date(1999, 1, 15), "department_id": 3, "employment_status": "on_leave"})
    assert payload == {"employee_id": 7, "department_id": 3, "employment_status": "on_leave", "changed_fields": ["address", "birthday", "department_id", "employment_status", "registration_number"]}


def test_reported_status_follows_is_active_when_legacy_rows_disagree():
    from app.hr.router import _employment_status

    assert _employment_status(SimpleNamespace(is_active=False), SimpleNamespace(employment_status="active")) == "inactive"
    assert _employment_status(SimpleNamespace(is_active=True), SimpleNamespace(employment_status="probation")) == "probation"
    assert _employment_status(SimpleNamespace(is_active=True), None) == "active"


def test_registration_defaults_do_not_override_existing_values():
    from app.hr.router import _registration_defaults

    filled = _registration_defaults({"registration_number": "УБ99011512", "birthday": None, "gender": None})
    assert (filled["birthday"], filled["gender"]) == (date(1999, 1, 15), "male")
    kept = _registration_defaults({"registration_number": "УБ99011512"}, birthday=date(1999, 1, 16), gender="female")
    assert "birthday" not in kept and "gender" not in kept
