import hashlib
import secrets
import hmac
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Cookie, Depends, File, Header, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import RedirectResponse
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.enterprise_deps import ActorContext, get_actor, require_roles
from app.core.security import (
    create_enterprise_access_token,
    hash_account_password,
    hash_refresh_token,
    new_refresh_token,
    verify_account_password,
)
from app.core.telegram_auth import verify_init_data
from app.models.models import Employee, JobQueue, Organization, PasswordResetToken, RefreshSession, RoleAssignment, TelegramOAuthState, UserAccount
from app.services.email_service import email_is_configured
from app.services.secret_box import encrypt_secret
from app.services.avatar_storage import InvalidAvatar, read_avatar, save_avatar
from app.services.malware_scanner import MalwareDetected, MalwareScanUnavailable
from app.services import telegram_oidc


router = APIRouter()
REFRESH_COOKIE = "oyuns_refresh"
TELEGRAM_WEB_STATE_COOKIE = "oyuns_telegram_oidc_state"
TELEGRAM_DEFAULT_ROLE = "member"


class LoginInput(BaseModel):
    email: str
    password: str
    device_label: str | None = Field(default=None, max_length=200)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class NativeTelegramStart(BaseModel):
    platform: Literal["ios", "android"]


class NativeTelegramExchange(BaseModel):
    code: str = Field(min_length=8, max_length=4096)
    state: str = Field(min_length=16, max_length=512)


class AccessTokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_token: str | None = None


class AuthCapabilities(BaseModel):
    telegram_native: bool


class RefreshInput(BaseModel):
    refresh_token: str | None = Field(default=None, min_length=32, max_length=512)


class AccountOut(BaseModel):
    id: int
    email: str
    employee_id: int | None
    locale: str
    roles: list[str]
    status: str
    name: str | None = None
    avatar_url: str | None = None
    telegram_id: str | None = None


class AccountCreate(BaseModel):
    email: str
    password: str = Field(min_length=10, max_length=128)
    employee_id: int | None = None
    locale: str = "mn"
    roles: list[str] = Field(default_factory=lambda: ["member"])
    must_change_password: bool = True

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        identifier = value.strip().lower()
        if not identifier or len(identifier) > 254 or any(char.isspace() for char in identifier):
            raise ValueError("A valid username is required")
        return identifier


class AccountAdminPatch(BaseModel):
    username: str | None = Field(default=None, min_length=1, max_length=254)
    password: str | None = Field(default=None, min_length=10, max_length=128)
    employee_id: int | None = None
    locale: str | None = Field(default=None, max_length=8)
    roles: list[str] | None = None
    status: Literal["active", "disabled"] | None = None

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().lower()
        if not value or any(char.isspace() for char in value):
            raise ValueError("A valid username is required")
        return value


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10, max_length=128)


class ProfilePatch(BaseModel):
    username: str | None = Field(default=None, min_length=1, max_length=254)
    avatar_url: str | None = Field(default=None, max_length=2048)
    locale: Literal["mn", "en", "ru"] | None = None
    phone_number: str | None = Field(default=None, max_length=80)
    birthday: date | None = None
    work_direction: str | None = Field(default=None, max_length=240)
    work_branch: str | None = Field(default=None, max_length=240)
    current_password: str | None = None

    @field_validator("username")
    @classmethod
    def normalize_profile_username(cls, value: str | None) -> str | None:
        if value is None:
            return None
        identifier = value.strip().lower()
        if not identifier or any(char.isspace() for char in identifier):
            raise ValueError("A valid username is required")
        return identifier

    @field_validator("avatar_url")
    @classmethod
    def validate_avatar_url(cls, value: str | None) -> str | None:
        value = value.strip() if value else None
        memoji_paths = {f"/emojis/memoji-{index:02d}.png" for index in range(1, 11)}
        uploaded = value and value.startswith("/api/v1/auth/avatars/") and value.endswith(".png")
        allowed = value and (value in memoji_paths or uploaded)
        if value and not allowed:
            raise ValueError("Choose a supplied memoji or upload a custom avatar")
        return value


DEFAULT_WORLD_CLOCKS = ["Asia/Ulaanbaatar"]
WORLD_CLOCK_MAX = 6


class WorldClockPreferences(BaseModel):
    clocks: list[str] = Field(default_factory=lambda: list(DEFAULT_WORLD_CLOCKS))
    display_mode: Literal["digital", "analog"] = "digital"
    hour_format: Literal["12", "24"] = "24"

    @field_validator("clocks")
    @classmethod
    def validate_clocks(cls, value: list[str]) -> list[str]:
        if len(value) > WORLD_CLOCK_MAX:
            raise ValueError(f"At most {WORLD_CLOCK_MAX} world clocks are supported")
        normalized: list[str] = []
        for timezone_name in value:
            timezone_name = timezone_name.strip()
            if not timezone_name:
                raise ValueError("Timezone cannot be empty")
            try:
                ZoneInfo(timezone_name)
            except ZoneInfoNotFoundError as exc:
                raise ValueError("Unknown timezone") from exc
            normalized.append(timezone_name)
        if len(normalized) != len(set(normalized)):
            raise ValueError("World clocks must use unique timezones")
        return normalized


