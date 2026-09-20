"""Reading one page of a type's records — the list endpoint's whole service.

Split from :mod:`sm_records.services.records`, whose subject is the lifecycle
of one document. A page is a different job with its own three questions, and
all three of them were findings of the perf study:

* **How many are there?** Exactly, up to ``RecordsSettings.max_count``, and
  then ``total_capped`` (F4). A page can stop after ``page_size`` matches; an
  unbounded ``COUNT`` never can, so a filter matching most of a large type
  paid for all of it on every page of it.
* **Which page?** ``?after=<cursor>`` resumes from the last row of the
  previous one instead of making the database produce and discard everything
  before it (F11). ``?page=`` stays, for the admin UI, which shows numbered
  pages.
* **In what order?** :mod:`sm_records.index._sorting` — and the order is what
  a cursor is bound to, which is why the two are decided in one place.

Nothing here commits, like everything else in this layer.
"""

from __future__ import annotations

from collections.abc import Sequence
from functools import partial
from typing import NamedTuple

from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.index.query import (
    Filter,
    Sort,
    bounded_count_query,
    decode_cursor,
    encode_cursor,
    only_trashed,
    page_query,
    sort_plan,
    sort_signature,
)
from sm_records.models import Record, RecordType, tables_for
from sm_records.settings import RecordsSettings

__all__ = ["RecordListPage", "list_records"]


class RecordListPage(NamedTuple):
    """One page of a listing, and everything a caller needs to ask for the next.

    A plain ``(items, total)`` pair no longer says enough: ``total`` is exact
    only up to ``RecordsSettings.max_count`` (F4) and may be absent entirely
    when the caller passed ``total=False``, and a cursor-paging caller needs
    the opaque ``next_cursor`` the last row produced (F11).
    """

    items: list[Record]
    """Rows of whichever table set the type lives in — the global ``Record``
    class names the shape, not the table (Phase 5 §6.3)."""
    total: int | None
    total_capped: bool
    next_cursor: str | None


async def list_records(
    db: AsyncSession,
    rtype: RecordType,
    *,
    settings: RecordsSettings,
    filters: Sequence[Filter] = (),
    sorts: Sequence[Sort] = (),
    page: int = 1,
    page_size: int | None = None,
    trashed: bool = False,
    after: str | None = None,
    with_total: bool = True,
) -> RecordListPage:
    """One page of records, with a bounded total and a cursor for the next.

    ``QueryError`` from the builder is allowed to propagate: only the endpoint
    layer knows the difference it has to express — 409 while a field is being
    reindexed, 400 for a field that is simply not queryable (§8.5).
    ``CursorError`` propagates the same way and is always a 400.

    ``trashed=True`` lists the trash and *only* the trash (see
    ``index.query.only_trashed``). Filters and sorts apply unchanged — index
    rows survive a soft delete (§7.3), so the trash is as queryable as
    anything else, and it is narrowed on both halves of the bounded count as
    well as on the page.

    ``after`` is an opaque cursor from a previous page's ``next_cursor``; it
    replaces ``OFFSET`` with the keyset predicate of
    ``index._sorting.keyset_clause``, so the cost of page 200 is the cost of
    page 1. It is bound to the sort it was produced under and refused if
    replayed against another (``index._cursor``).

    ``with_total=False`` skips the count statement altogether, which is what a
    caller walking the whole type with ``after`` should do: it is paying for a
    number it does not read, on every page.
    """
    size = settings.clamp_page_size(page_size)
    fields = list(rtype.fields or [])
    # ``only_trashed`` takes the document class because a collection type's
    # trash lives in that collection's table (Phase 5 §6.3); the ``narrow``
    # contract downstream is still one-argument, so it is bound here.
    record = tables_for(rtype).record
    narrow = partial(only_trashed, record) if trashed else None
    signature = sort_signature(rtype.key, sorts, trashed=trashed)
    decoded = decode_cursor(after, signature, sort_plan(rtype, fields, sorts)) if after else None

    total: int | None = None
    capped = False
    if with_total:
        cap = settings.max_count
        counted = int(
            (
                await db.execute(
                    bounded_count_query(rtype, fields, filters, cap=cap, narrow=narrow)
                )
            ).scalar_one()
        )
        capped = counted > cap
        total = cap if capped else counted

    stmt, terms = page_query(rtype, fields, filters, sorts, after=decoded)
    if narrow is not None:
        stmt = narrow(stmt)
    if decoded is None:
        stmt = stmt.offset(max(page - 1, 0) * size)
    rows = (await db.execute(stmt.limit(size))).all()
    items = [row[0] for row in rows]
    # A full page may have more behind it and a short one cannot, which is the
    # only "is this the last page" test that survives a capped — or absent —
    # total. A full *final* page costs the caller one more request that comes
    # back empty, which is the ordinary contract of cursor pagination.
    next_cursor = (
        encode_cursor(signature, [*rows[-1][1 : len(terms) + 1], items[-1].id])
        if len(rows) == size
        else None
    )
    return RecordListPage(items, total, capped, next_cursor)
