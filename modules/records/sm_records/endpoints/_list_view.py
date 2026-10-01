"""The record list view's one query — by offset, or by keyset past the cap.

Split from :mod:`sm_records.endpoints.views` for the 300-line cap when the
screen learned ``?after=``. What lives here is the part that differs from the
JSON API's ``GET …/records``: the same service call, but every refusal the API
answers with a 400 becomes a *reason* in the page's ``errors`` bag instead,
because this is a page navigation and Inertia shows any error status as a
modal over a screen that already knows how to say what is wrong.

**Two ways to ask for a page, as on the API.** ``?page=`` is the numbered
pager the footer draws; ``?after=<cursor>`` is "the rows the order puts after
this one" — the same opaque ``next_cursor`` the API returns, bound to the same
sort signature — and is how the screen reaches rows past
``RecordsSettings.max_count``, where the count (and so the numbered pager)
stops. ``page`` other than 1 *and* ``after`` is refused rather than resolved
in favour of either, for the reason ``deps.parse_cursor`` gives: they answer
the same question differently and a URL carrying both was not written by this
screen.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final, NamedTuple

from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.contracts.schemas import RecordPage
from sm_records.index.query import CursorError, Filter, QueryError, Sort
from sm_records.models import RecordType
from sm_records.services import records as record_service
from sm_records.settings import RecordsSettings

__all__ = [
    "BAD_CURSOR",
    "PAGE_AND_AFTER",
    "ListOutcome",
    "RecordListViewPage",
    "run_listing",
]

BAD_CURSOR: Final = "bad_cursor"
"""``errors["filter"]`` for an ``?after=`` the service refuses: one that does
not decode, or was minted under another sort, trash view or field kind
(``index._cursor``). The API's 400 for the same cursor, as a notice."""

PAGE_AND_AFTER: Final = "page_and_after"
"""``errors["filter"]`` for ``?page=N&after=…`` — the API's other paging 400."""


class RecordListViewPage(RecordPage):
    """:class:`RecordPage` as the list *screen* receives it.

    ``page`` is ``None`` on a page reached by cursor: it is somewhere past the
    numbered pages and has no number, and inventing one (1, or the last page
    of the cap) would put a false "Page N" in the footer. The JSON API's
    ``RecordPage`` is untouched — it echoes whatever ``page`` it was sent.
    """

    page: int | None  # type: ignore[assignment]


class ListOutcome(NamedTuple):
    items: list
    total: int | None
    capped: bool
    next_cursor: str | None
    error: str | None
    """The ``errors["filter"]`` reason, or ``None`` when the query ran."""


_REFUSED = ([], 0, False, None)


async def run_listing(
    db: AsyncSession,
    rtype: RecordType,
    *,
    settings: RecordsSettings,
    filters: Sequence[Filter],
    malformed: str | None,
    sorts: Sequence[Sort],
    page: int,
    page_size: int,
    trashed: bool,
    after: str | None,
) -> ListOutcome:
    """One page for the list screen, or the reason there is none.

    The total is counted on a cursor page too: the footer no longer shows a
    range there, but "Empty trash" still states and confirms a count, and the
    count is bounded by ``max_count`` whichever way the page was asked for.
    """
    if malformed is not None:
        # A ``?filter=`` term that does not parse at all, which the API
        # answers with a 400 raised from the dependency.
        return ListOutcome(*_REFUSED, malformed)
    if after is not None and page != 1:
        return ListOutcome(*_REFUSED, PAGE_AND_AFTER)
    try:
        result = await record_service.list_records(
            db,
            rtype,
            settings=settings,
            filters=filters,
            sorts=sorts,
            page=page,
            page_size=page_size,
            trashed=trashed,
            after=after,
        )
    except CursorError:
        return ListOutcome(*_REFUSED, BAD_CURSOR)
    except QueryError as exc:
        # A filter on a field that is mid-reindex (design §8.5), unknown or
        # unindexed — a 409/400 on the API, a notice here. The screen renders
        # empty with the reason in Inertia's own ``errors`` bag, the channel
        # form validation uses, and shows it inline.
        return ListOutcome(*_REFUSED, exc.reason)
    return ListOutcome(result.items, result.total, result.total_capped, result.next_cursor, None)
