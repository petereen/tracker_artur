"""Per-tenant Telegram bots (docs/multi-tenancy.md → "Telegram bots").

Every tenant connects its own BotFather bot in Settings → Интеграци. The
handshake has two halves:

1. the API checks the token with ``getMe`` and stores it encrypted
   (``status = pending``);
2. the bot runner starts polling the new bot within seconds, and the tenant
   admin opens ``t.me/<bot>?start=oyuns-<code>``. The ``/start`` reaches the
   runner through *that* bot, which proves both ends see each other, and the
   bot turns ``active``.

Only ``active`` bots deliver notifications; ``pending`` ones are polled only
so the handshake can arrive. The primary tenant keeps the platform bot from
``BOT_TOKEN`` until it connects a bot of its own.

The registry below is shared by the API (Mini App ``initData`` checks) and
the bot runner (polling, per-tenant senders). Loads always run in the system
context: a tenant-bound caller must still see every bot to route correctly.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import select

from app.core.config import settings
from app.core.tenancy import system_scope
from app.services.secret_box import decrypt_secret, encrypt_secret

log = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"
HANDSHAKE_PREFIX = "oyuns-"
HANDSHAKE_TTL = timedelta(hours=24)
REGISTRY_TTL_SECONDS = 20
# A bot counts as "online" while the runner reported it within this window.
ONLINE_WINDOW = timedelta(minutes=2)
TOKEN_PATTERN = re.compile(r"^(\d{5,16}):[A-Za-z0-9_-]{30,64}$")
POLLED_STATUSES = ("pending", "active")


class TelegramBotError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class BotIdentity:
    id: int
    username: str | None
    name: str | None


@dataclass(frozen=True)
class TenantBot:
    organization_id: int
    bot_id: int
    token: str
    username: str | None
    status: str
    # ``tenant`` = connected in settings, ``platform`` = BOT_TOKEN (primary only)
    source: str

    @property
    def delivers(self) -> bool:
        return self.status == "active"


def token_bot_id(token: str | None) -> int | None:
    match = TOKEN_PATTERN.match((token or "").strip())
    return int(match.group(1)) if match else None


def token_sha256(token: str) -> str:
    return hashlib.sha256(token.strip().encode()).hexdigest()


def platform_bot_token() -> str:
    return (settings.BOT_TOKEN or "").strip()


def mask_token(token: str) -> str:
    bot_id = token_bot_id(token)
    return f"{bot_id}:…{token.strip()[-4:]}" if bot_id else "…"


async def fetch_bot_identity(token: str) -> BotIdentity:
    """``getMe`` — proves the token is live and names the bot."""
    token = token.strip()
    if not TOKEN_PATTERN.match(token):
        raise TelegramBotError("invalid_token", "BotFather-ийн токены хэлбэр буруу байна (жишээ: 123456789:AA…).")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{TELEGRAM_API}/bot{token}/getMe")
    except httpx.HTTPError as exc:
        raise TelegramBotError("telegram_unavailable", "Telegram-тай холбогдож чадсангүй. Дахин оролдоно уу.", 503) from exc
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if response.status_code == 401 or payload.get("error_code") == 401:
        raise TelegramBotError("token_rejected", "Telegram энэ токеныг хүлээн авсангүй. BotFather-аас шинэ токен авна уу.")
    result = payload.get("result") if payload.get("ok") else None
    if not isinstance(result, dict) or not result.get("is_bot"):
        raise TelegramBotError("telegram_unavailable", "Telegram-ын хариу ойлгомжгүй байна. Дахин оролдоно уу.", 503)
    if int(result["id"]) != token_bot_id(token):
        raise TelegramBotError("invalid_token", "Токен ботын дугаартай таарахгүй байна.")
    return BotIdentity(id=int(result["id"]), username=result.get("username"), name=result.get("first_name"))


# ── Registry ───────────────────────────────────────────────────────────────
def _decrypt(row) -> str | None:
    try:
        return decrypt_secret(row.token_enc)
    except ValueError:
        log.error("telegram_bots.undecryptable_token organization=%s bot=%s", row.organization_id, row.bot_id)
        return None


def _build(rows: list[Any], primary_id: int | None) -> list[TenantBot]:
    bots: list[TenantBot] = []
    for row in rows:
        token = _decrypt(row)
        if token:
            bots.append(TenantBot(row.organization_id, int(row.bot_id), token, row.bot_username, row.status, "tenant"))
    platform_token = platform_bot_token()
    platform_id = token_bot_id(platform_token)
    if primary_id is not None and platform_id is not None:
        primary_has_bot = any(bot.organization_id == primary_id for bot in bots)
        platform_taken = any(bot.bot_id == platform_id for bot in bots)
        if not primary_has_bot and not platform_taken:
            bots.append(TenantBot(primary_id, platform_id, platform_token, None, "active", "platform"))
    return bots


class BotRegistry:
    """TTL-cached list of polled bots (tenant bots + the platform fallback)."""

    def __init__(self) -> None:
        self._bots: list[TenantBot] = []
        self._loaded_at: float | None = None

    def _fresh(self) -> bool:
        return self._loaded_at is not None and time.monotonic() - self._loaded_at < REGISTRY_TTL_SECONDS

    def _store(self, bots: list[TenantBot]) -> list[TenantBot]:
        self._bots = bots
        self._loaded_at = time.monotonic()
        return bots

    def load_sync(self) -> list[TenantBot]:
        from app.bot.db import get_session
        from app.models.models import Organization
        from app.models.platform import TenantTelegramBot

        with system_scope(), get_session() as s:
            rows = s.execute(select(TenantTelegramBot).where(TenantTelegramBot.status.in_(POLLED_STATUSES))).scalars().all()
            primary_id = s.execute(select(Organization.id).where(Organization.is_primary.is_(True))).scalar_one_or_none()
        return self._store(_build(list(rows), primary_id))

    async def load(self) -> list[TenantBot]:
        from app.core.database import AsyncSessionLocal
        from app.models.models import Organization
        from app.models.platform import TenantTelegramBot

        with system_scope():
            async with AsyncSessionLocal() as db:
                rows = (await db.execute(select(TenantTelegramBot).where(TenantTelegramBot.status.in_(POLLED_STATUSES)))).scalars().all()
                primary_id = await db.scalar(select(Organization.id).where(Organization.is_primary.is_(True)))
        return self._store(_build(list(rows), primary_id))

    def bots_sync(self) -> list[TenantBot]:
        return self._bots if self._fresh() else self.load_sync()

    async def bots(self) -> list[TenantBot]:
        return self._bots if self._fresh() else await self.load()

    def for_organization_sync(self, organization_id: int | None, *, delivering: bool = True) -> TenantBot | None:
        if organization_id is None:
            return None
        for bot in self.bots_sync():
            if bot.organization_id == organization_id and (bot.delivers or not delivering):
                return bot
        return None

    def for_bot_id_sync(self, bot_id: int) -> TenantBot | None:
        return next((bot for bot in self.bots_sync() if bot.bot_id == bot_id), None)

    def invalidate(self) -> None:
        self._loaded_at = None


registry = BotRegistry()


async def organization_has_bot(db, organization_id: int) -> bool:
    """Whether a tenant can reach workers on Telegram (gates Telegram ID fields)."""
    from app.models.models import Organization
    from app.models.platform import TenantTelegramBot

    status = await db.scalar(select(TenantTelegramBot.status).where(TenantTelegramBot.organization_id == organization_id))
    if status is not None:
        return status == "active"
    if not platform_bot_token():
        return False
    return bool(await db.scalar(select(Organization.is_primary).where(Organization.id == organization_id)))


async def _bot_owner(bot_id: int) -> int | None:
    """Tenant that already owns ``bot_id`` (RLS would hide another tenant's row)."""
    from app.core.database import AsyncSessionLocal
    from app.models.platform import TenantTelegramBot

    with system_scope():
        async with AsyncSessionLocal() as db:
            return await db.scalar(select(TenantTelegramBot.organization_id).where(TenantTelegramBot.bot_id == bot_id))


async def connect_tenant_bot(db, organization, token: str, *, account_id: int | None):
    """Verify a BotFather token and (re)attach it to ``organization`` as pending."""
    from app.models.platform import TenantTelegramBot

    token = token.strip()
    identity = await fetch_bot_identity(token)
    if identity.id == token_bot_id(platform_bot_token()) and not organization.is_primary:
        raise TelegramBotError("bot_reserved", "Энэ бот платформын үндсэн бот тул өөр байгууллагад холбогдохгүй.", 409)
    owner = await _bot_owner(identity.id)
    if owner is not None and owner != organization.id:
        raise TelegramBotError("bot_in_use", "Энэ бот өөр байгууллагад холбогдсон байна. BotFather-аар шинэ бот үүсгэнэ үү.", 409)
    row = await db.scalar(select(TenantTelegramBot).where(TenantTelegramBot.organization_id == organization.id).with_for_update())
    if row is None:
        row = TenantTelegramBot(organization_id=organization.id)
        db.add(row)
    row.bot_id = identity.id
    row.bot_username = identity.username
    row.bot_name = identity.name
    row.token_enc = encrypt_secret(token)
    row.token_sha256 = token_sha256(token)
    row.status = "pending"
    row.handshake_completed_at = None
    row.handshake_telegram_id = None
    row.last_seen_at = None
    row.last_error = None
    row.connected_by_account_id = account_id
    issue_handshake(row)
    await db.flush()
    registry.invalidate()
    return row


_platform_identity: tuple[float, BotIdentity | None] | None = None


async def platform_bot_identity() -> BotIdentity | None:
    """``getMe`` of the platform bot, cached for an hour (display only)."""
    global _platform_identity
    token = platform_bot_token()
    if not token:
        return None
    if _platform_identity and time.monotonic() - _platform_identity[0] < 3600:
        return _platform_identity[1]
    try:
        identity = await fetch_bot_identity(token)
    except TelegramBotError:
        identity = None
    _platform_identity = (time.monotonic(), identity)
    return identity


async def bot_username_for(db, organization_id: int) -> str | None:
    """@username of the bot a tenant's workers talk to (for deep links)."""
    from app.models.models import Organization
    from app.models.platform import TenantTelegramBot

    row = await db.scalar(select(TenantTelegramBot).where(TenantTelegramBot.organization_id == organization_id))
    if row is not None:
        return row.bot_username if row.status == "active" else None
    if not await db.scalar(select(Organization.is_primary).where(Organization.id == organization_id)):
        return None
    configured = settings.TELEGRAM_BOT_USERNAME.strip().lstrip("@")
    if configured:
        return configured
    identity = await platform_bot_identity()
    return identity.username if identity else None


async def require_bot_for_telegram_id(db, organization_id: int, telegram_id: str | None) -> None:
    """A worker's Telegram ID is only useful (and accepted) once a bot is live."""
    if telegram_id and not await organization_has_bot(db, organization_id):
        raise TelegramBotError(
            "telegram_bot_not_connected",
            "Telegram бот холбогдоогүй тул Telegram ID оруулах боломжгүй. Тохиргоо → Интеграци хэсэгт ботоо холбоно уу.",
            409,
        )


# ── Handshake ──────────────────────────────────────────────────────────────
def new_handshake_code() -> str:
    # Telegram deep-link payloads allow [A-Za-z0-9_-], at most 64 characters.
    return secrets.token_urlsafe(18)


def handshake_payload(code: str) -> str:
    return f"{HANDSHAKE_PREFIX}{code}"


def handshake_url(username: str | None, code: str) -> str | None:
    return f"https://t.me/{username}?start={handshake_payload(code)}" if username else None


def read_handshake_code(row) -> str | None:
    if not row.handshake_code_enc:
        return None
    try:
        return decrypt_secret(row.handshake_code_enc)
    except ValueError:
        return None


def issue_handshake(row, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    code = new_handshake_code()
    row.handshake_code_enc = encrypt_secret(code)
    row.handshake_expires_at = now + HANDSHAKE_TTL
    return code


def complete_handshake_sync(bot_id: int, code: str, telegram_user) -> tuple[str | None, str | None]:
    """Consume ``/start oyuns-<code>`` received by ``bot_id``.

    Returns ``(error, linked_employee_name)``. Also links the connecting
    admin's worker profile to this Telegram account when it has none yet.
    """
    from app.bot.db import get_session
    from app.models.models import Employee, UserAccount
    from app.models.platform import TenantTelegramBot

    now = datetime.now(timezone.utc)
    telegram_id = str(getattr(telegram_user, "id", "") or "")
    with system_scope(), get_session() as s:
        row = s.execute(select(TenantTelegramBot).where(TenantTelegramBot.bot_id == bot_id).with_for_update()).scalar_one_or_none()
        if row is None:
            return "not_found", None
        expected = read_handshake_code(row)
        if not expected or not hmac.compare_digest(expected.encode(), code.encode()):
            return "invalid", None
        if row.handshake_expires_at and row.handshake_expires_at < now:
            return "expired", None
        row.status = "active"
        row.handshake_completed_at = now
        row.handshake_telegram_id = telegram_id or None
        row.handshake_code_enc = None
        row.handshake_expires_at = None
        row.last_error = None
        linked_name = None
        if telegram_id.isdigit() and row.connected_by_account_id:
            account = s.get(UserAccount, row.connected_by_account_id)
            employee = s.get(Employee, account.employee_id) if account and account.employee_id else None
            taken = s.execute(select(Employee.id).where(Employee.telegram_id == telegram_id)).scalar_one_or_none()
            if employee and employee.organization_id == row.organization_id and not employee.telegram_id and not taken:
                employee.telegram_id = telegram_id
                employee.telegram_username = getattr(telegram_user, "username", None) or employee.telegram_username
                linked_name = employee.name
        s.commit()
    registry.invalidate()
    return None, linked_name


# ── Runner bookkeeping ────────────────────────────────────────────────────
def record_bot_seen_sync(bot_ids: list[int]) -> None:
    if not bot_ids:
        return
    from app.bot.db import get_session
    from app.models.platform import TenantTelegramBot

    now = datetime.now(timezone.utc)
    with system_scope(), get_session() as s:
        s.execute(
            TenantTelegramBot.__table__.update()
            .where(TenantTelegramBot.bot_id.in_(bot_ids))
            .values(last_seen_at=now, last_error=None)
        )
        s.commit()


def record_bot_error_sync(bot_id: int, message: str, *, disable: bool = False) -> None:
    from app.bot.db import get_session
    from app.models.platform import TenantTelegramBot

    values: dict[str, Any] = {"last_error": message[:500]}
    if disable:
        values["status"] = "error"
    with system_scope(), get_session() as s:
        s.execute(TenantTelegramBot.__table__.update().where(TenantTelegramBot.bot_id == bot_id).values(**values))
        s.commit()
    if disable:
        registry.invalidate()


# ── Tenant URLs ───────────────────────────────────────────────────────────
def _tenant_base_url(slug: str | None, is_primary: bool, custom_host: str | None) -> str:
    if custom_host:
        return f"https://{custom_host}"
    base = settings.TENANT_BASE_DOMAIN.strip().strip(".")
    if base and slug and not is_primary:
        return f"https://{slug}.{base}"
    return settings.PUBLIC_APP_URL.rstrip("/")


def tenant_app_url_sync(organization_id: int | None) -> str:
    """Public web address of a tenant (custom domain > subdomain > shared host)."""
    if organization_id is None:
        return settings.PUBLIC_APP_URL.rstrip("/")
    from app.bot.db import get_session
    from app.models.models import Organization
    from app.models.platform import TenantDomain

    with system_scope(), get_session() as s:
        organization = s.get(Organization, organization_id)
        if organization is None:
            return settings.PUBLIC_APP_URL.rstrip("/")
        host = s.execute(
            select(TenantDomain.hostname)
            .where(TenantDomain.organization_id == organization_id, TenantDomain.verified_at.is_not(None))
            .order_by(TenantDomain.id)
            .limit(1)
        ).scalar_one_or_none()
        return _tenant_base_url(organization.slug, bool(organization.is_primary), host)


def mini_app_url_sync(organization_id: int | None) -> str:
    """Mini App address for a tenant's bot. The primary tenant keeps MINI_APP_URL."""
    from app.bot.db import get_session
    from app.models.models import Organization

    if organization_id is not None:
        with system_scope(), get_session() as s:
            organization = s.get(Organization, organization_id)
            is_primary = bool(organization and organization.is_primary)
        if not is_primary:
            return f"{tenant_app_url_sync(organization_id)}/tg"
    return settings.MINI_APP_URL.strip()
