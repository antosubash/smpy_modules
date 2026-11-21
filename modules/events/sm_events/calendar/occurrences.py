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
from collections.abc import AsyncIterator, Sequence
from datetime import datetime, timedelta
from typing import Any

from simple_module_core.resources import ResourcePrincipal
from simple_module_db.listeners import current_tenant_id

from sm_events.calendar.occurrence import Occurrence, OccurrenceFilters, OccurrencePage
from sm_events.calendar.plugins import registry
from sm_events.calendar.plugins.extension_types import SourceViewer
from sm_events.calendar.plugins.plugin_runner import run_sources
from sm_events.calendar.plugins.plugin_scope import plugin_calls
from sm_events.calendar.sources import TRUNCATED, ReadContext, sort_key
from sm_events.calendar.times import supported_instant
from sm_events.core import constants
from sm_events.core.errors import InvalidRange
from sm_events.feeds.subscriptions.source import SUBSCRIPTIONS_SOURCE

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


async def _stream(items: Sequence[Occurrence]) -> AsyncIterator[Occurrence]:
    for item in items:
        yield item


async def occurrences(
    db: Any,
    *,
    tenant_id: str,
    viewer: ResourcePrincipal,
    start: datetime,
    end: datetime,
    filters: OccurrenceFilters,
    default_locale: str,
    source_viewer: SourceViewer | None = None,
) -> OccurrencePage:
    """What ``viewer`` may see in ``[start, end)``, sorted by ``(start, end, source, key)``.

    ``start`` and ``end`` are aware. ``tenant_id`` must be the tenant bound for
    this call. Plugin sources are called first, each isolated and bounded (see
    :mod:`sm_events.calendar.plugins.plugin_runner`), and their answers join the built-in stream
    in the one order and under the one cap; ``source_viewer`` is who they are asked for
    (``None`` for a signed-in viewer skips every plugin pair, see
    :mod:`sm_events.calendar.plugins.plugin_scope`). Raises :class:`InvalidRange` for
    ``end <= start`` and for more than 366 days, and :class:`ValueError` for an instant outside
    the supported years."""
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
    ctx = ReadContext(
        tenant_id=tenant_id,
        viewer=viewer,
        default_locale=default_locale,
        editor_url=_editor_url,
        locale=filters.locale,
    )
    calls, skipped = await plugin_calls(db, viewer, source_viewer, filters)
    ran = await run_sources(
        db,
        calls,
        tenant_id=tenant_id,
        viewer=None if viewer.user_id is None else source_viewer,
        start=start,
        end=end,
        locale=filters.locale or default_locale,
        default_locale=default_locale,
    )
    streams: list[AsyncIterator[Occurrence]] = []
    if filters.sources is None or constants.SOURCE_EVENTS in filters.sources:
        streams.append(registry.builtin_source().occurrences(db, ctx, start, end, filters))
    streams.append(SUBSCRIPTIONS_SOURCE.occurrences(db, ctx, start, end, filters))
    streams.append(_stream(ran.items))
    merged = _merge(streams)
    items: list[Occurrence] = []
    async for item in merged:
        items.append(item)
        if len(items) > constants.MAX_OCCURRENCES:
            break
    await merged.aclose()
    over = len(items) > constants.MAX_OCCURRENCES
    return OccurrencePage(
        items=items[: constants.MAX_OCCURRENCES],
        truncated=over or TRUNCATED in ctx.flags or ran.truncated,
        sources=[*ran.statuses, *skipped],
    )
