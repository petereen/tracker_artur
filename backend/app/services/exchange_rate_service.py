"""Server-only client for the OYUNS rates service."""

from __future__ import annotations

import asyncio
import os
from typing import Any

import aiohttp

RATES_API_URL = "https://rates.oyuns.mn/api/agent/rate"
RATES_TIMEOUT_SECONDS = 10


def _unavailable() -> dict[str, Any]:
    return {
        "ok": False,
        "error": "temporarily_unavailable",
        "user_message": "The exchange rate is temporarily unavailable. Please try again shortly.",
    }


async def get_exchange_rate(
    *, provider: str, pair: str, force_refresh: bool = False
) -> dict[str, Any]:
    """Fetch one exact rate result without ever estimating a replacement.

    The bearer token is intentionally read here, on the server, and is never
    included in a return value, exception, or log record.
    """
    provider = provider.strip() if isinstance(provider, str) else ""
    pair = pair.strip() if isinstance(pair, str) else ""
    if not provider or not pair or not isinstance(force_refresh, bool):
        return {
            "ok": False,
            "error": "invalid_request",
            "user_message": "Provider and currency pair are required, and force_refresh must be a boolean.",
        }

    api_key = os.getenv("AGENT_RATES_API_KEY", "").strip()
    if not api_key:
        return {
            "ok": False,
            "error": "authentication_configuration_error",
            "user_message": "The exchange-rate service authentication is not configured.",
        }

    timeout = aiohttp.ClientTimeout(total=RATES_TIMEOUT_SECONDS)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                RATES_API_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "provider": provider,
                    "pair": pair,
                    "force_refresh": bool(force_refresh),
                },
            ) as response:
                if response.status == 401:
                    return {
                        "ok": False,
                        "error": "authentication_configuration_error",
                        "user_message": "The exchange-rate service authentication is invalid or misconfigured.",
                    }
                if response.status == 404:
                    return {
                        "ok": False,
                        "error": "unsupported_provider_or_pair",
                        "user_message": "That provider or currency pair is unsupported.",
                    }
                if response.status < 200 or response.status >= 300:
                    return _unavailable()
                payload = await response.json(content_type=None)
    except (asyncio.TimeoutError, aiohttp.ClientError, ValueError):
        return _unavailable()

    if not isinstance(payload, dict):
        return _unavailable()
    source = payload.get("source")
    returned_pair = payload.get("pair")
    values = payload.get("values")
    fetched_at = payload.get("fetchedAt")
    status = payload.get("status")
    if (
        not isinstance(source, str)
        or not source.strip()
        or not isinstance(returned_pair, str)
        or not returned_pair.strip()
        or not isinstance(fetched_at, str)
        or not fetched_at.strip()
        or not isinstance(status, str)
        or status not in {"fresh", "stale"}
        or not isinstance(values, list)
        or not values
    ):
        return _unavailable()

    # Keep labels and amounts exactly as delivered. This preserves cash and
    # non-cash buy/sell distinctions and forbids accidental rounding.
    exact_values: list[dict[str, str]] = []
    for value in values:
        if (
            not isinstance(value, dict)
            or not isinstance(value.get("label"), str)
            or not isinstance(value.get("amount"), str)
        ):
            return _unavailable()
        exact_values.append({"label": value["label"], "amount": value["amount"]})

    result: dict[str, Any] = {
        "ok": True,
        "provider": source,
        "pair": returned_pair,
        "values": exact_values,
        "fetchedAt": fetched_at,
        "status": status,
    }
    if status == "stale":
        result["notice"] = (
            "The latest fetch failed; an older cached exchange rate is being shown."
        )
    return result
