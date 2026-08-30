"""Old slugs that should now point at an article's current one.

A slug change is not a private edit: the old URL is already in bookmarks, in
links from other sites, and in a search index that has not recrawled. Dropping
it silently turns a rename into a broken link nobody notices until traffic
falls, which is why the editor promises a redirect and this records one.

News used to read pagebuilder's redirect table, because the slug being renamed
was a page's. It keeps its own now — the same rule, over the rows this module
actually owns.
"""

from __future__ import annotations

from sqlalchemy import delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from news.models import ArticleStatus, NewsArticle, NewsArticleRedirect


async def record(
    db: AsyncSession, *, article_id: int, old_slug: str, new_slug: str
) -> None:
    """Point ``old_slug`` at the article, now living at ``new_slug``.

    Two rows are cleared first, and each for its own reason:

    * any redirect *from* the new slug, or an article reclaiming an address it
      once redirected away would send readers straight back off it — a loop;
    * any existing redirect from the old slug, so re-renaming an article updates
      where its old address lands instead of colliding on the unique index.

    A rename back to a slug the article already used therefore leaves no
    self-referential row behind.
    """
    if old_slug == new_slug:
        return

    await db.execute(
        sa_delete(NewsArticleRedirect).where(
            NewsArticleRedirect.from_slug.in_([old_slug, new_slug])
        )
    )
    db.add(NewsArticleRedirect(from_slug=old_slug, article_id=article_id))
    await db.flush()


async def resolve(db: AsyncSession, slug: str) -> str | None:
    """The current slug an old one should redirect to, or ``None``.

    Returns the *article's* slug rather than the redirect row, so a chain of
    renames collapses to one hop: every old address points at the article, and
    the article always knows where it lives now.

    An article the public viewer would not serve resolves to nothing.
    Forwarding to an address that would itself 404 is worse than saying so at
    the old one — and worse than it sounds, because the redirect is a 301: a
    browser that once followed it to a dead URL keeps doing so from cache, long
    after the article comes back. So the conditions below are deliberately the
    viewer's own: not trashed, published, and carrying a snapshot to serve.
    """
    result = await db.execute(
        select(NewsArticle.slug, NewsArticle.published_data)
        .join(NewsArticleRedirect, NewsArticleRedirect.article_id == NewsArticle.id)
        .where(
            NewsArticleRedirect.from_slug == slug,
            NewsArticle.deleted_at.is_(None),
            NewsArticle.status == ArticleStatus.PUBLISHED,
        )
    )
    row = result.first()
    # The snapshot is checked in Python rather than in the `WHERE`, and that is
    # forced rather than stylistic: `published_data` is a JSON column, and a
    # Python ``None`` is stored in one as the JSON text ``null``, not as SQL
    # NULL — so ``IS NOT NULL`` is true of an unpublished snapshot too. Cheap
    # here, where at most one row is ever loaded.
    if row is None or row.published_data is None:
        return None
    return row.slug


async def clear_for_article(db: AsyncSession, article_id: int) -> None:
    """Drop an article's redirects. Used when it is purged."""
    await db.execute(
        sa_delete(NewsArticleRedirect).where(
            NewsArticleRedirect.article_id == article_id
        )
    )
