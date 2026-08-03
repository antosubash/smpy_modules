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

    async def list_assets(
        self,
        *,
        search: str | None = None,
        content_type: str | None = None,
        folder: str | None = None,
        unfiled_only: bool = False,
        min_size_bytes: int | None = None,
        max_size_bytes: int | None = None,
        cursor: int | None = None,
        limit: int = _DEFAULT_PAGE_SIZE,
    ) -> tuple[list[MediaAsset], int | None]:
        """Return one page of assets newest-first plus the next cursor.

        The cursor is the smallest ``id`` returned on the previous page;
        callers fetch the next page by passing it as ``cursor``. The
        function asks the DB for ``limit + 1`` rows so it can detect the
        end of the list without a separate ``count()`` query.

        Pass ``unfiled_only=True`` to limit to rows with ``folder IS NULL``
        (the sidebar's "Unfiled" bucket). ``folder`` and ``unfiled_only``
        are mutually exclusive at the call site.
        """
        page_size = max(1, min(limit, _MAX_PAGE_SIZE))
        stmt = select(MediaAsset)
        if search:
            # SQLite LIKE is case-insensitive for ASCII by default; this
            # matches what users expect ("hero" finds "Hero.jpg").
            stmt = stmt.where(MediaAsset.original_filename.like(f"%{search}%"))
        if content_type:
            if content_type.endswith("/*"):
                prefix = content_type[:-1]
                stmt = stmt.where(MediaAsset.content_type.like(f"{prefix}%"))
            else:
                stmt = stmt.where(MediaAsset.content_type == content_type)
        if unfiled_only:
            stmt = stmt.where(MediaAsset.folder.is_(None))
        elif folder is not None:
            stmt = stmt.where(MediaAsset.folder == folder)
        if min_size_bytes is not None:
            stmt = stmt.where(MediaAsset.size_bytes >= min_size_bytes)
        if max_size_bytes is not None:
            stmt = stmt.where(MediaAsset.size_bytes <= max_size_bytes)
        if cursor is not None:
            stmt = stmt.where(MediaAsset.id < cursor)
        stmt = stmt.order_by(MediaAsset.id.desc()).limit(page_size + 1)
        result = await self.db.execute(stmt)
        rows = list(result.scalars().all())
        next_cursor: int | None = None
        if len(rows) > page_size:
            rows = rows[:page_size]
            tail = rows[-1].id
            next_cursor = tail
        return rows, next_cursor

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
