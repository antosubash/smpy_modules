"""Article endpoints.

Reads are anonymous: the feed block runs on public pages, so a visitor with no
session has to be able to list articles. Writes require ``news.edit``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from simple_module_db import get_db
from sqlalchemy.ext.asyncio import AsyncSession

from news import counts as counts_module
from news import service, tag_service
from news.constants import DEFAULT_LIMIT, MAX_LIMIT
from news.contracts.schemas import (
    ArticleCreate,
    ArticleListResponse,
    ArticleRead,
    ArticleTagsUpdate,
    ArticleUpdate,
    CategoryListResponse,
)
from news.endpoints.api._deps import may_see_drafts, read_one_by_page, require_edit

router = APIRouter()


@router.get("/articles", response_model=ArticleListResponse)
async def list_articles(
    request: Request,
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
    category: str | None = Query(None),
    q: str | None = Query(
        None,
        description="Free-text filter over headline and slug. Applied before "
        "paging, so `total` reflects the search rather than the whole list.",
    ),
    status: str | None = Query(
        None,
        description="`draft`, `published` or `undated`. Anyone who may not see "
        "drafts gets the published set whatever they ask for.",
    ),
    undated_first: bool = Query(
        False,
        description="Sort undated (work-in-progress) articles before dated "
        "ones — what the admin list wants. Public feeds keep the default, "
        "which pushes undated articles to the end.",
    ),
    db: AsyncSession = Depends(get_db),
) -> ArticleListResponse:
    may_draft = may_see_drafts(request)
    items, total = await service.list_articles(
        db,
        limit=limit,
        offset=offset,
        category=category,
        q=q,
        status=status,
        include_drafts=may_draft,
        undated_first=undated_first,
    )
    # Resolved once here rather than inside the count query: the listing
    # already turned a slug into a name, and counting against the raw slug
    # would report zero for every pill on a slug-filtered view.
    resolved = (
        await service.resolve_category_slug(db, category) or category if category else None
    )
    return ArticleListResponse(
        items=items,
        total=total,
        counts=await counts_module.count_by_status(
            db, category=resolved, q=q, include_drafts=may_draft
        ),
    )


@router.get("/categories", response_model=CategoryListResponse)
async def list_categories(
    request: Request, db: AsyncSession = Depends(get_db)
) -> CategoryListResponse:
    """Counts per category, for the filter pills and the public feed block.

    Deliberately still the narrow ``{category, count}`` shape. The richer
    management view lives at ``/categories/manage`` so this published,
    anonymously-readable contract does not change under its consumers.
    """
    items = await service.list_categories(db, include_drafts=may_see_drafts(request))
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
    if not await service.page_exists(db, body.page_id):
        raise HTTPException(status_code=404, detail=f"Page {body.page_id} does not exist.")
    if await service.get_by_page(db, body.page_id) is not None:
        raise HTTPException(
            status_code=409, detail=f"Page {body.page_id} is already an article."
        )
    await service.create(
        db, page_id=body.page_id, category=body.category, published_at=body.published_at
    )
    return await read_one_by_page(db, body.page_id)


@router.put(
    "/articles/{article_id}", response_model=ArticleRead, dependencies=[require_edit]
)
async def update_article(
    article_id: int, body: ArticleUpdate, db: AsyncSession = Depends(get_db)
) -> ArticleRead:
    article = await service.get(db, article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found.")
    # A partial update: an omitted `published_at` leaves the date alone, while
    # an explicit null undates the article. Only `model_fields_set` can tell
    # those apart, and the distinction is the endpoint's to make.
    await service.update(
        db,
        article,
        category=body.category,
        published_at=(
            body.published_at
            if "published_at" in body.model_fields_set
            else service.UNSET
        ),
    )
    return await read_one_by_page(db, article.page_id)


@router.get("/articles/{article_id}/tags", response_model=list[str])
async def list_article_tags(
    article_id: int, db: AsyncSession = Depends(get_db)
) -> list[str]:
    return await tag_service.list_for_article(db, article_id)


@router.put(
    "/articles/{article_id}/tags",
    response_model=list[str],
    dependencies=[require_edit],
)
async def set_article_tags(
    article_id: int, body: ArticleTagsUpdate, db: AsyncSession = Depends(get_db)
) -> list[str]:
    """Replace the article's tags, creating any name that is new."""
    if await service.get(db, article_id) is None:
        raise HTTPException(status_code=404, detail="Article not found.")
    return await tag_service.set_for_article(db, article_id, body.tags)


@router.delete("/articles/{article_id}", status_code=204, dependencies=[require_edit])
async def detach_article(article_id: int, db: AsyncSession = Depends(get_db)) -> None:
    """Detach the metadata. The page, and its body, stays."""
    article = await service.get(db, article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found.")
    await service.delete(db, article)
