"""Query fragments and value handling shared by the read and write halves.

Everything news borrows from pagebuilder arrives through
:mod:`news.integrations.pagebuilder`; nothing in this package imports that
package directly.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

from sqlalchemy import select

from news.contracts.schemas import ArticleRead
from news.integrations import pagebuilder as pb
from news.models import NewsArticle

PUBLIC_PAGE_URL = "/p/{slug}"


class _Unset:
    """Sentinel type — a field the caller omitted, as distinct from a null."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "UNSET"


UNSET: Final = _Unset()
"""Passed for ``published_at`` when the caller did not send the field.

A typed singleton rather than a bare ``object()`` so ``datetime | None | _Unset``
stays a real union that a type checker can narrow with ``isinstance``.
"""


def as_display_date(value: datetime | None) -> datetime | None:
    """Flatten an instant to the midnight-UTC date it should be listed under.

    ``published_at`` is a *display date*, not a timestamp: the admin list edits
    it with ``<input type=date>``, and every renderer formats it in UTC so that
    a date set by an editor in Vienna reads the same to a visitor in Auckland.
    The column is a timestamp, though, so the API accepts an instant — and an
    instant carries a time and an offset that the field has no meaning for.
    Stored verbatim, ``2026-02-01T12:00:00Z`` and ``2026-02-01T00:00:00Z`` sort
    against each other on the strength of a time nobody set.

    The day is taken **as the sender wrote it**, and the offset is deliberately
    not applied. Someone sending ``2026-02-01T23:00:00-06:00`` means the 1st;
    converting to UTC first would store the 2nd, which is precisely the
    off-by-one this exists to prevent. That the same wall-clock date in another
    offset is a different instant does not matter here — a display date is a
    date, and the instant is an artefact of the transport.

    A naive datetime is taken at face value too, matching how the admin list
    sends it.
    """
    if value is None:
        return None
    return value.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=UTC)


def visible(stmt, *, include_drafts: bool):
    """Restrict to published pages unless the caller may see drafts."""
    if include_drafts:
        return stmt
    return stmt.where(pb.Page.status == pb.PageStatus.PUBLISHED)


def categorised(stmt, category: str | None, uncategorised: bool):
    """Apply the category filter, which has three states rather than two.

    A named category, no filter at all, and "the ones with no category" are
    distinct asks, and the third had no spelling: ``category=""`` arrives as
    falsy and reads as "no filter", so an uncategorised article could not be
    listed for at all. It is usually the one an editor is looking for.
    """
    if uncategorised:
        return stmt.where(NewsArticle.category == "")
    if category:
        return stmt.where(NewsArticle.category == category)
    return stmt


def base_query(include_drafts: bool, category: str | None, uncategorised: bool = False):
    """The listing join, shared so every read has one shape.

    INNER join, not outer: an article whose page was deleted has no row to
    show, and this is what keeps such an orphan invisible rather than rendering
    a card that links nowhere. There is no database foreign key — see
    ``NewsArticle.page_id``.
    """
    stmt = (
        select(NewsArticle, pb.Page)
        .join(pb.Page, pb.Page.id == NewsArticle.page_id)
        .options(pb.card_columns())
    )
    return categorised(visible(stmt, include_drafts=include_drafts), category, uncategorised)


def to_read(article: NewsArticle, page) -> ArticleRead:
    return ArticleRead(
        id=article.id or 0,
        page_id=article.page_id,
        slug=page.slug,
        title=page.title,
        excerpt=page.meta_description or "",
        cover_image_url=page.og_image or "",
        category=article.category,
        published_at=article.published_at,
        page_status=pb.article_status(page.status),
        url=PUBLIC_PAGE_URL.format(slug=page.slug),
        edit_url=pb.page_editor_path(article.page_id),
    )
