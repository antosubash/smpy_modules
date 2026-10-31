"""Old slugs that still have to resolve."""

from __future__ import annotations

from simple_module_db.mixins import MultiTenantMixin
from sqlalchemy import Index
from sqlmodel import Field

from pagebuilder import locales
from pagebuilder.models._base import Base


class PageRedirect(Base, MultiTenantMixin, table=True):  # ty: ignore[unsupported-base]
    """An old slug that should now send visitors to a page's current one.

    Written whenever a slug changes, because the old URL is already out in the
    world — in someone's bookmarks, in a link from another site, in a search
    index that has not recrawled. Losing it silently turns an edit into a broken
    link that nobody notices until traffic drops.

    ``(tenant_id, locale, from_slug)`` is unique: one old address resolves to
    exactly one page of that tenant's site, and the row is replaced rather than
    duplicated when a slug is reused.
    """

    __tablename__ = "pagebuilder_page_redirects"

    __table_args__ = (
        Index(
            "ix_pagebuilder_page_redirects_tenant_locale_from_slug",
            "tenant_id",
            "locale",
            "from_slug",
            unique=True,
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    from_slug: str = Field(max_length=200)
    locale: str = Field(default_factory=locales.default, max_length=locales.MAX_LOCALE_LEN)
    """Which language's address this was.

    Carried on the redirect rather than read off the page it points at,
    because slugs are only unique per language: without it, renaming the
    German page to a slug the French one had already retired would collide on
    a unique index the two rows have no reason to share.
    """

    page_id: int = Field(foreign_key="pagebuilder_pages.id", index=True, ondelete="CASCADE")


