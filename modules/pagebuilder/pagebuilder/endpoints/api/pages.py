"""Page CRUD and listing endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from simple_module_db import get_db
from sqlalchemy.ext.asyncio import AsyncSession

from pagebuilder.contracts.schemas import (
    PageCreate,
    PageDetail,
    PageListResponse,
    PageRead,
    PageUpdate,
)
from pagebuilder.endpoints.api._deps import require_approve, require_edit
from pagebuilder.service import PagesService

router = APIRouter()


@router.get("/pages", response_model=PageListResponse)
async def list_pages(db: AsyncSession = Depends(get_db)) -> PageListResponse:
    pages = await PagesService(db).list_pages()
    return PageListResponse(items=[PageRead.model_validate(p) for p in pages])


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
    return PageListResponse(items=[PageRead.model_validate(p) for p in pages])


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
async def delete_page(page_id: int, db: AsyncSession = Depends(get_db)) -> None:
    await PagesService(db).delete(page_id)
