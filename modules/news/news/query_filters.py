"""Composable ``WHERE`` fragments for the article listing.

Separated from :mod:`news.service` so the listing module stays inside the
repo's 300-line cap, and so each rule is stated once. Every ``WHERE`` fragment
here only ever *narrows* a statement, which is what lets
``service.list_articles`` apply them in any order without widening what a
caller is allowed to see. :func:`ordered` is the one exception and says so in
its name: it sorts rather than filters, so it changes no caller's reach.
"""

from __future__ import annotations

from typing import Final

from news.like import like_pattern
from news.models import ArticleStatus, NewsArticle

STATUS_DRAFT: Final = "draft"
STATUS_PUBLISHED: Final = "published"
STATUS_UNDATED: Final = "undated"


def visible(stmt, *, include_drafts: bool):
    """Restrict to published articles unless the caller may see drafts."""
    if include_drafts:
        return stmt
    return stmt.where(NewsArticle.status == ArticleStatus.PUBLISHED)


def search(stmt, q: str | None):
    """Filter on headline or slug.

    ``ilike`` rather than ``like`` so the match is case-insensitive on Postgres
    as well as SQLite — SQLite's ``LIKE`` already ignores case for ASCII, so
    without this the two databases would disagree about what the same search
    finds.
    """
    if not q or not q.strip():
        return stmt
    # Escaped, and with the ESCAPE clause: `_` is a single-character
    # wildcard, so an unescaped search for `hero_1` also returned `heroX1`.
    pattern = like_pattern(q)
    return stmt.where(
        NewsArticle.title.ilike(pattern, escape="\\")
        | NewsArticle.slug.ilike(pattern, escape="\\")
    )


def status(stmt, value: str | None):
    """Narrow to one pipeline state.

    ``undated`` is not a status — it is an article with no display date, which
    the list treats as its own bucket because that is the work-in-progress pile.
    An unrecognised value is ignored rather than rejected: the filter arrives
    from a query string, and a stale link should show the list, not a validation
    error.
    """
    if value == STATUS_DRAFT:
        return stmt.where(NewsArticle.status == ArticleStatus.DRAFT)
    if value == STATUS_PUBLISHED:
        return stmt.where(NewsArticle.status == ArticleStatus.PUBLISHED)
    if value == STATUS_UNDATED:
        return stmt.where(NewsArticle.published_at.is_(None))
    return stmt


def ordered(stmt, *, undated_first: bool):
    """Newest first, with the undated at whichever end the caller asked for.

    NULLS placement is explicit either way: SQLite and Postgres disagree about
    where NULL lands on a DESC sort, so without this the two databases disagree
    about where an undated article goes.

    Pinning sorts *before* the date rather than rewriting it, so an article held
    at the top still reports honestly when it was published — unpin it and the
    archive reads correctly again. The two orders differ on purpose: a reader
    wants the pinned pieces first, while an editor wants the work-in-progress
    pile first, because that is the row they came to finish.
    """
    dated = NewsArticle.published_at.desc()
    if undated_first:
        clauses = (dated.nullsfirst(), NewsArticle.pinned.desc())
    else:
        clauses = (NewsArticle.pinned.desc(), dated.nullslast())
    return stmt.order_by(*clauses, NewsArticle.id.desc())
