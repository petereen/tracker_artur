"""Admin CRUD for curated company knowledge used by the OYUNS assistant."""

from datetime import datetime
import logging
import mimetypes
from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.config import settings
from app.models.models import CompanyKnowledge

router = APIRouter()
log = logging.getLogger(__name__)

MAX_ATTACHMENT_SIZE = 20 * 1024 * 1024
ALLOWED_ATTACHMENT_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".rtf", ".odt", ".xls", ".xlsx", ".ods", ".ppt", ".pptx", ".odp",
    ".txt", ".md", ".csv", ".png", ".jpg", ".jpeg", ".webp", ".svg",
}


class KnowledgeCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    category: Optional[str] = Field(default=None, max_length=80)
    content: str = Field(min_length=1, max_length=20_000)
    is_active: bool = True

    @field_validator("title", "content")
    @classmethod
    def _required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("category")
    @classmethod
    def _optional_text(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() or None if value else None


class KnowledgeUpdate(KnowledgeCreate):
    """PUT uses a complete representation, including the active state."""


class KnowledgeOut(BaseModel):
    id: int
    title: str
    category: Optional[str]
    content: str
    attachment_filename: Optional[str]
    attachment_content_type: Optional[str]
    attachment_size: Optional[int]
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


def _attachment_directory() -> Path:
    return Path(settings.KNOWLEDGE_UPLOAD_DIR)


def _safe_attachment_filename(filename: str | None) -> tuple[str, str]:
    safe_name = Path(filename or "attachment").name.strip() or "attachment"
    extension = Path(safe_name).suffix.casefold()
    if extension not in ALLOWED_ATTACHMENT_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_ATTACHMENT_EXTENSIONS))
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"unsupported file type; allowed: {allowed}",
        )
    return safe_name[:255], extension


async def _store_attachment(file: UploadFile) -> dict:
    filename, extension = _safe_attachment_filename(file.filename)
    content = await file.read(MAX_ATTACHMENT_SIZE + 1)
    if not content:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="uploaded file is empty")
    if len(content) > MAX_ATTACHMENT_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="uploaded file must be 20 MB or smaller",
        )

    directory = _attachment_directory()
    directory.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid4().hex}{extension}"
    (directory / stored_name).write_bytes(content)
    return {
        "attachment_filename": filename,
        "attachment_stored_name": stored_name,
        "attachment_content_type": mimetypes.guess_type(filename)[0] or file.content_type or "application/octet-stream",
        "attachment_size": len(content),
    }


def _delete_attachment(stored_name: str | None) -> None:
    if not stored_name or Path(stored_name).name != stored_name:
        return
    try:
        (_attachment_directory() / stored_name).unlink(missing_ok=True)
    except OSError:
        log.exception("knowledge.attachment_delete_failed stored_name=%s", stored_name)


@router.get("", response_model=list[KnowledgeOut])
async def list_knowledge(
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    rows = (
        await db.execute(
            select(CompanyKnowledge).order_by(
                CompanyKnowledge.is_active.desc(),
                CompanyKnowledge.updated_at.desc(),
                CompanyKnowledge.id.desc(),
            )
        )
    ).scalars().all()
    return rows


@router.post("", response_model=KnowledgeOut, status_code=status.HTTP_201_CREATED)
async def create_knowledge(
    data: KnowledgeCreate,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    entry = CompanyKnowledge(**data.model_dump())
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return entry


@router.post("/upload", response_model=KnowledgeOut, status_code=status.HTTP_201_CREATED)
async def create_knowledge_with_attachment(
    title: str = Form(...),
    category: Optional[str] = Form(default=None),
    content: str = Form(default=""),
    is_active: bool = Form(default=True),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Create a knowledge entry and attach one supported file in the same request."""
    fallback_content = f"Хавсаргасан файл: {Path(file.filename or 'attachment').name}"
    data = KnowledgeCreate(
        title=title,
        category=category,
        content=content.strip() or fallback_content,
        is_active=is_active,
    )
    attachment = await _store_attachment(file)
    entry = CompanyKnowledge(**data.model_dump(), **attachment)
    db.add(entry)
    try:
        await db.commit()
    except Exception:
        _delete_attachment(attachment["attachment_stored_name"])
        raise
    await db.refresh(entry)
    return entry


@router.put("/{entry_id}", response_model=KnowledgeOut)
async def update_knowledge(
    entry_id: int,
    data: KnowledgeUpdate,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    entry = await db.get(CompanyKnowledge, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="knowledge entry not found")
    for key, value in data.model_dump().items():
        setattr(entry, key, value)
    await db.commit()
    await db.refresh(entry)
    return entry


@router.post("/{entry_id}/attachment", response_model=KnowledgeOut)
async def replace_knowledge_attachment(
    entry_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    entry = await db.get(CompanyKnowledge, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="knowledge entry not found")
    attachment = await _store_attachment(file)
    old_stored_name = entry.attachment_stored_name
    for key, value in attachment.items():
        setattr(entry, key, value)
    try:
        await db.commit()
    except Exception:
        _delete_attachment(attachment["attachment_stored_name"])
        raise
    await db.refresh(entry)
    _delete_attachment(old_stored_name)
    return entry


@router.get("/{entry_id}/attachment")
async def download_knowledge_attachment(
    entry_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    entry = await db.get(CompanyKnowledge, entry_id)
    if not entry or not entry.attachment_stored_name or not entry.attachment_filename:
        raise HTTPException(status_code=404, detail="knowledge attachment not found")
    path = _attachment_directory() / entry.attachment_stored_name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="knowledge attachment file is unavailable")
    return FileResponse(
        path,
        media_type=entry.attachment_content_type or "application/octet-stream",
        filename=entry.attachment_filename,
        content_disposition_type="attachment",
    )


@router.delete("/{entry_id}/attachment", response_model=KnowledgeOut)
async def delete_knowledge_attachment(
    entry_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    entry = await db.get(CompanyKnowledge, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="knowledge entry not found")
    stored_name = entry.attachment_stored_name
    entry.attachment_filename = None
    entry.attachment_stored_name = None
    entry.attachment_content_type = None
    entry.attachment_size = None
    await db.commit()
    await db.refresh(entry)
    _delete_attachment(stored_name)
    return entry


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_knowledge(
    entry_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    entry = await db.get(CompanyKnowledge, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="knowledge entry not found")
    stored_name = entry.attachment_stored_name
    await db.delete(entry)
    await db.commit()
    _delete_attachment(stored_name)
