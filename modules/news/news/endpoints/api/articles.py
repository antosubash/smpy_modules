"""Article endpoints.

Reads are anonymous: the feed block runs on public pages, so a visitor with no
session has to be able to list articles. Writes require ``news.edit``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from simple_module_db import get_db
from sqlalchemy.exc import IntegrityError
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
from news.endpoints.api._deps import (
    already_an_article,
    cache,
    may_see_drafts,
    read_one_by_page,
    require_edit,
)

router = APIRouter()


@router.get("/articles", response_model=ArticleListResponse)
async def list_articles(
    request: Request,
    response: Response,
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
    in_feed: bool = Query(
        False,
        description="Only articles allowed in feed blocks. The admin list "
        "never sets this — hiding an article there would leave it unreachable "
        "from the one screen that can un-hide it.",
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
        in_feed_only=in_feed,
        include_drafts=may_draft,
        undated_first=undated_first,
    )
    # Tags in one query for the whole page rather than one per row — the list
    # renders 20 at a time, and per-row would make that 21 round trips.
    by_article = await tag_service.names_for_articles(db, [i.id for i in items])
    for item in items:
        item.tags = by_article.get(item.id, [])
    # Resolved once here rather than inside the count query: the listing
    # already turned a slug into a name, and counting against the raw slug
    # would report zero for every pill on a slug-filtered view.
    resolved = (
        await service.resolve_category_slug(db, category) or category if category else None
    )
    cache(response, include_drafts=may_draft)
    return ArticleListResponse(
        items=items,
        total=total,
        counts=await counts_module.count_by_status(
            db, category=resolved, q=q, include_drafts=may_draft
        ),
    )


@router.get("/categories", response_model=CategoryListResponse)
async def list_categories(
    request: Request, response: Response, db: AsyncSession = Depends(get_db)
) -> CategoryListResponse:
    """Counts per category, for the filter pills and the public feed block.

    Deliberately still the narrow ``{category, count}`` shape. The richer
    management view lives at ``/categories/manage`` so this published,
    anonymously-readable contract does not change under its consumers.
    """
    include_drafts = may_see_drafts(request)
    items = await service.list_categories(db, include_drafts=include_drafts)
    cache(response, include_drafts=include_drafts)
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
        raise already_an_article(body.page_id)
    try:
        await service.create(
            db,
            page_id=body.page_id,
            category=body.category,
            published_at=body.published_at,
            author=body.author,
        )
    except IntegrityError as exc:
        # The check above is not a lock: two requests attaching the same page
        # at once both pass it, and the loser meets the unique index on
        # `page_id` instead. That is the same conflict the check reports, so it
        # gets the same status rather than the 500 an unhandled database error
        # produced.
        await db.rollback()
        raise already_an_article(body.page_id) from exc
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
        pinned=body.pinned,
        show_in_feed=body.show_in_feed,
        author=body.author,
    )
    read = await read_one_by_page(db, article.page_id)
    read.tags = await tag_service.list_for_article(db, article.id or 0)
    return read


@router.get("/articles/{article_id}/tags", response_model=list[str])
async def list_article_tags(
    article_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> list[str]:
    """Tags on one article, under the same visibility rule as the listing.

    The gate is not optional here. ``PUBLIC_READ_PREFIXES`` is matched with
    ``str.startswith``, so this path is exempt from auth exactly like
    ``GET /articles`` is — and unlike that route it used to answer from
    ``NewsArticleTag`` alone, which never joins ``Page``. An anonymous visitor
    who guessed an id read the tags of an article nobody had published yet, and
    of one whose page was in the trash.

    Resolving through ``get_read_by_page`` rather than re-deriving the rule
    keeps it in one place: that query is the listing's own, so "visible" means
    the same thing here as it does there, including the trashed-page join.
    """
    article = await service.get(db, article_id)
    if article is not None:
        visible = await service.get_read_by_page(
            db, article.page_id, include_drafts=may_see_drafts(request)
        )
    # One message for both misses on purpose: a distinguishable "exists but is
    # hidden" would answer the question the 404 is there to refuse.
    if article is None or visible is None:
        raise HTTPException(status_code=404, detail="Article not found.")
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
