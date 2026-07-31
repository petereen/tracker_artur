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
    def __init__(self, response, captured):
        self.response = response
        self.captured = captured

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    def post(self, url, **kwargs):
        self.captured["url"] = url
        self.captured.update(kwargs)
        return self.response


def test_rate_result_preserves_exact_values_and_stale_notice(monkeypatch):
    captured = {}
    payload = {
        "source": "TDBM",
        "pair": "USD/MNT",
        "values": [
            {"label": "cash buy", "amount": "3420"},
            {"label": "cash sell", "amount": "3450.125"},
            {"label": "non-cash sell", "amount": "3451"},
        ],
        "fetchedAt": "2026-07-31T01:20:00+00:00",
        "status": "stale",
    }
    monkeypatch.setenv("AGENT_RATES_API_KEY", "server-only-test-key")
    monkeypatch.setattr(
        exchange_rate_service.aiohttp,
        "ClientSession",
        lambda **_kwargs: _Session(_Response(200, payload), captured),
    )

    result = asyncio.run(
        exchange_rate_service.get_exchange_rate(provider="TDBM", pair="USD/MNT")
    )

    assert result["provider"] == "TDBM"
    assert result["fetchedAt"] == "2026-07-31T01:20:00+00:00"
    assert result["values"] == payload["values"]
    assert "latest fetch failed" in result["notice"]
    assert captured["json"] == {
        "provider": "TDBM",
        "pair": "USD/MNT",
        "force_refresh": False,
    }
    assert captured["headers"]["Authorization"] == "Bearer server-only-test-key"


def test_mongolbank_alias_uses_case_sensitive_provider_code(monkeypatch):
    captured = {}
    payload = {
        "source": "MongolBank",
        "pair": "USD/MNT",
        "values": [{"label": "official", "amount": "3590.58"}],
        "fetchedAt": "2026-07-31T01:20:00+00:00",
        "status": "fresh",
    }
    monkeypatch.setenv("AGENT_RATES_API_KEY", "server-only-test-key")
    monkeypatch.setattr(
        exchange_rate_service.aiohttp,
        "ClientSession",
        lambda **_kwargs: _Session(_Response(200, payload), captured),
    )

    result = asyncio.run(
        exchange_rate_service.get_exchange_rate(
            provider="Монгол Банк",
            pair="USD/MNT",
        )
    )

    assert result["provider"] == "MongolBank"
    assert captured["json"]["provider"] == "MongolBank"


def test_mbank_alias_uses_case_sensitive_provider_code(monkeypatch):
    captured = {}
    payload = {
        "source": "MBank",
        "pair": "USD/MNT",
        "values": [{"label": "cash sell", "amount": "3611"}],
        "fetchedAt": "2026-07-31T01:20:00+00:00",
        "status": "fresh",
    }
    monkeypatch.setenv("AGENT_RATES_API_KEY", "server-only-test-key")
    monkeypatch.setattr(
        exchange_rate_service.aiohttp,
        "ClientSession",
        lambda **_kwargs: _Session(_Response(200, payload), captured),
    )

    result = asyncio.run(
        exchange_rate_service.get_exchange_rate(provider="mbank-ны", pair="USD/MNT")
    )

    assert result["provider"] == "MBank"
    assert captured["json"]["provider"] == "MBank"


def test_rate_401_does_not_expose_api_key(monkeypatch):
    captured = {}
    monkeypatch.setenv("AGENT_RATES_API_KEY", "not-for-output")
    monkeypatch.setattr(
        exchange_rate_service.aiohttp,
        "ClientSession",
        lambda **_kwargs: _Session(_Response(401, {}), captured),
    )

    result = asyncio.run(
        exchange_rate_service.get_exchange_rate(provider="TDBM", pair="USD/MNT")
    )

    assert result["error"] == "authentication_configuration_error"
    assert "not-for-output" not in str(result)


def test_rate_404_identifies_attempted_provider_and_pair(monkeypatch):
    captured = {}
    monkeypatch.setenv("AGENT_RATES_API_KEY", "not-for-output")
    monkeypatch.setattr(
        exchange_rate_service.aiohttp,
        "ClientSession",
        lambda **_kwargs: _Session(_Response(404, {}), captured),
    )

    result = asyncio.run(
        exchange_rate_service.get_exchange_rate(provider="TDBM", pair="USD/MNT")
    )

    assert result["error"] == "unsupported_provider_or_pair"
    assert "TDBM" in result["user_message"]
    assert "USD/MNT" in result["user_message"]
    assert "not-for-output" not in str(result)


def test_rate_does_not_call_api_when_required_input_is_blank(monkeypatch):
    monkeypatch.setenv("AGENT_RATES_API_KEY", "test-key")
    result = asyncio.run(exchange_rate_service.get_exchange_rate(provider=" ", pair="USD/MNT"))
    assert result["error"] == "invalid_request"
