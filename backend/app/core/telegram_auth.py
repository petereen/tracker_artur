"""Валидация Telegram Mini App initData (подпись HMAC по токену бота).

Each tenant has its own bot, so initData is signed with *that* bot's token.
``verify_tenant_init_data`` tries the known bots and also reports which
tenant the signing bot belongs to; on a tenant host only that tenant's bots
are tried.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Optional
from urllib.parse import parse_qsl

from app.core.config import settings

# initData считается протухшим спустя это время (защита от replay)
MAX_AUTH_AGE_SEC = 24 * 3600


def _verify_with_token(init_data: str, bot_token: str) -> Optional[dict]:
    if not init_data or not bot_token:
        return None
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    except Exception:
        return None

    received_hash = pairs.pop("hash", None)
    if not received_hash:
        return None

    data_check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    calc_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc_hash, received_hash):
        return None

    auth_date = pairs.get("auth_date")
    if auth_date and auth_date.isdigit():
        if time.time() - int(auth_date) > MAX_AUTH_AGE_SEC:
            return None

    user_raw = pairs.get("user")
    if not user_raw:
        return None
    try:
        return json.loads(user_raw)
    except Exception:
        return None


def verify_init_data(init_data: str) -> Optional[dict]:
    """Проверяет подпись initData платформенного бота (BOT_TOKEN)."""
    return _verify_with_token(init_data, settings.BOT_TOKEN)


async def verify_tenant_init_data(init_data: str) -> tuple[Optional[dict], Optional[int]]:
    """Verify initData against every tenant bot → ``(telegram user, tenant id)``."""
    from app.core.tenancy import current_tenant_id
    from app.services.telegram_bots import registry

    if not init_data:
        return None, None
    host_tenant = current_tenant_id()
    try:
        bots = await registry.bots()
    except Exception:  # pragma: no cover - registry outage falls back to the platform bot
        bots = []
    for bot in bots:
        if host_tenant is not None and bot.organization_id != host_tenant:
            continue
        user = _verify_with_token(init_data, bot.token)
        if user is not None:
            return user, bot.organization_id
    if not bots:
        return verify_init_data(init_data), None
    return None, None
