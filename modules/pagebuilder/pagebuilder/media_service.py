"""Storage + DB operations for uploaded media assets.

Files live on the local filesystem under
:attr:`PagebuilderSettings.media_root` and are served via a StaticFiles
mount registered in :meth:`PagebuilderModule.on_startup`. The DB row
holds the sanitized filename, original name, content-type, byte size,
intrinsic dimensions, and a ``variants`` map of server-generated
thumbnails. Public URLs are derived as
``f"{settings.media_url_prefix}/{filename}"``.
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from pagebuilder.contracts.schemas import MediaAssetRead, MediaAssetVariant
from pagebuilder.models import MediaAsset
from pagebuilder.settings import PagebuilderSettings

logger = logging.getLogger(__name__)

_EXT_RE = re.compile(r"\.[A-Za-z0-9]{1,8}$")

# Folders are user-supplied path-like strings, so we constrain the
# alphabet and reject traversal segments before they reach the DB.
_FOLDER_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_FOLDER_MAX_LENGTH = 300
_DEFAULT_PAGE_SIZE = 60
_MAX_PAGE_SIZE = 200


def normalize_folder(raw: str | None) -> str | None:
    """Canonicalize a folder path or raise 422.

    Strips surrounding slashes/whitespace, collapses double slashes,
    and validates each segment against ``_FOLDER_SEGMENT_RE``. An empty
    or ``None`` input becomes ``None`` (the asset is unfiled).
    """
    if raw is None:
        return None
    cleaned = raw.strip().strip("/")
    if not cleaned:
        return None
    if len(cleaned) > _FOLDER_MAX_LENGTH:
        raise HTTPException(status_code=422, detail="Folder path is too long")
    segments = [seg for seg in cleaned.split("/") if seg]
    for segment in segments:
        if segment in {".", ".."} or not _FOLDER_SEGMENT_RE.match(segment):
            raise HTTPException(
                status_code=422,
                detail=(
                    "Folder segments must start with an alphanumeric and "
                    "contain only letters, digits, '.', '_' or '-'"
                ),
            )
    return "/".join(segments)

# Header signatures for the formats this module accepts. We sniff the
# first bytes of every upload so a malicious client can't claim
# `image/png` while shipping HTML/JS/PHP that StaticFiles would later
# serve back under a same-origin URL. Pure-Python so no native dep.
_SNIFF_BYTES = 64

_MAGIC_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)

# WebP needs a two-part check (RIFF + WEBP at offset 8); handled inline.
_CONTENT_TYPE_EXTENSIONS: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
}


def _sniff_content_type(head: bytes) -> str | None:
    for sig, ctype in _MAGIC_SIGNATURES:
        if head.startswith(sig):
            return ctype
    if len(head) >= 12 and head[0:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None


def _safe_extension(name: str) -> str:
    match = _EXT_RE.search(name or "")
    return match.group(0).lower() if match else ""


def _is_animated(image: Image.Image) -> bool:
    """Detect multi-frame images we should leave alone.

    Pillow can downscale individual frames of animated GIF/WEBP but
    re-encoding the animation into webp is a different code path and
    the issue's acceptance criteria explicitly say animated GIFs skip
    transcoding. ``getattr`` defends against formats where Pillow
    doesn't set ``is_animated`` at all.
    """
    return bool(getattr(image, "is_animated", False))


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

        head = await upload.read(_SNIFF_BYTES)
        sniffed = _sniff_content_type(head)
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
        ext = _CONTENT_TYPE_EXTENSIONS.get(content_type) or _safe_extension(original)
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
        width, height, variants = await asyncio.to_thread(self._process_image, target)

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

    def _process_image(
        self, source: Path
    ) -> tuple[int | None, int | None, dict[str, Any]]:
        """Extract dimensions and generate webp thumbnails for a raster image.

        Returns ``(width, height, variants)``. On any failure (corrupt
        file, format Pillow can't decode, animated image) returns
        ``(None, None, {})`` so the upload still completes — the original
        is served as-is and the Image block falls back to a plain
        ``<img src>``.
        """
        try:
            with Image.open(source) as image:
                src_w, src_h = image.size
                if src_w <= 0 or src_h <= 0:
                    return src_w or None, src_h or None, {}
                # Capture dimensions even for animated images — the
                # original is still served, and a known intrinsic size
                # lets the Image block emit width/height to avoid CLS.
                if _is_animated(image):
                    return src_w, src_h, {}
                image.load()
                variants = self._generate_thumbnails(image, source, src_w, src_h)
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            # Logged at INFO because this is expected for corrupt or
            # exotic-but-valid uploads — not a code bug.
            logger.info("Skipping image processing for %s: %s", source.name, exc)
            return None, None, {}
        return src_w, src_h, variants

    def _generate_thumbnails(
        self,
        image: Image.Image,
        source: Path,
        src_w: int,
        src_h: int,
    ) -> dict[str, Any]:
        widths = sorted({w for w in self.settings.media_thumbnail_widths if w > 0})
        if not widths:
            return {}
        # Webp doesn't support paletted/CMYK directly the same way; convert
        # once up front so each resize doesn't re-do the work.
        if image.mode not in ("RGB", "RGBA"):
            base = image.convert("RGBA" if "A" in image.mode else "RGB")
        else:
            base = image
        stem = source.stem
        out_dir = source.parent
        quality = self.settings.media_webp_quality
        variants: dict[str, Any] = {}
        for width in widths:
            if width >= src_w:
                # No upscaling — skip widths at or above the source. The
                # original file already covers visitors at full size.
                continue
            ratio = width / src_w
            height = max(1, round(src_h * ratio))
            resized = base.resize((width, height), Image.Resampling.LANCZOS)
            out_name = f"{stem}_w{width}.webp"
            out_path = out_dir / out_name
            # method=4 is Google's recommended encoder default — method=6
            # is ~5x slower for marginal byte-size gains at q=82.
            resized.save(out_path, format="WEBP", quality=quality, method=4)
            variants[f"w{width}"] = {
                "filename": out_name,
                "content_type": "image/webp",
                "width": width,
                "height": height,
                "size_bytes": out_path.stat().st_size,
            }
        return variants
