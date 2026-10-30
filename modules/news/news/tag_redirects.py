"""Old tag slugs that should now point at a tag's current one (#174).

Renaming a tag moves its slug, and ``/news/tag/<old>`` is already out in the
world — in the sitemap, in links, in a search index. Without a row here the old
address renders an empty archive, which reads as "nobody uses this tag" rather
than "it moved". The article redirects in :mod:`news.redirects` make the same
promise for articles; this is the tag half.

Not per locale: a tag has one slug across every language, so one row serves
every language's archive.
"""

from __future__ import annotations

from sqlalchemy import delete as sa_delete
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from news.models import NewsTag, NewsTagRedirect


async def record(db: AsyncSession, *, tag_id: int, old_slug: str, new_slug: str) -> None:
    """Point ``old_slug`` at the tag, now living at ``new_slug``.

    Clears any redirect from either slug first, for the reasons
    :func:`news.redirects.record` gives: a tag reclaiming an address it once
    redirected away would loop, and a re-rename has to update the old row
    rather than collide with it.
    """
    if old_slug == new_slug:
        return
    await db.execute(
        sa_delete(NewsTagRedirect).where(NewsTagRedirect.from_slug.in_([old_slug, new_slug]))
    )
    db.add(NewsTagRedirect(from_slug=old_slug, tag_id=tag_id))
    await db.flush()


async def release(db: AsyncSession, slug: str) -> None:
    """A new tag claims ``slug``: a dormant redirect from it must not outlive it.

    The live tag already wins at the archive route, but the row would come back
    to life, pointing at some other tag, the day this one is renamed or deleted.
    """
    await db.execute(sa_delete(NewsTagRedirect).where(NewsTagRedirect.from_slug == slug))


async def repoint(db: AsyncSession, *, source: NewsTag, target: NewsTag) -> None:
    """A merge folds ``source`` into ``target``: its addresses go with it."""
    await db.execute(
        update(NewsTagRedirect).where(NewsTagRedirect.tag_id == source.id).values(tag_id=target.id)
    )
    await record(db, tag_id=target.id or 0, old_slug=source.slug, new_slug=target.slug)


async def clear_for_tag(db: AsyncSession, tag_id: int) -> None:
    """Drop a deleted tag's redirects.

    Explicit for the reason ``tag_service.delete`` gives about SQLite and
    ``ON DELETE CASCADE``: a surviving row would hand a reused id the old
    addresses of a tag nobody renamed into it.
    """
    await db.execute(sa_delete(NewsTagRedirect).where(NewsTagRedirect.tag_id == tag_id))


async def resolve(db: AsyncSession, slug: str) -> str | None:
    """The current slug an old one should redirect to, or ``None``.

    Returns the tag's slug rather than the row's, so a chain of renames
    collapses to one hop.
    """
    return await db.scalar(
        select(NewsTag.slug)
        .join(NewsTagRedirect, NewsTagRedirect.tag_id == NewsTag.id)
        .where(NewsTagRedirect.from_slug == slug)
    )
