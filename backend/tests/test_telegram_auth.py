import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

from app.core.config import settings
from app.core.telegram_auth import verify_init_data


def _make_init_data(user: dict, token: str, auth_date: int | None = None) -> str:
    data = {
        "auth_date": str(auth_date or int(time.time())),
        "user": json.dumps(user, separators=(",", ":")),
    }
    dcs = "\n".join(f"{k}={data[k]}" for k in sorted(data))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    h = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    return urlencode({**data, "hash": h})


def test_valid_init_data_returns_user():
    init = _make_init_data({"id": 111, "first_name": "Тест"}, settings.BOT_TOKEN)
    user = verify_init_data(init)
    assert user is not None
    assert user["id"] == 111


def test_tampered_hash_rejected():
    init = _make_init_data({"id": 111}, settings.BOT_TOKEN)
    tampered = init.replace("id%22%3A111", "id%22%3A999") if "id%22%3A111" in init else init + "&x=1"
    assert verify_init_data(tampered) is None


def test_wrong_token_rejected():
    init = _make_init_data({"id": 111}, "some-other-token")
    assert verify_init_data(init) is None


def test_stale_auth_date_rejected():
    init = _make_init_data({"id": 111}, settings.BOT_TOKEN, auth_date=1)  # 1970
    assert verify_init_data(init) is None


def test_empty_returns_none():
    assert verify_init_data("") is None
