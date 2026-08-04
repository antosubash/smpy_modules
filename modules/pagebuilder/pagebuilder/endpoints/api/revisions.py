"""Page revision history, diffing, and restore."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from simple_module_db import get_db
from sqlalchemy.ext.asyncio import AsyncSession

from pagebuilder.contracts.schemas import (
    PageDetail,
    PageRevisionDetail,
    PageRevisionListResponse,
    PageRevisionRead,
    RevisionDiffResponse,
)
from pagebuilder.endpoints.api._deps import require_edit
from pagebuilder.service import PagesService

router = APIRouter()


@router.get("/pages/{page_id}/revisions", response_model=PageRevisionListResponse)
async def list_revisions(
    page_id: int,
    db: AsyncSession = Depends(get_db),
) -> PageRevisionListResponse:
    service = PagesService(db)
    await service.get_page(page_id)
    revisions = await service.list_revisions(page_id)
    return PageRevisionListResponse(items=[PageRevisionRead.model_validate(r) for r in revisions])


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
    dependencies=[require_edit],
)
async def restore_revision(
    page_id: int,
    revision_id: int,
    db: AsyncSession = Depends(get_db),
) -> PageDetail:
    page = await PagesService(db).restore_revision(page_id, revision_id)
    return PageDetail.model_validate(page)
