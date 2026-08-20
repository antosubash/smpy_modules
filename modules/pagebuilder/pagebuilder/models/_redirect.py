"""Old slugs that still have to resolve."""

from __future__ import annotations

from sqlmodel import Field

from pagebuilder.models._base import Base


class PageRedirect(Base, table=True):  # ty: ignore[unsupported-base]
    """An old slug that should now send visitors to a page's current one.

    Written whenever a slug changes, because the old URL is already out in the
    world — in someone's bookmarks, in a link from another site, in a search
    index that has not recrawled. Losing it silently turns an edit into a broken
    link that nobody notices until traffic drops.

    ``from_slug`` is unique: one old address resolves to exactly one page, and
    the row is replaced rather than duplicated when a slug is reused.
    """

    __tablename__ = "pagebuilder_page_redirects"

    id: int | None = Field(default=None, primary_key=True)
    from_slug: str = Field(max_length=200, unique=True, index=True)
    page_id: int = Field(foreign_key="pagebuilder_pages.id", index=True, ondelete="CASCADE")


