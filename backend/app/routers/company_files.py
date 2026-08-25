from __future__ import annotations

import hashlib
import mimetypes
import uuid
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.enterprise_deps import ActorContext, get_actor, require_roles
from app.models.models import CompanyLibraryItem, JobQueue
from app.services.attachment_storage import delete_attachment, get_attachment, iter_attachment_chunks, put_attachment
from app.services.enterprise_events import record_change
from app.services.file_search_service import (
    FileSearchPrincipal,
    FileSearchServiceError,
    authorized_file,
    compact_search_text,
    search_files,
)
from app.services.malware_scanner import MalwareDetected, MalwareScanUnavailable, scan_upload
from app.services.enterprise_tools import _policy_for_file, can_read_policy


router = APIRouter()
MANAGEMENT_ROLES = ("admin", "manager", "team_lead")
BLOCKED_CONTENT_TYPES = {"application/x-msdownload", "application/x-sh", "application/x-executable"}
BLOCKED_EXTENSIONS = (".exe", ".dll", ".bat", ".cmd", ".sh")
ARCHIVE_MAX_FILES = 500
ARCHIVE_MAX_BYTES = 1024 * 1024 * 1024
TEXT_PREVIEW_EXTENSIONS = {".js", ".ts", ".json", ".md", ".txt", ".csv"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif"}
TEXT_PREVIEW_MAX_BYTES = 64 * 1024


class FolderInput(BaseModel):
    name: str
    parent_id: int | None = None


class ItemPatch(BaseModel):
    name: str | None = None
    title: str | None = None
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
        "title": getattr(item, "title", None) or item.name,
        "extension": getattr(item, "extension", None),
        "searchable_metadata": getattr(item, "searchable_metadata", None) or {},
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
    if not await can_read_policy(db, actor, await _policy_for_file(db, folder)):
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


def _active_descendants(folder: CompanyLibraryItem, all_items: list[CompanyLibraryItem]) -> list[tuple[CompanyLibraryItem, str]]:
    """Return active descendants paired with a safe ZIP-relative path."""
    by_id = {item.id: item for item in all_items}
    children: dict[int, list[CompanyLibraryItem]] = {}
    for candidate in all_items:
        if candidate.parent_id is not None:
            children.setdefault(candidate.parent_id, []).append(candidate)
    results: list[tuple[CompanyLibraryItem, str]] = []
    stack: list[tuple[CompanyLibraryItem, PurePosixPath, set[int]]] = [(folder, PurePosixPath(folder.name), {folder.id})]
    while stack:
        current, path, ancestors = stack.pop()
        for child in children.get(current.id, []):
            if child.id in ancestors or child.deleted_at is not None or _has_deleted_ancestor(child, by_id):
                continue
            child_path = path / child.name
            results.append((child, str(child_path)))
            if child.kind == "folder":
                stack.append((child, child_path, ancestors | {child.id}))
    return results


def _file_extension(item: CompanyLibraryItem) -> str:
    return PurePosixPath(item.name).suffix.casefold()


async def _previewable_file(db: AsyncSession, item_id: int, actor: ActorContext) -> CompanyLibraryItem:
    try:
        resolved = await authorized_file(db, FileSearchPrincipal.from_actor(actor), item_id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="File authorization is temporarily unavailable") from exc
    if not resolved:
        # Match a missing resource to avoid leaking restricted file names.
        raise HTTPException(status_code=404, detail="File not found")
    return resolved[0]


async def _read_file_storage(item: CompanyLibraryItem) -> bytes:
    try:
        return await get_attachment(item.storage_key)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="File storage is temporarily unavailable") from exc


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
    try:
        all_items = await _organization_items(db, actor.organization_id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Company file storage is temporarily unavailable") from exc
    by_id = {item.id: item for item in all_items}
    search_status = None
    search_diagnostics: list[dict] = []
    search_warnings: list[str] = []
    if trash:
        items = [item for item in all_items if item.deleted_at is not None and not _has_deleted_ancestor(item, by_id)]
    else:
        items = [item for item in all_items if item.deleted_at is None and not _has_deleted_ancestor(item, by_id)]
        if q and q.strip():
            request = type("FileRequest", (), {
                "operation": "search", "query": q.strip(), "search_mode": "keyword",
                "folder_id": parent_id, "file_types": [], "limit": 500, "delivery": "none",
            })()
            try:
                search_result = await search_files(db, FileSearchPrincipal.from_actor(actor), request)
            except FileSearchServiceError as exc:
                raise HTTPException(status_code=503, detail="Company file search is temporarily unavailable") from exc
            search_status = search_result["status"]
            search_diagnostics = search_result.get("diagnostics", [])
            search_warnings = search_result.get("warnings", [])
            matched_ids = {int(row["source_id"].split(":", 1)[1]) for row in search_result["data"].get("results", [])}
            items = [item for item in items if item.id in matched_ids]
        else:
            items = [item for item in items if item.parent_id == parent_id]
    if not can_manage:
        visible: list[CompanyLibraryItem] = []
        for item in items:
            if item.kind == "folder" or await can_read_policy(db, actor, await _policy_for_file(db, item)):
                visible.append(item)
        items = visible
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
        "can_upload": True,
        "can_manage": can_manage,
        "is_search": bool(q and q.strip()),
        "is_trash": trash,
        "search_status": search_status,
        "search_diagnostics": search_diagnostics,
        "search_warnings": search_warnings,
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
    item = CompanyLibraryItem(organization_id=actor.organization_id, parent_id=data.parent_id, kind="folder", name=name, title=name, searchable_metadata={}, search_key=compact_search_text(name), uploaded_by_account_id=actor.account_id)
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
    actor: ActorContext = Depends(get_actor),
):
    await _active_folder(db, parent_id, actor)
    if not files:
        raise HTTPException(status_code=400, detail="No files were uploaded")
    seen_names: set[str] = set()
    uploaded_items: list[CompanyLibraryItem] = []
    storage_keys: list[str] = []
    try:
        for upload in files:
            name = _clean_name(upload.filename or "file")
            lower_name = name.casefold()
            if lower_name in seen_names:
                raise HTTPException(status_code=409, detail="An item with this name already exists in the folder")
            seen_names.add(lower_name)
            await _ensure_name_available(db, actor, name, parent_id)
            content = await upload.read(settings.ATTACHMENT_MAX_BYTES + 1)
            if len(content) > settings.ATTACHMENT_MAX_BYTES:
                raise HTTPException(status_code=413, detail="File exceeds configured size limit")
            if not content:
                raise HTTPException(status_code=400, detail="File is empty")
            content_type = upload.content_type or mimetypes.guess_type(name)[0] or "application/octet-stream"
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
                title=PurePosixPath(name).stem,
                extension=PurePosixPath(name).suffix.casefold().lstrip("."),
                searchable_metadata={"filename": name, "mime_type": content_type},
                search_key=compact_search_text(name),
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
            db.add(JobQueue(job_type="knowledge_index_file", payload={"item_id": item.id}, dedup_key=f"knowledge-index-file:{item.id}:{checksum}"))
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
    if data.title is not None:
        title = data.title.strip()
        if not title or len(title) > 240:
            raise HTTPException(status_code=422, detail="Title must be 1-240 characters")
        item.title = title
    elif item.kind == "file" and data.name is not None:
        item.title = PurePosixPath(new_name).stem
    if item.kind == "file":
        item.extension = PurePosixPath(new_name).suffix.casefold().lstrip(".")
        item.search_key = compact_search_text(new_name)
        item.searchable_metadata = {**(getattr(item, "searchable_metadata", None) or {}), "filename": new_name}
    item.parent_id = target_parent_id
    item.updated_at = datetime.now(timezone.utc)
    try:
        await record_change(db, actor=actor, topic="company_files", aggregate_type="company_library_item", aggregate_id=item.id, operation="updated", before=before, after={"name": item.name, "title": getattr(item, "title", None), "parent_id": item.parent_id})
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


