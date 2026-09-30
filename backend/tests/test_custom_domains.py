"""Tenant custom domains through Cloudflare for SaaS."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest

from app.core.config import settings
from app.services import custom_domains
from app.services.custom_domains import DomainError

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def cloudflare(monkeypatch):
    monkeypatch.setattr(settings, "CLOUDFLARE_API_TOKEN", "cf-token")
    monkeypatch.setattr(settings, "CLOUDFLARE_ZONE_ID", "zone-1")
    monkeypatch.setattr(settings, "CLOUDFLARE_CNAME_TARGET", "customers.oyunserp.com")
    monkeypatch.setattr(settings, "TENANT_BASE_DOMAIN", "oyunserp.com")
    monkeypatch.setattr(settings, "PLATFORM_ROOT_HOSTS", "erp.oyuns.mn,localhost")
    monkeypatch.setattr(settings, "CLOUDFLARE_SSL_METHOD", "http")
    monkeypatch.setattr(settings, "CLOUDFLARE_CUSTOM_ORIGIN_SERVER", "")
    monkeypatch.setattr(settings, "CLOUDFLARE_CUSTOM_ORIGIN_SNI", "")


def _domain(**values):
    base = dict(id=1, organization_id=2, hostname="erp.acme.mn", provider="cloudflare", provider_hostname_id=None, status="pending",
                ssl_status=None, verified_at=None, dns_records=[], last_error=None, last_checked_at=None, created_at=NOW)
    base.update(values)
    return SimpleNamespace(**base)


def _hostname(status="pending", ssl_status="pending_validation", **extra):
    return {
        "id": "cf-1", "hostname": "erp.acme.mn", "status": status,
        "ownership_verification": {"type": "txt", "name": "_cf-custom-hostname.erp.acme.mn", "value": "uuid-1"},
        "ssl": {"status": ssl_status, "validation_records": [{"txt_name": "_acme-challenge.erp.acme.mn", "txt_value": "abc"}]},
        **extra,
    }


@pytest.mark.parametrize("raw, expected", [
    ("ERP.Acme.MN", "erp.acme.mn"),
    ("https://erp.acme.mn/login", "erp.acme.mn"),
    ("erp.acme.mn.", "erp.acme.mn"),
    ("эрп.жишээ.мон", "xn--o1ab2b.xn--f1ae2cuaa.xn--l1acc"),
])
def test_hostnames_are_normalized(cloudflare, raw, expected):
    assert custom_domains.normalize_hostname(raw) == expected


@pytest.mark.parametrize("raw, code", [
    ("localhost", "invalid_hostname"),
    ("not a domain", "invalid_hostname"),
    ("acme.oyunserp.com", "domain_reserved"),
    ("erp.oyuns.mn", "domain_reserved"),
    ("customers.oyunserp.com", "domain_reserved"),
    ("127.0.0.1", "invalid_hostname"),
])
def test_platform_hosts_cannot_be_claimed(cloudflare, raw, code):
    with pytest.raises(DomainError) as error:
        custom_domains.normalize_hostname(raw)
    assert error.value.code == code


def test_pending_hostname_lists_cname_and_validation_records(cloudflare):
    domain = _domain()
    custom_domains.apply_cloudflare_state(domain, _hostname(), NOW)
    assert domain.status == "pending" and domain.verified_at is None and domain.provider_hostname_id == "cf-1"
    assert [(r["type"], r["purpose"]) for r in domain.dns_records] == [("CNAME", "routing"), ("TXT", "ownership"), ("TXT", "certificate")]
    assert domain.dns_records[0]["value"] == "customers.oyunserp.com"


def test_domain_routes_only_once_hostname_and_certificate_are_active(cloudflare):
    domain = _domain()
    custom_domains.apply_cloudflare_state(domain, _hostname(status="active", ssl_status="pending_issuance"), NOW)
    assert domain.status == "pending" and domain.verified_at is None
    custom_domains.apply_cloudflare_state(domain, _hostname(status="active", ssl_status="active"), NOW)
    assert domain.status == "active" and domain.verified_at == NOW
    assert [r["purpose"] for r in domain.dns_records] == ["routing"]
    # Certificate renewal keeps an already routed domain online.
    custom_domains.apply_cloudflare_state(domain, _hostname(status="active", ssl_status="pending_validation"), NOW)
    assert domain.status == "active" and domain.verified_at == NOW


def test_blocked_or_deleted_hostnames_stop_routing(cloudflare):
    domain = _domain(status="active", verified_at=NOW)
    custom_domains.apply_cloudflare_state(domain, _hostname(status="blocked", verification_errors=["blocked by policy"]), NOW)
    assert domain.status == "error" and domain.verified_at is None and "blocked" in domain.last_error
    domain = _domain(status="active", verified_at=NOW)
    custom_domains.apply_cloudflare_state(domain, None, NOW)
    assert domain.status == "error" and domain.verified_at is None


def test_certificate_timeouts_are_errors(cloudflare):
    domain = _domain()
    custom_domains.apply_cloudflare_state(domain, _hostname(ssl_status="validation_timed_out"), NOW)
    assert domain.status == "error"


def test_create_custom_hostname_calls_the_zone_api(cloudflare, monkeypatch):
    seen = {}

    def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = request.read().decode()
        return httpx.Response(200, json={"success": True, "result": _hostname()})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(custom_domains.httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    monkeypatch.setattr(settings, "CLOUDFLARE_CUSTOM_ORIGIN_SNI", "app.oyunserp.com")
    result = asyncio.run(custom_domains.create_custom_hostname("erp.acme.mn"))
    assert result["id"] == "cf-1"
    assert seen["url"] == "https://api.cloudflare.com/client/v4/zones/zone-1/custom_hostnames"
    assert seen["auth"] == "Bearer cf-token"
    assert '"method":"http"' in seen["body"].replace(" ", "") and '"custom_origin_sni":"app.oyunserp.com"' in seen["body"].replace(" ", "")


def test_cloudflare_duplicates_and_outages_have_stable_codes(cloudflare, monkeypatch):
    responses = iter([
        httpx.Response(409, json={"success": False, "errors": [{"code": 1406, "message": "Duplicate custom hostname found."}]}),
        httpx.Response(500, json={"success": False, "errors": [{"code": 1000, "message": "boom"}]}),
    ])
    real_client = httpx.AsyncClient
    monkeypatch.setattr(custom_domains.httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(lambda request: next(responses)), **kwargs))
    with pytest.raises(DomainError) as duplicate:
        asyncio.run(custom_domains.create_custom_hostname("erp.acme.mn"))
    assert duplicate.value.code == "domain_taken"
    with pytest.raises(DomainError) as outage:
        asyncio.run(custom_domains.create_custom_hostname("erp.acme.mn"))
    assert outage.value.code == "cloudflare_unavailable"


def test_self_service_is_off_without_cloudflare_credentials(monkeypatch):
    monkeypatch.setattr(settings, "CLOUDFLARE_API_TOKEN", "")
    assert custom_domains.cloudflare_configured() is False
    with pytest.raises(DomainError) as error:
        asyncio.run(custom_domains.create_custom_hostname("erp.acme.mn"))
    assert error.value.code == "custom_domains_unavailable" and error.value.status_code == 503
