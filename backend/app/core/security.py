import time
import hashlib
import secrets
from typing import Any
import base64
import hmac

import bcrypt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from jose import JWTError, jwt

from app.core.config import settings

ALGORITHM = "HS256"
_argon2 = PasswordHasher()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def hash_account_password(password: str) -> str:
    return _argon2.hash(password)


def verify_account_password(password: str, hashed: str) -> tuple[bool, bool]:
    """Return (valid, needs_rehash), accepting legacy bcrypt admin hashes."""
    if hashed.startswith("$2"):
        try:
            return bcrypt.checkpw(password.encode(), hashed.encode()), True
        except ValueError:
            return False, False
    try:
        valid = _argon2.verify(hashed, password)
        return valid, valid and _argon2.check_needs_rehash(hashed)
    except (InvalidHashError, VerificationError):
        return False, False


def create_access_token(data: dict) -> str:
    payload = data.copy()
    payload["exp"] = int(time.time()) + settings.ACCESS_TOKEN_EXPIRE_HOURS * 3600
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def create_enterprise_access_token(account_id: int, organization_id: int) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "sub": str(account_id),
            "organization_id": organization_id,
            "kind": "enterprise",
            "iat": now,
            "exp": now + settings.ENTERPRISE_ACCESS_TOKEN_MINUTES * 60,
        },
        settings.SECRET_KEY,
        algorithm=ALGORITHM,
    )


def create_mcp_access_token(
    *,
    account_id: int,
    organization_id: int,
    channel: str,
    conversation_id: int | None,
    allowed_tools: list[str],
) -> str:
    """Create a short-lived capability token for one OYUNS MCP turn.

    The edge still reloads account status and roles at execution time. Claims
    therefore constrain exposure but never replace database authorization.
    """
    now = int(time.time())
    return jwt.encode(
        {
            "sub": str(account_id),
            "organization_id": organization_id,
            "kind": "oyuns_mcp",
            "aud": "oyuns-mcp",
            "iss": settings.MCP_TOKEN_ISSUER,
            "channel": channel,
            "conversation_id": conversation_id,
            "tools": sorted(set(allowed_tools)),
            "jti": secrets.token_urlsafe(18),
            "iat": now,
            "nbf": now,
            "exp": now + settings.MCP_TOKEN_TTL_SECONDS,
        },
        settings.SECRET_KEY,
        algorithm=ALGORITHM,
    )


def new_refresh_token() -> tuple[str, str]:
    token = secrets.token_urlsafe(48)
    return token, hashlib.sha256(token.encode()).hexdigest()


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


def decode_mcp_access_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM], audience="oyuns-mcp", issuer=settings.MCP_TOKEN_ISSUER)
    except JWTError:
        return None
    if payload.get("kind") != "oyuns_mcp" or not payload.get("jti"):
        return None
    return payload


def create_action_preview_token(*, action_id: int, payload_digest: str, account_id: int,
                                organization_id: int, channel: str, nonce: str | None = None,
                                ttl_seconds: int | None = None) -> str:
    """Sign an opaque, actor/channel-bound reference to protected action state."""
    # Telegram callback_data is capped at 64 bytes.  The full validated
    # payload and expiry remain in AssistantPendingAction; this compact token
    # carries enough signed material to bind the callback to that row.
    action_ref = base64.b32encode(str(action_id).encode()).decode().rstrip("=").lower()
    short_nonce = (nonce or secrets.token_urlsafe(8)).replace("-", "").replace("_", "")[:8]
    digest_prefix = payload_digest[:12]
    expires_at = int(time.time()) + (ttl_seconds or settings.AI_PREVIEW_TOKEN_TTL_SECONDS)
    expires_ref = format(expires_at, "x")
    canonical = f"{action_ref}|{digest_prefix}|{short_nonce}|{expires_ref}|{account_id}|{organization_id}|{channel}"
    signature = base64.urlsafe_b64encode(hmac.new(settings.SECRET_KEY.encode(), canonical.encode(), hashlib.sha256).digest()).decode().rstrip("=")[:16]
    return f"ap1.{action_ref}.{digest_prefix}.{short_nonce}.{expires_ref}.{signature}"


def decode_action_preview_token(token: str) -> dict[str, Any] | None:
    try:
        version, action_ref, digest_prefix, nonce, expires_ref, signature = token.split(".", 5)
        if version != "ap1" or not action_ref or len(digest_prefix) != 12 or not nonce or not expires_ref or len(signature) != 16:
            return None
        padded = action_ref.upper() + "=" * (-len(action_ref) % 8)
        action_id = base64.b32decode(padded.encode()).decode()
        if not action_id.isdigit():
            return None
        expires_at = int(expires_ref, 16)
    except (ValueError, UnicodeDecodeError, base64.binascii.Error):
        return None
    if expires_at < int(time.time()):
        return None
    return {"kind": "oyuns_action_preview", "action_id": action_id, "digest_prefix": digest_prefix, "nonce": nonce, "expires_at": expires_at, "expires_ref": expires_ref, "signature": signature}


def verify_action_preview_token(token: str, *, payload_digest: str, account_id: int,
                               organization_id: int, channel: str) -> bool:
    claims = decode_action_preview_token(token)
    if not claims or claims["digest_prefix"] != payload_digest[:12]:
        return False
    canonical = f"{base64.b32encode(str(claims['action_id']).encode()).decode().rstrip('=').lower()}|{claims['digest_prefix']}|{claims['nonce']}|{claims['expires_ref']}|{account_id}|{organization_id}|{channel}"
    expected = base64.urlsafe_b64encode(hmac.new(settings.SECRET_KEY.encode(), canonical.encode(), hashlib.sha256).digest()).decode().rstrip("=")[:16]
    return hmac.compare_digest(expected, str(claims["signature"]))
