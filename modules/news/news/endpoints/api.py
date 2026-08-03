"""REST API for News.

Reads are anonymous: the feed block runs on public pages, so a visitor with no
session has to be able to list articles. Writes require ``news.edit``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from simple_module_db import get_db
from simple_module_hosting.permissions import RequiresPermission
from sqlalchemy.ext.asyncio import AsyncSession

from news import service
from news.constants import DEFAULT_LIMIT, MAX_LIMIT, PERM_EDIT
from news.contracts.schemas import (
    ArticleCreate,
    ArticleListResponse,
    ArticleRead,
    ArticleUpdate,
    CategoryListResponse,
)

router = APIRouter()

require_edit = Depends(RequiresPermission(PERM_EDIT))


def _may_see_drafts(request: Request) -> bool:
    """Only an editor sees articles whose page is still a draft.

    Everyone else gets the published site, which is what the public feed block
    must show.
    """
    user = getattr(request.state, "user", None)
    return PERM_EDIT in (getattr(user, "permissions", None) or [])


async def _read_one_by_page(db: AsyncSession, page_id: int) -> ArticleRead:
    """Re-read through the listing join so every response has one shape.

    Drafts are included: an editor has just written this row and must see it
    back whatever state its page is in.
    """
    items, _ = await service.list_articles(db, limit=MAX_LIMIT, include_drafts=True)
    for item in items:
        if item.page_id == page_id:
            return item
    # The page is the only source of slug and title, so without it there is
    # nothing to return.
    raise HTTPException(status_code=404, detail="Article's page not found.")


@router.get("/articles", response_model=ArticleListResponse)
async def list_articles(
    request: Request,
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
    category: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> ArticleListResponse:
    items, total = await service.list_articles(
        db,
        limit=limit,
        offset=offset,
        category=category,
        include_drafts=_may_see_drafts(request),
    )
    return ArticleListResponse(items=items, total=total)


@router.get("/categories", response_model=CategoryListResponse)
async def list_categories(
    request: Request, db: AsyncSession = Depends(get_db)
) -> CategoryListResponse:
    items = await service.list_categories(db, include_drafts=_may_see_drafts(request))
    return CategoryListResponse(items=items)


@router.post(
    "/articles",
    response_model=ArticleRead,
    status_code=201,
    dependencies=[require_edit],
)
async def attach_article(
    body: ArticleCreate, db: AsyncSession = Depends(get_db)
) -> ArticleRead:
    """Make an existing page an article."""
    if await service.get_by_page(db, body.page_id) is not None:
        raise HTTPException(
            status_code=409, detail=f"Page {body.page_id} is already an article."
        )
    await service.create(
        db, page_id=body.page_id, category=body.category, published_at=body.published_at
    )
    return await _read_one_by_page(db, body.page_id)


@router.put(
    "/articles/{article_id}", response_model=ArticleRead, dependencies=[require_edit]
)
async def update_article(
    article_id: int, body: ArticleUpdate, db: AsyncSession = Depends(get_db)
) -> ArticleRead:
    article = await service.get(db, article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found.")
    await service.update(
        db, article, category=body.category, published_at=body.published_at
    )
    return await _read_one_by_page(db, article.page_id)


@router.delete("/articles/{article_id}", status_code=204, dependencies=[require_edit])
async def detach_article(article_id: int, db: AsyncSession = Depends(get_db)) -> None:
    """Detach the metadata. The page, and its body, stays."""
    article = await service.get(db, article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found.")
    await service.delete(db, article)
