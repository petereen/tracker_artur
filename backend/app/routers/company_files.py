from __future__ import annotations

import hashlib
import mimetypes
import uuid
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.enterprise_deps import ActorContext, get_actor, require_roles
from app.models.models import CompanyLibraryItem
from app.services.attachment_storage import delete_attachment, get_attachment, put_attachment
from app.services.enterprise_events import record_change
from app.services.malware_scanner import MalwareDetected, MalwareScanUnavailable, scan_upload


router = APIRouter()
MANAGEMENT_ROLES = ("admin", "manager", "team_lead")
BLOCKED_CONTENT_TYPES = {"application/x-msdownload", "application/x-sh", "application/x-executable"}
BLOCKED_EXTENSIONS = (".exe", ".dll", ".bat", ".cmd", ".sh")


class FolderInput(BaseModel):
    name: str
    parent_id: int | None = None


class ItemPatch(BaseModel):
    name: str | None = None
    parent_id: int | None = None
    move_to_root: bool = False


def _clean_name(value: str) -> str:
    name = value.replace("\\", "/").split("/")[-1].strip()
    if not name or name in {".", ".."}:
        raise HTTPException(status_code=422, detail="A valid name is required")
    if len(name) > 240:
        raise HTTPException(status_code=422, detail="Name must be 240 characters or fewer")
    return name


def _item_out(item: CompanyLibraryItem) -> dict:
    return {
        "id": item.id,
        "parent_id": item.parent_id,
        "kind": item.kind,
        "name": item.name,
        "content_type": item.content_type,
        "size": item.size,
        "checksum": item.checksum,
        "uploaded_by_account_id": item.uploaded_by_account_id,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
        "deleted_at": item.deleted_at,
    }


async def _organization_items(db: AsyncSession, organization_id: int) -> list[CompanyLibraryItem]:
    return list((await db.execute(select(CompanyLibraryItem).where(CompanyLibraryItem.organization_id == organization_id))).scalars().all())


def _has_deleted_ancestor(item: CompanyLibraryItem, by_id: dict[int, CompanyLibraryItem]) -> bool:
    seen: set[int] = set()
    parent_id = item.parent_id
    while parent_id is not None:
        if parent_id in seen:
            return True
        seen.add(parent_id)
        parent = by_id.get(parent_id)
        if parent is None or parent.deleted_at is not None:
            return True
        parent_id = parent.parent_id
    return False


async def _active_folder(db: AsyncSession, folder_id: int | None, actor: ActorContext) -> CompanyLibraryItem | None:
    if folder_id is None:
        return None
    folder = await db.get(CompanyLibraryItem, folder_id)
    if not folder or folder.organization_id != actor.organization_id or folder.kind != "folder" or folder.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Folder not found")
    items = await _organization_items(db, actor.organization_id)
    if _has_deleted_ancestor(folder, {item.id: item for item in items}):
        raise HTTPException(status_code=404, detail="Folder not found")
    return folder


async def _item_for_actor(db: AsyncSession, item_id: int, actor: ActorContext) -> CompanyLibraryItem:
    item = await db.get(CompanyLibraryItem, item_id)
    if not item or item.organization_id != actor.organization_id:
        raise HTTPException(status_code=404, detail="Library item not found")
    return item


async def _ensure_name_available(
    db: AsyncSession,
    actor: ActorContext,
    name: str,
    parent_id: int | None,
    *,
    exclude_id: int | None = None,
) -> None:
    query = select(CompanyLibraryItem.id).where(
        CompanyLibraryItem.organization_id == actor.organization_id,
        CompanyLibraryItem.deleted_at.is_(None),
        func.lower(CompanyLibraryItem.name) == name.lower(),
    )
    query = query.where(CompanyLibraryItem.parent_id == parent_id) if parent_id is not None else query.where(CompanyLibraryItem.parent_id.is_(None))
    if exclude_id is not None:
        query = query.where(CompanyLibraryItem.id != exclude_id)
    if await db.scalar(query):
        raise HTTPException(status_code=409, detail="An item with this name already exists in the folder")


def _breadcrumbs(folder: CompanyLibraryItem | None, by_id: dict[int, CompanyLibraryItem]) -> list[dict]:
    result: list[dict] = []
    current = folder
    seen: set[int] = set()
    while current is not None and current.id not in seen:
        seen.add(current.id)
        result.append({"id": current.id, "name": current.name})
        current = by_id.get(current.parent_id) if current.parent_id is not None else None
    return list(reversed(result))


