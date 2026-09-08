"""One article, flattened into the shape every listing returns.

Its own module rather than a private helper in :mod:`news.service`, because
that file is at the repo's 300-line cap and because this is the one place the
wire shape of an article is decided — the listing, the single-article read and
the search screen all go through it, so a field added here appears everywhere
at once rather than in whichever caller remembered.

It takes a *row*, not an entity: the listing selects the handful of columns a
card actually reads, because selecting the whole ``NewsArticle`` drags both
block-JSON columns through the ORM for every row and makes list cost scale with
article content size instead of card count. See ``service._CARD_COLUMNS``,
which is the tuple this unpacks.
"""

from __future__ import annotations

from news.constants import ARTICLE_BODY_URL
from news.contracts.schemas import ArticleRead
from news.settings import public_article_path


def to_read(row) -> ArticleRead:
    """One card row — the ``_CARD_COLUMNS`` tuple — as the published DTO."""
    return ArticleRead(
        id=row.id or 0,
        slug=row.slug,
        title=row.title,
        excerpt=row.meta_description or "",
        cover_image_url=row.og_image or "",
        category=row.category,
        tags=[],
        pinned=row.pinned,
        show_in_feed=row.show_in_feed,
        author=row.author,
        published_at=row.published_at,
        status=row.status,
        locale=row.locale,
        translation_group=row.translation_group,
        # Locale-prefixed, so a German article's card links to the German
        # address rather than to a URL where only the English one answers.
        url=public_article_path(row.slug, row.locale),
        # Served rather than assembled in the browser, so the admin list holds
        # no opinion about how this module routes its own body canvas.
        edit_url=ARTICLE_BODY_URL.format(article_id=row.id or 0),
    )
