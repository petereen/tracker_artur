"""OYUNS ERP license keys: Ed25519-signed JWS tokens (RFC 7515 + RFC 8037).

A license token is a standard compact JWS::

    base64url(header) . base64url(claims) . base64url(ed25519 signature)

    header = {"alg": "EdDSA", "typ": "oyuns-license+jwt", "kid": "<key id>"}
    claims = {"iss", "aud", "sub": <tenant public_id>, "tenant": <slug>,
              "jti": <license id>, "iat", "nbf", "exp", "seats",
              "features": [...], "plan", "cycle", "ver": 1}

Why asymmetric: only the issuer (operator console) holds the private key.
Every verifier — this API, a self-hosted install, support tooling — needs
just the public key, so a leaked application server cannot mint licenses,
and keys rotate by ``kid``. Signature checks are offline; revocation and the
"one active license" rule come from the ``tenant_licenses`` registry.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from app.core.config import settings
from app.core.tenancy import normalize_features

TOKEN_TYPE = "oyuns-license+jwt"
TOKEN_VERSION = 1
MAX_TOKEN_BYTES = 8192
CLOCK_LEEWAY_SECONDS = 60


class LicenseError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class LicenseClaims:
    license_id: str
    tenant_public_id: str
    tenant_slug: str | None
    seats: int
    features: tuple[str, ...]
    plan: str | None
    billing_cycle: str
    issued_at: datetime
    valid_from: datetime
    expires_at: datetime
    key_id: str
    issuer: str

    def as_dict(self) -> dict:
        return {
            "license_id": self.license_id,
            "tenant_public_id": self.tenant_public_id,
            "tenant_slug": self.tenant_slug,
            "seats": self.seats,
            "features": list(self.features),
            "plan": self.plan,
            "billing_cycle": self.billing_cycle,
            "issued_at": self.issued_at.isoformat(),
            "valid_from": self.valid_from.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "key_id": self.key_id,
            "issuer": self.issuer,
        }


# ── encoding helpers ───────────────────────────────────────────────────────
def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    if not value or any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for char in value):
        raise LicenseError("malformed", "Лицензийн түлхүүр буруу форматтай байна.")
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (binascii.Error, ValueError) as exc:
        raise LicenseError("malformed", "Лицензийн түлхүүр буруу форматтай байна.") from exc


def _json(raw: bytes) -> dict:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LicenseError("malformed", "Лицензийн түлхүүр буруу форматтай байна.") from exc
    if not isinstance(value, dict):
        raise LicenseError("malformed", "Лицензийн түлхүүр буруу форматтай байна.")
    return value


def token_fingerprint(token: str) -> str:
    return hashlib.sha256(token.strip().encode("utf-8")).hexdigest()


# ── keys ───────────────────────────────────────────────────────────────────
def _key_material(value: str) -> bytes:
    value = value.strip()
    if "-----BEGIN" in value:
        return value.replace("\\n", "\n").encode("ascii")
    return base64.b64decode(value + "=" * (-len(value) % 4))


def load_private_key(value: str) -> Ed25519PrivateKey:
    material = _key_material(value)
    if material.startswith(b"-----BEGIN"):
        key = serialization.load_pem_private_key(material, password=None)
    else:
        key = Ed25519PrivateKey.from_private_bytes(material)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("License signing key must be Ed25519")
    return key


def load_public_key(value: str) -> Ed25519PublicKey:
    material = _key_material(value)
    if material.startswith(b"-----BEGIN"):
        key = serialization.load_pem_public_key(material)
    else:
        key = Ed25519PublicKey.from_public_bytes(material)
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("License verification key must be Ed25519")
    return key


def generate_keypair() -> tuple[str, str]:
    """Return a fresh (private PEM, public PEM) Ed25519 pair."""
    private = Ed25519PrivateKey.generate()
    private_pem = private.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode("ascii")
    public_pem = private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode("ascii")
    return private_pem, public_pem


@lru_cache(maxsize=4)
def _signing_key(private_value: str, key_id: str) -> tuple[str, Ed25519PrivateKey] | None:
    if not private_value.strip():
        return None
    return key_id, load_private_key(private_value)


@lru_cache(maxsize=4)
def _keyring(public_json: str, private_value: str, key_id: str) -> dict[str, Ed25519PublicKey]:
    ring: dict[str, Ed25519PublicKey] = {}
    if public_json.strip():
        entries = json.loads(public_json)
        if not isinstance(entries, dict):
            raise ValueError("LICENSE_PUBLIC_KEYS must be a JSON object of kid -> key")
        for kid, value in entries.items():
            ring[str(kid)] = load_public_key(str(value))
    signing = _signing_key(private_value, key_id)
    if signing:
        ring.setdefault(signing[0], signing[1].public_key())
    return ring


def signing_key() -> tuple[str, Ed25519PrivateKey]:
    signing = _signing_key(settings.LICENSE_SIGNING_PRIVATE_KEY, settings.LICENSE_SIGNING_KEY_ID)
    if signing is None:
        raise LicenseError("signing_unavailable", "LICENSE_SIGNING_PRIVATE_KEY is not configured on this server")
    return signing


def signing_available() -> bool:
    try:
        signing_key()
        return True
    except (LicenseError, ValueError, TypeError):
        return False


def public_keyring() -> dict[str, Ed25519PublicKey]:
    return _keyring(settings.LICENSE_PUBLIC_KEYS, settings.LICENSE_SIGNING_PRIVATE_KEY, settings.LICENSE_SIGNING_KEY_ID)


def public_key_pem(kid: str | None = None) -> str | None:
    ring = public_keyring()
    key = ring.get(kid or settings.LICENSE_SIGNING_KEY_ID)
    if key is None:
        return None
    return key.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode("ascii")


# ── issue / verify ─────────────────────────────────────────────────────────
def _timestamp(value: datetime) -> int:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return int(value.timestamp())


def issue_token(
    *,
    license_id: str,
    tenant_public_id: str,
    tenant_slug: str | None,
    seats: int,
    features: list[str] | tuple[str, ...],
    plan: str | None,
    billing_cycle: str,
    valid_from: datetime,
    expires_at: datetime,
    now: datetime | None = None,
) -> tuple[str, str]:
    """Sign a license and return ``(token, key_id)``."""
    if seats < 1:
        raise LicenseError("invalid_claims", "A license needs at least one seat")
    if expires_at <= valid_from:
        raise LicenseError("invalid_claims", "License expiry must be after its start")
    try:
        kid, private_key = signing_key()
    except (ValueError, TypeError) as exc:
        if isinstance(exc, LicenseError):
            raise
        raise LicenseError("signing_unavailable", "LICENSE_SIGNING_PRIVATE_KEY is not a valid Ed25519 key") from exc
    now = now or datetime.now(timezone.utc)
    header = {"alg": "EdDSA", "typ": TOKEN_TYPE, "kid": kid}
    claims = {
        "iss": settings.LICENSE_ISSUER,
        "aud": settings.LICENSE_AUDIENCE,
        "sub": str(tenant_public_id),
        "tenant": tenant_slug,
        "jti": str(license_id),
        "iat": _timestamp(now),
        "nbf": _timestamp(valid_from),
        "exp": _timestamp(expires_at),
        "seats": int(seats),
        "features": normalize_features(features),
        "plan": plan,
        "cycle": billing_cycle,
        "ver": TOKEN_VERSION,
    }
    signing_input = f"{_b64encode(json.dumps(header, separators=(',', ':'), sort_keys=True).encode())}.{_b64encode(json.dumps(claims, separators=(',', ':'), sort_keys=True).encode())}"
    signature = private_key.sign(signing_input.encode("ascii"))
    return f"{signing_input}.{_b64encode(signature)}", kid


def _int_claim(claims: dict, name: str) -> int:
    value = claims.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise LicenseError("invalid_claims", f"License claim '{name}' is missing or invalid")
    return value


def verify_token(token: str, *, now: datetime | None = None, expected_tenant: str | None = None) -> LicenseClaims:
    """Validate signature, issuer, audience, validity window and tenant binding."""
    token = (token or "").strip()
    if not token or len(token.encode("utf-8", "ignore")) > MAX_TOKEN_BYTES or token.count(".") != 2:
        raise LicenseError("malformed", "Лицензийн түлхүүр буруу форматтай байна.")
    encoded_header, encoded_claims, encoded_signature = token.split(".")
    header = _json(_b64decode(encoded_header))
    if header.get("alg") != "EdDSA" or header.get("typ") != TOKEN_TYPE:
        raise LicenseError("unsupported_algorithm", "Лицензийн түлхүүрийн төрөл дэмжигдэхгүй.")
    kid = header.get("kid")
    try:
        ring = public_keyring()
    except (ValueError, TypeError) as exc:
        raise LicenseError("verification_unavailable", "License verification keys are misconfigured on this server") from exc
    key = ring.get(kid) if isinstance(kid, str) else None
    if key is None:
        raise LicenseError("unknown_key", "Лицензийг таних гарын үсгийн түлхүүр олдсонгүй.")
    try:
        key.verify(_b64decode(encoded_signature), f"{encoded_header}.{encoded_claims}".encode("ascii"))
    except InvalidSignature as exc:
        raise LicenseError("bad_signature", "Лицензийн гарын үсэг хүчингүй байна.") from exc

    claims = _json(_b64decode(encoded_claims))
    if claims.get("ver") != TOKEN_VERSION:
        raise LicenseError("unsupported_version", "Лицензийн хувилбар дэмжигдэхгүй.")
    if claims.get("iss") != settings.LICENSE_ISSUER:
        raise LicenseError("wrong_issuer", "Лиценз өөр гаргагчийнх байна.")
    if claims.get("aud") != settings.LICENSE_AUDIENCE:
        raise LicenseError("wrong_audience", "Лиценз энэ бүтээгдэхүүнд зориулагдаагүй.")
    subject, license_id = claims.get("sub"), claims.get("jti")
    if not isinstance(subject, str) or not isinstance(license_id, str):
        raise LicenseError("invalid_claims", "License subject or id is missing")
    try:
        uuid.UUID(license_id)
    except ValueError as exc:
        raise LicenseError("invalid_claims", "License id is invalid") from exc
    seats = _int_claim(claims, "seats")
    issued_at, not_before, expires = (_int_claim(claims, name) for name in ("iat", "nbf", "exp"))
    if seats < 1 or expires <= not_before:
        raise LicenseError("invalid_claims", "License seats or validity window are invalid")
    features = claims.get("features")
    if not isinstance(features, list) or not all(isinstance(item, str) for item in features):
        raise LicenseError("invalid_claims", "License features are invalid")

    current = _timestamp(now or datetime.now(timezone.utc))
    if current + CLOCK_LEEWAY_SECONDS < not_before:
        raise LicenseError("not_yet_valid", "Лицензийн хугацаа хараахан эхлээгүй байна.")
    if current >= expires:
        raise LicenseError("expired", "Лицензийн хугацаа дууссан байна.")
    if expected_tenant is not None and subject != str(expected_tenant):
        raise LicenseError("tenant_mismatch", "Энэ лиценз өөр байгууллагад зориулагдсан.")

    as_datetime = lambda value: datetime.fromtimestamp(value, tz=timezone.utc)  # noqa: E731
    cycle = claims.get("cycle") if isinstance(claims.get("cycle"), str) else "custom"
    return LicenseClaims(
        license_id=license_id,
        tenant_public_id=subject,
        tenant_slug=claims.get("tenant") if isinstance(claims.get("tenant"), str) else None,
        seats=seats,
        features=tuple(normalize_features(features)),
        plan=claims.get("plan") if isinstance(claims.get("plan"), str) else None,
        billing_cycle=cycle,
        issued_at=as_datetime(issued_at),
        valid_from=as_datetime(not_before),
        expires_at=as_datetime(expires),
        key_id=kid,
        issuer=claims["iss"],
    )