@router.get("/{folder_id}/archive")
async def download_company_folder_archive(
    folder_id: int,
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    """Stream an organization-scoped folder as a ZIP without buffering the archive."""
    folder = await _active_folder(db, folder_id, actor)
    assert folder is not None
    try:
        descendants = _active_descendants(folder, await _organization_items(db, actor.organization_id))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Company file storage is temporarily unavailable") from exc
    files: list[tuple[CompanyLibraryItem, str]] = []
    for item, path in descendants:
        if item.kind != "file":
            continue
        try:
            allowed = await authorized_file(db, FileSearchPrincipal.from_actor(actor), item.id)
        except Exception as exc:
            raise HTTPException(status_code=503, detail="File authorization is temporarily unavailable") from exc
        if allowed:
            files.append((item, path))
    total_bytes = sum(item.size or 0 for item, _ in files)
    if len(files) > ARCHIVE_MAX_FILES or total_bytes > ARCHIVE_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Folder archive exceeds the {ARCHIVE_MAX_FILES}-file or 1 GB limit",
        )

    try:
        import zipstream
    except ImportError as exc:  # pragma: no cover - deployment dependency guard
        raise HTTPException(status_code=503, detail="Folder archive support is temporarily unavailable") from exc

    archive = zipstream.ZipStream(compress_type=zipstream.ZIP_DEFLATED)
    archive.mkdir(f"{folder.name}/")
    allowed_paths = {path for _, path in files}
    for item, path in descendants:
        if item.kind == "folder" and any(file_path.startswith(f"{path}/") for file_path in allowed_paths):
            archive.mkdir(f"{path}/")
    for item, path in files:
        archive.add(iter_attachment_chunks(item.storage_key), arcname=path)
    encoded_name = quote(f"{folder.name}.zip", safe="")
    return StreamingResponse(
        archive,
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}",
            "X-Content-Type-Options": "nosniff",
            "X-Archive-File-Count": str(len(files)),
        },
    )


