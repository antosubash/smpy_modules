"""The tags on one article — reading them, and replacing them.

Split from :mod:`news.endpoints.api.articles` rather than filed with the tag
CRUD in :mod:`news.endpoints.api.tags`, and both halves of that are deliberate.
These two routes are *about an article*, so they answer under ``/articles/…``
and follow the listing's visibility rule; the taxonomy routes are behind
``/taxonomy`` and behind ``news.edit`` wholesale, which the read below must not
be. Leaving them in ``articles`` was only ever thrift, and that file is at the
repo's 300-line cap.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from simple_module_db import get_db
from sqlalchemy.ext.asyncio import AsyncSession

from news import service, tag_service
from news.contracts.schemas import ArticleTagsUpdate
from news.endpoints.api._deps import may_see_drafts, require_edit
from news.tag_service import TagNameError

router = APIRouter()


@router.get("/articles/{article_id}/tags", response_model=list[str])
async def list_article_tags(
    article_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> list[str]:
    """Tags on one article, under the same visibility rule as the listing.

    The gate is not optional here. ``PUBLIC_READ_PREFIXES`` is matched with
    ``str.startswith``, so this path is exempt from auth exactly like
    ``GET /articles`` is — and it used to answer from ``NewsArticleTag`` alone,
    which never applied the visibility rule. An anonymous visitor who guessed an
    id read the tags of an article nobody had published yet.

    Resolving through ``service.get_read`` rather than re-deriving the rule
    keeps it in one place: that query is the listing's own, so "visible" means
    the same thing here as it does there, trash included.
    """
    visible = await service.get_read(
        db, article_id, include_drafts=may_see_drafts(request)
    )
    # One message for both misses on purpose: a distinguishable "exists but is
    # hidden" would answer the question the 404 is there to refuse.
    if visible is None:
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
    try:
        return await tag_service.set_for_article(db, article_id, body.tags)
    except TagNameError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
