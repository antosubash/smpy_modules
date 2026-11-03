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

from fastapi import Depends, HTTPException
from simple_module_db import get_db
from sqlalchemy.ext.asyncio import AsyncSession

from news.content import service
from news.content._fresh import ensure_fresh
from news.content.articles import ArticlesService
from news.contracts.schemas import (
    ArticleCreate,
    ArticleRead,
    ArticleUpdate,
)
from news.web.endpoints.api._article_listing import router
from news.web.endpoints.api._deps import (
    checked_locale,
    read_one,
    require_edit,
    require_publish,
)


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
    language is a sibling — see :mod:`news.web.endpoints.api.translations`.
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

    ensure_fresh(article, body.expected_updated_at)

    sent = body.model_dump(exclude_unset=True)
    sent.pop("expected_updated_at", None)
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
