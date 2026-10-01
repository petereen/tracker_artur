"""TOTP (RFC 6238) second factor for operator console logins.

Standard parameters (SHA-1, 6 digits, 30 s) so every authenticator app works:
Google Authenticator, Microsoft Authenticator, Authy, 1Password, Bitwarden…
Recovery codes are random (50 bits), so a plain SHA-256 is enough to store them.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote, urlencode

DIGITS = 6
PERIOD = 30
# Steps accepted on either side of "now" (phone clock drift).
WINDOW = 1
RECOVERY_CODE_COUNT = 10
_RECOVERY_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"


def generate_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode()


def _key(secret: str) -> bytes:
    cleaned = secret.replace(" ", "").upper()
    return base64.b32decode(cleaned + "=" * (-len(cleaned) % 8))


def code_at(secret: str, step: int) -> str:
    digest = hmac.new(_key(secret), struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10**DIGITS).zfill(DIGITS)


def current_step(now: float | None = None) -> int:
    return int((time.time() if now is None else now) // PERIOD)


def normalize_code(code: str) -> str:
    return "".join(ch for ch in code if not ch.isspace() and ch != "-").lower()


def verify(secret: str, code: str, *, last_step: int | None = None, now: float | None = None) -> int | None:
    """Return the matched time step, or ``None``.

    Steps at or before ``last_step`` are refused, so a code that was already
    used (or observed) cannot be replayed inside its validity window.
    """
    candidate = normalize_code(code)
    if len(candidate) != DIGITS or not candidate.isdigit():
        return None
    step = current_step(now)
    matched: int | None = None
    for offset in range(-WINDOW, WINDOW + 1):
        if hmac.compare_digest(code_at(secret, step + offset), candidate):
            matched = step + offset
    if matched is None or (last_step is not None and matched <= last_step):
        return None
    return matched


def provisioning_uri(secret: str, account: str, issuer: str) -> str:
    label = quote(f"{issuer}:{account}", safe="")
    query = urlencode({"secret": secret, "issuer": issuer, "algorithm": "SHA1", "digits": DIGITS, "period": PERIOD})
    return f"otpauth://totp/{label}?{query}"


def generate_recovery_codes(count: int = RECOVERY_CODE_COUNT) -> list[str]:
    def one() -> str:
        raw = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(10))
        return f"{raw[:5]}-{raw[5:]}"

    return [one() for _ in range(count)]


def hash_recovery_code(code: str) -> str:
    return hashlib.sha256(normalize_code(code).encode()).hexdigest()


def consume_recovery_code(hashes: list[str], code: str) -> list[str] | None:
    """Return the remaining hashes when ``code`` is an unused recovery code."""
    digest = hash_recovery_code(code)
    remaining = [item for item in hashes if not hmac.compare_digest(item, digest)]
    return remaining if len(remaining) != len(hashes) else None
