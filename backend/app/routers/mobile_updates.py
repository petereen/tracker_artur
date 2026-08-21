"""Self-hosted OTA bundle API for the Capacitor web layer.

The updater intentionally has no account dependency: update checks and bundle
downloads must work before a user session exists. Upload and channel mutation
are protected by a deployment-only bearer token.
"""

from __future__ import annotations

import re
import secrets
import zipfile
from datetime import datetime, timezone
from typing import AsyncIterator

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.models import MobileUpdateBundle, MobileUpdateChannel
from app.services.ota_storage import delete_bundle, ensure_root, local_path, write_bundle


router = APIRouter()
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class UpdateCheckInput(BaseModel):
    app_id: str = Field(min_length=1, max_length=128)
    channel: str = Field(default=settings.OTA_DEFAULT_CHANNEL, min_length=1, max_length=64)
    platform: str = Field(min_length=1, max_length=16)
    current_version: str = Field(default="builtin", max_length=64)
    device_id: str | None = Field(default=None, max_length=128)

    @field_validator("channel")
    @classmethod
    def validate_channel(cls, value: str) -> str:
        value = value.strip()
        if not _NAME_RE.fullmatch(value):
            raise ValueError("Invalid OTA channel")
        return value


class UpdateDescriptor(BaseModel):
    version: str
    url: str
    checksum: str
    size: int
    channel: str


class UpdateCheckOutput(BaseModel):
    update: UpdateDescriptor | None = None


class BundleOutput(BaseModel):
    app_id: str
    version: str
    checksum: str
    size: int
    storage_url: str


def _enabled() -> None:
    if not settings.OTA_ENABLED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="OTA is disabled")


def _require_upload_token(authorization: str | None, x_ota_token: str | None) -> None:
    _enabled()
    expected = settings.OTA_UPLOAD_TOKEN.strip()
    presented = (x_ota_token or "").strip()
    if not presented and authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer":
            presented = value.strip()
    if not expected or not presented or not secrets.compare_digest(expected, presented):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid OTA credentials")


def _version_key(version: str) -> tuple[int, ...] | None:
    if version == "builtin":
        return None
    pieces = version.split(".")
    if not pieces or any(not piece.isdigit() for piece in pieces):
        return None
    return tuple(int(piece) for piece in pieces)


def _is_newer(candidate: str, current: str) -> bool:
    if current in {"", "builtin"}:
        return True
    candidate_key = _version_key(candidate)
    current_key = _version_key(current)
    if candidate_key is None or current_key is None:
        return candidate != current
    return candidate_key > current_key


def _bundle_url(version: str) -> str:
    return f"{settings.OTA_PUBLIC_BASE_URL.rstrip('/')}/bundles/{version}"


@router.post("/check", response_model=UpdateCheckOutput)
async def check_for_update(data: UpdateCheckInput):
    _enabled()
    if data.app_id != settings.OTA_APP_ID:
        return UpdateCheckOutput()
    if data.platform not in {"ios", "android"}:
        return UpdateCheckOutput()

    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(
                select(MobileUpdateBundle, MobileUpdateChannel)
                .join(MobileUpdateChannel, MobileUpdateChannel.active_bundle_id == MobileUpdateBundle.id)
                .where(
                    MobileUpdateChannel.app_id == data.app_id,
                    MobileUpdateChannel.name == data.channel,
                )
            )
        ).first()
    if not row:
        return UpdateCheckOutput()
    bundle, channel = row
    if not _is_newer(bundle.version, data.current_version):
        return UpdateCheckOutput()
    return UpdateCheckOutput(
        update=UpdateDescriptor(
            version=bundle.version,
            url=_bundle_url(bundle.version),
            checksum=bundle.checksum,
            size=bundle.size,
            channel=channel.name,
        )
    )


@router.get("/bundles/{version}")
async def download_bundle(version: str):
    _enabled()
    if not _NAME_RE.fullmatch(version):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bundle not found")
    async with AsyncSessionLocal() as db:
        bundle = (
            await db.execute(
                select(MobileUpdateBundle).where(
                    MobileUpdateBundle.app_id == settings.OTA_APP_ID,
                    MobileUpdateBundle.version == version,
                )
            )
        ).scalar_one_or_none()
    if not bundle:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bundle not found")
    path = local_path(bundle.storage_key)
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bundle content unavailable")
    return FileResponse(
        path,
        media_type="application/zip",
        filename=f"{settings.OTA_APP_ID}-{bundle.version}.zip",
        headers={"Cache-Control": "public, max-age=31536000, immutable", "ETag": bundle.checksum},
    )


