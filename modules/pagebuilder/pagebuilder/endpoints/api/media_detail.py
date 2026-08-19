"""One asset: read it with its usage, describe it, or delete it.

Split from ``uploads.py`` because it answers a different question. That module
is about getting bytes in and out; this one is about what an asset *means* and
who depends on it.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from simple_module_db import get_db
from sqlalchemy.ext.asyncio import AsyncSession

from pagebuilder import media_usage
from pagebuilder.contracts.schemas import (
    MediaAssetDetail,
    MediaAssetUpdate,
    MediaUsage,
)
from pagebuilder.deps import get_media_service
from pagebuilder.endpoints.api._deps import require_edit
from pagebuilder.media_service import MediaService

router = APIRouter(dependencies=[require_edit])

#: Pages listed on the detail screen before it stops enumerating them.
_USAGE_LIMIT = 20


async def _load(media: MediaService, asset_id: int):
    """``get_asset`` already raises 404 for a missing id — kept as one call site
    so the three handlers cannot drift on what "missing" means."""
    return await media.get_asset(asset_id)


@router.get("/uploads/{asset_id}", response_model=MediaAssetDetail)
async def get_upload(
    asset_id: int,
    db: AsyncSession = Depends(get_db),
    media: MediaService = Depends(get_media_service),
) -> MediaAssetDetail:
    asset = await _load(media, asset_id)
    read = media.to_read(asset)
    usages, total = await media_usage.find(db, read.url, limit=_USAGE_LIMIT)
    return MediaAssetDetail(
        asset=read,
        used_in=[MediaUsage(**vars(u)) for u in usages],
        used_in_total=total,
    )


@router.put("/uploads/{asset_id}", response_model=MediaAssetDetail)
async def update_upload(
    asset_id: int,
    body: MediaAssetUpdate,
    db: AsyncSession = Depends(get_db),
    media: MediaService = Depends(get_media_service),
) -> MediaAssetDetail:
    """Describe the asset. Editing alt text updates every page using it at once,
    which is the reason it lives here rather than on each placement."""
    asset = await _load(media, asset_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(asset, field, value)
    db.add(asset)
    await db.flush()
    await db.refresh(asset)

    read = media.to_read(asset)
    usages, total = await media_usage.find(db, read.url, limit=_USAGE_LIMIT)
    return MediaAssetDetail(
        asset=read,
        used_in=[MediaUsage(**vars(u)) for u in usages],
        used_in_total=total,
    )


@router.delete("/uploads/{asset_id}/checked", status_code=status.HTTP_204_NO_CONTENT)
async def delete_if_unused(
    asset_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    media: MediaService = Depends(get_media_service),
) -> None:
    """Delete, but refuse while the asset is still on a page.

    Deleting an asset in use fails silently in the worst way: the row goes, the
    file goes, and the pages referencing it start serving a broken image that
    nobody notices. The 409 names the pages so the refusal is actionable rather
    than merely obstructive.
    """
    asset = await _load(media, asset_id)
    read = media.to_read(asset)
    usages, total = await media_usage.find(db, read.url, limit=_USAGE_LIMIT)
    if total:
        where = ", ".join(u.title for u in usages[:3])
        more = f" and {total - 3} more" if total > 3 else ""
        raise HTTPException(
            status_code=409,
            detail=f"Still used on {total} page(s): {where}{more}. Detach it there first.",
        )
    await media.delete(asset_id)
