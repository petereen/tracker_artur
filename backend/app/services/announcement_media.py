"""Images attached to news & announcements.

Every upload is decoded and re-encoded (metadata such as EXIF/GPS is dropped,
oversized pictures are scaled down), then stored under an unguessable name.
Like avatars, the files are served by that name so plain ``<img>`` tags work.
"""
from __future__ import annotations

import io
import re
import secrets
from pathlib import Path

import aiofiles
from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.config import settings
from app.services.malware_scanner import scan_upload

ALLOWED_TYPES = {"image/png", "image/jpeg", "image/webp"}
MEDIA_URL_PREFIX = "/api/v1/announcements/media/"
MEDIA_TYPES = {"jpg": "image/jpeg", "png": "image/png"}
_NAME = re.compile(r"^[A-Za-z0-9_-]{16,64}\.(jpg|png)$")


class InvalidAnnouncementImage(ValueError):
    pass


def media_url(name: str) -> str:
    return f"{MEDIA_URL_PREFIX}{name}"


def is_media_url(value: str) -> bool:
    """True for a URL this module issued (the only image sources a post may use)."""
    return value.startswith(MEDIA_URL_PREFIX) and bool(_NAME.match(value[len(MEDIA_URL_PREFIX):]))


def encode_image(content: bytes, content_type: str) -> tuple[bytes, str, int, int]:
    """Validate and normalise an upload → ``(bytes, extension, width, height)``."""
    if content_type not in ALLOWED_TYPES:
        raise InvalidAnnouncementImage("Image must be PNG, JPEG, or WebP")
    if not content or len(content) > settings.ANNOUNCEMENT_IMAGE_MAX_BYTES:
        raise InvalidAnnouncementImage(f"Image exceeds the {settings.ANNOUNCEMENT_IMAGE_MAX_BYTES // (1024 * 1024)} MB size limit")
    try:
        Image.open(io.BytesIO(content)).verify()
        source = Image.open(io.BytesIO(content))
        if getattr(source, "n_frames", 1) != 1:
            raise InvalidAnnouncementImage("Animated images are not allowed")
        source = ImageOps.exif_transpose(source)
        limit = settings.ANNOUNCEMENT_IMAGE_MAX_PIXELS
        source.thumbnail((limit, limit), Image.LANCZOS)
        has_alpha = source.mode in {"RGBA", "LA"} or (source.mode == "P" and "transparency" in source.info)
        output = io.BytesIO()
        if has_alpha:
            source.convert("RGBA").save(output, format="PNG", optimize=True)
            extension = "png"
        else:
            source.convert("RGB").save(output, format="JPEG", quality=86, optimize=True)
            extension = "jpg"
        width, height = source.size
    except InvalidAnnouncementImage:
        raise
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError) as exc:
        raise InvalidAnnouncementImage("Image is malformed") from exc
    return output.getvalue(), extension, width, height


async def save_image(content: bytes, content_type: str) -> tuple[str, int, int, int]:
    """Store an upload → ``(file name, width, height, stored size)``."""
    encoded, extension, width, height = encode_image(content, content_type)
    await scan_upload(content)
    root = Path(settings.ANNOUNCEMENT_IMAGE_DIR).resolve()
    root.mkdir(parents=True, exist_ok=True)
    name = f"{secrets.token_urlsafe(24)}.{extension}"
    async with aiofiles.open(root / name, "xb") as handle:
        await handle.write(encoded)
    return name, width, height, len(encoded)


async def read_image(name: str) -> tuple[bytes, str]:
    if not _NAME.match(name or ""):
        raise FileNotFoundError
    root = Path(settings.ANNOUNCEMENT_IMAGE_DIR).resolve()
    path = (root / name).resolve()
    if root not in path.parents:
        raise FileNotFoundError
    async with aiofiles.open(path, "rb") as handle:
        return await handle.read(), MEDIA_TYPES[name.rsplit(".", 1)[1]]
