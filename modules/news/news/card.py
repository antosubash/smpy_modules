"""One article, flattened into the shape every listing returns.

Its own module rather than a private helper in :mod:`news.service`, because
that file is at the repo's 300-line cap and because this is the one place the
wire shape of an article is decided — the listing, the single-article read and
the search screen all go through it, so a field added here appears everywhere
at once rather than in whichever caller remembered.
"""

from __future__ import annotations

from news.contracts.schemas import ArticleRead
from news.integrations.pagebuilder import Page, article_status, page_editor_path
from news.models import NewsArticle
from news.settings import public_article_path


def to_read(
    article: NewsArticle, page: Page, tags: list[str] | None = None
) -> ArticleRead:
    return ArticleRead(
        id=article.id or 0,
        page_id=article.page_id,
        slug=page.slug,
        title=page.title,
        excerpt=page.meta_description or "",
        cover_image_url=page.og_image or "",
        category=article.category,
        tags=tags or [],
        pinned=article.pinned,
        show_in_feed=article.show_in_feed,
        author=article.author,
        published_at=article.published_at,
        page_status=article_status(page.status),
        locale=page.locale,
        translation_group=page.translation_group,
        # News' own prefix, not pagebuilder's generic one: an article no
        # longer answers at /p/{slug} at all — and locale-prefixed, so a
        # German article's card links to the German address rather than to a
        # URL where only the English one answers.
        url=public_article_path(page.slug, page.locale),
        # Served rather than assembled in the browser: the admin list then
        # holds no opinion about how pagebuilder routes its editor.
        edit_url=page_editor_path(article.page_id),
    )
