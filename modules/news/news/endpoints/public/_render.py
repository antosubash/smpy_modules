"""One article row, turned into the document it renders as.

Two routes render an article, and they must render it identically: the public
viewer, which serves ``published_data`` to a reader, and the authenticated
preview, which serves ``draft_data`` to whoever is deciding whether to publish
it. A preview that looked different from the real thing would be worth nothing
to the reviewer relying on it — and the Inertia props, the ``<Head>`` tags and
the server-rendered head are three separate places the two could have drifted
apart. So neither route builds them; this does.

It lives under ``public/`` even though the preview is emphatically not public.
What it builds *is* the reader's document, and the preview borrows it on
purpose rather than owning a second version of it. What the preview does not
borrow is the *rule* about which rows may be served — that stays in
``_article``, where the 404 for anything unpublished belongs.
"""

from __future__ import annotations

from typing import Any

from fastapi import Response
from simple_module_hosting.inertia_deps import InertiaDep

from news import constants
from news.authors import slug_for as author_slug
from news.endpoints.public import _head
from news.models import NewsArticle
from news.settings import NewsSettings, public_author_path


async def render_article(
    inertia: InertiaDep,
    *,
    article: NewsArticle,
    data: dict[str, Any],
    locale: str,
    settings: NewsSettings,
    canonical: str | None = None,
    alternates: list[dict[str, str]] | None = None,
    index_in_search: bool = True,
    preview: dict[str, Any] | None = None,
) -> Response:
    """Render ``data`` as this article, through the reader's own screen.

    ``data`` rather than ``article.published_data`` because the body is the one
    thing the two callers disagree about, and it is the whole disagreement: the
    viewer passes the published snapshot, the preview passes the draft. Every
    other prop is read off the row, so the byline, the category and the display
    date a reviewer sees are the ones a reader would.

    ``canonical`` and ``alternates`` default to nothing, which is the preview's
    case: a permission-gated URL should claim to be the canonical version of
    nothing and should advertise no translations, because none of the addresses
    it could name are addresses it is reachable at.

    ``index_in_search`` is a parameter rather than ``article.index_in_search``
    for the same reason — the preview forces it False regardless of what the
    article says, which is what puts ``noindex`` in both heads.
    """
    published_at = (
        article.published_at.isoformat() if article.published_at is not None else None
    )
    # The byline's archive, where it has one. It was a dead end before: rendered
    # on the page and emitted as ``article:author``, with nowhere for a reader
    # who liked the writer to go, while a category and a tag each had a page.
    #
    # ``None`` for a byline that slugs to nothing — a name in a script that does
    # not transliterate — and the viewer then renders it as plain text. An
    # address that cannot name this author is worse than no address; see
    # :mod:`news.authors`.
    byline_slug = author_slug(article.author)
    props: dict[str, Any] = {
        "title": article.title,
        # Which article this is, for the blocks in its own body that need to
        # know. `Related` is the one: a "read next" list that includes the
        # article you are reading is visibly broken, and the slug is the only
        # thing that identifies it inside the block document.
        "slug": article.slug,
        "data": data,
        "meta_description": article.meta_description,
        "og_image": article.og_image,
        "canonical_url": canonical,
        "og_url": canonical,
        "index_in_search": index_in_search,
        "json_ld": article.json_ld,
        "site_name": settings.site_name or None,
        "twitter_handle": settings.twitter_handle or None,
        "category": article.category,
        "author": article.author,
        "author_url": public_author_path(byline_slug, locale) if byline_slug else None,
        "published_at": published_at,
        "locale": locale,
        "alternates": alternates or [],
    }
    if preview is not None:
        # Absent entirely on the public route rather than sent as null: this
        # prop is what makes the banner appear, and a reader's page should not
        # carry even an empty version of it.
        props["preview"] = preview

    rendered = await inertia.render(constants._PAGE_PUBLIC_ARTICLE, props)

    # The same tags `PublicArticle` renders through Inertia's `<Head>`, written
    # into the document server-side — see `_head` for why both are needed.
    return _head.inject(
        rendered,
        _head.article_head(
            title=article.title,
            description=article.meta_description or None,
            canonical=canonical,
            image=article.og_image or None,
            site_name=settings.site_name or None,
            twitter_handle=settings.twitter_handle or None,
            published_at=published_at,
            author=article.author or None,
            section=article.category or None,
            index_in_search=index_in_search,
            json_ld=article.json_ld,
            locale=locale,
            alternates=alternates,
        ),
    )
