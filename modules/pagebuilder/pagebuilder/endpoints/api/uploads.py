"""Media upload, listing, and deletion."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Query, UploadFile, status

from pagebuilder.contracts.schemas import MediaAssetListResponse, MediaAssetRead
from pagebuilder.deps import get_media_service
from pagebuilder.endpoints.api._deps import require_edit
from pagebuilder.media_service import MediaService

router = APIRouter()


@router.get("/uploads", response_model=MediaAssetListResponse)
async def list_uploads(
    media: MediaService = Depends(get_media_service),
    search: str | None = Query(default=None, max_length=200),
    content_type: str | None = Query(default=None, max_length=120),
    folder: str | None = Query(default=None, max_length=300),
    min_size_bytes: int | None = Query(default=None, ge=0),
    max_size_bytes: int | None = Query(default=None, ge=0),
    cursor: int | None = Query(default=None, ge=1),
    offset: int | None = Query(
        default=None,
        ge=0,
        description=(
            'Offset paging, for callers that jump to an arbitrary page (the '
            'image-picker gallery). Takes precedence over `cursor` and makes '
            'the response carry `total`.'
        ),
    ),
    limit: int = Query(default=60, ge=1, le=200),
) -> MediaAssetListResponse:
    # ``folder`` absent → no folder filter. ``folder=""`` (or whitespace)
    # → the "Unfiled" sidebar bucket. Any other value → that exact path.
    folder_filter: str | None = None
    unfiled_only = False
    if folder is not None:
        trimmed = folder.strip().strip("/")
        if trimmed:
            folder_filter = trimmed
        else:
            unfiled_only = True
    filters = {
        "search": search,
        "content_type": content_type,
        "folder": folder_filter,
        "unfiled_only": unfiled_only,
        "min_size_bytes": min_size_bytes,
        "max_size_bytes": max_size_bytes,
    }
    assets, next_cursor = await media.list_assets(
        cursor=cursor, offset=offset, limit=limit, **filters
    )
    folders = await media.list_folders()
    # The COUNT is only worth running for offset callers; cursor paging
    # detects the end of the list from the row count it already fetched.
    total = await media.count_assets(**filters) if offset is not None else None
    return MediaAssetListResponse(
        items=[media.to_read(a) for a in assets],
        next_cursor=next_cursor,
        folders=folders,
        total=total,
    )


@router.post(
    "/uploads",
    response_model=MediaAssetRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[require_edit],
)
async def create_upload(
    file: UploadFile,
    folder: str | None = Form(default=None),
    media: MediaService = Depends(get_media_service),
) -> MediaAssetRead:
    asset = await media.upload(file, folder=folder)
    return media.to_read(asset)


@router.delete(
    "/uploads/{asset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[require_edit],
)
async def delete_upload(
    asset_id: int,
    media: MediaService = Depends(get_media_service),
) -> None:
    await media.delete(asset_id)
