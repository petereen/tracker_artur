from __future__ import annotations

import io
import secrets
from pathlib import Path

import aiofiles
from PIL import Image, UnidentifiedImageError

from app.core.config import settings
from app.services.malware_scanner import scan_upload

ALLOWED_TYPES = {"image/png", "image/jpeg", "image/webp"}


class InvalidAvatar(ValueError):
    pass


async def save_avatar(content: bytes, content_type: str) -> tuple[str, int, int, int]:
    if content_type not in ALLOWED_TYPES:
        raise InvalidAvatar("Avatar must be PNG, JPEG, or WebP")
    if not content or len(content) > settings.AVATAR_MAX_BYTES:
        raise InvalidAvatar("Avatar exceeds the 2 MB size limit")
    await scan_upload(content)
    try:
        source = Image.open(io.BytesIO(content))
        source.verify()
        source = Image.open(io.BytesIO(content))
        if getattr(source, "n_frames", 1) != 1:
            raise InvalidAvatar("Animated avatars are not allowed")
        width, height = source.size
        if width > settings.AVATAR_MAX_PIXELS or height > settings.AVATAR_MAX_PIXELS:
            raise InvalidAvatar(f"Avatar dimensions must not exceed {settings.AVATAR_MAX_PIXELS}×{settings.AVATAR_MAX_PIXELS}")
        clean = source.convert("RGBA")
        output = io.BytesIO()
        clean.save(output, format="PNG", optimize=True)
        encoded = output.getvalue()
    except InvalidAvatar:
        raise
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError) as exc:
        raise InvalidAvatar("Avatar image is malformed") from exc
    token = secrets.token_urlsafe(24)
    root = Path(settings.AVATAR_UPLOAD_DIR).resolve()
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{token}.png"
    async with aiofiles.open(path, "xb") as handle:
        await handle.write(encoded)
    return token, width, height, len(encoded)


async def read_avatar(token: str) -> bytes:
    if not token or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for char in token):
        raise FileNotFoundError
    root = Path(settings.AVATAR_UPLOAD_DIR).resolve()
    path = (root / f"{token}.png").resolve()
    if root not in path.parents:
        raise FileNotFoundError
    async with aiofiles.open(path, "rb") as handle:
        return await handle.read()
