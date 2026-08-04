"""Site-wide layout and its revision history."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from simple_module_db import get_db
from sqlalchemy.ext.asyncio import AsyncSession

from pagebuilder.contracts.schemas import (
    LayoutDetail,
    LayoutRevisionDetail,
    LayoutRevisionListResponse,
    LayoutRevisionRead,
    LayoutUpdate,
)
from pagebuilder.endpoints.api._deps import require_edit
from pagebuilder.layout_service import LayoutService

router = APIRouter()


@router.get("/layout", response_model=LayoutDetail)
async def get_layout(db: AsyncSession = Depends(get_db)) -> LayoutDetail:
    """Return the site-wide layout. Created lazily on first read."""
    layout = await LayoutService(db).get()
    return LayoutDetail.model_validate(layout)


@router.put(
    "/layout",
    response_model=LayoutDetail,
    dependencies=[require_edit],
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
    dependencies=[require_edit],
)
async def restore_layout_revision(
    revision_id: int,
    db: AsyncSession = Depends(get_db),
) -> LayoutDetail:
    layout = await LayoutService(db).restore(revision_id)
    return LayoutDetail.model_validate(layout)
