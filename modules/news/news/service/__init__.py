"""Queries joining article metadata to the pages that hold the articles.

Split into reads and writes because the two halves share only the listing join
and the display-date rule, and because one flat module had reached the file-size
cap with the admin filters still to come. Callers import from ``news.service``
either way — the split is an implementation detail, not a new surface.

Everything news borrows from pagebuilder arrives through
:mod:`news.integrations.pagebuilder`; nothing in this package imports that
package directly.
"""

from __future__ import annotations

from news.service._reads import (
    get,
    get_by_page,
    get_read_by_page,
    list_articles,
    list_categories,
    page_exists,
)
from news.service._shared import PUBLIC_PAGE_URL, UNSET, as_display_date
from news.service._writes import (
    create,
    create_page_and_article,
    delete,
    reconcile_orphans,
    update,
)

__all__ = [
    "PUBLIC_PAGE_URL",
    "UNSET",
    "as_display_date",
    "create",
    "create_page_and_article",
    "delete",
    "get",
    "get_by_page",
    "get_read_by_page",
    "list_articles",
    "list_categories",
    "page_exists",
    "reconcile_orphans",
    "update",
]
