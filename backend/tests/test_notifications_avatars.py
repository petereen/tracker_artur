import asyncio
import io
from pathlib import Path

import pytest
from PIL import Image

from app.core.config import settings
from app.models.models import NotificationOutbox, UserNotification
from app.services.avatar_storage import InvalidAvatar, read_avatar, save_avatar


def _png(size: tuple[int, int]) -> bytes:
    output = io.BytesIO()
    Image.new("RGBA", size, (40, 120, 220, 255)).save(output, format="PNG")
    return output.getvalue()


def test_notification_schema_links_web_and_telegram_delivery():
    assert "recipient_account_id" in UserNotification.__table__.c
    assert "read_at" in UserNotification.__table__.c
    assert "telegram_status" in UserNotification.__table__.c
    assert "user_notification_id" in NotificationOutbox.__table__.c


def test_avatar_accepts_exact_limit_and_strips_to_png(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "AVATAR_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "CLAMAV_ENABLED", False)
    token, width, height, size = asyncio.run(save_avatar(_png((256, 256)), "image/png"))
    stored = asyncio.run(read_avatar(token))
    assert (width, height) == (256, 256)
    assert size == len(stored)
    assert stored.startswith(b"\x89PNG")


def test_avatar_rejects_oversized_or_malformed_content(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "AVATAR_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "CLAMAV_ENABLED", False)
    with pytest.raises(InvalidAvatar, match="256×256"):
        asyncio.run(save_avatar(_png((257, 256)), "image/png"))
    with pytest.raises(InvalidAvatar, match="malformed"):
        asyncio.run(save_avatar(b"not-an-image", "image/png"))
