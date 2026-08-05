import time
import hashlib
import secrets

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
