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

from sqlalchemy import false, select

from news.like import like_pattern
from news.models import ArticleStatus, NewsArticle, NewsArticleTag, NewsTag

STATUS_DRAFT: Final = "draft"
STATUS_PUBLISHED: Final = "published"
STATUS_UNDATED: Final = "undated"


def visible(stmt, *, include_drafts: bool):
    """Restrict to published articles unless the caller may see drafts."""
    if include_drafts:
        return stmt
    return stmt.where(NewsArticle.status == ArticleStatus.PUBLISHED)


def locale(stmt, value: str | None):
    """Narrow to articles written in one language.

    The column is the article's own. It was the joined page's while an article
    *was* a page; the article carries its content now, so it carries its
    language, and a host without pagebuilder still has one to filter on.
    ``None`` means every language, which is what the admin list wants by
    default: an editor looking for an article should not have to guess which
    translation they filed it under.
    """
    if not value:
        return stmt
    return stmt.where(NewsArticle.locale == value)


def translation_group(stmt, value: str | None):
    """Narrow to one article and its counterparts in other languages.

    What the editor's language switcher lists. Goes through the ordinary
    listing rather than a route of its own so it inherits the visibility rule
    for free: a reader without ``news.edit`` sees the published translations
    and nothing else, which is the same thing they would see anywhere else.
    """
    if not value:
        return stmt
    return stmt.where(NewsArticle.translation_group == value)


def search(stmt, q: str | None):
    """Filter on what a reader can see of an article without opening it.

    Headline, address, excerpt and tags — the four things a card shows. The
    excerpt and the tags were added when the archive grew a search box: a
    reader searching an archive is matching remembered words, and the
    standfirst is where most of the remembered words are.

    Deliberately **not** the body, which the admin's cross-section screen does
    search (:mod:`news.search_service`). Two reasons, and the first is not
    about cost: the column that screen scans is ``draft_data``, so a public
    search over it would answer for text nobody has published — a phrase
    existing only in an unpublished edit would surface the article and tell an
    outsider that edit exists. Matching ``published_data`` instead would be
    correct but is a ``LIKE '%…%'`` over the largest column in the table on an
    anonymous route anyone can hammer, with no index that can serve it. The
    honest public answer is narrower than the admin's.

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
    # Tags are a join away, so they arrive as a subquery rather than widening
    # every row of the scan — the same shape ``service.list_articles`` uses to
    # filter by one tag, for the same reason.
    tagged = (
        select(NewsArticleTag.article_id)
        .join(NewsTag, NewsTag.id == NewsArticleTag.tag_id)
        .where(NewsTag.name.ilike(pattern, escape="\\"))
    )
    # No body here, and adding one "for completeness" is a disclosure bug, not
    # a slow query. The admin screen's body match scans ``draft_data`` — text
    # that may never have been published — so a public search over it would
    # surface an article for a phrase that exists only in an unpublished edit,
    # telling an outsider that edit exists. Pointing the same scan at
    # ``published_data`` closes the leak and leaves a ``LIKE '%…%'`` over the
    # largest column in the table on a route anyone can hammer.
    return stmt.where(
        NewsArticle.title.ilike(pattern, escape="\\")
        | NewsArticle.slug.ilike(pattern, escape="\\")
        | NewsArticle.meta_description.ilike(pattern, escape="\\")
        | NewsArticle.id.in_(tagged)
    )


def author(stmt, names: list[str] | None):
    """Narrow to the articles carrying one of these bylines.

    A *list*, because one address can mean more than one spelling of a byline —
    see :mod:`news.authors`. ``None`` is no filter at all; an **empty list**
    matches nothing, which is what an address nobody has published under has to
    mean. The two are not the same question, and collapsing them is how an
    unknown author's page would list the entire archive.
    """
    if names is None:
        return stmt
    if not names:
        return stmt.where(false())
    return stmt.where(NewsArticle.author.in_(names))


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
