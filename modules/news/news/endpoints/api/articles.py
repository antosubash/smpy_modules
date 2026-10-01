"""Article endpoints — listing, creation and the metadata writes.

Reads are anonymous: the feed block runs on public pages, so a visitor with no
session has to be able to list articles. Writes require ``news.edit``.

The body and the workflow live next door in :mod:`news.endpoints.api.body` and
:mod:`news.endpoints.api.workflow`, which is a split by *authority* rather than
by tidiness — publishing is gated on ``news.publish``, and an autosave must not
be able to reach a slug. An article's tags and its translations have modules of
their own for the ordinary reason: this file is at the repo's 300-line cap.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from simple_module_db import get_db
from sqlalchemy.ext.asyncio import AsyncSession

from news import counts as counts_module
from news import locales, service, tag_service
from news.constants import DEFAULT_LIMIT, MAX_LIMIT
from news.content import ArticlesService
from news.contracts.schemas import (
    ArticleCreate,
    ArticleListResponse,
    ArticleRead,
    ArticleUpdate,
    CategoryListResponse,
)
from news.endpoints.api._deps import (
    blank_filter,
    cache,
    checked_locale,
    may_see_drafts,
    read_one,
    require_edit,
    require_publish,
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
        cache(response, include_drafts=False)
        return ArticleListResponse(items=[], total=0)
    if blank_filter(group) or blank_filter(locale):
        # A filter supplied as nothing narrows to nothing. The reasoning is
        # on `blank_filter`, because that is the part that must not be
        # simplified away.
        cache(response, include_drafts=may_draft)
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
async def create_article(
    body: ArticleCreate, db: AsyncSession = Depends(get_db)
) -> ArticleRead:
    """Create an article, body and all, in one insert.

    This was two requests against two modules while an article was metadata
    *about* a page — and could only ever be half-done, stranding an empty page
    whenever the second call failed. One table means one write, so a failure
    leaves nothing behind to adopt.

    The language is chosen here and never again: it is fixed for the article's
    lifetime, because moving one between languages would strand its slug in the
    old one and orphan every redirect pointing at it. The counterpart in another
    language is a sibling — see :mod:`news.endpoints.api.translations`.
    """
    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="An article needs a headline.")
    article = await ArticlesService(db).create(
        title=title,
        slug=body.slug,
        locale=checked_locale(body.locale),
        category=body.category,
        published_at=body.published_at,
        author=body.author,
    )
    return await read_one(db, article.id or 0)


@router.put(
    "/articles/{article_id}", response_model=ArticleRead, dependencies=[require_edit]
)
async def update_article(
    article_id: int, body: ArticleUpdate, db: AsyncSession = Depends(get_db)
) -> ArticleRead:
    """Edit an article's metadata, identity and SEO — never its body.

    A partial update: an omitted ``published_at`` leaves the date alone, while
    an explicit null undates the article. Only ``model_fields_set`` can tell
    those apart, and the distinction is the endpoint's to make.
    """
    # Read once and kept. `ArticlesService.update` re-reads through the session
    # identity map, so it costs no second round trip — but re-running this
    # `select` further down did, and returned the very row already in hand.
    article = await service.get(db, article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found.")

    sent = body.model_dump(exclude_unset=True)
    # Split by who owns the write. The identity and SEO columns go through
    # ArticlesService because renaming a slug has to record a redirect; the
    # listing metadata does not, and routing it through the same path would
    # make every inline pin toggle look like a rename.
    identity = {
        field: sent.pop(field)
        for field in (
            "title",
            "slug",
            "meta_description",
            "og_image",
            "canonical_url",
            "index_in_search",
            "json_ld",
        )
        if field in sent
    }
    if identity:
        await ArticlesService(db).update(article_id, identity)

    if sent:
        await service.update(
            db,
            article,
            category=sent.get("category"),
            published_at=sent.get("published_at", service.UNSET),
            pinned=sent.get("pinned"),
            show_in_feed=sent.get("show_in_feed"),
            author=sent.get("author"),
        )

    return await read_one(db, article_id)


@router.delete(
    "/articles/{article_id}",
    status_code=204,
    dependencies=[require_edit, require_publish],
)
async def delete_article(
    article_id: int, db: AsyncSession = Depends(get_db)
) -> None:
    """Delete the article outright — body, tags and all.

    There is no longer a page left standing behind it, which is why this is a
    delete and not the "detach" it used to be: detaching removed news' metadata
    and left the document in pagebuilder, and with no such document there is
    nothing for that word to mean.

    Gated on ``news.publish`` as well as ``news.edit``, the same pair
    ``purge`` carries, because it is the same act: the row and its body go, and
    nothing brings them back. An author who may write is left the recoverable
    door — ``trash`` — which is what that permission split is for.
    """
    article = await service.get(db, article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found.")
    await service.delete(db, article)
