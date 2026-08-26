"""Shared dependencies for the News API.

Split out of the endpoint modules so the draft-visibility rule has exactly one
definition. It is subtle enough (see ``may_see_drafts``) that a second copy
would drift.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, Response
from simple_module_hosting.permissions import (
    WILDCARD,
    RequiresPermission,
    resolve_permissions,
)
from sqlalchemy.ext.asyncio import AsyncSession

from news import service
from news.constants import (
    PERM_EDIT,
    PERM_PUBLISH,
    PRIVATE_CACHE_CONTROL,
    PUBLIC_CACHE_CONTROL,
)
from news.contracts.schemas import ArticleDetail, ArticleRead
from news.models import NewsArticle

require_edit = Depends(RequiresPermission(PERM_EDIT))

require_publish = Depends(RequiresPermission(PERM_PUBLISH))
"""Separate from ``news.edit``.

Publishing used to go through pagebuilder's own editor→publisher separation,
because the body lived on one of its pages. Owning the content means owning that
separation: without a gate of its own, every author would get a way straight
past a review step the host may well want.
"""


def may_see_drafts(request: Request) -> bool:
    """Only an editor sees articles that are still drafts.

    Everyone else gets the published site, which is what the public feed block
    must show.

    Reads ``request.state.resolved_permissions`` — where the hosting middleware
    and ``RequiresPermission`` both put the resolved set — rather than a
    ``permissions`` attribute on the user. ``UserContext`` has no such
    attribute, so testing it always yielded an empty list and no editor ever
    saw a draft.

    The fallback mirrors ``RequiresPermission.__call__``: these listings are
    registered as public routes, so on an anonymous-readable GET nothing has
    populated ``resolved_permissions`` by the time we are asked. ``WILDCARD`` is
    checked because an administrator resolves to it rather than to a literal
    ``news.edit``.
    """
    resolved = getattr(request.state, "resolved_permissions", None)
    if resolved is None:
        user = getattr(request.state, "user", None)
        if user is None:
            return False
        sm = getattr(getattr(request.app, "state", None), "sm", None)
        registry = getattr(sm, "permissions", None) if sm is not None else None
        resolved = resolve_permissions(
            getattr(user, "roles", None) or [],
            role_map=registry.role_map if registry is not None else None,
        )
    return WILDCARD in resolved or PERM_EDIT in resolved


def cache(response: Response, *, include_drafts: bool) -> None:
    """Let a shared cache hold the public answer, and never the editor's.

    The feed block runs on every public page carrying it, so an uncacheable
    listing costs a database round trip per page view. The editor's listing
    differs by permission — it includes drafts — so it must not be stored
    anywhere another visitor could be served it from, which is why the two
    answers cannot share one header.

    ``Vary: Cookie`` is what keeps the two apart in a shared cache. The URL is
    identical for both, so without it a proxy that stored the anonymous answer
    would go on serving it to an editor for the whole max-age — the admin list
    losing its drafts, and a just-created article, for up to a minute.
    """
    response.headers["Cache-Control"] = (
        PRIVATE_CACHE_CONTROL if include_drafts else PUBLIC_CACHE_CONTROL
    )
    response.headers["Vary"] = "Cookie"


async def read_one(db: AsyncSession, article_id: int) -> ArticleRead:
    """Re-read through the listing query so every response has one shape.

    Drafts are included: an editor has just written this row and must see it
    back whatever state it is in.
    """
    article = await service.get_read(db, article_id, include_drafts=True)
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found.")
    return article


def detail_of(article: NewsArticle, listing: ArticleRead) -> ArticleDetail:
    """Widen a listing row with the fields only the editor needs.

    Built from the listing DTO rather than beside it so the two can never
    disagree about what a title, a URL or a status is.
    """
    return ArticleDetail(
        **listing.model_dump(),
        draft_data=article.draft_data or {},
        has_published=article.has_published,
        meta_description=article.meta_description or "",
        og_image=article.og_image or "",
        canonical_url=article.canonical_url or "",
        index_in_search=article.index_in_search,
        json_ld=article.json_ld,
        rejection_note=article.rejection_note,
        publish_at=article.publish_at,
        unpublish_at=article.unpublish_at,
    )
