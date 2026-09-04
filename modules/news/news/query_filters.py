"""Composable ``WHERE`` fragments for the article listing.

Separated from :mod:`news.service` so the listing module stays inside the
repo's 300-line cap, and so each rule is stated once. Every function here only
ever *narrows* a statement, which is what lets ``service.list_articles`` apply
them in any order without widening what a caller is allowed to see.
"""

from __future__ import annotations

from typing import Final

from news.integrations.pagebuilder import Page, PageStatus
from news.like import like_pattern
from news.models import NewsArticle

STATUS_DRAFT: Final = "draft"
STATUS_PUBLISHED: Final = "published"
STATUS_UNDATED: Final = "undated"


def visible(stmt, *, include_drafts: bool):
    """Restrict to published pages unless the caller may see drafts."""
    if include_drafts:
        return stmt
    return stmt.where(Page.status == PageStatus.PUBLISHED)


def locale(stmt, value: str | None):
    """Narrow to articles written in one language.

    The column is the joined page's — an article *is* a page, so its language
    is the page's language and there is no second copy to disagree with it.
    ``None`` means every language, which is what the admin list wants by
    default: an editor looking for an article should not have to guess which
    translation they filed it under.
    """
    if not value:
        return stmt
    return stmt.where(Page.locale == value)


def translation_group(stmt, value: str | None):
    """Narrow to one article and its counterparts in other languages.

    What the editor's language switcher lists. Goes through the ordinary
    listing rather than a route of its own so it inherits the visibility rule
    for free: a reader without ``news.edit`` sees the published translations
    and nothing else, which is the same thing they would see anywhere else.
    """
    if not value:
        return stmt
    return stmt.where(Page.translation_group == value)


def search(stmt, q: str | None):
    """Filter on headline or slug.

    Both columns live on the joined page, which is why this cannot be pushed
    into the sidecar table's own query. ``ilike`` rather than ``like`` so the
    match is case-insensitive on Postgres as well as SQLite — SQLite's ``LIKE``
    already ignores case for ASCII, so without this the two databases would
    disagree about what the same search finds.
    """
    if not q or not q.strip():
        return stmt
    # Escaped, and with the ESCAPE clause: `_` is a single-character
    # wildcard, so an unescaped search for `hero_1` also returned `heroX1`.
    pattern = like_pattern(q)
    return stmt.where(
        Page.title.ilike(pattern, escape="\\") | Page.slug.ilike(pattern, escape="\\")
    )


def status(stmt, value: str | None):
    """Narrow to one pipeline state.

    ``undated`` is not a page status — it is an article with no display date,
    which the list treats as its own bucket because that is the work-in-progress
    pile. An unrecognised value is ignored rather than rejected: the filter
    arrives from a query string, and a stale link should show the list, not a
    validation error.
    """
    if value == STATUS_DRAFT:
        return stmt.where(Page.status == PageStatus.DRAFT)
    if value == STATUS_PUBLISHED:
        return stmt.where(Page.status == PageStatus.PUBLISHED)
    if value == STATUS_UNDATED:
        return stmt.where(NewsArticle.published_at.is_(None))
    return stmt
