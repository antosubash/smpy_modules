"""The occurrences read: every range question about a calendar goes through here.

Bounds are enforced here and not by callers: a range is at most
``MAX_RANGE_DAYS`` days, at most ``MAX_OCCURRENCES`` occurrences come back and
``truncated`` says there were more, and no series is ever iterated without an
upper bound (see :mod:`sm_events.calendar.expand`). The work done is roughly the
cap plus the number of series, whatever the range holds.
"""

from __future__ import annotations

import heapq
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from typing import Any

from simple_module_core.resources import ResourcePrincipal
from simple_module_db.listeners import current_tenant_id

from sm_events.calendar.occurrence import Occurrence, OccurrenceFilters, OccurrencePage
from sm_events.calendar.sources import SOURCES, TRUNCATED, SourceContext, sort_key
from sm_events.calendar.times import supported_instant
from sm_events.core import constants
from sm_events.core.errors import InvalidRange

__all__ = ["occurrences"]


def _aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")


def _editor_url(event_id: uuid.UUID) -> str:
    return f"{constants.EDITOR_URL}/{event_id}"


async def _merge(streams: list[AsyncIterator[Occurrence]]) -> AsyncIterator[Occurrence]:
    """A k-way merge of async streams, each ascending by :func:`sort_key`."""
    heap: list[tuple[Any, int, Occurrence]] = []
    for index, stream in enumerate(streams):
        first = await anext(stream, None)
        if first is not None:
            heap.append((sort_key(first), index, first))
    heapq.heapify(heap)
    while heap:
        _key, index, item = heapq.heappop(heap)
        yield item
        following = await anext(streams[index], None)
        if following is not None:
            heapq.heappush(heap, (sort_key(following), index, following))


async def occurrences(
    db: Any,
    *,
    tenant_id: str,
    viewer: ResourcePrincipal,
    start: datetime,
    end: datetime,
    filters: OccurrenceFilters,
    default_locale: str,
) -> OccurrencePage:
    """What ``viewer`` may see in ``[start, end)``, sorted by ``(start, end, source, key)``.

    ``start`` and ``end`` are aware. ``tenant_id`` must be the tenant bound for
    this call. Raises :class:`InvalidRange` for ``end <= start`` and for more than
    366 days, and :class:`ValueError` for an instant outside the supported years."""
    _aware(start, "start")
    _aware(end, "end")
    supported_instant(start)
    supported_instant(end)
    if end <= start:
        raise InvalidRange
    if end - start > timedelta(days=constants.MAX_RANGE_DAYS):
        raise InvalidRange(constants.RANGE_TOO_LONG_DETAIL, code=constants.RANGE_TOO_LONG_CODE)
    if current_tenant_id.get() != tenant_id:
        raise ValueError("tenant_id is not the tenant bound for this read")
    ctx = SourceContext(
        tenant_id=tenant_id,
        viewer=viewer,
        default_locale=default_locale,
        editor_url=_editor_url,
        locale=filters.locale,
    )
    merged = _merge([s.occurrences(db, ctx, start, end, filters) for s in SOURCES.values()])
    items: list[Occurrence] = []
    async for item in merged:
        items.append(item)
        if len(items) > constants.MAX_OCCURRENCES:
            break
    await merged.aclose()
    over = len(items) > constants.MAX_OCCURRENCES
    return OccurrencePage(
        items=items[: constants.MAX_OCCURRENCES], truncated=over or TRUNCATED in ctx.flags
    )
