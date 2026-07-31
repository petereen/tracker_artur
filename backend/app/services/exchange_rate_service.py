"""Server-only client for the OYUNS rates service."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from typing import Any

import aiohttp

RATES_API_BASE_URL = os.getenv("AGENT_RATES_API_URL", "https://rates.oyuns.mn/api/agent")
RATES_API_URL = f"{RATES_API_BASE_URL}/rate"
RATES_CATALOG_URL = f"{RATES_API_BASE_URL}/rates"
RATES_TIMEOUT_SECONDS = 10
DEFAULT_CACHE_TTL_SECONDS = 15
log = logging.getLogger(__name__)

_PROVIDER_ALIASES = {
    "mongolbank": "MongolBank", "bankofmongolia": "MongolBank", "монголбанк": "MongolBank",
    "tdbm": "TDBM", "mbank": "MBank", "khanbank": "KhanBank", "golomtbank": "GolomtBank",
    "xacbank": "XacBank", "arigbank": "ArigBank", "statebank": "StateBank",
    "capitronbank": "CapitronBank", "bogdbank": "BogdBank", "ckbank": "CKBank",
    "nibank": "NIBank", "transbank": "TransBank", "naimansharga": "NaimanSharga", "sendmn": "SendMN",
}
_MONGOLBANK_CURRENCY_NAMES = {
    "dollar": "USD", "амдоллар": "USD", "доллар": "USD",
    "yuan": "CNY", "юань": "CNY", "юанийн": "CNY",
    "yen": "JPY", "иен": "JPY", "иений": "JPY",
    "ruble": "RUB", "рубль": "RUB", "рублийн": "RUB",
    "euro": "EUR", "евро": "EUR", "won": "KRW", "вон": "KRW",
}
_catalog_cache: tuple[float, list[dict[str, Any]]] | None = None
_catalog_lock = asyncio.Lock()


def _canonical_provider(provider: str) -> str:
    alias_key = re.sub(r"[\s_'’.-]+", "", provider).casefold()
    for suffix in ("ний", "ийн", "ны", "ын"):
        if alias_key.endswith(suffix) and alias_key[: -len(suffix)] in _PROVIDER_ALIASES:
            alias_key = alias_key[: -len(suffix)]
            break
    return _PROVIDER_ALIASES.get(alias_key, provider)


def normalize_mongolbank_pair(pair: str) -> str:
    """Turn names, bare ISO codes, and pairs into uppercase XXX/MNT."""
    value = re.sub(r"\s+", "", pair.strip()).casefold()
    value = value.replace("ам.", "ам").replace(".", "")
    if "/" in value:
        base, quote = value.split("/", 1)
        if quote and quote != "mnt":
            return f"{base.upper()}/{quote.upper()}"
    else:
        to_match = re.fullmatch(r"([a-z]{3})(?:to)(?:mnt)?", value)
        if to_match:
            value = to_match.group(1)
        value = re.sub(r"(?:to|төгрөг|төгрөгөөр|mnt)$", "", value)
    code = _MONGOLBANK_CURRENCY_NAMES.get(value, value.upper())
    if re.fullmatch(r"[A-Z]{3}", code):
        return f"{code}/MNT"
    return pair.strip().upper()


def _unavailable(message: str = "The exchange-rate service is temporarily unavailable.") -> dict[str, Any]:
    return {"ok": False, "error": "rates_service_failure", "user_message": message}


def _validate_entry(entry: Any) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    values = entry.get("values")
    status = entry.get("status")
    if status == "error" or not isinstance(values, list) or not values:
        return None
    exact_values: list[dict[str, str]] = []
    for value in values:
        if not isinstance(value, dict) or not isinstance(value.get("label"), str) or value.get("amount") is None:
            return None
        exact_values.append({"label": value["label"], "amount": str(value["amount"])})
    if not isinstance(entry.get("source"), str) or not isinstance(entry.get("pair"), str):
        return None
    result = dict(entry)
    result["values"] = exact_values
    return result


def _result(entry: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True, **entry}


def _auth_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


async def _fetch_catalog(session: aiohttp.ClientSession, api_key: str) -> list[dict[str, Any]] | dict[str, Any]:
    try:
        async with session.get(RATES_CATALOG_URL, headers=_auth_headers(api_key)) as response:
            if response.status == 401:
                return {"ok": False, "error": "authentication_configuration_error", "user_message": "The exchange-rate service authentication is invalid or misconfigured."}
            if response.status < 200 or response.status >= 300:
                log.warning("exchange_rates.catalog_response status=%s", response.status)
                return _unavailable()
            payload = await response.json(content_type=None)
    except (asyncio.TimeoutError, aiohttp.ClientError, ValueError) as exc:
        log.warning("exchange_rates.catalog_failed error_type=%s", type(exc).__name__)
        return _unavailable()
    rates = payload.get("rates") if isinstance(payload, dict) else None
    if not isinstance(rates, list):
        return _unavailable()
    return [raw for raw in rates if isinstance(raw, dict) and isinstance(raw.get("source"), str) and isinstance(raw.get("pair"), str)]


async def _catalog(force_refresh: bool = False) -> list[dict[str, Any]] | dict[str, Any]:
    global _catalog_cache
    try:
        ttl = max(0.0, float(os.getenv("AGENT_RATES_CACHE_TTL_SECONDS", DEFAULT_CACHE_TTL_SECONDS)))
    except ValueError:
        ttl = DEFAULT_CACHE_TTL_SECONDS
    async with _catalog_lock:
        if not force_refresh and _catalog_cache and time.monotonic() - _catalog_cache[0] <= ttl:
            return _catalog_cache[1]
        api_key = os.getenv("AGENT_RATES_API_KEY", "").strip()
        if not api_key:
            return {"ok": False, "error": "authentication_configuration_error", "user_message": "The exchange-rate service authentication is not configured."}
        timeout = aiohttp.ClientTimeout(total=RATES_TIMEOUT_SECONDS)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            fetched = await _fetch_catalog(session, api_key)
        if isinstance(fetched, list):
            _catalog_cache = (time.monotonic(), fetched)
        return fetched


def clear_catalog_cache() -> None:
    global _catalog_cache
    _catalog_cache = None


async def _fetch_single(provider: str, pair: str, force_refresh: bool) -> dict[str, Any]:
    api_key = os.getenv("AGENT_RATES_API_KEY", "").strip()
    timeout = aiohttp.ClientTimeout(total=RATES_TIMEOUT_SECONDS)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(RATES_API_URL, headers=_auth_headers(api_key), json={"provider": provider, "pair": pair, "force_refresh": force_refresh}) as response:
                if response.status == 401:
                    return {"ok": False, "error": "authentication_configuration_error", "user_message": "The exchange-rate service authentication is invalid or misconfigured."}
                if response.status == 404:
                    return {"ok": False, "error": "not_published_by_provider", "user_message": f"{provider} has not published {pair}."}
                if response.status < 200 or response.status >= 300:
                    log.warning("exchange_rate.response provider=%s pair=%s status=%s", provider, pair, response.status)
                    return _unavailable()
                payload = await response.json(content_type=None)
    except (asyncio.TimeoutError, aiohttp.ClientError, ValueError) as exc:
        log.warning("exchange_rate.request_failed provider=%s pair=%s error_type=%s", provider, pair, type(exc).__name__)
        return _unavailable()
    entry = _validate_entry(payload)
    if entry:
        return _result(entry)
    if isinstance(payload, dict) and (payload.get("status") == "error" or payload.get("values") == []):
        return {"ok": False, "error": "rate_unavailable", "user_message": f"{provider} published {pair}, but the current value is unavailable."}
    return _unavailable()


def _matches(entry: dict[str, Any], provider: str, pair: str, calculated: bool = False) -> bool:
    return (entry.get("kind") == "calculated") == calculated and str(entry.get("source", "")).casefold() == provider.casefold() and str(entry.get("pair", "")).casefold() == pair.casefold()


def _unavailable_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return {"ok": False, "error": "rate_unavailable", "user_message": f"{entry.get('source', 'The provider')} has published {entry.get('pair', 'this rate')}, but it is currently unavailable."}


def _calculated_query(value: str) -> str:
    return re.sub(r"\s+(?:ханш|rate)$", "", value.strip(), flags=re.IGNORECASE).casefold()


async def get_exchange_rate(*, provider: str, pair: str, force_refresh: bool = False, request_type: str = "single") -> dict[str, Any]:
    if not isinstance(provider, str) or not isinstance(pair, str) or not provider.strip() or not pair.strip() or not isinstance(force_refresh, bool):
        return {"ok": False, "error": "invalid_request", "user_message": "Provider and currency pair are required, and force_refresh must be a boolean."}
    provider = _canonical_provider(provider.strip())
    normalized_pair = normalize_mongolbank_pair(pair) if provider == "MongolBank" else pair.strip().upper()
    catalog = await _catalog(force_refresh=force_refresh)
    if isinstance(catalog, dict):
        # The catalog is primary, but a transient catalog outage must not take
        # down an exact provider lookup when the pair endpoint still works.
        # Keep catalog/all-rates failures visible to callers.
        if request_type == "single":
            return await _fetch_single(provider, normalized_pair, force_refresh)
        return catalog
    if request_type == "all" or pair.strip().casefold() in {"all", "all rates", "бүх ханш"}:
        return {"ok": True, "rates": [_result(entry) for entry in catalog if _validate_entry(entry) is not None]}
    if request_type == "calculated" or pair.strip().casefold() in {"all calculated", "тооцоолсон ханшууд", "тооцоолсон"}:
        query = _calculated_query(pair)
        matches = [entry for entry in catalog if entry.get("kind") == "calculated" and (query in {"all calculated", "тооцоолсон ханшууд", "тооцоолсон"} or _calculated_query(str(entry.get("pair", ""))) == query or str(entry.get("formula", "")).casefold() == query or str(entry.get("key", "")).casefold() == query)]
        if matches and any(_validate_entry(entry) is None for entry in matches):
            return _unavailable_entry(next(entry for entry in matches if _validate_entry(entry) is None))
        return {"ok": True, "rates": [_result(entry) for entry in matches]} if matches else {"ok": False, "error": "not_published_by_provider", "user_message": f"No calculated rate matched {pair}."}
    for entry in catalog:
        if _matches(entry, provider, normalized_pair):
            if _validate_entry(entry) is None:
                return _unavailable_entry(entry)
            return _result(entry)
    # A catalog is not an authority for pair availability. Ask the provider
    # endpoint before reporting that a pair is unpublished, for every provider.
    return await _fetch_single(provider, normalized_pair, force_refresh)
