"""Local storage for immutable self-hosted Capacitor update bundles."""

from __future__ import annotations

from pathlib import Path

import aiofiles

from app.core.config import settings


def local_path(storage_key: str) -> Path:
    root = Path(settings.OTA_BUNDLE_DIR).resolve()
    path = (root / storage_key).resolve()
    if root not in path.parents or path.name != storage_key:
        raise ValueError("Invalid OTA storage key")
    return path


def ensure_root() -> Path:
    root = Path(settings.OTA_BUNDLE_DIR).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


async def write_bundle(storage_key: str, chunks) -> tuple[int, str]:
    """Write an upload once while calculating its SHA-256 checksum."""
    import hashlib

    path = local_path(storage_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    async with aiofiles.open(path, "xb") as handle:
        async for chunk in chunks:
            if not chunk:
                continue
            size += len(chunk)
            if size > settings.OTA_MAX_BUNDLE_BYTES:
                raise ValueError("OTA bundle exceeds the configured size limit")
            digest.update(chunk)
            await handle.write(chunk)
    return size, digest.hexdigest()


def delete_bundle(storage_key: str) -> None:
    local_path(storage_key).unlink(missing_ok=True)

