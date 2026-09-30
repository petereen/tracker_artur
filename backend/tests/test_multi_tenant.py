"""Multi-tenant SaaS core: license tokens, host routing, request gating, guards.

PostgreSQL behaviour (RLS, triggers, the full operator → tenant flow) lives in
``test_multi_tenant_db.py``.
"""

import asyncio
import base64
import json
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core import tenancy
from app.core.config import settings
from app.core.security import create_access_token, create_enterprise_access_token, create_platform_access_token, decode_platform_access_token, decode_token
from app.core.tenancy import (
    TenantBoundaryViolation,
    TenantNotFound,
    TenantState,
    _guard_flush,
    _guard_loaded_instance,
    bind_tenant,
    classify_host,
    current_tenant_id,
    evaluate_tenant_access,
    feature_for_path,
    normalize_features,
    tenant_scope,
)
from app.core.tenant_middleware import TenantContextMiddleware
from app.models.models import Employee, Organization, UserAccount
from app.services import licensing
from app.services.licensing import LicenseError
from app.services.tenant_service import SeatUsage, account_consumes_seat, add_months, default_expiry, is_seat_limit_error

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def signing(monkeypatch):
    private_pem, public_pem = licensing.generate_keypair()
    monkeypatch.setattr(settings, "LICENSE_SIGNING_PRIVATE_KEY", private_pem)
    monkeypatch.setattr(settings, "LICENSE_SIGNING_KEY_ID", "test-key-1")
    monkeypatch.setattr(settings, "LICENSE_PUBLIC_KEYS", "")
    return private_pem, public_pem


def _issue(**overrides):
    values = dict(
        license_id=str(uuid.uuid4()), tenant_public_id="tenant-a", tenant_slug="acme", seats=5,
        features=["crm", "payroll", "not-a-module"], plan="professional", billing_cycle="monthly",
        valid_from=NOW, expires_at=NOW + timedelta(days=30), now=NOW,
    )
    values.update(overrides)
    return licensing.issue_token(**values)


def _segments(token):
    return token.split(".")


