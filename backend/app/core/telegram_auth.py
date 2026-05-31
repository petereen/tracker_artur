"""Валидация Telegram Mini App initData (подпись HMAC по BOT_TOKEN)."""
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


def verify_init_data(init_data: str) -> Optional[dict]:
    """Проверяет подпись initData. Возвращает dict telegram-пользователя или None."""
    if not init_data or not settings.BOT_TOKEN:
        return None
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    except Exception:
        return None

    received_hash = pairs.pop("hash", None)
    if not received_hash:
        return None

    data_check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret_key = hmac.new(b"WebAppData", settings.BOT_TOKEN.encode(), hashlib.sha256).digest()
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
