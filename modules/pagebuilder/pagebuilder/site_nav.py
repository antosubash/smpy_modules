"""The pages a site's header and footer list because the page asked to be.

``Page.show_in_header_nav`` / ``show_in_footer`` are membership only. The public
page sends this list next to the layout, and the SiteHeader / SiteFooter widgets
append it after the layout's own links, skipping any page the layout already
links to. That keeps the order the layout's, as the model docstring requires:
an author who wants a page somewhere specific puts it there in the layout
editor, and the flag stops adding a second copy.
"""

from __future__ import annotations

from typing import TypedDict

from sqlalchemy import or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from pagebuilder import locales, public_claims
from pagebuilder.models import NOT_TRASHED, Page, PageStatus


class NavLink(TypedDict):
    label: str
    href: str


class SiteNav(TypedDict):
    header: list[NavLink]
    footer: list[NavLink]


async def site_nav(db: AsyncSession, prefix: str, locale: str) -> SiteNav:
    """Flagged, published pages in ``locale``, ordered by title.

    Only the page's own language: a German page's header linking to the English
    "About" would drop a reader into the wrong language with no way back. The
    href goes through the claims registry, so a page another module serves (a
    news article) links to that module's address rather than to a ``/p/`` URL
    that 404s.
    """
    result = await db.execute(
        select(Page.title, Page.slug, Page.show_in_header_nav, Page.show_in_footer)
        .where(
            NOT_TRASHED,
            Page.locale == locale,
            Page.status == PageStatus.PUBLISHED,
            or_(Page.show_in_header_nav, Page.show_in_footer),
        )
        .order_by(Page.title, Page.id)
    )
    rows = result.all()
    claimed = await public_claims.resolve(db, [row.slug for row in rows], locale)
    nav: SiteNav = {"header": [], "footer": []}
    for row in rows:
        link: NavLink = {
            "label": row.title,
            "href": claimed.get(row.slug) or locales.public_path(prefix, row.slug, locale),
        }
        if row.show_in_header_nav:
            nav["header"].append(link)
        if row.show_in_footer:
            nav["footer"].append(link)
    return nav

