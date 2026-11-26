"""Article and archive markup; shared escaping and injection live in ``_head``."""

from __future__ import annotations

import html
from typing import Any

from news.web.endpoints.public import _head


def _locale_links(
    locale: str | None, alternates: list[dict[str, str]] | None
) -> list[str]:
    parts = _head._alternate_links(alternates, managed=True)
    for entry in alternates or []:
        language = entry["locale"]
        if language not in {locale, "x-default"}:
            parts.append(
                '<meta property="og:locale:alternate" '
                f'data-inertia="og:locale:alternate-{html.escape(language, quote=True)}" '
                f'content="{html.escape(language, quote=True)}">'
            )
    return parts


def _feed_link(title: str, feed_url: str | None) -> str:
    # Feed autodiscovery serves browser extensions and readers without JavaScript.
    if not feed_url:
        return ""
    return (
        '<link rel="alternate" type="application/rss+xml" data-inertia="feed" '
        f'title="{html.escape(title, quote=True)}" '
        f'href="{html.escape(feed_url, quote=True)}">'
    )


def article_head(
    *,
    title: str,
    description: str | None,
    canonical: str | None,
    image: str | None,
    site_name: str | None,
    twitter_handle: str | None,
    published_at: str | None,
    author: str | None,
    section: str | None,
    index_in_search: bool,
    json_ld: dict[str, Any] | None,
    locale: str | None = None,
    alternates: list[dict[str, str]] | None = None,
    feed_url: str | None = None,
) -> str:
    """Markup from the same resolved values sent as the page's ``head`` prop."""
    parts = [
        f"<title>{html.escape(title)}</title>",
        _head._tag("description", description, managed=True),
        _head._tag("og:title", title, prop=True, managed=True),
        _head._tag("og:description", description, prop=True, managed=True),
        # ``article``, not ``website``: the whole reason this module took its
        # own address is that these documents are not generic pages.
        _head._tag("og:type", "article", prop=True, managed=True),
        _head._tag("og:url", canonical, prop=True, managed=True),
        _head._tag("og:site_name", site_name, prop=True, managed=True),
        _head._tag("og:image", image, prop=True, managed=True),
        _head._tag("article:published_time", published_at, prop=True, managed=True),
        _head._tag("article:author", author, prop=True, managed=True),
        _head._tag("article:section", section, prop=True, managed=True),
        _head._tag("twitter:card", "summary_large_image" if image else "summary", managed=True),
        _head._tag("twitter:image", image, managed=True),
        _head._tag("twitter:site", twitter_handle, managed=True),
        # The bare language tag, not a full ``ll_CC`` locale: content locales
        # here are BCP-47 and often just ``de``, and inventing a region to fill
        # the Open Graph shape would claim something nobody configured.
        _head._tag("og:locale", locale, prop=True, managed=True),
    ]
    parts.extend(_locale_links(locale, alternates))
    parts.append(_feed_link(title, feed_url))
    if canonical:
        parts.append(
            f'<link rel="canonical" {_head._MANAGED}="{_head.KEY_CANONICAL}" '
            f'href="{html.escape(canonical, quote=True)}">'
        )
    if not index_in_search:
        parts.append(
            f'<meta name="robots" {_head._MANAGED}="{_head.KEY_ROBOTS}" '
            'content="noindex,nofollow">'
        )
    if json_ld:
        parts.append(
            f'<script type="application/ld+json" {_head._MANAGED}="{_head.KEY_JSON_LD}">'
            f"{_head._safe_json_ld(json_ld)}</script>"
        )
    return "".join(part for part in parts if part)


def listing_head(
    *,
    title: str,
    description: str | None,
    canonical: str | None,
    site_name: str | None,
    feed_url: str | None,
    locale: str | None = None,
    alternates: list[dict[str, str]] | None = None,
    robots: str | None = None,
) -> str:
    """The head an archive page needs.

    ``og:type`` is ``website`` here and ``article`` above, which is the
    distinction the split was about in the first place.

    The ``hreflang`` set is the same archive in the site's other languages,
    which is a fixed list of addresses rather than something to look up: every
    language has an index, a category page and a tag page at the same shape of
    URL under its own prefix.

    ``robots`` is a directive rather than a boolean because the archive needs
    one the article page never does: a *search results* page is
    ``noindex,follow`` — keep it out of the index, but do follow the links out
    of it — where an article opted out of indexing is ``noindex,nofollow``.
    Omitted entirely by default, which is what every ordinary archive page
    wants.
    """
    parts = [
        f"<title>{html.escape(title)}</title>",
        _head._tag("description", description, managed=True),
        _head._tag("og:title", title, prop=True, managed=True),
        _head._tag("og:description", description, prop=True, managed=True),
        _head._tag("og:type", "website", prop=True, managed=True),
        _head._tag("og:url", canonical, prop=True, managed=True),
        _head._tag("og:site_name", site_name, prop=True, managed=True),
        _head._tag("og:locale", locale, prop=True, managed=True),
        _head._tag("robots", robots, managed=True),
    ]
    parts.extend(_locale_links(locale, alternates))
    parts.append(_feed_link(title, feed_url))
    if canonical:
        parts.append(
            f'<link rel="canonical" {_head._MANAGED}="{_head.KEY_CANONICAL}" '
            f'href="{html.escape(canonical, quote=True)}">'
        )
    return "".join(part for part in parts if part)
