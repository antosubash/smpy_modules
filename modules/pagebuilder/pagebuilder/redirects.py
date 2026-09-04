"""Old slugs that should now point at a page's current one.

A slug change is not a private edit: the old URL is already in bookmarks, in
links from other sites, and in a search index that has not recrawled. Dropping
it silently turns a rename into a broken link nobody notices until traffic
falls, which is why the editor promises a redirect and this records one.

Every lookup is scoped to a locale, because slugs are only unique within one:
two languages can legitimately have retired the same word, and resolving
without the locale would forward a German visitor to the French page.
"""

from __future__ import annotations

from sqlalchemy import delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from pagebuilder.models import PageRedirect


async def record(
    db: AsyncSession, *, page_id: int, old_slug: str, new_slug: str, locale: str
) -> None:
    """Point ``old_slug`` at the page, now living at ``new_slug``.

    Two rows are cleared first, and each for its own reason:

    * any redirect *from* the new slug, or a page reclaiming an address it once
      redirected away would send visitors straight back off it — a loop;
    * any existing redirect from the old slug, so re-renaming a page updates
      where its old address lands instead of colliding on the unique index.

    A rename back to a slug the page already used therefore leaves no
    self-referential row behind.

    Both deletes are locale-scoped, so clearing the German page's path never
    disturbs the French page's redirect from the same word.
    """
    if old_slug == new_slug:
        return

    await db.execute(
        sa_delete(PageRedirect).where(
            PageRedirect.locale == locale,
            PageRedirect.from_slug.in_([old_slug, new_slug]),
        )
    )
    db.add(PageRedirect(from_slug=old_slug, page_id=page_id, locale=locale))
    await db.flush()


async def resolve(db: AsyncSession, slug: str, locale: str) -> str | None:
    """The current slug an old one should redirect to, or ``None``.

    Returns the *page's* slug rather than the redirect row, so a chain of
    renames collapses to one hop: every old address points at the page, and the
    page always knows where it lives now.

    The page's own locale is checked as well as the redirect's. They agree
    today — a rename cannot change a page's language — but a redirect that
    outlived a locale change would otherwise hand ``/de/p/x`` an English slug
    and send the visitor to a URL that 404s.
    """
    from pagebuilder.models import Page

    result = await db.execute(
        select(Page.slug)
        .join(PageRedirect, PageRedirect.page_id == Page.id)
        .where(
            PageRedirect.from_slug == slug,
            PageRedirect.locale == locale,
            Page.locale == locale,
            Page.deleted_at.is_(None),
        )
    )
    return result.scalars().first()


async def clear_for_page(db: AsyncSession, page_id: int) -> None:
    """Drop a page's redirects. Used when it is purged."""
    await db.execute(sa_delete(PageRedirect).where(PageRedirect.page_id == page_id))
