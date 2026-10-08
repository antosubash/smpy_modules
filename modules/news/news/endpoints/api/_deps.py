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

from news import locales, service, tag_service, tenancy
from news.constants import (
    PERM_EDIT,
    PERM_PUBLISH,
    PRIVATE_CACHE_CONTROL,
    PUBLIC_CACHE_CONTROL,
)
from news.contracts.schemas import ArticleDetail, ArticleRead
from news.models import NewsArticle
from news.naive_utc import as_utc

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


def checked_locale(value: str | None) -> str | None:
    """``value`` as a content locale, or a 422 naming the configured ones.

    A write is refused rather than quietly filed under the default language:
    an article's locale is fixed for its lifetime and is part of its address,
    so accepting ``fr`` on a site that publishes ``en`` and ``de`` would put the
    article at a URL the author did not ask for and cannot move it off.

    ``None`` passes through, meaning "the site's default" — which is what every
    caller written before there was such a thing as a language means, and what
    keeps a monolingual host from having to say ``en`` on every create.

    The *listing* filter deliberately does the opposite and ignores an
    unconfigured value (see ``resolve_locale`` there): that one arrives from a
    query string, where a stale link should show the list rather than an error.
    """
    if value is None:
        return None
    resolved = locales.resolve(value)
    if resolved is None:
        raise HTTPException(
            status_code=422,
            detail=(
                f"{value!r} is not a content locale. "
                f"Configured: {', '.join(locales.supported())}."
            ),
        )
    return resolved


def blank_filter(value: str | None) -> bool:
    """Was this filter supplied, and supplied as nothing?

    ``None`` is absent; ``""`` and ``"   "`` are present and empty. Only this
    boundary can tell them apart — below it both reach ``query_filters``, where
    ``if not value`` reads an empty string as "no filter" and hands back the
    *whole site* under a name that promised one story's translations. So an
    empty value narrows to nothing instead: a caller that computed an empty
    group id gets a visibly empty panel, not every article on the site.

    Not the same as ``?locale=fr`` where the site publishes en and de. That
    names a language, just not a configured one, and its documented rule is to
    ignore the filter — a stale link should not be an error. An empty value
    names nothing at all, so there is no list it could mean.

    Same class as the ``published_data`` bug this branch fixed: a falsy-but-
    present value one layer reads as absent and another as a value. Please
    don't re-simplify it away.
    """
    return value is not None and not value.strip()


def cache(response: Response, request: Request, *, include_drafts: bool) -> None:
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

    On a multi-tenant host the tenant header (when one is configured) picks the
    tenant too, so it joins the ``Vary`` list.
    """
    response.headers["Cache-Control"] = (
        PRIVATE_CACHE_CONTROL if include_drafts else PUBLIC_CACHE_CONTROL
    )
    response.headers["Vary"] = "Cookie"
    tenancy.vary_on_tenant(response, request.app)


async def read_one(db: AsyncSession, article_id: int) -> ArticleRead:
    """Re-read through the listing query so every response has one shape.

    Drafts are included: an editor has just written this row and must see it
    back whatever state it is in. So are tags, which the listing attaches in
    one query per page: a single read that left them off would hand the editor
    an article with none, and its next Save would write that back.
    """
    article = await service.get_read(db, article_id, include_drafts=True)
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found.")
    article.tags = await tag_service.list_for_article(db, article_id)
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
        # A SQLite-backed database returns these without their zone; the
        # browser would read a bare timestamp as local time.
        publish_at=as_utc(article.publish_at),
        unpublish_at=as_utc(article.unpublish_at),
    )
