"""Custom roles only grant what the code enforces; admin is never grantable."""
import asyncio

import pytest
from fastapi import HTTPException

from app.erp.role_catalog import CATALOG_PAIRS, GRANTABLE_SYSTEM_ROLE_KEYS, catalog, granted_system_roles, normalize_system_roles
from app.erp.router import CapabilityInput, _validated_capabilities, _validated_system_roles


def test_catalog_offers_the_resources_the_modules_check():
    for pair in [("crm_activity", "edit"), ("budget", "approve"), ("budget_settings", "edit"), ("crm_settings", "edit"),
                 ("payroll", "view_salary"), ("accounts", "view"), ("parties", "archive"), ("erp_roles", "administer")]:
        assert pair in CATALOG_PAIRS


def test_unlicensed_modules_are_hidden_from_the_editor():
    modules = {module["key"] for module in catalog({"crm"})["modules"]}
    assert "crm" in modules and "budget" not in modules and "payroll" not in modules
    assert "accounting" in modules  # always-on core


def test_capabilities_from_the_catalog_validate_and_deduplicate():
    pairs = _validated_capabilities([CapabilityInput(resource="crm_activity", action="edit"), CapabilityInput(resource="crm_activity", action="edit"), CapabilityInput(resource="budget", action="view")])
    assert pairs == [("crm_activity", "edit"), ("budget", "view")]


def test_unknown_capabilities_are_rejected_with_a_reason():
    with pytest.raises(HTTPException) as error:
        _validated_capabilities([CapabilityInput(resource="crm_activity", action="pay")])
    assert error.value.status_code == 422 and error.value.detail["code"] == "erp_role_unknown_capability"


def test_admin_cannot_be_granted_through_a_role():
    assert "admin" not in GRANTABLE_SYSTEM_ROLE_KEYS
    assert normalize_system_roles(["manager", "hr", "manager"]) == ["hr", "manager"]
    with pytest.raises(HTTPException):
        _validated_system_roles(["admin"])
    # Stored junk never turns into access.
    assert granted_system_roles(["admin", "hr", "nope"]) == {"hr"}


class _Result:
    def __init__(self, rows): self._rows = rows
    def scalars(self): return self
    def all(self): return self._rows


class _Db:
    def __init__(self, *results): self._results = list(results)
    async def execute(self, _query): return _Result(self._results.pop(0))


def test_actor_gets_platform_roles_from_direct_and_team_roles():
    from app.core.enterprise_deps import custom_role_grants

    grants = asyncio.run(custom_role_grants(_Db([["manager"], ["admin"]], [["hr"]]), account_id=1, employee_id=2))
    assert grants == {"manager", "hr"}
    # Without a worker there are no team roles to look up.
    assert asyncio.run(custom_role_grants(_Db([["legal_counsel"]]), account_id=1, employee_id=None)) == {"legal_counsel"}


def test_template_wildcards_survive_editing_a_cloned_role():
    pairs = _validated_capabilities([CapabilityInput(resource="accounts", action="*"), CapabilityInput(resource="customer", action="*"), CapabilityInput(resource="*", action="*")])
    assert pairs == [("accounts", "*"), ("customer", "*"), ("*", "*")]
