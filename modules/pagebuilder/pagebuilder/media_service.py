"""Storage + DB operations for uploaded media assets.

Files live on the local filesystem under
:attr:`PagebuilderSettings.media_root` and are served via a StaticFiles
mount registered in :meth:`PagebuilderModule.on_startup`. The DB row
holds the sanitized filename, original name, content-type, byte size,
intrinsic dimensions, and a ``variants`` map of server-generated
thumbnails. Public URLs are derived as
``f"{settings.media_url_prefix}/{filename}"``.

Filename sanitising, content sniffing, and thumbnail generation live in
:mod:`pagebuilder.media_images`.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from pagebuilder import media_queries
from pagebuilder.contracts.schemas import MediaAssetRead, MediaAssetVariant
from pagebuilder.media_images import (
    CONTENT_TYPE_EXTENSIONS,
    SNIFF_BYTES,
    normalize_folder,
    process_image,
    safe_extension,
    sniff_content_type,
)
from pagebuilder.models import MediaAsset
from pagebuilder.settings import PagebuilderSettings

_DEFAULT_PAGE_SIZE = 60
_MAX_PAGE_SIZE = 200

# Re-exported: callers reach for these through the service module.
__all__ = ["MediaService", "normalize_folder"]


class MediaService:
    def __init__(self, db: AsyncSession, settings: PagebuilderSettings) -> None:
        self.db = db
        self.settings = settings

    @property
    def storage_root(self) -> Path:
        return Path(self.settings.media_root).resolve()

    def url_for(self, filename: str) -> str:
        return f"{self.settings.media_url_prefix.rstrip('/')}/{filename}"

    def to_read(self, asset: MediaAsset) -> MediaAssetRead:
        variants = {
            key: MediaAssetVariant(
                filename=meta["filename"],
                url=self.url_for(meta["filename"]),
                content_type=meta["content_type"],
                width=meta["width"],
                height=meta.get("height"),
                size_bytes=meta.get("size_bytes", 0),
            )
            for key, meta in (asset.variants or {}).items()
        }
        return MediaAssetRead(
            id=asset.id or 0,
            filename=asset.filename,
            original_filename=asset.original_filename,
            content_type=asset.content_type,
            size_bytes=asset.size_bytes,
            url=self.url_for(asset.filename),
            width=asset.width,
            height=asset.height,
            folder=asset.folder,
            variants=variants,
            created_at=asset.created_at,
        )

    async def count_assets(self, **filters) -> int:
        """Total rows matching *filters* — pairs with offset paging."""
        return await media_queries.count_assets(self.db, **filters)

    async def list_assets(
        self,
        *,
        cursor: int | None = None,
        offset: int | None = None,
        limit: int = _DEFAULT_PAGE_SIZE,
        **filters,
    ) -> tuple[list[MediaAsset], int | None]:
        """One page of assets newest-first, plus the next cursor.

        See :func:`pagebuilder.media_queries.list_assets` for the two paging
        modes; the image-picker gallery uses the offset one.
        """
        return await media_queries.list_assets(
            self.db, cursor=cursor, offset=offset, limit=limit, **filters
        )

    async def list_folders(self) -> list[str]:
        """Return every distinct non-empty folder name, sorted."""
        result = await self.db.execute(
            select(MediaAsset.folder)
            .where(MediaAsset.folder.is_not(None))
            .distinct()
        )
        return sorted({row for row in result.scalars().all() if row})

    async def get_asset(self, asset_id: int) -> MediaAsset:
        asset = await self.db.get(MediaAsset, asset_id)
        if asset is None:
            raise HTTPException(status_code=404, detail="Asset not found")
        return asset

    async def upload(
        self,
        upload: UploadFile,
        *,
        folder: str | None = None,
    ) -> MediaAsset:
        folder_value = normalize_folder(folder)
        original = upload.filename or "upload"
        declared = upload.content_type or "application/octet-stream"
        allowed = self.settings.media_allowed_content_types
        if declared not in allowed:
            raise HTTPException(
                status_code=415,
                detail=f"Content-type {declared!r} is not allowed",
            )

        head = await upload.read(SNIFF_BYTES)
        sniffed = sniff_content_type(head)
        if sniffed is None or sniffed not in allowed:
            raise HTTPException(
                status_code=415,
                detail="File contents do not match an allowed image format",
            )
        if sniffed != declared:
            raise HTTPException(
                status_code=415,
                detail=(
                    f"Declared content-type {declared!r} does not match "
                    f"sniffed type {sniffed!r}"
                ),
            )
        content_type = sniffed

        # Pin the on-disk extension to the sniffed type so we never store
        # a JPEG under a `.png` name (StaticFiles serves the mime based
        # on the extension).
        ext = CONTENT_TYPE_EXTENSIONS.get(content_type) or safe_extension(original)
        filename = f"{uuid.uuid4().hex}{ext}"

        root = self.storage_root
        root.mkdir(parents=True, exist_ok=True)
        target = root / filename

        size = len(head)
        max_bytes = self.settings.media_max_bytes
        if size > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"File exceeds {max_bytes} bytes",
            )
        chunk_size = 64 * 1024
        with target.open("wb") as fh:
            fh.write(head)
            while True:
                chunk = await upload.read(chunk_size)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    fh.close()
                    target.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=413,
                        detail=f"File exceeds {max_bytes} bytes",
                    )
                fh.write(chunk)

        # Pillow's decode + webp encode are sync and CPU-bound — running
        # them on the event loop blocks other concurrent uploads. The
        # thread offload is essentially free for a single request and
        # turns parallel uploads back into parallel work.
        width, height, variants = await asyncio.to_thread(
            process_image,
            target,
            thumbnail_widths=self.settings.media_thumbnail_widths,
            webp_quality=self.settings.media_webp_quality,
        )

        asset = MediaAsset(
            filename=filename,
            original_filename=original,
            content_type=content_type,
            size_bytes=size,
            width=width,
            height=height,
            folder=folder_value,
            variants=variants,
        )
        self.db.add(asset)
        await self.db.flush()
        await self.db.refresh(asset)
        return asset

    async def delete(self, asset_id: int) -> None:
        asset = await self.get_asset(asset_id)
        root = self.storage_root
        (root / asset.filename).unlink(missing_ok=True)
        for meta in (asset.variants or {}).values():
            if isinstance(meta, dict):
                name = meta.get("filename")
                if name:
                    (root / name).unlink(missing_ok=True)
        await self.db.delete(asset)
        await self.db.flush()
