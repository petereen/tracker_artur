"""Telegram OIDC discovery, PKCE authorization, and ID-token validation."""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import aiohttp
from jose import JWTError, jwt

from app.core.config import settings
from app.services.secret_box import decrypt_secret, encrypt_secret


STATE_TTL = timedelta(minutes=10)
DISCOVERY_TTL = timedelta(hours=1)

_discovery_cache: tuple[datetime, dict[str, Any]] | None = None
_jwks_cache: tuple[datetime, dict[str, Any]] | None = None


class TelegramOIDCError(RuntimeError):
    pass


def is_configured() -> bool:
    return bool(settings.TELEGRAM_OIDC_CLIENT_ID and settings.TELEGRAM_OIDC_CLIENT_SECRET and settings.TELEGRAM_OIDC_REDIRECT_URI)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _code_challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


async def _get_json(url: str) -> dict[str, Any]:
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers={"Accept": "application/json"}) as response:
                payload = await response.json(content_type=None)
                if response.status != 200 or not isinstance(payload, dict):
                    raise TelegramOIDCError("Telegram OIDC provider unavailable")
                return payload
    except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
        raise TelegramOIDCError("Telegram OIDC provider unavailable") from exc


async def discovery() -> dict[str, Any]:
    global _discovery_cache
    now = datetime.now(timezone.utc)
    if _discovery_cache and _discovery_cache[0] > now:
        return _discovery_cache[1]
    payload = await _get_json(settings.TELEGRAM_OIDC_ISSUER.rstrip("/") + "/.well-known/openid-configuration")
    required = ("authorization_endpoint", "token_endpoint", "jwks_uri", "issuer")
    if any(not payload.get(key) for key in required) or payload["issuer"].rstrip("/") != settings.TELEGRAM_OIDC_ISSUER.rstrip("/"):
        raise TelegramOIDCError("Telegram OIDC discovery is incomplete")
    _discovery_cache = (now + DISCOVERY_TTL, payload)
    return payload


async def authorization_url(state: str, nonce: str, verifier: str) -> str:
    metadata = await discovery()
    values = {
        "client_id": settings.TELEGRAM_OIDC_CLIENT_ID,
        "redirect_uri": settings.TELEGRAM_OIDC_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid profile",
        "state": state,
        "nonce": nonce,
        "code_challenge": _code_challenge(verifier),
        "code_challenge_method": "S256",
    }
    return str(metadata["authorization_endpoint"]) + "?" + urlencode(values)


async def exchange_code(code: str, verifier: str) -> dict[str, Any]:
    metadata = await discovery()
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": settings.TELEGRAM_OIDC_CLIENT_ID,
        "client_secret": settings.TELEGRAM_OIDC_CLIENT_SECRET,
        "redirect_uri": settings.TELEGRAM_OIDC_REDIRECT_URI,
        "code_verifier": verifier,
    }
    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(str(metadata["token_endpoint"]), data=data, headers={"Accept": "application/json"}) as response:
                payload = await response.json(content_type=None)
                if response.status != 200 or not isinstance(payload, dict) or not payload.get("id_token"):
                    raise TelegramOIDCError("Telegram authorization could not be completed")
                return payload
    except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
        raise TelegramOIDCError("Telegram authorization could not be completed") from exc


async def validate_id_token(id_token: str, nonce: str) -> dict[str, Any]:
    global _jwks_cache
    metadata = await discovery()
    now = datetime.now(timezone.utc)
    if not _jwks_cache or _jwks_cache[0] <= now:
        _jwks_cache = (now + DISCOVERY_TTL, await _get_json(str(metadata["jwks_uri"])))
    try:
        claims = jwt.decode(
            id_token,
            _jwks_cache[1],
            algorithms=["RS256"],
            audience=settings.TELEGRAM_OIDC_CLIENT_ID,
            issuer=str(metadata["issuer"]),
            options={"verify_at_hash": False},
        )
    except JWTError as exc:
        # A rotated signing key may not be in the cached JWKS. Retry once.
        try:
            _jwks_cache = (now + DISCOVERY_TTL, await _get_json(str(metadata["jwks_uri"])))
            claims = jwt.decode(
                id_token,
                _jwks_cache[1],
                algorithms=["RS256"],
                audience=settings.TELEGRAM_OIDC_CLIENT_ID,
                issuer=str(metadata["issuer"]),
                options={"verify_at_hash": False},
            )
        except (JWTError, TelegramOIDCError) as retry_exc:
            raise TelegramOIDCError("Telegram ID token is invalid") from retry_exc
    if claims.get("nonce") != nonce or not claims.get("sub"):
        raise TelegramOIDCError("Telegram ID token is invalid")
    try:
        expires_at = int(claims.get("exp", 0))
    except (TypeError, ValueError) as exc:
        raise TelegramOIDCError("Telegram ID token is invalid") from exc
    if expires_at <= int(time.time()):
        raise TelegramOIDCError("Telegram ID token is expired")
    return claims


def new_state_values() -> tuple[str, str, str, str, str]:
    state = secrets.token_urlsafe(48)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    return state, nonce, verifier, _sha256(state), _sha256(nonce)


def encrypt_verifier(verifier: str) -> str:
    return encrypt_secret(verifier)


def decrypt_verifier(value: str) -> str:
    return decrypt_secret(value)


def encrypt_nonce(nonce: str) -> str:
    return encrypt_secret(nonce)


def decrypt_nonce(value: str) -> str:
    return decrypt_secret(value)
