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

from sqlalchemy import func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from pagebuilder import locales
from pagebuilder.models import NOT_TRASHED, Page, PageStatus


class NavLink(TypedDict):
    label: str
    href: str


class SiteNav(TypedDict):
    header: list[NavLink]
    footer: list[NavLink]


async def site_nav(db: AsyncSession, prefix: str, locale: str) -> SiteNav:
    """Flagged, published pages in ``locale``, ordered by title, ignoring case.

    ``lower()`` so "about" and "Zebra" sort alphabetically on SQLite and
    PostgreSQL alike. Accented or punctuated titles can still follow each
    database's collation.

    Only the page's own language: a German page's header linking to the English
    "About" would drop a reader into the wrong language with no way back.
    """
    result = await db.execute(
        select(Page.title, Page.slug, Page.show_in_header_nav, Page.show_in_footer)
        .where(
            NOT_TRASHED,
            Page.locale == locale,
            Page.status == PageStatus.PUBLISHED,
            or_(Page.show_in_header_nav, Page.show_in_footer),
        )
        .order_by(func.lower(Page.title), Page.id)
    )
    nav: SiteNav = {"header": [], "footer": []}
    for row in result.all():
        link: NavLink = {
            "label": row.title,
            "href": locales.public_path(prefix, row.slug, locale),
        }
        if row.show_in_header_nav:
            nav["header"].append(link)
        if row.show_in_footer:
            nav["footer"].append(link)
    return nav
