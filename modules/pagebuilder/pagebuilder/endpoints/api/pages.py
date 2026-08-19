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


@router.get("/pages/trash", response_model=PageListResponse, dependencies=[require_edit])
async def list_trash(db: AsyncSession = Depends(get_db)) -> PageListResponse:
    """Pages waiting out the retention window.

    Declared above "/pages/{page_id}" with the other literal paths, or "trash"
    is parsed as a page id and answers 422.
    """
    pages = await PagesService(db).list_trash()
    return PageListResponse(items=[PageRead.model_validate(p) for p in pages], total=len(pages))


@router.get("/pages/templates", response_model=PageListResponse)
async def list_templates(db: AsyncSession = Depends(get_db)) -> PageListResponse:
    """Starting points offered by the New page dialog.

    Declared with the other literal paths, above "/pages/{page_id}", or
    "templates" is parsed as a page id and answers 422.
    """
    pages = await PagesService(db).list_templates()
    return PageListResponse(items=[PageRead.model_validate(p) for p in pages], total=len(pages))


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


@router.post(
    "/pages/{page_id}/restore",
    response_model=PageDetail,
    dependencies=[require_edit],
)
async def restore_page(page_id: int, db: AsyncSession = Depends(get_db)) -> PageDetail:
    """Bring a page back out of the trash. It returns as a draft."""
    page = await PagesService(db).restore(page_id)
    return PageDetail.model_validate(page)


@router.delete(
    "/pages/{page_id}/purge",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[require_edit],
)
async def purge_page(
    page_id: int, request: Request, db: AsyncSession = Depends(get_db)
) -> None:
    """Remove a trashed page for good. Not reversible.

    Carries the bus for the same reason the soft delete no longer does: this is
    the point at which other modules must drop what they keyed to the page.
    """
    bus = getattr(request.app.state.sm, "event_bus", None)
    await PagesService(db, event_bus=bus).purge(page_id)


@router.delete(
    "/pages/{page_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[require_edit],
)
async def delete_page(page_id: int, db: AsyncSession = Depends(get_db)) -> None:
    """Move the page to trash. Reversible until the retention sweep runs.

    Deliberately publishes nothing: `PageDeleted` is what tells other modules to
    drop their own rows, and a restore would then bring the page back stripped
    of everything keyed to it. That event belongs to purge.
    """
    await PagesService(db).delete(page_id)