def _encode(value: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=").decode()


# ── license tokens ──────────────────────────────────────────────────────────
def test_license_round_trip_carries_tenant_seats_modules_and_window(signing):
    token, kid = _issue()
    claims = licensing.verify_token(token, now=NOW + timedelta(days=1), expected_tenant="tenant-a")
    assert kid == "test-key-1" and claims.key_id == "test-key-1"
    assert claims.seats == 5
    assert claims.features == ("crm", "payroll")  # unknown modules are dropped
    assert claims.tenant_slug == "acme" and claims.plan == "professional"
    assert claims.expires_at == NOW + timedelta(days=30)
    header = json.loads(base64.urlsafe_b64decode(_segments(token)[0] + "=="))
    assert header == {"alg": "EdDSA", "kid": "test-key-1", "typ": "oyuns-license+jwt"}


@pytest.mark.parametrize(
    "mutate, code",
    [
        (lambda h, c, s: (h, _encode({**c, "seats": 500}), s), "bad_signature"),
        (lambda h, c, s: (h, _encode({**c, "sub": "tenant-b"}), s), "bad_signature"),
        (lambda h, c, s: (_encode({"alg": "HS256", "typ": "oyuns-license+jwt", "kid": "test-key-1"}), _encode(c), s), "unsupported_algorithm"),
        (lambda h, c, s: (_encode({"alg": "EdDSA", "typ": "oyuns-license+jwt", "kid": "other"}), _encode(c), s), "unknown_key"),
    ],
)
def test_tampered_or_foreign_tokens_are_rejected(signing, mutate, code):
    token, _ = _issue()
    header, claims, signature = _segments(token)
    decoded = json.loads(base64.urlsafe_b64decode(claims + "=="))
    forged = ".".join(mutate(header, decoded, signature))
    with pytest.raises(LicenseError) as error:
        licensing.verify_token(forged, now=NOW)
    assert error.value.code == code


def test_expiry_validity_window_and_tenant_binding(signing):
    token, _ = _issue(valid_from=NOW + timedelta(days=2), expires_at=NOW + timedelta(days=30))
    with pytest.raises(LicenseError) as early:
        licensing.verify_token(token, now=NOW)
    assert early.value.code == "not_yet_valid"
    with pytest.raises(LicenseError) as late:
        licensing.verify_token(token, now=NOW + timedelta(days=31))
    assert late.value.code == "expired"
    with pytest.raises(LicenseError) as other:
        licensing.verify_token(token, now=NOW + timedelta(days=3), expected_tenant="tenant-b")
    assert other.value.code == "tenant_mismatch"


@pytest.mark.parametrize("token", ["", "abc", "a.b", "a.b.c.d", "!!.??.**", "x" * 9000])
def test_malformed_tokens_fail_cleanly(signing, token):
    with pytest.raises(LicenseError):
        licensing.verify_token(token, now=NOW)


def test_rotated_signing_key_keeps_old_licenses_verifiable(monkeypatch, signing):
    old_private, old_public = signing
    token, _ = _issue()
    new_private, _ = licensing.generate_keypair()
    monkeypatch.setattr(settings, "LICENSE_SIGNING_PRIVATE_KEY", new_private)
    monkeypatch.setattr(settings, "LICENSE_SIGNING_KEY_ID", "test-key-2")
    monkeypatch.setattr(settings, "LICENSE_PUBLIC_KEYS", json.dumps({"test-key-1": old_public}))
    assert licensing.verify_token(token, now=NOW).key_id == "test-key-1"
    new_token, kid = _issue()
    assert kid == "test-key-2" and licensing.verify_token(new_token, now=NOW).seats == 5


def test_verifier_only_needs_the_public_key(monkeypatch, signing):
    _, public_pem = signing
    token, _ = _issue()
    monkeypatch.setattr(settings, "LICENSE_SIGNING_PRIVATE_KEY", "")
    monkeypatch.setattr(settings, "LICENSE_PUBLIC_KEYS", json.dumps({"test-key-1": public_pem}))
    assert licensing.verify_token(token, now=NOW).seats == 5
    assert not licensing.signing_available()
    with pytest.raises(LicenseError) as error:
        _issue()
    assert error.value.code == "signing_unavailable"


def test_issue_rejects_empty_licenses(signing):
    with pytest.raises(LicenseError):
        _issue(seats=0)
    with pytest.raises(LicenseError):
        _issue(expires_at=NOW)


# ── routing and gating ──────────────────────────────────────────────────────
def test_host_classification(monkeypatch):
    monkeypatch.setattr(settings, "TENANT_BASE_DOMAIN", "oyunserp.com")
    monkeypatch.setattr(settings, "PLATFORM_ROOT_HOSTS", "erp.oyuns.mn,localhost")
    assert classify_host("acme.oyunserp.com") == ("subdomain", "acme")
    assert classify_host("ACME.oyunserp.com:443") == ("subdomain", "acme")
    assert classify_host("www.oyunserp.com") == ("root", None)
    assert classify_host("oyunserp.com") == ("root", None)
    assert classify_host("erp.oyuns.mn") == ("root", None)
    assert classify_host("localhost:5173") == ("root", None)
    assert classify_host("10.1.2.3:8000") == ("root", None)
    assert classify_host("erp.acme.mn") == ("custom", "erp.acme.mn")
    assert classify_host(None) == ("root", None)


def _state(**overrides) -> TenantState:
    values = dict(
        id=2, public_id="p", slug="acme", name="Acme", status="active", is_primary=False, license_required=True,
        license_expires_at=NOW + timedelta(days=10), seat_limit=5, features=frozenset({"crm"}),
    )
    values.update(overrides)
    return TenantState(**values)


def test_feature_routes_respect_segment_boundaries():
    assert feature_for_path("/v1/erp/crm/parties") == "crm"
    assert feature_for_path("/v1/erp/crm") == "crm"
    assert feature_for_path("/v1/erp/crmx") is None
    assert feature_for_path("/tasks") == "legacy_workspace"
    assert feature_for_path("/v1/tasks") is None
    assert feature_for_path("/auth/me") == "legacy_workspace"
    assert feature_for_path("/v1/auth/me") is None
    assert normalize_features(["crm", "crm", "bogus", "payroll"]) == ["crm", "payroll"]


def test_status_license_and_feature_gates():
    active = _state()
    assert evaluate_tenant_access(active, "/v1/erp/crm/parties", NOW) is None
    assert evaluate_tenant_access(active, "/v1/erp/payroll/monthly", NOW).code == "feature_not_licensed"
    assert evaluate_tenant_access(active, "/questions", NOW).code == "feature_not_licensed"

    suspended = _state(status="suspended")
    assert evaluate_tenant_access(suspended, "/v1/tasks", NOW).code == "tenant_suspended"
    assert evaluate_tenant_access(suspended, "/v1/tenant/license", NOW).status_code == 403
    assert evaluate_tenant_access(suspended, "/v1/tenant/branding", NOW) is None
    assert evaluate_tenant_access(_state(status="terminated"), "/v1/tasks", NOW).code == "tenant_terminated"

    missing = _state(license_expires_at=None)
    assert evaluate_tenant_access(missing, "/v1/tasks", NOW).status_code == 402
    assert evaluate_tenant_access(missing, "/v1/tenant/license/activate", NOW) is None
    assert evaluate_tenant_access(missing, "/v1/auth/me", NOW) is None

    lapsed = _state(license_expires_at=NOW - timedelta(days=2))
    assert lapsed.license_state(NOW) == "grace"
    assert evaluate_tenant_access(lapsed, "/v1/tasks", NOW) is None
    expired = _state(license_expires_at=NOW - timedelta(days=settings.LICENSE_GRACE_DAYS + 1))
    assert evaluate_tenant_access(expired, "/v1/tasks", NOW).code == "license_expired"

    grandfathered = _state(license_required=False, license_expires_at=None, is_primary=True, features=frozenset({"legacy_workspace"}))
    assert evaluate_tenant_access(grandfathered, "/questions", NOW) is None
    # Legacy tools stay primary-only even if a license lists them.
    assert not _state(features=frozenset({"legacy_workspace"})).has_feature("legacy_workspace")


class FakeDirectory:
    def __init__(self, states: dict[int, TenantState], hosts: dict[str, int], primary: int = 1):
        self.states, self.hosts, self.primary = states, hosts, primary

    async def resolve_host(self, host):
        kind, value = classify_host(host)
        if kind == "root":
            return None
        if value in self.hosts:
            return self.hosts[value]
        raise TenantNotFound(value)

    async def state(self, tenant_id):
        return self.states.get(tenant_id)

    async def primary_id(self):
        return self.primary


@pytest.fixture
def gated_client(monkeypatch):
    monkeypatch.setattr(settings, "TENANT_BASE_DOMAIN", "oyunserp.test")
    monkeypatch.setattr(settings, "PLATFORM_ROOT_HOSTS", "app.oyunserp.test")
    monkeypatch.setattr(settings, "PLATFORM_CONSOLE_HOSTS", "")
    monkeypatch.setattr(settings, "PLATFORM_ALLOWED_CIDRS", "")
    states = {
        1: _state(id=1, slug="oyuns", is_primary=True, license_required=False, license_expires_at=None, features=frozenset({"legacy_workspace", "crm"})),
        2: _state(id=2, slug="acme"),
        3: _state(id=3, slug="beta", status="suspended"),
        4: _state(id=4, slug="gamma", license_expires_at=None),
    }
    directory = FakeDirectory(states, {"acme": 2, "beta": 3, "gamma": 4, "oyuns": 1})
    inner = FastAPI()

    @inner.get("/{path:path}")
    async def echo(path: str):
        return {"tenant": current_tenant_id(), "path": path}

    app = TenantContextMiddleware(inner, directory=directory)
    return TestClient(app)


def _bearer(org_id: int) -> dict:
    return {"Authorization": f"Bearer {create_enterprise_access_token(10 + org_id, org_id)}"}


def test_middleware_binds_the_token_tenant_on_shared_hosts(gated_client):
    response = gated_client.get("/v1/tasks", headers={**_bearer(2), "host": "app.oyunserp.test"})
    assert response.status_code == 200 and response.json()["tenant"] == 2
    anonymous = gated_client.get("/v1/auth/capabilities", headers={"host": "app.oyunserp.test"})
    assert anonymous.json()["tenant"] is None
    legacy = gated_client.get("/questions", headers={"Authorization": f"Bearer {create_access_token({'sub': '1'})}", "host": "app.oyunserp.test"})
    assert legacy.json()["tenant"] == 1


def test_middleware_enforces_host_and_token_agreement(gated_client):
    assert gated_client.get("/v1/tasks", headers={**_bearer(2), "host": "acme.oyunserp.test"}).json()["tenant"] == 2
    mismatch = gated_client.get("/v1/tasks", headers={**_bearer(1), "host": "acme.oyunserp.test"})
    assert mismatch.status_code == 403 and mismatch.json()["detail"]["code"] == "tenant_mismatch"
    unknown = gated_client.get("/v1/tasks", headers={"host": "nope.oyunserp.test"})
    assert unknown.status_code == 404 and unknown.json()["detail"]["code"] == "tenant_not_found"
    # Anonymous requests on a tenant host run in that tenant (login page).
    assert gated_client.get("/v1/tenant/branding", headers={"host": "acme.oyunserp.test"}).json()["tenant"] == 2


def test_middleware_applies_status_license_and_feature_gates(gated_client):
    suspended = gated_client.get("/v1/tasks", headers={**_bearer(3), "host": "app.oyunserp.test"})
    assert suspended.status_code == 403 and suspended.json()["detail"]["code"] == "tenant_suspended"
    unlicensed = gated_client.get("/v1/tasks", headers={**_bearer(4), "host": "app.oyunserp.test"})
    assert unlicensed.status_code == 402
    assert gated_client.get("/v1/tenant/license", headers={**_bearer(4), "host": "app.oyunserp.test"}).status_code == 200
    blocked_module = gated_client.get("/v1/erp/payroll/monthly", headers={**_bearer(2), "host": "app.oyunserp.test"})
    assert blocked_module.status_code == 403 and blocked_module.json()["detail"]["code"] == "feature_not_licensed"


def test_operator_console_is_isolated_from_tenant_hosts_and_tokens(gated_client, monkeypatch):
    on_tenant_host = gated_client.get("/v1/platform/tenants", headers={"host": "acme.oyunserp.test"})
    assert on_tenant_host.status_code == 404
    on_root = gated_client.get("/v1/platform/tenants", headers={**_bearer(2), "host": "app.oyunserp.test"})
    assert on_root.status_code == 200 and on_root.json()["tenant"] is None  # system context
    monkeypatch.setattr(settings, "PLATFORM_CONSOLE_HOSTS", "console.oyunserp.test")
    assert gated_client.get("/v1/platform/tenants", headers={"host": "app.oyunserp.test"}).status_code == 404
    assert gated_client.get("/v1/platform/tenants", headers={"host": "console.oyunserp.test"}).status_code == 200
    monkeypatch.setattr(settings, "PLATFORM_ALLOWED_CIDRS", "10.0.0.0/8")
    denied = gated_client.get("/v1/platform/tenants", headers={"host": "console.oyunserp.test", "x-forwarded-for": "203.0.113.9"})
    assert denied.status_code == 403
    allowed = gated_client.get("/v1/platform/tenants", headers={"host": "console.oyunserp.test", "x-forwarded-for": "10.4.5.6"})
    assert allowed.status_code == 200


def test_operator_and_tenant_tokens_never_cross():
    tenant_token = create_enterprise_access_token(5, 2)
    operator_token = create_platform_access_token(7, "superadmin")
    assert decode_platform_access_token(tenant_token) is None
    assert decode_token(operator_token) is None
    assert decode_platform_access_token(operator_token)["sub"] == "7"


# ── ORM guard ───────────────────────────────────────────────────────────────
def test_guard_rejects_rows_of_another_tenant_on_load():
    foreign = Employee(organization_id=2, name="Other tenant")
    own = Employee(organization_id=1, name="Mine")
    with tenant_scope(1):
        _guard_loaded_instance(own, None)
        with pytest.raises(TenantBoundaryViolation):
            _guard_loaded_instance(foreign, None)
        with pytest.raises(TenantBoundaryViolation):
            _guard_loaded_instance(Organization(id=2, name="x", slug="x"), None)
    _guard_loaded_instance(foreign, None)  # system context: no tenant, no guard


def test_guard_stamps_new_rows_and_blocks_cross_tenant_writes():
    unstamped = UserAccount(email="a@b", password_hash="x")
    session = SimpleNamespace(new=[unstamped], dirty=[], deleted=[])
    with tenant_scope(3):
        _guard_flush(session, None, None)
        assert unstamped.organization_id == 3
        with pytest.raises(TenantBoundaryViolation):
            _guard_flush(SimpleNamespace(new=[UserAccount(organization_id=4, email="c", password_hash="x")], dirty=[], deleted=[]), None, None)
        with pytest.raises(TenantBoundaryViolation):
            _guard_flush(SimpleNamespace(new=[Organization(name="New")], dirty=[], deleted=[]), None, None)


def test_bind_tenant_never_switches_tenants_mid_request():
    async def scenario():
        db = SimpleNamespace(bind=None)
        await bind_tenant(db, 5)
        await bind_tenant(db, 5)
        assert current_tenant_id() == 5
        with pytest.raises(TenantBoundaryViolation):
            await bind_tenant(db, 6)

    asyncio.run(scenario())
    assert current_tenant_id() is None


# ── seats and billing helpers ───────────────────────────────────────────────
def test_seat_accounting_rules():
    assert SeatUsage(used=3, limit=5).available == 2
    assert SeatUsage(used=7, limit=5).available == 0
    assert SeatUsage(used=7, limit=None).unlimited and SeatUsage(used=7, limit=None).available is None
    assert account_consumes_seat("active", {})
    assert account_consumes_seat("invited", None)
    assert account_consumes_seat("locked", {})
    assert not account_consumes_seat("disabled", {})
    assert not account_consumes_seat("active", {"system_agent": "oyuns"})
    trigger_error = SimpleNamespace(orig=SimpleNamespace(sqlstate="OY001"))
    assert is_seat_limit_error(trigger_error)
    assert not is_seat_limit_error(SimpleNamespace(orig=SimpleNamespace(sqlstate="23505")))


def test_billing_cycle_expiry():
    assert add_months(datetime(2026, 1, 31, tzinfo=timezone.utc), 1) == datetime(2026, 2, 28, tzinfo=timezone.utc)
    assert add_months(datetime(2026, 11, 15, tzinfo=timezone.utc), 3) == datetime(2027, 2, 15, tzinfo=timezone.utc)
    assert default_expiry(NOW, "yearly") == datetime(2027, 9, 29, 12, 0, tzinfo=timezone.utc)
    assert default_expiry(NOW, "custom") is None
