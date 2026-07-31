from __future__ import annotations

import asyncio

from app.services import exchange_rate_service


class _Response:
    def __init__(self, status: int, payload):
        self.status = status
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def json(self, **_kwargs):
        return self._payload


class _Session:
    def __init__(self, get_response, post_response, captured):
        self.get_response = get_response
        self.post_response = post_response
        self.captured = captured

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    def get(self, url, **kwargs):
        self.captured["get"] = {"url": url, **kwargs}
        return self.get_response

    def post(self, url, **kwargs):
        self.captured["post"] = {"url": url, **kwargs}
        return self.post_response


def _entry(source="MongolBank", pair="EUR/MNT", *, kind="subscription", values=None, **extra):
    return {
        "key": f"rate:{source}:{pair}",
        "kind": kind,
        "source": source,
        "pair": pair,
        "values": values or [{"label": "value", "amount": "3750.25"}],
        "status": "fresh",
        "fetchedAt": "2026-07-31T01:20:00+00:00",
        "error": None,
        **extra,
    }


def _mock(monkeypatch, rates, *, get_status=200, post_payload=None, post_status=200):
    captured = {}
    monkeypatch.setenv("AGENT_RATES_API_KEY", "server-only-test-key")
    exchange_rate_service.clear_catalog_cache()
    monkeypatch.setattr(
        exchange_rate_service.aiohttp,
        "ClientSession",
        lambda **_kwargs: _Session(
            _Response(get_status, {"rates": rates}),
            _Response(post_status, post_payload or {}),
            captured,
        ),
    )
    return captured


def test_mongolbank_eur_without_hard_coded_pair_entry(monkeypatch):
    captured = _mock(monkeypatch, [_entry(pair="EUR/MNT")])
    result = asyncio.run(exchange_rate_service.get_exchange_rate(provider="MongolBank", pair="EUR"))
    assert result["ok"] is True
    assert result["pair"] == "EUR/MNT"
    assert "post" not in captured


def test_mongolbank_krw_and_lowercase_iso_normalize(monkeypatch):
    captured = _mock(monkeypatch, [_entry(pair="KRW/MNT", values=[{"label": "value", "amount": "2.61"}])])
    result = asyncio.run(exchange_rate_service.get_exchange_rate(provider="mongolbank", pair="krw/mnt"))
    assert result["pair"] == "KRW/MNT"
    assert captured["get"]["headers"]["Authorization"] == "Bearer server-only-test-key"


def test_mongolian_currency_name_normalization(monkeypatch):
    captured = _mock(monkeypatch, [], post_payload=_entry(pair="EUR/MNT"))
    result = asyncio.run(exchange_rate_service.get_exchange_rate(provider="Монгол Банк", pair="евро"))
    assert result["ok"] is True
    assert captured["post"]["json"]["pair"] == "EUR/MNT"


def test_missing_pair_falls_back_from_catalog_to_exact_post(monkeypatch):
    captured = _mock(monkeypatch, [], post_payload=_entry(pair="GBP/MNT"))
    result = asyncio.run(exchange_rate_service.get_exchange_rate(provider="MongolBank", pair="gbp"))
    assert result["ok"] is True
    assert captured["post"]["json"] == {"provider": "MongolBank", "pair": "GBP/MNT", "force_refresh": False}


def test_calculated_lookup_by_title_and_all_calculated(monkeypatch):
    calculated = _entry(
        source="Тооцоолсон", pair="ДЕЛЬКРАДО", kind="calculated",
        formula="MongolBank RUB/MNT × 1.005", key="formula:delkrado",
        values=[{"label": "value", "amount": "45.19"}],
    )
    second = _entry(source="Тооцоолсон", pair="ТРИКУЭТРА", kind="calculated", key="formula:triquetra")
    _mock(monkeypatch, [calculated, second])
    title = asyncio.run(exchange_rate_service.get_exchange_rate(provider="Тооцоолсон", pair="Делькрадо", request_type="calculated"))
    assert title["pair"] == "ДЕЛЬКРАДО"
    listed = asyncio.run(exchange_rate_service.get_exchange_rate(provider="rates", pair="all calculated"))
    assert len(listed["rates"]) == 2
    assert all(item["kind"] == "calculated" for item in listed["rates"])


def test_multiple_values_are_preserved_generically(monkeypatch):
    values = [{"label": "buy", "amount": "3400"}, {"label": "sell", "amount": "3450"}]
    _mock(monkeypatch, [_entry(source="TDBM", pair="USD/MNT", values=values)])
    result = asyncio.run(exchange_rate_service.get_exchange_rate(provider="tdbm", pair="usd/mnt"))
    assert result["values"] == values


def test_empty_or_error_entry_is_unavailable(monkeypatch):
    _mock(monkeypatch, [_entry(pair="USD/MNT", values=[], status="error")])
    result = asyncio.run(exchange_rate_service.get_exchange_rate(provider="MongolBank", pair="USD"))
    assert result["ok"] is False
    assert result["error"] == "rate_unavailable"


def test_post_upstream_failure_is_distinguished(monkeypatch):
    captured = _mock(monkeypatch, [], post_status=503)
    result = asyncio.run(exchange_rate_service.get_exchange_rate(provider="MongolBank", pair="CHF"))
    assert result["error"] == "rates_service_failure"
    assert "CHF/MNT" in captured["post"]["json"]["pair"]


def test_catalog_failure_uses_exact_mongolbank_fallback(monkeypatch):
    captured = _mock(monkeypatch, [], get_status=503, post_payload=_entry(pair="USD/MNT"))
    result = asyncio.run(exchange_rate_service.get_exchange_rate(provider="MongolBank", pair="USD"))
    assert result["ok"] is True
    assert captured["post"]["json"]["pair"] == "USD/MNT"


def test_catalog_failure_uses_exact_fallback_for_other_provider(monkeypatch):
    captured = _mock(monkeypatch, [], get_status=503, post_payload=_entry(source="TDBM", pair="USD/MNT"))
    result = asyncio.run(exchange_rate_service.get_exchange_rate(provider="TDBM", pair="USD/MNT"))
    assert result["ok"] is True
    assert captured["post"]["json"] == {"provider": "TDBM", "pair": "USD/MNT", "force_refresh": False}


def test_api_key_never_appears_in_result(monkeypatch):
    _mock(monkeypatch, [], post_status=401)
    result = asyncio.run(exchange_rate_service.get_exchange_rate(provider="MongolBank", pair="USD"))
    assert result["error"] == "authentication_configuration_error"
    assert "server-only-test-key" not in str(result)
