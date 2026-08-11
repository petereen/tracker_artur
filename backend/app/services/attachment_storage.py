"""Private attachment storage on the Dokploy VPS volume.

The initial self-hosted deployment intentionally uses PostgreSQL metadata plus
the mounted local attachment volume.  A storage abstraction is retained so a
future provider can be added without changing domain services.
"""

from __future__ import annotations

from pathlib import Path

import aiofiles

from app.core.config import settings


def _local_path(storage_key: str) -> Path:
    root = Path(settings.ATTACHMENT_UPLOAD_DIR).resolve()
    path = (root / storage_key).resolve()
    if root not in path.parents:
        raise ValueError("Invalid attachment storage key")
    return path


def _ensure_local_backend() -> None:
    if settings.ATTACHMENT_STORAGE_BACKEND != "local":
        raise RuntimeError("Only local attachment storage is enabled for this VPS deployment")


async def put_attachment(storage_key: str, content: bytes, content_type: str) -> None:
    _ensure_local_backend()
    path = _local_path(storage_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    async with aiofiles.open(path, "xb") as handle:
        await handle.write(content)


async def get_attachment(storage_key: str) -> bytes:
    _ensure_local_backend()
    async with aiofiles.open(_local_path(storage_key), "rb") as handle:
        return await handle.read()


def iter_attachment_chunks(storage_key: str, chunk_size: int = 64 * 1024):
    """Yield a local attachment without loading the complete file into memory."""
    _ensure_local_backend()
    with _local_path(storage_key).open("rb") as handle:
        while chunk := handle.read(chunk_size):
            yield chunk


async def delete_attachment(storage_key: str) -> None:
    _ensure_local_backend()
    _local_path(storage_key).unlink(missing_ok=True)
