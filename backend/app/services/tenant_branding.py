"""Tenant branding: company name, logo, favicon and theme colours.

``organizations.branding`` holds the operator/tenant-admin editable values.
Logos uploaded from Settings → Profile (``settings["branding"]`` light/dark)
remain the fallback, so existing branding keeps working unchanged.
"""

from __future__ import annotations

import base64
import binascii
import re

from pydantic import BaseModel, Field, field_validator

HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
LEGACY_LOGOS = {"legacy-aio": "/oyuns-aio-logo.png", "legacy-icon": "/favicon.png"}
DEFAULT_FAVICON = "/favicon.png"
BRANDING_FIELDS = ("display_name", "logo_url", "favicon_url", "primary_color", "secondary_color")


LOGO_MAX_BYTES = 512 * 1024
FAVICON_MAX_BYTES = 128 * 1024
_DATA_IMAGE = re.compile(r"^data:(image/(?:png|jpeg|webp|gif|x-icon|vnd\.microsoft\.icon));base64,([A-Za-z0-9+/]+={0,2})$")
_IMAGE_MAGIC = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/gif": (b"GIF87a", b"GIF89a"),
    "image/x-icon": (b"\x00\x00\x01\x00",),
    "image/vnd.microsoft.icon": (b"\x00\x00\x01\x00",),
}


def _safe_data_image(value: str, max_bytes: int) -> str:
    """An attached image file (``data:image/...;base64``): raster types only, size-capped, signature-checked."""
    match = _DATA_IMAGE.match(value)
    if not match:
        raise ValueError("Attach a PNG, JPEG, WebP, GIF or ICO image")
    content_type, payload = match.groups()
    if len(payload) > max_bytes * 4 // 3 + 4:
        raise ValueError(f"Image exceeds the {max_bytes // 1024} KB limit")
    try:
        content = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Image data is corrupted") from exc
    if len(content) > max_bytes:
        raise ValueError(f"Image exceeds the {max_bytes // 1024} KB limit")
    if content_type == "image/webp":
        valid = content.startswith(b"RIFF") and content[8:12] == b"WEBP"
    else:
        valid = any(content.startswith(magic) for magic in _IMAGE_MAGIC[content_type])
    if not valid:
        raise ValueError("Image content does not match its type")
    return value


def _safe_url(value: str | None, max_data_bytes: int = LOGO_MAX_BYTES) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if value.lower().startswith("data:"):
        return _safe_data_image(value, max_data_bytes)
    if len(value) > 2048:
        raise ValueError("URL is too long")
    if value.startswith("/") and not value.startswith("//"):
        return value
    if value.lower().startswith("https://"):
        return value
    raise ValueError("Use an https:// URL or a site-relative path")


class BrandingInput(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)
    logo_url: str | None = None
    favicon_url: str | None = None
    primary_color: str | None = None
    secondary_color: str | None = None

    @field_validator("display_name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        value = (value or "").strip()
        return value or None

    @field_validator("logo_url")
    @classmethod
    def _logo(cls, value: str | None) -> str | None:
        return _safe_url(value, LOGO_MAX_BYTES)

    @field_validator("favicon_url")
    @classmethod
    def _favicon(cls, value: str | None) -> str | None:
        return _safe_url(value, FAVICON_MAX_BYTES)

    @field_validator("primary_color", "secondary_color")
    @classmethod
    def _color(cls, value: str | None) -> str | None:
        value = (value or "").strip()
        if not value:
            return None
        if not HEX_COLOR.match(value):
            raise ValueError("Use a #RRGGBB colour")
        return value.lower()


def merge_branding(current: dict | None, patch: BrandingInput) -> dict:
    """Apply only the fields present in the request (``None`` clears one)."""
    merged = dict(current or {})
    for key, value in patch.model_dump(exclude_unset=True).items():
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    return merged


def _uploaded_logo(settings: dict | None, theme: str, fallback: str) -> str:
    source = ((settings or {}).get("branding") or {}).get(theme, "default")
    if isinstance(source, str) and source.startswith("data:image/"):
        return source
    return LEGACY_LOGOS.get(source, fallback)


def public_branding(organization) -> dict:
    """Branding safe to expose before sign-in (login page, favicon, theme)."""
    branding = organization.branding or {}
    light = _uploaded_logo(organization.settings, "light", LEGACY_LOGOS["legacy-icon"])
    dark = _uploaded_logo(organization.settings, "dark", LEGACY_LOGOS["legacy-aio"])
    return {
        "slug": organization.slug,
        "name": branding.get("display_name") or organization.name,
        "custom_logo": bool(branding.get("logo_url")),
        "logo_url": branding.get("logo_url") or light,
        "dark_logo_url": branding.get("logo_url") or dark,
        "favicon_url": branding.get("favicon_url") or DEFAULT_FAVICON,
        "primary_color": branding.get("primary_color"),
        "secondary_color": branding.get("secondary_color"),
    }


def editable_branding(organization) -> dict:
    branding = organization.branding or {}
    return {field: branding.get(field) for field in BRANDING_FIELDS}