@router.post("/bundles", response_model=BundleOutput, status_code=status.HTTP_201_CREATED)
async def upload_bundle(
    version: str = Form(...),
    file: UploadFile = File(...),
    authorization: str | None = Header(default=None),
    x_ota_token: str | None = Header(default=None),
):
    _require_upload_token(authorization, x_ota_token)
    version = version.strip()
    if not _NAME_RE.fullmatch(version) or _version_key(version) is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Use a numeric semantic bundle version")
    if file.content_type not in {"application/zip", "application/x-zip-compressed", "application/octet-stream"}:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="OTA bundles must be ZIP files")

    storage_key = f"{version}-{secrets.token_hex(8)}.zip"
    ensure_root()

    async def chunks() -> AsyncIterator[bytes]:
        while chunk := await file.read(1024 * 1024):
            yield chunk

    try:
        size, checksum = await write_bundle(storage_key, chunks())
    except ValueError as exc:
        delete_bundle(storage_key)
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)) from exc
    except OSError as exc:
        delete_bundle(storage_key)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unable to store OTA bundle") from exc

    bundle_path = local_path(storage_key)
    if not zipfile.is_zipfile(bundle_path):
        delete_bundle(storage_key)
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="OTA bundle is not a valid ZIP archive")

    async with AsyncSessionLocal() as db:
        bundle = MobileUpdateBundle(
            app_id=settings.OTA_APP_ID,
            version=version,
            storage_key=storage_key,
            checksum=checksum,
            size=size,
        )
        db.add(bundle)
        try:
            await db.commit()
            await db.refresh(bundle)
        except IntegrityError as exc:
            await db.rollback()
            delete_bundle(storage_key)
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Bundle version already exists") from exc

    return BundleOutput(
        app_id=bundle.app_id,
        version=bundle.version,
        checksum=bundle.checksum,
        size=bundle.size,
        storage_url=_bundle_url(bundle.version),
    )


@router.put("/channels/{channel}/bundle/{version}")
async def promote_bundle(
    channel: str,
    version: str,
    authorization: str | None = Header(default=None),
    x_ota_token: str | None = Header(default=None),
):
    _require_upload_token(authorization, x_ota_token)
    if not _NAME_RE.fullmatch(channel) or not _NAME_RE.fullmatch(version) or _version_key(version) is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid OTA channel or version")
    async with AsyncSessionLocal() as db:
        bundle = (
            await db.execute(
                select(MobileUpdateBundle).where(
                    MobileUpdateBundle.app_id == settings.OTA_APP_ID,
                    MobileUpdateBundle.version == version,
                )
            )
        ).scalar_one_or_none()
        if not bundle:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bundle not found")
        channel_row = (
            await db.execute(
                select(MobileUpdateChannel)
                .where(MobileUpdateChannel.app_id == settings.OTA_APP_ID, MobileUpdateChannel.name == channel)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if not channel_row:
            channel_row = MobileUpdateChannel(app_id=settings.OTA_APP_ID, name=channel)
            db.add(channel_row)
            await db.flush()
        if channel_row.active_bundle_id != bundle.id:
            channel_row.previous_bundle_id = channel_row.active_bundle_id
            channel_row.active_bundle_id = bundle.id
            channel_row.updated_at = datetime.now(timezone.utc)
        await db.commit()
    return {"channel": channel, "version": version, "status": "active"}


@router.post("/channels/{channel}/rollback")
async def rollback_channel(
    channel: str,
    authorization: str | None = Header(default=None),
    x_ota_token: str | None = Header(default=None),
):
    _require_upload_token(authorization, x_ota_token)
    async with AsyncSessionLocal() as db:
        channel_row = (
            await db.execute(
                select(MobileUpdateChannel)
                .where(MobileUpdateChannel.app_id == settings.OTA_APP_ID, MobileUpdateChannel.name == channel)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if not channel_row or not channel_row.previous_bundle_id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No previous bundle is available")
        channel_row.active_bundle_id, channel_row.previous_bundle_id = channel_row.previous_bundle_id, channel_row.active_bundle_id
        channel_row.updated_at = datetime.now(timezone.utc)
        await db.commit()
        active = await db.get(MobileUpdateBundle, channel_row.active_bundle_id)
    return {"channel": channel, "version": active.version, "status": "rolled_back"}