@router.get("/{item_id}/preview")
async def preview_company_file(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    """Return a bounded text snippet or a small image for authenticated previews."""
    item = await _previewable_file(db, item_id, actor)
    extension = _file_extension(item)
    if extension in TEXT_PREVIEW_EXTENSIONS:
        content = await _read_file_storage(item)
        truncated = len(content) > TEXT_PREVIEW_MAX_BYTES
        snippet = content[:TEXT_PREVIEW_MAX_BYTES].decode("utf-8", errors="replace")
        return Response(
            snippet,
            media_type="text/plain; charset=utf-8",
            headers={"X-Preview-Truncated": str(truncated).lower(), "X-Content-Type-Options": "nosniff"},
        )
    if extension not in IMAGE_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Preview is unavailable for this file type")
    content = await _read_file_storage(item)
    # SVG and animated GIF stay intact: rasterising them would remove their useful fidelity.
    if extension in {".svg", ".gif"}:
        return Response(content, media_type=item.content_type or mimetypes.guess_type(item.name)[0] or "image/*", headers={"X-Content-Type-Options": "nosniff"})
    try:
        from io import BytesIO

        from PIL import Image

        image = Image.open(BytesIO(content))
        image.thumbnail((480, 320))
        buffer = BytesIO()
        output_format = "PNG" if image.mode in {"RGBA", "LA"} else "JPEG"
        if output_format == "JPEG" and image.mode != "RGB":
            image = image.convert("RGB")
        image.save(buffer, format=output_format, optimize=True)
        media_type = "image/png" if output_format == "PNG" else "image/jpeg"
        return Response(buffer.getvalue(), media_type=media_type, headers={"X-Content-Type-Options": "nosniff"})
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Image preview could not be generated") from exc


@router.get("/{item_id}/download")
async def download_company_file(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    item = await _previewable_file(db, item_id, actor)
    content = await _read_file_storage(item)
    encoded_name = quote(item.name, safe="")
    return Response(
        content,
        media_type=item.content_type or "application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}", "X-Content-Type-Options": "nosniff"},
    )
