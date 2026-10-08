"""Absolute URLs, cache policy and ETags for everything news serves publicly.

One copy, because the article viewer, the archive pages, the sitemap and the
feed all have to agree about what this site is called and how long its pages may
be held — and the first three used to agree only by having been written on the
same afternoon.
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from fastapi import Request, Response

from news import tenancy
from news.settings import NewsSettings, public_article_path


def etag_for(article_id: int, updated_at: datetime | None, variant: str = "html") -> str:
    """Stable, short ETag derived from identity + last-modified time.

    Deliberately not a hash of the payload: the body is the biggest column in
    the table, and hashing it on every request would make a conditional GET cost
    more than an unconditional one.

    ``variant`` names the representation. One URL answers with a full HTML
    page or, for an in-app visit, Inertia's JSON; sharing a tag let a browser
    holding the page revalidate the JSON request, get a 304, and hand Inertia
    the cached HTML instead.
    """
    stamp = updated_at.isoformat() if updated_at is not None else ""
    digest = hashlib.sha1(f"{article_id}:{stamp}:{variant}".encode()).hexdigest()[:16]
    return f'W/"{digest}"'


def public_base_url(request: Request, settings: NewsSettings) -> str:
    """Resolve the public origin used to build absolute URLs.

    Prefer the explicit setting — the deployment knows its public host — and
    only fall back to the inbound request for local development and scenarios
    where the Host header is trustworthy. Always returned without a trailing
    slash so callers can concatenate path segments directly.
    """
    if settings.public_base_url:
        return settings.public_base_url.rstrip("/")
    return f"{request.url.scheme}://{request.url.netloc}".rstrip("/")


def absolute(request: Request, settings: NewsSettings, path: str) -> str:
    """An origin-qualified URL for a path this module already built."""
    return f"{public_base_url(request, settings)}{path}"


def absolute_article(
    request: Request, settings: NewsSettings, slug: str, locale: str | None = None
) -> str:
    """An article's own absolute address, in the language it is written in.

    The locale is not optional information here even though the parameter is: a
    slug identifies an article only within one language, so ``/news/budget`` and
    ``/de/news/budget`` are two documents. ``None`` means the site's default,
    which is the only thing an unqualified slug can mean.
    """
    return absolute(request, settings, public_article_path(slug, locale))


def cache_control(settings: NewsSettings) -> str:
    parts = [f"max-age={settings.public_cache_max_age}"]
    if settings.public_cache_swr > 0:
        parts.append(f"stale-while-revalidate={settings.public_cache_swr}")
    return "public, " + ", ".join(parts)


def listing_cache_control(settings: NewsSettings) -> str:
    """How long an archive page may be held.

    Shorter than an article's, and not configurable separately: an article
    changes only when someone republishes it, but every archive page changes the
    moment *any* article is published — so the number that is safe for one is
    too long for the other.
    """
    return f"public, max-age={min(settings.public_cache_max_age, 60)}"


def apply_cache(
    response: Response, request: Request, settings: NewsSettings, *, listing: bool = False
) -> Response:
    """Mark a public response shared-cacheable — keyed on whatever picks its tenant.

    On a multi-tenant host the tenant can come from the reader's session rather
    than the Host, so ``public`` alone would let a shared cache hand one
    tenant's page to another's reader; :func:`news.tenancy.vary_on_tenant` adds
    the fields that tell them apart. A single-tenant host gets no ``Vary``
    from here.
    """
    response.headers["Cache-Control"] = (
        listing_cache_control(settings) if listing else cache_control(settings)
    )
    return tenancy.vary_on_tenant(response, request.app)