class PasswordResetRequest(BaseModel):
    email: str

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class PasswordResetConfirm(BaseModel):
    token: str = Field(min_length=32, max_length=512)
    new_password: str = Field(min_length=10, max_length=128)


class AccountInvite(BaseModel):
    email: str
    employee_id: int | None = None
    locale: str = "mn"
    roles: list[str] = Field(default_factory=lambda: ["member"])

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        email = value.strip().lower()
        if "@" not in email:
            raise ValueError("A valid email is required")
        return email


def _set_refresh_cookie(response: Response, token: str, expires_at: datetime) -> None:
    max_age = max(1, int((expires_at - datetime.now(timezone.utc)).total_seconds()))
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=max_age,
        httponly=True,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite="lax",
        path="/api/v1/auth",
    )


def _web_telegram_error(code: str) -> RedirectResponse:
    # Keep the browser on the host that completed OAuth. This matters while
    # the legacy and current OYUNS domains are both reachable; an absolute
    # PUBLIC_APP_URL redirect could strand the host-only refresh cookie.
    target = f"/?{urlencode({'telegram_auth_error': code})}"
    response = RedirectResponse(target, status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(TELEGRAM_WEB_STATE_COOKIE, path="/api/v1/auth/telegram")
    return response


def _clear_web_telegram_state(response: Response) -> None:
    response.delete_cookie(TELEGRAM_WEB_STATE_COOKIE, path="/api/v1/auth/telegram")


def _native_origins() -> set[str]:
    return {origin.strip() for origin in settings.NATIVE_APP_ORIGINS.split(",") if origin.strip()}


def _is_native_origin(origin: str | None) -> bool:
    return bool(origin and origin in _native_origins())


def _access(account: UserAccount, refresh_token: str | None = None) -> AccessTokenOut:
    return AccessTokenOut(
        access_token=create_enterprise_access_token(account.id, account.organization_id),
        expires_in=settings.ENTERPRISE_ACCESS_TOKEN_MINUTES * 60,
        refresh_token=refresh_token,
    )


def _complete_session(response: Response, account: UserAccount, token: str, expires_at: datetime, origin: str | None):
    if _is_native_origin(origin):
        return _access(account, refresh_token=token)
    _set_refresh_cookie(response, token, expires_at)
    return _access(account)


async def _issue_action_token(db: AsyncSession, account: UserAccount, purpose: str) -> str:
    now = datetime.now(timezone.utc)
    await db.execute(
        PasswordResetToken.__table__.update()
        .where(
            PasswordResetToken.account_id == account.id,
            PasswordResetToken.purpose == purpose,
            PasswordResetToken.used_at.is_(None),
        )
        .values(used_at=now)
    )
    raw_token = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    lifetime = timedelta(hours=settings.INVITATION_EXPIRE_HOURS) if purpose == "invitation" else timedelta(minutes=settings.PASSWORD_RESET_MINUTES)
    token = PasswordResetToken(account_id=account.id, token_hash=token_hash, purpose=purpose, expires_at=now + lifetime)
    db.add(token)
    await db.flush()
    action_url = f"{settings.PUBLIC_APP_URL.rstrip('/')}/reset-password?token={quote(raw_token)}"
    db.add(
        JobQueue(
            job_type="auth_email",
            payload={
                "to": account.email,
                "kind": purpose,
                "locale": account.locale,
                "action_url_encrypted": encrypt_secret(action_url),
                "idempotency_key": f"auth-{purpose}-{token.id}",
            },
            dedup_key=f"auth-email:{purpose}:{token.id}",
        )
    )
    return raw_token


@router.post("/login", response_model=AccessTokenOut, response_model_exclude_none=True)
async def login(
    data: LoginInput,
    response: Response,
    origin: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    account = (
        await db.execute(select(UserAccount).where(func.lower(UserAccount.email) == data.email))
    ).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if not account or account.status not in {"active", "locked"}:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if account.locked_until and account.locked_until > now:
        raise HTTPException(status_code=423, detail="Account is temporarily locked")
    valid, needs_rehash = verify_account_password(data.password, account.password_hash)
    if not valid:
        account.failed_login_count = (account.failed_login_count or 0) + 1
        if account.failed_login_count >= 5:
            account.locked_until = now + timedelta(minutes=15)
        await db.commit()
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if needs_rehash:
        account.password_hash = hash_account_password(data.password)
    account.status = "active"
    account.failed_login_count = 0
    account.locked_until = None
    account.last_login_at = now
    refresh_token, token_hash = new_refresh_token()
    refresh_expires_at = now + timedelta(days=settings.REFRESH_TOKEN_DAYS)
    db.add(
        RefreshSession(
            account_id=account.id,
            token_hash=token_hash,
            device_label=data.device_label,
            auth_method="password",
            expires_at=refresh_expires_at,
        )
    )
    await db.commit()
    return _complete_session(response, account, refresh_token, refresh_expires_at, origin)


async def _telegram_session(
    response: Response,
    db: AsyncSession,
    telegram_id: str,
    username: str | None,
    device_label: str,
    origin: str | None,
    oidc_subject: str | None = None,
):
    """Link a registered Telegram identity and issue the one-year session."""
    telegram_user = {"id": telegram_id, "username": username} if username else {"id": telegram_id}
    if not telegram_user or not telegram_id.isdigit():
        raise HTTPException(status_code=401, detail="Invalid Telegram login")

    account = None
    employee = None
    if oidc_subject:
        account = await db.scalar(select(UserAccount).where(UserAccount.telegram_oidc_subject == oidc_subject))
        if account and account.employee_id:
            employee = await db.scalar(select(Employee).where(Employee.id == account.employee_id))

    if employee is None:
        employee = await db.scalar(select(Employee).where(Employee.telegram_id == telegram_id))
    if employee is None and telegram_user.get("username"):
        username = str(telegram_user["username"]).lstrip("@")
        employee = await db.scalar(select(Employee).where(Employee.telegram_username.ilike(username)))
        if employee and employee.telegram_id != telegram_id:
            employee.telegram_id = telegram_id
    if not employee or not employee.is_active:
        raise HTTPException(status_code=403, detail="Telegram user is not registered as an active employee")

    if account is None:
        account = await db.scalar(select(UserAccount).where(UserAccount.employee_id == employee.id))
    if account is None and employee.email:
        account = await db.scalar(select(UserAccount).where(func.lower(UserAccount.email) == employee.email.lower()))
        if account and account.employee_id is None:
            account.employee_id = employee.id
        elif account and account.employee_id != employee.id:
            raise HTTPException(status_code=409, detail="Employee email is linked to another account")
    if account is None:
        organization = await db.get(Organization, 1)
        if not organization:
            raise HTTPException(status_code=503, detail="Organization setup is incomplete")
        account = UserAccount(
            organization_id=organization.id,
            employee_id=employee.id,
            email=f"telegram-{telegram_id}",
            telegram_oidc_subject=oidc_subject,
            password_hash=hash_account_password(secrets.token_urlsafe(48)),
            status="active",
            locale=employee.primary_language or "mn",
            must_change_password=True,
        )
        db.add(account)
        await db.flush()
    elif oidc_subject:
        if account.telegram_oidc_subject and account.telegram_oidc_subject != oidc_subject:
            raise HTTPException(status_code=409, detail="This account is linked to another Telegram identity")
        account.telegram_oidc_subject = oidc_subject

    if account.status == "disabled":
        raise HTTPException(status_code=403, detail="Account is disabled")
    account.status = "active"
    account.failed_login_count = 0
    account.locked_until = None
    account.last_login_at = datetime.now(timezone.utc)
    roles = (await db.execute(select(RoleAssignment.role).where(RoleAssignment.account_id == account.id))).scalars().all()
    if not roles:
        db.add(RoleAssignment(account_id=account.id, role=TELEGRAM_DEFAULT_ROLE))

    now = datetime.now(timezone.utc)
    refresh_expires_at = now + timedelta(days=settings.TELEGRAM_REFRESH_TOKEN_DAYS)
    refresh_token, token_hash = new_refresh_token()
    db.add(RefreshSession(
        account_id=account.id,
        token_hash=token_hash,
        device_label=device_label,
        auth_method="telegram",
        expires_at=refresh_expires_at,
    ))
    await db.commit()
    return _complete_session(response, account, refresh_token, refresh_expires_at, origin)


@router.get("/capabilities", response_model=AuthCapabilities)
async def auth_capabilities():
    """Expose non-secret authentication capabilities for login surfaces."""
    return AuthCapabilities(telegram_native=telegram_oidc.is_configured())


@router.post("/telegram-native/start")
async def native_telegram_start(
    data: NativeTelegramStart,
    origin: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Create a short-lived native Telegram OIDC authorization transaction."""
    if not _is_native_origin(origin):
        raise HTTPException(status_code=403, detail="Native Telegram authentication is only available in the mobile app")
    if not telegram_oidc.is_configured():
        raise HTTPException(status_code=503, detail="Telegram authentication is not configured")

    state, nonce, verifier, state_hash, nonce_hash = telegram_oidc.new_state_values()
    try:
        authorization = await telegram_oidc.authorization_url(
            state,
            nonce,
            verifier,
            redirect_uri=settings.TELEGRAM_OIDC_NATIVE_REDIRECT_URI,
        )
    except telegram_oidc.TelegramOIDCError as exc:
        raise HTTPException(status_code=503, detail="Telegram authentication is temporarily unavailable") from exc

    db.add(TelegramOAuthState(
        state_hash=state_hash,
        nonce_hash=nonce_hash,
        encrypted_nonce=telegram_oidc.encrypt_nonce(nonce),
        encrypted_code_verifier=telegram_oidc.encrypt_verifier(verifier),
        platform=data.platform,
        expires_at=datetime.now(timezone.utc) + telegram_oidc.STATE_TTL,
    ))
    await db.commit()
    return {"authorization_url": authorization, "expires_in": int(telegram_oidc.STATE_TTL.total_seconds())}


@router.post("/telegram-native/exchange", response_model=AccessTokenOut, response_model_exclude_none=True)
async def native_telegram_exchange(
    data: NativeTelegramExchange,
    response: Response,
    origin: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Consume a native Telegram OIDC callback and issue the normal app session."""
    if not _is_native_origin(origin):
        raise HTTPException(status_code=403, detail="Native Telegram authentication is only available in the mobile app")
    if not telegram_oidc.is_configured():
        raise HTTPException(status_code=503, detail="Telegram authentication is not configured")

    now = datetime.now(timezone.utc)
    state_hash = hashlib.sha256(data.state.encode()).hexdigest()
    record = (
        await db.execute(
            select(TelegramOAuthState)
            .where(
                TelegramOAuthState.state_hash == state_hash,
                TelegramOAuthState.used_at.is_(None),
                TelegramOAuthState.expires_at > now,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=401, detail="Telegram login has expired or was already used")

    try:
        verifier = telegram_oidc.decrypt_verifier(record.encrypted_code_verifier)
        nonce = telegram_oidc.decrypt_nonce(record.encrypted_nonce)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Telegram login state is invalid") from exc
    platform = record.platform
    # Consume before contacting Telegram so a callback cannot be replayed while
    # the provider is slow or returns an invalid authorization code.
    record.used_at = now
    await db.commit()

    try:
        token_payload = await telegram_oidc.exchange_code(
            data.code,
            verifier,
            redirect_uri=settings.TELEGRAM_OIDC_NATIVE_REDIRECT_URI,
        )
        claims = await telegram_oidc.validate_id_token(str(token_payload["id_token"]), nonce)
    except telegram_oidc.TelegramOIDCError as exc:
        raise HTTPException(status_code=401, detail="Telegram authorization failed") from exc

    telegram_id = str(claims.get("id") or claims.get("sub") or "")
    oidc_subject = str(claims.get("sub") or "")
    username = claims.get("preferred_username") or claims.get("username")
    return await _telegram_session(response, db, telegram_id, str(username) if username else None, f"telegram-oidc-{platform}", origin, oidc_subject)


@router.get("/telegram")
async def telegram_web_start(db: AsyncSession = Depends(get_db)):
    """Start Telegram OIDC in the user's normal browser."""
    if not telegram_oidc.is_configured():
        return _web_telegram_error("not_configured")

    state, nonce, verifier, state_hash, nonce_hash = telegram_oidc.new_state_values()
    try:
        authorization = await telegram_oidc.authorization_url(
            state,
            nonce,
            verifier,
            redirect_uri=settings.TELEGRAM_OIDC_REDIRECT_URI,
        )
    except telegram_oidc.TelegramOIDCError:
        return _web_telegram_error("provider_unavailable")

    db.add(TelegramOAuthState(
        state_hash=state_hash,
        nonce_hash=nonce_hash,
        encrypted_nonce=telegram_oidc.encrypt_nonce(nonce),
        encrypted_code_verifier=telegram_oidc.encrypt_verifier(verifier),
        platform="web",
        expires_at=datetime.now(timezone.utc) + telegram_oidc.STATE_TTL,
    ))
    await db.commit()
    response = RedirectResponse(authorization, status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        TELEGRAM_WEB_STATE_COOKIE,
        telegram_oidc.encrypt_state(state),
        max_age=int(telegram_oidc.STATE_TTL.total_seconds()),
        httponly=True,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite="lax",
        path="/api/v1/auth/telegram",
    )
    return response


@router.get("/telegram/callback")
async def telegram_web_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    provider_error: str | None = Query(default=None, alias="error"),
    state_cookie: str | None = Cookie(default=None, alias=TELEGRAM_WEB_STATE_COOKIE),
    db: AsyncSession = Depends(get_db),
):
    """Validate the browser transaction, redeem the code, and set the app session."""
    if not telegram_oidc.is_configured():
        return _web_telegram_error("not_configured")
    if not state or not state_cookie:
        return _web_telegram_error("invalid_state")
    try:
        cookie_state = telegram_oidc.decrypt_state(state_cookie)
    except ValueError:
        return _web_telegram_error("invalid_state")
    if not hmac.compare_digest(cookie_state, state):
        return _web_telegram_error("invalid_state")

    now = datetime.now(timezone.utc)
    state_hash = hashlib.sha256(state.encode()).hexdigest()
    record = (
        await db.execute(
            select(TelegramOAuthState)
            .where(
                TelegramOAuthState.state_hash == state_hash,
                TelegramOAuthState.platform == "web",
                TelegramOAuthState.used_at.is_(None),
                TelegramOAuthState.expires_at > now,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if not record:
        return _web_telegram_error("invalid_state")
    try:
        verifier = telegram_oidc.decrypt_verifier(record.encrypted_code_verifier)
        nonce = telegram_oidc.decrypt_nonce(record.encrypted_nonce)
    except ValueError:
        record.used_at = now
        await db.commit()
        return _web_telegram_error("invalid_state")

    record.used_at = now
    await db.commit()
    if provider_error:
        return _web_telegram_error("cancelled" if provider_error == "access_denied" else "provider_error")
    if not code:
        return _web_telegram_error("invalid_callback")

    try:
        token_payload = await telegram_oidc.exchange_code(
            code,
            verifier,
            redirect_uri=settings.TELEGRAM_OIDC_REDIRECT_URI,
        )
    except telegram_oidc.TelegramOIDCError:
        return _web_telegram_error("token_exchange_failed")
    try:
        claims = await telegram_oidc.validate_id_token(str(token_payload["id_token"]), nonce)
    except (KeyError, telegram_oidc.TelegramOIDCError):
        return _web_telegram_error("invalid_id_token")

    telegram_id = str(claims.get("id") or claims.get("sub") or "")
    oidc_subject = str(claims.get("sub") or "")
    username = claims.get("preferred_username") or claims.get("username")
    response = RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    _clear_web_telegram_state(response)
    try:
        await _telegram_session(response, db, telegram_id, str(username) if username else None, "telegram-oidc-web", None, oidc_subject)
    except HTTPException as exc:
        return _web_telegram_error("account_unavailable" if exc.status_code in {401, 403, 409} else "login_failed")
    return response


@router.post("/telegram", response_model=AccessTokenOut, response_model_exclude_none=True)
async def telegram_login(
    response: Response,
    db: AsyncSession = Depends(get_db),
    x_telegram_init_data: str | None = Header(default=None),
    origin: str | None = Header(default=None),
):
    """Exchange verified Telegram Mini App data for a durable web session."""
    telegram_user = verify_init_data(x_telegram_init_data or "")
    telegram_id = str((telegram_user or {}).get("id") or "")
    if not telegram_user or not telegram_id.isdigit():
        raise HTTPException(status_code=401, detail="Invalid Telegram login")
    return await _telegram_session(response, db, telegram_id, telegram_user.get("username"), "telegram-mini-app", origin)


@router.post("/refresh", response_model=AccessTokenOut, response_model_exclude_none=True)
async def refresh(
    response: Response,
    data: RefreshInput | None = None,
    oyuns_refresh: str | None = Cookie(default=None),
    origin: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    supplied_refresh = data.refresh_token if _is_native_origin(origin) and data else oyuns_refresh
    if not supplied_refresh:
        raise HTTPException(status_code=401, detail="Refresh session required")
    now = datetime.now(timezone.utc)
    session = (
        await db.execute(
            select(RefreshSession).where(
                RefreshSession.token_hash == hash_refresh_token(supplied_refresh),
                RefreshSession.revoked_at.is_(None),
                RefreshSession.expires_at > now,
            )
        )
    ).scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=401, detail="Refresh session expired")
    account = await db.get(UserAccount, session.account_id)
    if not account or account.status != "active":
        raise HTTPException(status_code=401, detail="Account unavailable")
    session.revoked_at = now
    session.last_used_at = now
    token, token_hash = new_refresh_token()
    expires_at = session.expires_at if session.auth_method == "telegram" else now + timedelta(days=settings.REFRESH_TOKEN_DAYS)
    db.add(RefreshSession(
        account_id=account.id,
        token_hash=token_hash,
        device_label=session.device_label,
        auth_method=session.auth_method,
        expires_at=expires_at,
    ))
    await db.commit()
    return _complete_session(response, account, token, expires_at, origin)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    data: RefreshInput | None = None,
    oyuns_refresh: str | None = Cookie(default=None),
    origin: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    supplied_refresh = data.refresh_token if _is_native_origin(origin) and data else oyuns_refresh
    if supplied_refresh:
        session = (
            await db.execute(select(RefreshSession).where(RefreshSession.token_hash == hash_refresh_token(supplied_refresh)))
        ).scalar_one_or_none()
        if session and not session.revoked_at:
            session.revoked_at = datetime.now(timezone.utc)
            await db.commit()
    response.delete_cookie(REFRESH_COOKIE, path="/api/v1/auth")


@router.get("/me", response_model=AccountOut)
async def me(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    employee = await db.get(Employee, actor.employee_id) if actor.employee_id else None
    return AccountOut(id=actor.account_id, email=actor.email, employee_id=actor.employee_id, locale=actor.locale, roles=sorted(actor.roles), status="active", name=employee.name if employee else actor.email, avatar_url=(employee.metadata_json or {}).get("avatar_url") if employee else None)


@router.get("/profile")
async def profile(db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    account = await db.get(UserAccount, actor.account_id)
    employee = await db.get(Employee, actor.employee_id) if actor.employee_id else None
    password_setup_required = bool(account and account.must_change_password) or bool(await db.scalar(select(RefreshSession.id).where(RefreshSession.account_id == actor.account_id, RefreshSession.auth_method == "telegram", RefreshSession.revoked_at.is_(None)).limit(1)))
    return {
        "username": actor.email,
        "locale": actor.locale,
        "employee_id": actor.employee_id,
        "name": employee.name if employee else actor.email,
        "telegram_username": employee.telegram_username if employee else None,
        "avatar_url": (employee.metadata_json or {}).get("avatar_url") if employee else None,
        "phone_number": employee.phone_number if employee else None,
        "birthday": employee.birthday if employee else None,
        "work_direction": employee.work_direction if employee else None,
        "work_branch": employee.work_branch if employee else None,
        "telegram_connected": bool(employee and employee.telegram_id),
        "requires_password_setup": password_setup_required,
        "roles": sorted(actor.roles),
    }


@router.get("/preferences/world-clock", response_model=WorldClockPreferences)
async def world_clock_preferences(
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    account = await db.get(UserAccount, actor.account_id)
    saved = (account.preferences or {}).get("world_clock") if account else None
    if not saved:
        return WorldClockPreferences()
    return WorldClockPreferences.model_validate(saved)


@router.put("/preferences/world-clock", response_model=WorldClockPreferences)
async def update_world_clock_preferences(
    data: WorldClockPreferences,
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    account = await db.get(UserAccount, actor.account_id, with_for_update=True)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    account.preferences = {
        **(account.preferences or {}),
        "world_clock": data.model_dump(),
    }
    await db.commit()
    return data


@router.get("/avatars/{token}.png")
async def avatar_media(token: str):
    try:
        content = await read_avatar(token)
    except (FileNotFoundError, OSError):
        raise HTTPException(status_code=404, detail="Avatar not found")
    return Response(content, media_type="image/png", headers={
        "Cache-Control": "public, max-age=31536000, immutable",
        "X-Content-Type-Options": "nosniff",
    })


@router.post("/profile/avatar")
async def upload_profile_avatar(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    if not actor.employee_id:
        raise HTTPException(status_code=400, detail="An employee profile is required")
    content = await file.read(settings.AVATAR_MAX_BYTES + 1)
    try:
        token, width, height, size = await save_avatar(content, file.content_type or "application/octet-stream")
    except InvalidAvatar as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except MalwareDetected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except MalwareScanUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    employee = await db.get(Employee, actor.employee_id, with_for_update=True)
    avatar_url = f"/api/v1/auth/avatars/{token}.png"
    employee.metadata_json = {**(employee.metadata_json or {}), "avatar_url": avatar_url}
    await db.commit()
    return {"avatar_url": avatar_url, "content_type": "image/png", "width": width, "height": height, "size": size}


@router.patch("/profile")
async def update_profile(data: ProfilePatch, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    account = await db.get(UserAccount, actor.account_id, with_for_update=True)
    employee = await db.get(Employee, actor.employee_id, with_for_update=True) if actor.employee_id else None
    password_setup_required = account.must_change_password or bool(await db.scalar(select(RefreshSession.id).where(RefreshSession.account_id == account.id, RefreshSession.auth_method == "telegram", RefreshSession.revoked_at.is_(None)).limit(1)))
    if data.username and data.username != account.email:
        if password_setup_required:
            raise HTTPException(status_code=400, detail="Set a password before changing the username")
        if not data.current_password or not verify_account_password(data.current_password, account.password_hash)[0]:
            raise HTTPException(status_code=400, detail="Current password is required to change username")
        duplicate = await db.scalar(select(UserAccount.id).where(func.lower(UserAccount.email) == data.username, UserAccount.id != account.id))
        if duplicate:
            raise HTTPException(status_code=409, detail="Username already exists")
        account.email = data.username
    if data.locale:
        account.locale = data.locale
        if employee:
            employee.primary_language = data.locale
    if employee and "avatar_url" in data.model_fields_set:
        employee.metadata_json = {**(employee.metadata_json or {}), "avatar_url": data.avatar_url}
    if employee:
        for field in ("phone_number", "birthday", "work_direction", "work_branch"):
            if field in data.model_fields_set:
                setattr(employee, field, getattr(data, field))
    await db.commit()
    return {"username": account.email, "locale": account.locale, "employee_id": actor.employee_id, "name": employee.name if employee else account.email, "telegram_username": employee.telegram_username if employee else None, "avatar_url": (employee.metadata_json or {}).get("avatar_url") if employee else None, "phone_number": employee.phone_number if employee else None, "birthday": employee.birthday if employee else None, "work_direction": employee.work_direction if employee else None, "work_branch": employee.work_branch if employee else None, "telegram_connected": bool(employee and employee.telegram_id), "requires_password_setup": account.must_change_password, "roles": sorted(actor.roles)}


class ProfilePasswordChange(BaseModel):
    current_password: str | None = None
    new_password: str = Field(min_length=10, max_length=128)


@router.patch("/profile/password")
async def change_profile_password(data: ProfilePasswordChange, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    account = await db.get(UserAccount, actor.account_id, with_for_update=True)
    password_setup_required = account.must_change_password or bool(await db.scalar(select(RefreshSession.id).where(RefreshSession.account_id == account.id, RefreshSession.auth_method == "telegram", RefreshSession.revoked_at.is_(None)).limit(1)))
    if not password_setup_required and (not data.current_password or not verify_account_password(data.current_password, account.password_hash)[0]):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    account.password_hash = hash_account_password(data.new_password)
    account.must_change_password = False
    await db.execute(RefreshSession.__table__.update().where(RefreshSession.account_id == account.id, RefreshSession.revoked_at.is_(None)).values(revoked_at=datetime.now(timezone.utc)))
    await db.commit()
    return {"password_changed": True, "requires_password_setup": False}


@router.get("/workers/{employee_id}/profile")
async def worker_profile(employee_id: int, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    employee = await db.get(Employee, employee_id)
    if not employee or not employee.is_active:
        raise HTTPException(status_code=404, detail="Worker not found")
    telegram_chat_url = f"https://t.me/{employee.telegram_username.lstrip('@')}" if employee.telegram_username else (f"tg://user?id={employee.telegram_id}" if employee.telegram_id else None)
    return {"id": employee.id, "name": employee.name, "avatar_url": (employee.metadata_json or {}).get("avatar_url"), "phone_number": employee.phone_number, "birthday": employee.birthday, "work_direction": employee.work_direction, "work_branch": employee.work_branch, "telegram_username": employee.telegram_username, "telegram_connected": bool(employee.telegram_id), "telegram_chat_url": telegram_chat_url, "job_title": employee.job_title}


@router.post("/profile/telegram-link")
async def complete_telegram_link(init_data: str, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(get_actor)):
    if not actor.employee_id:
        raise HTTPException(status_code=409, detail="Link an employee profile before connecting Telegram")
    telegram_user = verify_init_data(init_data)
    telegram_id = str((telegram_user or {}).get("id") or "")
    if not telegram_id.isdigit():
        raise HTTPException(status_code=400, detail="Telegram account is missing")
    duplicate = await db.scalar(select(Employee.id).where(Employee.telegram_id == telegram_id, Employee.id != actor.employee_id))
    if duplicate:
        raise HTTPException(status_code=409, detail="This Telegram account is already connected")
    employee = await db.get(Employee, actor.employee_id, with_for_update=True)
    employee.telegram_id = telegram_id
    employee.telegram_username = telegram_user.get("username") or employee.telegram_username
    await db.commit()
    return {"telegram_connected": True, "telegram_username": employee.telegram_username}


@router.post("/accounts", response_model=AccountOut, status_code=status.HTTP_201_CREATED)
async def create_account(
    data: AccountCreate,
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_roles("admin")),
):
    allowed = {"admin", "manager", "team_lead", "member", "contractor", "client_auditor"}
    roles = sorted(set(data.roles))
    if not roles or not set(roles).issubset(allowed):
        raise HTTPException(status_code=400, detail="Invalid roles")
    if data.employee_id:
        employee = await db.get(Employee, data.employee_id)
        if not employee:
            raise HTTPException(status_code=404, detail="Employee not found")
        linked_account = await db.scalar(select(UserAccount.id).where(UserAccount.employee_id == data.employee_id))
        if linked_account:
            raise HTTPException(status_code=409, detail="Employee already has an account")
    existing = await db.scalar(select(UserAccount.id).where(func.lower(UserAccount.email) == data.email))
    if existing:
        raise HTTPException(status_code=409, detail="Email already has an account")
    account = UserAccount(
        organization_id=actor.organization_id,
        employee_id=data.employee_id,
        email=data.email,
        password_hash=hash_account_password(data.password),
        locale=data.locale,
        status="active",
        must_change_password=data.must_change_password,
    )
    db.add(account)
    await db.flush()
    for role in roles:
        db.add(RoleAssignment(account_id=account.id, role=role))
    await db.commit()
    employee = await db.get(Employee, account.employee_id) if account.employee_id else None
    return AccountOut(id=account.id, email=account.email, employee_id=account.employee_id, locale=account.locale, roles=roles, status=account.status, telegram_id=employee.telegram_id if employee else None)


@router.get("/accounts", response_model=list[AccountOut])
async def list_accounts(
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_roles("admin")),
):
    accounts = (await db.execute(select(UserAccount).where(UserAccount.organization_id == actor.organization_id).order_by(UserAccount.email))).scalars().all()
    output = []
    for account in accounts:
        roles = (await db.execute(select(RoleAssignment.role).where(RoleAssignment.account_id == account.id))).scalars().all()
        employee = await db.get(Employee, account.employee_id) if account.employee_id else None
        output.append(AccountOut(id=account.id, email=account.email, employee_id=account.employee_id, locale=account.locale, roles=sorted(set(roles)), status=account.status, telegram_id=employee.telegram_id if employee else None))
    return output


@router.patch("/accounts/{account_id}", response_model=AccountOut)
async def update_account(
    account_id: int,
    data: AccountAdminPatch,
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_roles("admin")),
):
    account = await db.get(UserAccount, account_id, with_for_update=True)
    if not account or account.organization_id != actor.organization_id:
        raise HTTPException(status_code=404, detail="Account not found")
    patch = data.model_dump(exclude_unset=True)
    username = patch.pop("username", None)
    password = patch.pop("password", None)
    roles = patch.pop("roles", None)
    if username and username != account.email:
        duplicate = await db.scalar(select(UserAccount.id).where(func.lower(UserAccount.email) == username, UserAccount.id != account.id))
        if duplicate:
            raise HTTPException(status_code=409, detail="Username already exists")
        account.email = username
    if password:
        account.password_hash = hash_account_password(password)
        account.must_change_password = False
        await db.execute(RefreshSession.__table__.update().where(RefreshSession.account_id == account.id, RefreshSession.revoked_at.is_(None)).values(revoked_at=datetime.now(timezone.utc)))
    for field, value in patch.items():
        setattr(account, field, value)
    if account.id == actor.account_id and account.status == "disabled":
        raise HTTPException(status_code=400, detail="You cannot disable your own account")
    if roles is not None:
        allowed = {"admin", "manager", "team_lead", "member", "contractor", "client_auditor"}
        roles = sorted(set(roles))
        if not roles or not set(roles).issubset(allowed):
            raise HTTPException(status_code=400, detail="Invalid roles")
        current_roles = set((await db.execute(select(RoleAssignment.role).where(RoleAssignment.account_id == account.id))).scalars().all())
        if "admin" in current_roles and "admin" not in roles:
            other_admins = await db.scalar(
                select(func.count()).select_from(RoleAssignment).join(UserAccount, UserAccount.id == RoleAssignment.account_id).where(
                    RoleAssignment.role == "admin",
                    RoleAssignment.account_id != account.id,
                    UserAccount.organization_id == actor.organization_id,
                    UserAccount.status == "active",
                )
            )
            if not other_admins:
                raise HTTPException(status_code=400, detail="At least one active administrator is required")
        await db.execute(RoleAssignment.__table__.delete().where(RoleAssignment.account_id == account.id))
        for role in roles:
            db.add(RoleAssignment(account_id=account.id, role=role))
    else:
        roles = sorted(set((await db.execute(select(RoleAssignment.role).where(RoleAssignment.account_id == account.id))).scalars().all()))
    await db.commit()
    employee = await db.get(Employee, account.employee_id) if account.employee_id else None
    return AccountOut(id=account.id, email=account.email, employee_id=account.employee_id, locale=account.locale, roles=roles, status=account.status, telegram_id=employee.telegram_id if employee else None)


@router.post("/accounts/invite", response_model=AccountOut, status_code=status.HTTP_201_CREATED)
async def invite_account(
    data: AccountInvite,
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_roles("admin")),
):
    if not settings.AUTH_EMAIL_VERIFICATION_ENABLED:
        raise HTTPException(status_code=404, detail="Email invitations are disabled; provision accounts with a password from the admin panel")
    if not email_is_configured():
        raise HTTPException(status_code=503, detail="Authentication email delivery is not configured")
    allowed = {"admin", "manager", "team_lead", "member", "contractor", "client_auditor"}
    roles = sorted(set(data.roles))
    if not roles or not set(roles).issubset(allowed):
        raise HTTPException(status_code=400, detail="Invalid roles")
    existing = await db.scalar(select(UserAccount.id).where(func.lower(UserAccount.email) == data.email))
    if existing:
        raise HTTPException(status_code=409, detail="Email already has an account")
    account = UserAccount(
        organization_id=actor.organization_id,
        employee_id=data.employee_id,
        email=data.email,
        password_hash=hash_account_password(secrets.token_urlsafe(48)),
        locale=data.locale,
        status="invited",
        must_change_password=True,
    )
    db.add(account)
    await db.flush()
    for role in roles:
        db.add(RoleAssignment(account_id=account.id, role=role))
    await _issue_action_token(db, account, "invitation")
    await db.commit()
    return AccountOut(id=account.id, email=account.email, employee_id=account.employee_id, locale=account.locale, roles=roles, status=account.status)


@router.post("/password-reset/request", status_code=status.HTTP_202_ACCEPTED)
async def request_password_reset(data: PasswordResetRequest, db: AsyncSession = Depends(get_db)):
    if not settings.AUTH_EMAIL_VERIFICATION_ENABLED:
        return {"message": "Email password reset is disabled. Use the predefined administrator credentials or change the password from the admin panel."}
    account = (
        await db.execute(select(UserAccount).where(func.lower(UserAccount.email) == data.email))
    ).scalar_one_or_none()
    if account and account.status != "disabled" and email_is_configured():
        await _issue_action_token(db, account, "password_reset")
        await db.commit()
    return {"message": "If that account exists, a secure password link will be sent."}


@router.post("/password-reset/confirm", status_code=status.HTTP_204_NO_CONTENT)
async def confirm_password_reset(data: PasswordResetConfirm, db: AsyncSession = Depends(get_db)):
    now = datetime.now(timezone.utc)
    token_hash = hashlib.sha256(data.token.encode()).hexdigest()
    token = (
        await db.execute(
            select(PasswordResetToken)
            .where(
                PasswordResetToken.token_hash == token_hash,
                PasswordResetToken.used_at.is_(None),
                PasswordResetToken.expires_at > now,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if not token:
        raise HTTPException(status_code=400, detail="Password link is invalid or expired")
    account = await db.get(UserAccount, token.account_id, with_for_update=True)
    if not account or account.status == "disabled":
        raise HTTPException(status_code=400, detail="Password link is invalid or expired")
    account.password_hash = hash_account_password(data.new_password)
    account.must_change_password = False
    account.status = "active"
    account.failed_login_count = 0
    account.locked_until = None
    token.used_at = now
    await db.execute(
        RefreshSession.__table__.update()
        .where(RefreshSession.account_id == account.id, RefreshSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    await db.commit()


@router.put("/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    data: PasswordChange,
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    account = await db.get(UserAccount, actor.account_id)
    valid, _ = verify_account_password(data.current_password, account.password_hash)
    if not valid:
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    account.password_hash = hash_account_password(data.new_password)
    account.must_change_password = False
    await db.execute(
        RefreshSession.__table__.update()
        .where(RefreshSession.account_id == account.id, RefreshSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )
    await db.commit()
