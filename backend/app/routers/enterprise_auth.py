import hashlib
import secrets
import hmac
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Response, status
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
from app.models.models import Employee, JobQueue, ManagerSettings, Organization, PasswordResetToken, RefreshSession, RoleAssignment, UserAccount
from app.services.manager_recipients import manager_telegram_ids
from app.services.email_service import email_is_configured
from app.services.secret_box import encrypt_secret


router = APIRouter()
REFRESH_COOKIE = "oyuns_refresh"


class LoginInput(BaseModel):
    email: str
    password: str
    device_label: str | None = Field(default=None, max_length=200)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class TelegramWidgetLogin(BaseModel):
    id: int
    first_name: str = ""
    last_name: str | None = None
    username: str | None = None
    photo_url: str | None = None
    auth_date: int
    hash: str


class AccessTokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class AccountOut(BaseModel):
    id: int
    email: str
    employee_id: int | None
    locale: str
    roles: list[str]
    status: str


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


def _access(account: UserAccount) -> AccessTokenOut:
    return AccessTokenOut(
        access_token=create_enterprise_access_token(account.id, account.organization_id),
        expires_in=settings.ENTERPRISE_ACCESS_TOKEN_MINUTES * 60,
    )


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


@router.post("/login", response_model=AccessTokenOut)
async def login(data: LoginInput, response: Response, db: AsyncSession = Depends(get_db)):
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
    _set_refresh_cookie(response, refresh_token, refresh_expires_at)
    return _access(account)


async def _telegram_session(response: Response, db: AsyncSession, telegram_id: str, username: str | None, device_label: str):
    """Link a registered Telegram identity and issue the one-year session."""
    telegram_user = {"id": telegram_id, "username": username} if username else {"id": telegram_id}
    if not telegram_user or not telegram_id.isdigit():
        raise HTTPException(status_code=401, detail="Invalid Telegram login")

    employee = await db.scalar(select(Employee).where(Employee.telegram_id == telegram_id))
    if employee is None and telegram_user.get("username"):
        username = str(telegram_user["username"]).lstrip("@")
        employee = await db.scalar(select(Employee).where(Employee.telegram_username.ilike(username)))
        if employee and employee.telegram_id != telegram_id:
            employee.telegram_id = telegram_id
    if not employee or not employee.is_active:
        raise HTTPException(status_code=403, detail="Telegram user is not registered as an active employee")

    manager_settings = (await db.execute(select(ManagerSettings))).scalars().first()
    is_manager = telegram_id == str(settings.MANAGER_TG_ID) or telegram_id in manager_telegram_ids(manager_settings)
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
            password_hash=hash_account_password(secrets.token_urlsafe(48)),
            status="active",
            locale=employee.primary_language or "mn",
        )
        db.add(account)
        await db.flush()

    if account.status == "disabled":
        raise HTTPException(status_code=403, detail="Account is disabled")
    account.status = "active"
    account.failed_login_count = 0
    account.locked_until = None
    account.last_login_at = datetime.now(timezone.utc)
    roles = (await db.execute(select(RoleAssignment.role).where(RoleAssignment.account_id == account.id))).scalars().all()
    if not roles:
        db.add(RoleAssignment(account_id=account.id, role="manager" if is_manager else "member"))
    elif is_manager and "manager" not in roles:
        db.add(RoleAssignment(account_id=account.id, role="manager"))

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
    _set_refresh_cookie(response, refresh_token, refresh_expires_at)
    return _access(account)


@router.post("/telegram", response_model=AccessTokenOut)
async def telegram_login(
    response: Response,
    db: AsyncSession = Depends(get_db),
    x_telegram_init_data: str | None = Header(default=None),
):
    """Exchange verified Telegram Mini App data for a durable web session."""
    telegram_user = verify_init_data(x_telegram_init_data or "")
    telegram_id = str((telegram_user or {}).get("id") or "")
    if not telegram_user or not telegram_id.isdigit():
        raise HTTPException(status_code=401, detail="Invalid Telegram login")
    return await _telegram_session(response, db, telegram_id, telegram_user.get("username"), "telegram-mini-app")


@router.post("/telegram-widget", response_model=AccessTokenOut)
async def telegram_widget_login(data: TelegramWidgetLogin, response: Response, db: AsyncSession = Depends(get_db)):
    """Verify the browser Login Widget payload and issue the same session."""
    if not settings.BOT_TOKEN:
        raise HTTPException(status_code=503, detail="Telegram authentication is not configured")
    if abs(datetime.now(timezone.utc).timestamp() - data.auth_date) > 86400:
        raise HTTPException(status_code=401, detail="Telegram login has expired")
    payload = data.model_dump(exclude={"hash"}, exclude_none=True)
    check_string = "\n".join(f"{key}={value}" for key, value in sorted(payload.items()))
    secret_key = hashlib.sha256(settings.BOT_TOKEN.encode()).digest()
    expected = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, data.hash):
        raise HTTPException(status_code=401, detail="Invalid Telegram login")
    return await _telegram_session(response, db, str(data.id), data.username, "telegram-login-widget")


@router.post("/refresh", response_model=AccessTokenOut)
async def refresh(
    response: Response,
    oyuns_refresh: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    if not oyuns_refresh:
        raise HTTPException(status_code=401, detail="Refresh session required")
    now = datetime.now(timezone.utc)
    session = (
        await db.execute(
            select(RefreshSession).where(
                RefreshSession.token_hash == hash_refresh_token(oyuns_refresh),
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
    _set_refresh_cookie(response, token, expires_at)
    return _access(account)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    oyuns_refresh: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    if oyuns_refresh:
        session = (
            await db.execute(select(RefreshSession).where(RefreshSession.token_hash == hash_refresh_token(oyuns_refresh)))
        ).scalar_one_or_none()
        if session and not session.revoked_at:
            session.revoked_at = datetime.now(timezone.utc)
            await db.commit()
    response.delete_cookie(REFRESH_COOKIE, path="/api/v1/auth")


@router.get("/me", response_model=AccountOut)
async def me(actor: ActorContext = Depends(get_actor)):
    return AccountOut(id=actor.account_id, email=actor.email, employee_id=actor.employee_id, locale=actor.locale, roles=sorted(actor.roles), status="active")


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
    return AccountOut(id=account.id, email=account.email, employee_id=account.employee_id, locale=account.locale, roles=roles, status=account.status)


@router.get("/accounts", response_model=list[AccountOut])
async def list_accounts(
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_roles("admin")),
):
    accounts = (await db.execute(select(UserAccount).where(UserAccount.organization_id == actor.organization_id).order_by(UserAccount.email))).scalars().all()
    output = []
    for account in accounts:
        roles = (await db.execute(select(RoleAssignment.role).where(RoleAssignment.account_id == account.id))).scalars().all()
        output.append(AccountOut(id=account.id, email=account.email, employee_id=account.employee_id, locale=account.locale, roles=sorted(set(roles)), status=account.status))
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
        await db.execute(RoleAssignment.__table__.delete().where(RoleAssignment.account_id == account.id))
        for role in roles:
            db.add(RoleAssignment(account_id=account.id, role=role))
    else:
        roles = sorted(set((await db.execute(select(RoleAssignment.role).where(RoleAssignment.account_id == account.id))).scalars().all()))
    await db.commit()
    return AccountOut(id=account.id, email=account.email, employee_id=account.employee_id, locale=account.locale, roles=roles, status=account.status)


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
