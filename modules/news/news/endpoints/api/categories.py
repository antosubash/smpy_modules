"""Category management endpoints.

Mounted under ``/taxonomy`` rather than alongside the public
``/categories`` listing on purpose: ``register_public_routes`` opens every GET
under ``/api/news/categories`` to anonymous callers, so an admin listing placed
there would publish per-category draft counts to the world.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from simple_module_db import get_db
from sqlalchemy.ext.asyncio import AsyncSession

from news import category_service
from news.constants import UNCATEGORISED_LABEL
from news.contracts.schemas import (
    CategoryAdminListResponse,
    CategoryCreate,
    CategoryDeleteResult,
    CategoryRead,
    CategoryReorder,
    CategoryUpdate,
)
from news.endpoints.api._deps import require_edit

router = APIRouter(prefix="/taxonomy", dependencies=[require_edit])


async def _load(db: AsyncSession, category_id: int):
    category = await category_service.get(db, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found.")
    return category


@router.get("/categories", response_model=CategoryAdminListResponse)
async def list_categories(
    db: AsyncSession = Depends(get_db),
) -> CategoryAdminListResponse:
    return CategoryAdminListResponse(items=await category_service.list_categories(db))


@router.post("/categories", response_model=CategoryRead, status_code=201)
async def create_category(
    body: CategoryCreate, db: AsyncSession = Depends(get_db)
) -> CategoryRead:
    if body.name.strip().lower() == UNCATEGORISED_LABEL.lower():
        # Not a real row anywhere — it is the empty-category bucket. Letting
        # one be created would produce two rows on the screen claiming the same
        # articles, only one of which counts them.
        raise HTTPException(
            status_code=409,
            detail=f"{UNCATEGORISED_LABEL} is a system category and always exists.",
        )
    if await category_service.get_by_name(db, body.name) is not None:
        raise HTTPException(
            status_code=409, detail=f"A category named {body.name!r} already exists."
        )
    category = await category_service.create(db, name=body.name, slug=body.slug)
    return CategoryRead(
        id=category.id or 0,
        name=category.name,
        slug=category.slug,
        position=category.position,
        article_count=0,
        is_system=False,
    )


@router.put("/categories/{category_id}", response_model=CategoryRead)
async def update_category(
    category_id: int, body: CategoryUpdate, db: AsyncSession = Depends(get_db)
) -> CategoryRead:
    """Rename, re-slug, or both. Renaming carries the articles with it."""
    category = await _load(db, category_id)
    if body.name is not None and body.name != category.name:
        if body.name.strip().lower() == UNCATEGORISED_LABEL.lower():
            # The same rule `create_category` enforces. Without it here, the
            # name is reachable by the back door: rename any category into it
            # and the screen shows two Uncategorised rows — a real one holding
            # these articles, and the synthetic bucket `list_categories`
            # always appends.
            raise HTTPException(
                status_code=409,
                detail=f"{UNCATEGORISED_LABEL} is a system category and always exists.",
            )
        clash = await category_service.get_by_name(db, body.name)
        if clash is not None:
            raise HTTPException(
                status_code=409,
                detail=f"A category named {body.name!r} already exists.",
            )
    updated = await category_service.rename(
        db, category, name=body.name, slug=body.slug
    )
    counts = {c.name: c.article_count for c in await category_service.list_categories(db)}
    return CategoryRead(
        id=updated.id or 0,
        name=updated.name,
        slug=updated.slug,
        position=updated.position,
        article_count=counts.get(updated.name, 0),
        is_system=False,
    )


@router.post("/categories/reorder", status_code=204)
async def reorder_categories(
    body: CategoryReorder, db: AsyncSession = Depends(get_db)
) -> None:
    await category_service.reorder(db, body.ordered_ids)


@router.delete("/categories/{category_id}", response_model=CategoryDeleteResult)
async def delete_category(
    category_id: int,
    reassign_to: str = "",
    db: AsyncSession = Depends(get_db),
) -> CategoryDeleteResult:
    """Delete the category and move its articles.

    ``reassign_to`` is a category *name*; empty means Uncategorised. No article
    is ever deleted here — that is the promise the screen makes before asking.
    """
    category = await _load(db, category_id)
    if (
        reassign_to
        and reassign_to != category.name
        and await category_service.get_by_name(db, reassign_to) is None
    ):
        raise HTTPException(
            status_code=404,
            detail=f"Cannot reassign to {reassign_to!r}: no such category.",
        )
    moved = await category_service.delete(db, category, reassign_to=reassign_to)
    return CategoryDeleteResult(reassigned=moved)