@router.get("")
async def browse_company_files(
    parent_id: int | None = None,
    q: str | None = Query(default=None, max_length=200),
    sort: Literal["name", "newest", "oldest", "size"] = "name",
    trash: bool = False,
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    can_manage = actor.has_any_role(*MANAGEMENT_ROLES)
    if trash and not can_manage:
        raise HTTPException(status_code=403, detail="Insufficient permission")
    parent = None if trash else await _active_folder(db, parent_id, actor)
    all_items = await _organization_items(db, actor.organization_id)
    by_id = {item.id: item for item in all_items}
    if trash:
        items = [item for item in all_items if item.deleted_at is not None and not _has_deleted_ancestor(item, by_id)]
    else:
        items = [item for item in all_items if item.deleted_at is None and not _has_deleted_ancestor(item, by_id)]
        if q and q.strip():
            needle = q.strip().casefold()
            items = [item for item in items if needle in item.name.casefold()]
        else:
            items = [item for item in items if item.parent_id == parent_id]
    if sort == "newest":
        items.sort(key=lambda item: item.created_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    elif sort == "oldest":
        items.sort(key=lambda item: item.created_at or datetime.min.replace(tzinfo=timezone.utc))
    elif sort == "size":
        items.sort(key=lambda item: (item.kind != "folder", -(item.size or 0), item.name.casefold()))
    else:
        items.sort(key=lambda item: (item.kind != "folder", item.name.casefold()))
    folders = [item for item in all_items if item.kind == "folder" and item.deleted_at is None and not _has_deleted_ancestor(item, by_id)]
    folders.sort(key=lambda item: item.name.casefold())
    return {
        "current_folder": _item_out(parent) if parent else None,
        "breadcrumbs": _breadcrumbs(parent, by_id),
        "items": [_item_out(item) for item in items],
        "folders": [{"id": item.id, "parent_id": item.parent_id, "name": item.name} for item in folders],
        "can_manage": can_manage,
        "is_search": bool(q and q.strip()),
        "is_trash": trash,
    }


@router.post("/folders", status_code=status.HTTP_201_CREATED)
async def create_folder(
    data: FolderInput,
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_roles(*MANAGEMENT_ROLES)),
):
    name = _clean_name(data.name)
    await _active_folder(db, data.parent_id, actor)
    await _ensure_name_available(db, actor, name, data.parent_id)
    item = CompanyLibraryItem(organization_id=actor.organization_id, parent_id=data.parent_id, kind="folder", name=name, uploaded_by_account_id=actor.account_id)
    db.add(item)
    try:
        await db.flush()
        await record_change(db, actor=actor, topic="company_files", aggregate_type="company_library_item", aggregate_id=item.id, operation="created", after={"kind": "folder", "name": name, "parent_id": data.parent_id})
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="An item with this name already exists in the folder") from exc
    return _item_out(item)


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_company_file(
    files: list[UploadFile] = File(...),
    parent_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_roles(*MANAGEMENT_ROLES)),
):
    await _active_folder(db, parent_id, actor)
    if not files:
        raise HTTPException(status_code=400, detail="No files were uploaded")
    seen_names: set[str] = set()
    uploaded_items: list[CompanyLibraryItem] = []
    storage_keys: list[str] = []
    try:
        for file in files:
            name = _clean_name(file.filename or "file")
            lower_name = name.casefold()
            if lower_name in seen_names:
                raise HTTPException(status_code=409, detail="An item with this name already exists in the folder")
            seen_names.add(lower_name)
            await _ensure_name_available(db, actor, name, parent_id)
            content = await file.read(settings.ATTACHMENT_MAX_BYTES + 1)
            if len(content) > settings.ATTACHMENT_MAX_BYTES:
                raise HTTPException(status_code=413, detail="File exceeds configured size limit")
            if not content:
                raise HTTPException(status_code=400, detail="File is empty")
            content_type = file.content_type or mimetypes.guess_type(name)[0] or "application/octet-stream"
            if content_type in BLOCKED_CONTENT_TYPES or name.lower().endswith(BLOCKED_EXTENSIONS):
                raise HTTPException(status_code=415, detail="Executable files are not allowed")
            try:
                scan_status = await scan_upload(content)
            except MalwareDetected as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            except MalwareScanUnavailable as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            storage_key = f"{actor.organization_id}/library/{uuid.uuid4().hex}"
            checksum = hashlib.sha256(content).hexdigest()
            await put_attachment(storage_key, content, content_type)
            storage_keys.append(storage_key)
            item = CompanyLibraryItem(
                organization_id=actor.organization_id,
                parent_id=parent_id,
                kind="file",
                name=name,
                storage_key=storage_key,
                content_type=content_type,
                size=len(content),
                checksum=checksum,
                uploaded_by_account_id=actor.account_id,
            )
            db.add(item)
            uploaded_items.append((item, scan_status, name, checksum))
        await db.flush()
        for item, scan_status, name, checksum in uploaded_items:
            await record_change(db, actor=actor, topic="company_files", aggregate_type="company_library_item", aggregate_id=item.id, operation="uploaded", after={"name": name, "parent_id": parent_id, "size": item.size, "checksum": checksum, "scan_status": scan_status})
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        for key in storage_keys:
            await delete_attachment(key)
        raise HTTPException(status_code=409, detail="An item with this name already exists in the folder") from exc
    except HTTPException:
        await db.rollback()
        for key in storage_keys:
            await delete_attachment(key)
        raise
    except Exception:
        await db.rollback()
        for key in storage_keys:
            await delete_attachment(key)
        raise
    return [_item_out(item) for item, _, _, _ in uploaded_items]


