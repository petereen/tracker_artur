"""News & announcements (``/v1/announcements``).

* ``GET ""`` — published feed for every signed-in user (the «Өнөөдөр» widget).
* ``GET /manage``, ``POST ""``, ``PATCH /{id}``, ``DELETE /{id}``,
  ``POST /images`` — authoring for admins, managers and team leads. Admins and
  managers edit every post; a team lead edits their own.
* ``GET /media/{name}`` — uploaded images, served by unguessable name.

Posts are Markdown; images are uploaded here and referenced by the returned
URL (external image URLs are rejected).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.enterprise_deps import ActorContext, get_actor, require_roles
from app.models.announcements import Announcement
from app.models.models import Employee
from app.services.announcement_media import InvalidAnnouncementImage, is_media_url, media_url, read_image, save_image
from app.services.enterprise_events import record_change
from app.services.malware_scanner import MalwareDetected, MalwareScanUnavailable

router = APIRouter()

AUTHOR_ROLES = ("admin", "manager", "team_lead")
# May edit, pin and delete posts written by somebody else.
EDITOR_ROLES = ("admin", "manager")
MAX_GALLERY_IMAGES = 12
TITLE_MAX = 200
SUMMARY_MAX = 500
BODY_MAX = 20_000
CATEGORY_MAX = 60

AnnouncementStatus = Literal["draft", "published", "archived"]


def _clean(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def _own_image(value: str | None) -> str | None:
    value = _clean(value)
    if value is not None and not is_media_url(value):
        raise ValueError("Images must be uploaded through /v1/announcements/images")
    return value


def _own_images(values: list[str]) -> list[str]:
    cleaned = [_own_image(value) for value in values]
    return list(dict.fromkeys(value for value in cleaned if value))


class AnnouncementFields(BaseModel):
    summary: str | None = Field(default=None, max_length=SUMMARY_MAX)
    body: str = Field(default="", max_length=BODY_MAX)
    cover_url: str | None = None
    image_urls: list[str] = Field(default_factory=list, max_length=MAX_GALLERY_IMAGES)
    category: str | None = Field(default=None, max_length=CATEGORY_MAX)
    is_pinned: bool = False
    status: AnnouncementStatus = "draft"

    @field_validator("summary", "category")
    @classmethod
    def clean_text(cls, value: str | None) -> str | None:
        return _clean(value)

    @field_validator("cover_url")
    @classmethod
    def validate_cover(cls, value: str | None) -> str | None:
        return _own_image(value)

    @field_validator("image_urls")
    @classmethod
    def validate_images(cls, values: list[str]) -> list[str]:
        return _own_images(values)


class AnnouncementCreate(AnnouncementFields):
    title: str = Field(min_length=1, max_length=TITLE_MAX)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Title is required")
        return value


class AnnouncementPatch(AnnouncementFields):
    title: str | None = Field(default=None, max_length=TITLE_MAX)
    body: str | None = Field(default=None, max_length=BODY_MAX)
    image_urls: list[str] | None = Field(default=None, max_length=MAX_GALLERY_IMAGES)
    is_pinned: bool | None = None
    status: AnnouncementStatus | None = None

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Title is required")
        return value.strip() if value is not None else None

    @field_validator("image_urls")
    @classmethod
    def validate_images(cls, values: list[str] | None) -> list[str] | None:
        return None if values is None else _own_images(values)


def can_edit(actor: ActorContext, author_account_id: int | None) -> bool:
    if actor.has_any_role(*EDITOR_ROLES):
        return True
    return actor.has_any_role(*AUTHOR_ROLES) and author_account_id == actor.account_id


def _public_out(row: Announcement) -> dict:
    return {
        "id": row.id,
        "title": row.title,
        "summary": row.summary,
        "body": row.body or "",
        "cover_url": row.cover_url,
        "image_urls": list(row.image_urls or []),
        "author_name": row.author_name,
        "category": row.category,
        "is_pinned": bool(row.is_pinned),
        "published_at": row.published_at or row.created_at,
    }


def _manage_out(row: Announcement, actor: ActorContext) -> dict:
    return {
        **_public_out(row),
        "published_at": row.published_at,
        "status": row.status,
        "author_account_id": row.author_account_id,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "can_edit": can_edit(actor, row.author_account_id),
    }


def _audit(row: Announcement) -> dict:
    return {"title": row.title, "status": row.status, "is_pinned": bool(row.is_pinned), "category": row.category}


async def _author_name(db: AsyncSession, actor: ActorContext) -> str:
    employee = await db.get(Employee, actor.employee_id) if actor.employee_id else None
    return (employee.name if employee and employee.name else None) or actor.email


async def _editable(db: AsyncSession, actor: ActorContext, announcement_id: int) -> Announcement:
    row = (await db.execute(
        select(Announcement)
        .where(Announcement.id == announcement_id, Announcement.organization_id == actor.organization_id)
        .with_for_update()
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Announcement not found")
    if not can_edit(actor, row.author_account_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permission")
    return row


@router.get("")
async def list_published(
    limit: int = Query(default=30, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    rows = (await db.execute(
        select(Announcement)
        .where(Announcement.organization_id == actor.organization_id, Announcement.status == "published")
        .order_by(Announcement.is_pinned.desc(), Announcement.published_at.desc(), Announcement.id.desc())
        .limit(limit)
    )).scalars().all()
    return [_public_out(row) for row in rows]


@router.get("/manage")
async def list_for_authors(
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_roles(*AUTHOR_ROLES)),
):
    query = select(Announcement).where(Announcement.organization_id == actor.organization_id)
    if not actor.has_any_role(*EDITOR_ROLES):
        # A team lead sees published posts plus their own drafts and archive.
        query = query.where((Announcement.status == "published") | (Announcement.author_account_id == actor.account_id))
    rows = (await db.execute(query.order_by(Announcement.updated_at.desc(), Announcement.id.desc()).limit(500))).scalars().all()
    return [_manage_out(row, actor) for row in rows]


@router.get("/media/{name}")
async def announcement_media(name: str):
    try:
        content, media_type = await read_image(name)
    except (FileNotFoundError, OSError):
        raise HTTPException(status_code=404, detail="Image not found")
    return Response(content, media_type=media_type, headers={
        "Cache-Control": "public, max-age=31536000, immutable",
        "X-Content-Type-Options": "nosniff",
    })


@router.post("/images", status_code=status.HTTP_201_CREATED)
async def upload_image(
    file: UploadFile = File(...),
    actor: ActorContext = Depends(require_roles(*AUTHOR_ROLES)),
):
    content = await file.read(settings.ANNOUNCEMENT_IMAGE_MAX_BYTES + 1)
    try:
        name, width, height, size = await save_image(content, file.content_type or "application/octet-stream")
    except (InvalidAnnouncementImage, MalwareDetected) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except MalwareScanUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"url": media_url(name), "width": width, "height": height, "size": size}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_announcement(
    data: AnnouncementCreate,
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_roles(*AUTHOR_ROLES)),
):
    if data.is_pinned and not actor.has_any_role(*EDITOR_ROLES):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admins and managers can pin announcements")
    row = Announcement(
        organization_id=actor.organization_id,
        title=data.title,
        summary=data.summary,
        body=data.body,
        cover_url=data.cover_url,
        image_urls=data.image_urls,
        category=data.category,
        is_pinned=data.is_pinned,
        status=data.status,
        published_at=datetime.now(timezone.utc) if data.status == "published" else None,
        author_account_id=actor.account_id,
        author_name=await _author_name(db, actor),
    )
    db.add(row)
    await db.flush()
    await record_change(db, actor=actor, topic="announcements", aggregate_type="announcement", aggregate_id=row.id, operation="created", after=_audit(row))
    await db.commit()
    await db.refresh(row)
    return _manage_out(row, actor)


@router.patch("/{announcement_id}")
async def update_announcement(
    announcement_id: int,
    data: AnnouncementPatch,
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_roles(*AUTHOR_ROLES)),
):
    row = await _editable(db, actor, announcement_id)
    changes = data.model_dump(exclude_unset=True)
    for required in ("title", "body", "image_urls", "is_pinned", "status"):
        if required in changes and changes[required] is None:
            del changes[required]
    if changes.get("is_pinned") and not row.is_pinned and not actor.has_any_role(*EDITOR_ROLES):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admins and managers can pin announcements")
    before = _audit(row)
    for key, value in changes.items():
        setattr(row, key, value)
    if row.status == "published" and row.published_at is None:
        row.published_at = datetime.now(timezone.utc)
    await record_change(db, actor=actor, topic="announcements", aggregate_type="announcement", aggregate_id=row.id, operation="updated", before=before, after=_audit(row))
    await db.commit()
    await db.refresh(row)
    return _manage_out(row, actor)


@router.delete("/{announcement_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_announcement(
    announcement_id: int,
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_roles(*AUTHOR_ROLES)),
):
    row = await _editable(db, actor, announcement_id)
    await record_change(db, actor=actor, topic="announcements", aggregate_type="announcement", aggregate_id=row.id, operation="deleted", before=_audit(row))
    await db.delete(row)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
