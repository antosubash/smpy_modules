"""Article endpoints — listing, creation and the metadata writes.

Reads are anonymous: the feed block runs on public pages, so a visitor with no
session has to be able to list articles. Writes require ``news.edit``.

The body and the workflow live next door in :mod:`news.web.endpoints.api.body` and
:mod:`news.web.endpoints.api.workflow`, which is a split by *authority* rather than
by tidiness — publishing is gated on ``news.publish``, and an autosave must not
be able to reach a slug. An article's tags and its translations have modules of
their own because each is a separate resource with its own routes, not a field
of the article this module writes.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response
from simple_module_db import get_db
from sqlalchemy.ext.asyncio import AsyncSession

from news.content import counts as counts_module
from news.content import service
from news.content.taxonomy import tag_service
from news.contracts.schemas import (
    ArticleListResponse,
    CategoryListResponse,
)
from news.core import locales
from news.core.constants import DEFAULT_LIMIT, MAX_LIMIT
from news.web.endpoints.api._deps import (
    blank_filter,
    cache,
    may_see_drafts,
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
        description="Free-text filter over headline, address, excerpt and "
        "tags — what a card shows. Not the body: the admin search screen "
        "covers that, and it scans the *draft*, which a public route must not "
        "answer for. Applied before paging, so `total` reflects the search "
        "rather than the whole list.",
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
    tag: str | None = Query(
        None, description="Only articles carrying this tag, by slug or by name."
    ),
    trashed: bool = Query(
        False,
        description="The trash instead of the list — the complement of the "
        "filter every other listing applies. Anyone who may not see drafts "
        "gets nothing, because a trashed article is not published.",
    ),
    locale: str | None = Query(
        None,
        description="Only articles written in this language. A feed block on "
        "a German page passes `de` so it lists German articles; the admin list "
        "leaves it unset and shows every language, badged per row. An "
        "unconfigured value is ignored rather than rejected — the filter "
        "arrives from a query string, and a stale link should show the list.",
    ),
    group: str | None = Query(
        None,
        alias="translation_group",
        description="One article and its counterparts in other languages — "
        "what the editor's language switcher lists. Goes through this route "
        "rather than one of its own so it inherits the same visibility rule: "
        "a reader without `news.edit` sees the published translations only.",
    ),
    db: AsyncSession = Depends(get_db),
) -> ArticleListResponse:
    may_draft = may_see_drafts(request)
    if trashed and not may_draft:
        # An empty bin, not the ordinary listing. A trashed article is never
        # published, so there is nothing here such a caller may see — and
        # answering with the published list would silently return a different
        # question's answer to a client that asked for the trash. Not a 403
        # either: this route is anonymously readable, and refusing would
        # confirm the bin has something in it.
        cache(response, request, include_drafts=False)
        return ArticleListResponse(items=[], total=0)
    if blank_filter(group) or blank_filter(locale):
        # A filter supplied as nothing narrows to nothing. The reasoning is
        # on `blank_filter`, because that is the part that must not be
        # simplified away.
        cache(response, request, include_drafts=may_draft)
        return ArticleListResponse(items=[], total=0)
    items, total = await service.list_articles(
        db,
        limit=limit,
        offset=offset,
        category=category,
        tag=tag,
        q=q,
        status=status,
        locale=locales.resolve(locale),
        group=group,
        in_feed_only=in_feed,
        include_drafts=may_draft,
        undated_first=undated_first,
        trashed_only=trashed,
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
        await service.resolve_category_slug(db, category) or category
        if category
        else None
    )
    cache(response, request, include_drafts=may_draft)
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
    cache(response, request, include_drafts=include_drafts)
    return CategoryListResponse(items=items)