@router.patch("/{item_id}")
async def update_company_item(
    item_id: int,
    data: ItemPatch,
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_roles(*MANAGEMENT_ROLES)),
):
    item = await _item_for_actor(db, item_id, actor)
    if item.deleted_at is not None:
        raise HTTPException(status_code=409, detail="Restore the item before changing it")
    new_name = _clean_name(data.name) if data.name is not None else item.name
    target_parent_id = None if data.move_to_root else data.parent_id if data.parent_id is not None else item.parent_id
    target_parent = await _active_folder(db, target_parent_id, actor)
    if target_parent and target_parent.id == item.id:
        raise HTTPException(status_code=409, detail="A folder cannot contain itself")
    if item.kind == "folder" and target_parent:
        current: CompanyLibraryItem | None = target_parent
        seen: set[int] = set()
        while current is not None and current.id not in seen:
            if current.id == item.id:
                raise HTTPException(status_code=409, detail="A folder cannot be moved into its descendant")
            seen.add(current.id)
            current = await db.get(CompanyLibraryItem, current.parent_id) if current.parent_id is not None else None
    await _ensure_name_available(db, actor, new_name, target_parent_id, exclude_id=item.id)
    before = {"name": item.name, "parent_id": item.parent_id}
    item.name = new_name
    item.parent_id = target_parent_id
    item.updated_at = datetime.now(timezone.utc)
    try:
        await record_change(db, actor=actor, topic="company_files", aggregate_type="company_library_item", aggregate_id=item.id, operation="updated", before=before, after={"name": item.name, "parent_id": item.parent_id})
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="An item with this name already exists in the folder") from exc
    return _item_out(item)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def trash_company_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_roles(*MANAGEMENT_ROLES)),
):
    item = await _item_for_actor(db, item_id, actor)
    if item.deleted_at is not None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    item.deleted_at = datetime.now(timezone.utc)
    item.deleted_by_account_id = actor.account_id
    await record_change(db, actor=actor, topic="company_files", aggregate_type="company_library_item", aggregate_id=item.id, operation="trashed", before={"name": item.name, "parent_id": item.parent_id})
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{item_id}/restore")
async def restore_company_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_roles(*MANAGEMENT_ROLES)),
):
    item = await _item_for_actor(db, item_id, actor)
    if item.deleted_at is None:
        return _item_out(item)
    await _active_folder(db, item.parent_id, actor)
    await _ensure_name_available(db, actor, item.name, item.parent_id, exclude_id=item.id)
    item.deleted_at = None
    item.deleted_by_account_id = None
    item.updated_at = datetime.now(timezone.utc)
    try:
        await record_change(db, actor=actor, topic="company_files", aggregate_type="company_library_item", aggregate_id=item.id, operation="restored", after={"name": item.name, "parent_id": item.parent_id})
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="An item with this name already exists in the folder") from exc
    return _item_out(item)


@router.delete("/{item_id}/permanent", status_code=status.HTTP_204_NO_CONTENT)
async def permanently_delete_company_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_roles(*MANAGEMENT_ROLES)),
):
    item = await _item_for_actor(db, item_id, actor)
    if item.deleted_at is None:
        raise HTTPException(status_code=409, detail="Move the item to trash before deleting it permanently")
    all_items = await _organization_items(db, actor.organization_id)
    children: dict[int, list[CompanyLibraryItem]] = {}
    for candidate in all_items:
        if candidate.parent_id is not None:
            children.setdefault(candidate.parent_id, []).append(candidate)
    descendants: list[CompanyLibraryItem] = []
    stack = [item]
    while stack:
        current = stack.pop()
        descendants.append(current)
        stack.extend(children.get(current.id, []))
    storage_keys = [candidate.storage_key for candidate in descendants if candidate.storage_key]
    await record_change(db, actor=actor, topic="company_files", aggregate_type="company_library_item", aggregate_id=item.id, operation="deleted", before={"name": item.name, "kind": item.kind})
    await db.delete(item)
    await db.commit()
    for storage_key in storage_keys:
        await delete_attachment(storage_key)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{item_id}/download")
async def download_company_file(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    item = await _item_for_actor(db, item_id, actor)
    all_items = await _organization_items(db, actor.organization_id)
    if item.kind != "file" or item.deleted_at is not None or _has_deleted_ancestor(item, {candidate.id: candidate for candidate in all_items}):
        raise HTTPException(status_code=404, detail="File not found")
    content = await get_attachment(item.storage_key)
    encoded_name = quote(item.name, safe="")
    return Response(
        content,
        media_type=item.content_type or "application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}", "X-Content-Type-Options": "nosniff"},
    )
