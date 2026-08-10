"""Page CRUD and listing endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from simple_module_db import get_db
from sqlalchemy.ext.asyncio import AsyncSession

from pagebuilder.contracts.schemas import (
    PageCreate,
    PageDetail,
    PageListResponse,
    PageRead,
    PageUpdate,
    StatusFilter,
)
from pagebuilder.endpoints.api._deps import require_approve, require_edit
from pagebuilder.service import PagesService

router = APIRouter()


@router.get("/pages", response_model=PageListResponse)
async def list_pages(
    db: AsyncSession = Depends(get_db),
    search: str | None = None,
    status_filter: Annotated[StatusFilter, Query(alias="status")] = None,
    # Unbounded by default, deliberately: a seed reads this endpoint to build a
    # slug-to-id map, and a default page size would make it recreate pages it
    # already has. Callers that page ask for it.
    limit: int | None = Query(default=None, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> PageListResponse:
    pages, total = await PagesService(db).list_pages(
        search=search, status=status_filter, limit=limit, offset=offset
    )
    return PageListResponse(items=[PageRead.model_validate(p) for p in pages], total=total)


# Declared before "/pages/{page_id}" so the literal path wins the match.
# Keep these two adjacent — separating them across modules would make the
# ordering depend on router include order instead of being visible here.
@router.get(
    "/pages/pending",
    response_model=PageListResponse,
    dependencies=[require_approve],
)
async def list_pending(db: AsyncSession = Depends(get_db)) -> PageListResponse:
    """Approver queue — pages currently in ``submitted_for_review``."""
    pages = await PagesService(db).list_pending()
    return PageListResponse(items=[PageRead.model_validate(p) for p in pages], total=len(pages))


@router.post(
    "/pages",
    response_model=PageDetail,
    status_code=status.HTTP_201_CREATED,
    dependencies=[require_edit],
)
async def create_page(data: PageCreate, db: AsyncSession = Depends(get_db)) -> PageDetail:
    page = await PagesService(db).create(data)
    return PageDetail.model_validate(page)


@router.get("/pages/{page_id}", response_model=PageDetail)
async def get_page(page_id: int, db: AsyncSession = Depends(get_db)) -> PageDetail:
    page = await PagesService(db).get_page(page_id)
    return PageDetail.model_validate(page)


@router.put(
    "/pages/{page_id}",
    response_model=PageDetail,
    dependencies=[require_edit],
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
    dependencies=[require_edit],
)
async def delete_page(
    page_id: int, request: Request, db: AsyncSession = Depends(get_db)
) -> None:
    # The bus is passed only here: deleting a page is the one operation other
    # modules must hear about, because nothing at the database level can tell
    # them (no cross-module foreign keys, so no cascade).
    bus = getattr(request.app.state.sm, "event_bus", None)
    await PagesService(db, event_bus=bus).delete(page_id)
