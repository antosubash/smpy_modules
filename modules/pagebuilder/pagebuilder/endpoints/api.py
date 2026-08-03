"""JSON admin API for the pagebuilder module.

Mounted by ``PagebuilderModule.register_routes`` under ``/api/pagebuilder``.

Per-endpoint :class:`~pagebuilder.permissions.RequiresPermission` deps
let hosts run the editor → publisher workflow without granting every
editor publish rights.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Query, UploadFile, status
from simple_module_db import get_db
from sqlalchemy.ext.asyncio import AsyncSession

from pagebuilder.contracts.schemas import (
    LayoutDetail,
    LayoutRevisionDetail,
    LayoutRevisionListResponse,
    LayoutRevisionRead,
    LayoutUpdate,
    MediaAssetListResponse,
    MediaAssetRead,
    PageCreate,
    PageDetail,
    PageListResponse,
    PageNoteRequest,
    PageRead,
    PageRejectRequest,
    PageRevisionDetail,
    PageRevisionListResponse,
    PageRevisionRead,
    PageScheduleRequest,
    PageUpdate,
    RevisionDiffResponse,
)
from pagebuilder.deps import get_media_service
from pagebuilder.layout_service import LayoutService
from pagebuilder.media_service import MediaService
from pagebuilder.permissions import (
    PERM_APPROVE,
    PERM_EDIT,
    PERM_PUBLISH,
    RequiresPermission,
)
from pagebuilder.service import _UNSET, PagesService

router = APIRouter()

_require_edit = Depends(RequiresPermission(PERM_EDIT))
_require_publish = Depends(RequiresPermission(PERM_PUBLISH))
_require_approve = Depends(RequiresPermission(PERM_APPROVE))


@router.get("/pages", response_model=PageListResponse)
async def list_pages(db: AsyncSession = Depends(get_db)) -> PageListResponse:
    pages = await PagesService(db).list_pages()
    return PageListResponse(items=[PageRead.model_validate(p) for p in pages])


@router.get(
    "/pages/pending",
    response_model=PageListResponse,
    dependencies=[_require_approve],
)
async def list_pending(db: AsyncSession = Depends(get_db)) -> PageListResponse:
    """Approver queue — pages currently in ``submitted_for_review``."""
    pages = await PagesService(db).list_pending()
    return PageListResponse(items=[PageRead.model_validate(p) for p in pages])


@router.post(
    "/pages",
    response_model=PageDetail,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_require_edit],
)
async def create_page(
    data: PageCreate, db: AsyncSession = Depends(get_db)
) -> PageDetail:
    page = await PagesService(db).create(data)
    return PageDetail.model_validate(page)


@router.get("/pages/{page_id}", response_model=PageDetail)
async def get_page(page_id: int, db: AsyncSession = Depends(get_db)) -> PageDetail:
    page = await PagesService(db).get_page(page_id)
    return PageDetail.model_validate(page)


@router.put(
    "/pages/{page_id}",
    response_model=PageDetail,
    dependencies=[_require_edit],
)
async def update_page(
    page_id: int,
    data: PageUpdate,
    db: AsyncSession = Depends(get_db),
) -> PageDetail:
    page = await PagesService(db).update(page_id, data)
    return PageDetail.model_validate(page)


@router.delete(
    "/pages/{page_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[_require_edit],
)
async def delete_page(page_id: int, db: AsyncSession = Depends(get_db)) -> None:
    await PagesService(db).delete(page_id)


def _note(body: PageNoteRequest | None) -> str | None:
    return body.note if body else None


@router.post(
    "/pages/{page_id}/publish",
    response_model=PageRead,
    dependencies=[_require_publish],
)
async def publish_page(
    page_id: int,
    db: AsyncSession = Depends(get_db),
    body: PageNoteRequest | None = None,
) -> PageRead:
    """Publish the current draft. The optional ``note`` is captured on
    the revision row so the history panel can label the publish."""
    page = await PagesService(db).publish(page_id, note=_note(body))
    return PageRead.model_validate(page)


@router.post(
    "/pages/{page_id}/unpublish",
    response_model=PageRead,
    dependencies=[_require_publish],
)
async def unpublish_page(
    page_id: int,
    db: AsyncSession = Depends(get_db),
    body: PageNoteRequest | None = None,
) -> PageRead:
    page = await PagesService(db).unpublish(page_id, note=_note(body))
    return PageRead.model_validate(page)


@router.post(
    "/pages/{page_id}/submit",
    response_model=PageRead,
    dependencies=[_require_edit],
)
async def submit_page(
    page_id: int,
    db: AsyncSession = Depends(get_db),
    body: PageNoteRequest | None = None,
) -> PageRead:
    """Editor action: hand a draft off to the approver queue."""
    page = await PagesService(db).submit_for_review(page_id, note=_note(body))
    return PageRead.model_validate(page)


@router.post(
    "/pages/{page_id}/approve",
    response_model=PageRead,
    dependencies=[_require_approve],
)
async def approve_page(
    page_id: int,
    db: AsyncSession = Depends(get_db),
    body: PageNoteRequest | None = None,
) -> PageRead:
    """Approver action: take a submission live (also publishes)."""
    page = await PagesService(db).approve(page_id, note=_note(body))
    return PageRead.model_validate(page)


@router.post(
    "/pages/{page_id}/schedule",
    response_model=PageRead,
    dependencies=[_require_publish],
)
async def schedule_page(
    page_id: int,
    body: PageScheduleRequest,
    db: AsyncSession = Depends(get_db),
) -> PageRead:
    """Set or clear scheduled flip timestamps.

    Each field uses ``model_fields_set`` to distinguish "field absent"
    (leave the existing value alone) from ``"field": null`` (clear). So
    ``POST {"publish_at": "..."}`` only touches ``publish_at`` and leaves
    ``unpublish_at`` as-is.
    """
    publish_at = body.publish_at if "publish_at" in body.model_fields_set else _UNSET
    unpublish_at = (
        body.unpublish_at if "unpublish_at" in body.model_fields_set else _UNSET
    )
    page = await PagesService(db).schedule(
        page_id,
        publish_at=publish_at,
        unpublish_at=unpublish_at,
    )
    return PageRead.model_validate(page)


@router.post(
    "/pages/{page_id}/reject",
    response_model=PageRead,
    dependencies=[_require_approve],
)
async def reject_page(
    page_id: int,
    body: PageRejectRequest,
    db: AsyncSession = Depends(get_db),
) -> PageRead:
    """Approver action: send a submission back to draft with feedback."""
    page = await PagesService(db).reject(page_id, body.note)
    return PageRead.model_validate(page)


@router.get("/pages/{page_id}/revisions", response_model=PageRevisionListResponse)
async def list_revisions(
    page_id: int,
    db: AsyncSession = Depends(get_db),
) -> PageRevisionListResponse:
    service = PagesService(db)
    await service.get_page(page_id)
    revisions = await service.list_revisions(page_id)
    return PageRevisionListResponse(
        items=[PageRevisionRead.model_validate(r) for r in revisions]
    )


@router.get(
    "/pages/{page_id}/revisions/{revision_id}",
    response_model=PageRevisionDetail,
)
async def get_revision(
    page_id: int,
    revision_id: int,
    db: AsyncSession = Depends(get_db),
) -> PageRevisionDetail:
    revision = await PagesService(db).get_revision(page_id, revision_id)
    return PageRevisionDetail.model_validate(revision)


@router.get(
    "/pages/{page_id}/revisions/{before_id}/diff/{after_id}",
    response_model=RevisionDiffResponse,
    response_model_exclude_none=True,
)
async def diff_revisions(
    page_id: int,
    before_id: int,
    after_id: int,
    db: AsyncSession = Depends(get_db),
) -> RevisionDiffResponse:
    """Block-level diff between two revisions.

    The URL spells the direction explicitly (``before`` vs ``after``)
    rather than relying on numeric ordering — restoring an older
    revision can produce a higher id with older content, so id sort
    isn't a reliable proxy for chronology.
    """
    result = await PagesService(db).diff_revisions(page_id, before_id, after_id)
    return RevisionDiffResponse.model_validate(result)


@router.post(
    "/pages/{page_id}/revisions/{revision_id}/restore",
    response_model=PageDetail,
    dependencies=[_require_edit],
)
async def restore_revision(
    page_id: int,
    revision_id: int,
    db: AsyncSession = Depends(get_db),
) -> PageDetail:
    page = await PagesService(db).restore_revision(page_id, revision_id)
    return PageDetail.model_validate(page)


@router.get("/layout", response_model=LayoutDetail)
async def get_layout(db: AsyncSession = Depends(get_db)) -> LayoutDetail:
    """Return the site-wide layout. Created lazily on first read."""
    layout = await LayoutService(db).get()
    return LayoutDetail.model_validate(layout)


@router.put(
    "/layout",
    response_model=LayoutDetail,
    dependencies=[_require_edit],
)
async def update_layout(
    body: LayoutUpdate,
    db: AsyncSession = Depends(get_db),
) -> LayoutDetail:
    layout = await LayoutService(db).update(
        header_data=body.header_data,
        footer_data=body.footer_data,
        note=body.note,
    )
    return LayoutDetail.model_validate(layout)


@router.get("/layout/revisions", response_model=LayoutRevisionListResponse)
async def list_layout_revisions(
    db: AsyncSession = Depends(get_db),
) -> LayoutRevisionListResponse:
    revisions = await LayoutService(db).list_revisions()
    return LayoutRevisionListResponse(
        items=[LayoutRevisionRead.model_validate(r) for r in revisions]
    )


@router.get(
    "/layout/revisions/{revision_id}",
    response_model=LayoutRevisionDetail,
)
async def get_layout_revision(
    revision_id: int,
    db: AsyncSession = Depends(get_db),
) -> LayoutRevisionDetail:
    revision = await LayoutService(db).get_revision(revision_id)
    return LayoutRevisionDetail.model_validate(revision)


@router.post(
    "/layout/revisions/{revision_id}/restore",
    response_model=LayoutDetail,
    dependencies=[_require_edit],
)
async def restore_layout_revision(
    revision_id: int,
    db: AsyncSession = Depends(get_db),
) -> LayoutDetail:
    layout = await LayoutService(db).restore(revision_id)
    return LayoutDetail.model_validate(layout)


@router.get("/uploads", response_model=MediaAssetListResponse)
async def list_uploads(
    media: MediaService = Depends(get_media_service),
    search: str | None = Query(default=None, max_length=200),
    content_type: str | None = Query(default=None, max_length=120),
    folder: str | None = Query(default=None, max_length=300),
    min_size_bytes: int | None = Query(default=None, ge=0),
    max_size_bytes: int | None = Query(default=None, ge=0),
    cursor: int | None = Query(default=None, ge=1),
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
    assets, next_cursor = await media.list_assets(
        search=search,
        content_type=content_type,
        folder=folder_filter,
        unfiled_only=unfiled_only,
        min_size_bytes=min_size_bytes,
        max_size_bytes=max_size_bytes,
        cursor=cursor,
        limit=limit,
    )
    folders = await media.list_folders()
    return MediaAssetListResponse(
        items=[media.to_read(a) for a in assets],
        next_cursor=next_cursor,
        folders=folders,
    )


@router.post(
    "/uploads",
    response_model=MediaAssetRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_require_edit],
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
    dependencies=[_require_edit],
)
async def delete_upload(
    asset_id: int,
    media: MediaService = Depends(get_media_service),
) -> None:
    await media.delete(asset_id)
