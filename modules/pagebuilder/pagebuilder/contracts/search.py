"""Searching pages and media from another module (#130).

News' admin search has Pages and Media sections. It used to build those
queries itself against :class:`~pagebuilder.models.Page` and
:class:`~pagebuilder.models.MediaAsset` — a string ``"published"`` for the
status, a hand-written ``tenant_id`` pin — so any change to those tables broke
news at runtime and nothing here said so. These two functions are the contract
instead: the columns, the status vocabulary and the tenant predicate are
pagebuilder's to change, and what crosses the boundary is a small read-only
hit, not an ORM row bound to this module's session.

**Tenant.** The caller names it and it is pinned *here*, as a ``WHERE``, not
left to the framework's filter. On a single-tenant host nothing is bound and
that filter does nothing, so an unpinned read would list every tenant's rows.
A strict session with no tenant bound raises before any SQL runs; that is
answered as "nothing found", the same as an unknown query, rather than as an
error on a screen that only wanted to add a section.

**Pattern.** A SQL ``LIKE`` pattern with ``\\`` as the escape character — the
caller owns escaping and wildcards, so both modules' sections match on the
same rule.

**Limit.** An ``int`` from 1 to :data:`MAX_SEARCH_LIMIT`; anything else raises
``ValueError`` before a query runs. SQLAlchemy reads ``None`` (and SQLite a
negative number) as "no limit", which would load every matching page body.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict
from simple_module_db import MissingTenantError
from sqlalchemy import Text, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from pagebuilder.models import NOT_TRASHED, MediaAsset, Page, PageStatus

__all__ = [
    "MAX_SEARCH_LIMIT",
    "MediaSearchHit",
    "PageSearchHit",
    "search_media",
    "search_pages",
]

MAX_SEARCH_LIMIT = 100
"""The most hits one call returns. The total is still the full count."""


def _checked_limit(limit: object) -> int:
    # `bool` is an `int`; `True` as a limit is a caller bug, not "one row".
    if not isinstance(limit, int) or isinstance(limit, bool):
        raise ValueError(f"limit must be an int, got {type(limit).__name__}")
    if not 1 <= limit <= MAX_SEARCH_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_SEARCH_LIMIT}, got {limit}")
    return limit


class PageSearchHit(BaseModel):
    """A page that matched, with what a results row needs to show it."""

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: int
    title: str
    slug: str
    locale: str
    status: PageStatus
    draft_data: dict[str, Any] | None = None
    """The body blocks, for the caller's excerpt. The draft, as an editor sees
    it — this is an admin search, not the public site."""


class MediaSearchHit(BaseModel):
    """A media asset that matched."""

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: int
    filename: str
    original_filename: str
    content_type: str


async def _page_of(db: AsyncSession, stmt: Any, order: Any, limit: int) -> tuple[list, int]:
    """The first ``limit`` rows of ``stmt`` by ``order``, and the full count."""
    try:
        total = int(await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
        rows = (await db.execute(stmt.order_by(order).limit(limit))).scalars()
    except MissingTenantError:
        return [], 0
    return list(rows), total


async def search_pages(
    db: AsyncSession,
    pattern: str,
    *,
    tenant_id: str,
    include_drafts: bool,
    limit: int,
    locale: str | None = None,
) -> tuple[list[PageSearchHit], int]:
    """Pages in ``tenant_id`` matching ``pattern``, newest first, and the total.

    Matches the title, the slug and the draft body. Trashed pages never match;
    unpublished ones only with ``include_drafts``. Every language unless
    ``locale`` names one. ``limit`` must be 1..:data:`MAX_SEARCH_LIMIT`.
    """
    limit = _checked_limit(limit)
    stmt = select(Page).where(
        NOT_TRASHED,
        Page.tenant_id == tenant_id,
        or_(
            Page.title.ilike(pattern, escape="\\"),
            Page.slug.ilike(pattern, escape="\\"),
            # The body, as a LIKE against the JSON cast to text, evaluated in
            # the database. The cast target is explicit: an untyped
            # `func.cast` compiles to NullType and the statement fails.
            cast(Page.draft_data, Text).ilike(pattern, escape="\\"),
        ),
    )
    if not include_drafts:
        stmt = stmt.where(Page.status == PageStatus.PUBLISHED)
    if locale is not None:
        stmt = stmt.where(Page.locale == locale)
    rows, total = await _page_of(db, stmt, Page.id.desc(), limit)
    return [PageSearchHit.model_validate(row) for row in rows], total


async def search_media(
    db: AsyncSession, pattern: str, *, tenant_id: str, limit: int
) -> tuple[list[MediaSearchHit], int]:
    """Media in ``tenant_id`` whose name matches ``pattern``, newest first, and
    the total. Both the uploaded name and the stored one are matched.
    ``limit`` must be 1..:data:`MAX_SEARCH_LIMIT`."""
    limit = _checked_limit(limit)
    stmt = select(MediaAsset).where(
        MediaAsset.tenant_id == tenant_id,
        or_(
            MediaAsset.original_filename.ilike(pattern, escape="\\"),
            MediaAsset.filename.ilike(pattern, escape="\\"),
        ),
    )
    rows, total = await _page_of(db, stmt, MediaAsset.id.desc(), limit)
    return [MediaSearchHit.model_validate(row) for row in rows], total
