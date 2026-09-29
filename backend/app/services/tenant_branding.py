"""Tenant branding: company name, logo, favicon and theme colours.

``organizations.branding`` holds the operator/tenant-admin editable values.
Logos uploaded from Settings → Profile (``settings["branding"]`` light/dark)
remain the fallback, so existing branding keeps working unchanged.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
LEGACY_LOGOS = {"legacy-aio": "/oyuns-aio-logo.png", "legacy-icon": "/favicon.png"}
DEFAULT_FAVICON = "/favicon.png"
BRANDING_FIELDS = ("display_name", "logo_url", "favicon_url", "primary_color", "secondary_color")


def _safe_url(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
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

    @field_validator("logo_url", "favicon_url")
    @classmethod
    def _url(cls, value: str | None) -> str | None:
        return _safe_url(value)

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
        "logo_url": branding.get("logo_url") or light,
        "dark_logo_url": branding.get("logo_url") or dark,
        "favicon_url": branding.get("favicon_url") or DEFAULT_FAVICON,
        "primary_color": branding.get("primary_color"),
        "secondary_color": branding.get("secondary_color"),
    }


def editable_branding(organization) -> dict:
    branding = organization.branding or {}
    return {field: branding.get(field) for field in BRANDING_FIELDS}
