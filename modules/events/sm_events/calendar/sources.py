"""Occurrence sources. The module's own events are the built-in source ``events``.

A source is one object behind :class:`Source`; the read merges every source in
:data:`SOURCES` (PR 6 swaps that dict for its registry). A source yields its
occurrences ascending by ``(start, end, key)`` and never more than it needs: the
caller stops pulling at the cap.
"""

from __future__ import annotations

import heapq
import logging
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from simple_module_core.resources import ResourcePrincipal

from sm_events.calendar import rrule, window
from sm_events.calendar.expand import Instance, instances
from sm_events.calendar.occurrence import Occurrence, OccurrenceFilters
from sm_events.calendar.times import Span, all_day_dates
from sm_events.core import constants
from sm_events.core.access.events import is_locked
from sm_events.core.errors import InvalidRule
from sm_events.models import OccurrenceOverride, OverrideKind

__all__ = ["EVENTS_SOURCE", "SOURCES", "Source", "SourceContext", "sort_key"]

logger = logging.getLogger(__name__)

TRUNCATED = "truncated"


@dataclass(frozen=True)
class SourceContext:
    tenant_id: str
    viewer: ResourcePrincipal
    default_locale: str
    editor_url: Callable[[uuid.UUID], str]
    locale: str | None = None
    flags: set[str] = field(default_factory=set)
    """A source adds :data:`TRUNCATED` when it left rows out for its own bounds."""


class Source(Protocol):
    id: str

    def occurrences(
        self,
        db: Any,
        ctx: SourceContext,
        start: datetime,
        end: datetime,
        filters: OccurrenceFilters,
    ) -> AsyncIterator[Occurrence]: ...


def sort_key(item: Occurrence) -> tuple[datetime, datetime, str, str]:
    return item.start, item.end, item.source, item.key


def _pick_title(texts: dict[str, str], *locales: str | None) -> tuple[str, str]:
    for locale in locales:
        if locale is not None and locale in texts:
            return texts[locale], locale
    if not texts:
        return "", ""
    first = min(texts)
    return texts[first], first


class _Builder:
    """Turns an event and a time into an :class:`Occurrence`."""

    def __init__(self, ctx: SourceContext, titles: dict, writable: set[uuid.UUID]) -> None:
        self.ctx, self.titles, self.writable = ctx, titles, writable
        self.can_publish = ctx.viewer.has(constants.PERM_PUBLISH)

    def build(
        self,
        row: window.Row,
        start: datetime,
        end: datetime,
        *,
        key: str,
        original_start: datetime | None,
        cancelled: bool,
    ) -> Occurrence:
        event, calendar_color, category_color = row
        title, lang = _pick_title(
            self.titles.get(event.id, {}), self.ctx.locale, self.ctx.default_locale
        )
        editable = event.calendar_id in self.writable and (self.can_publish or not is_locked(event))
        first = last = None
        if event.all_day:
            first, last = all_day_dates(Span(start, end), event.timezone)
        return Occurrence(
            source=constants.SOURCE_EVENTS,
            key=key,
            calendar_id=event.calendar_id,
            start=start,
            end=end,
            all_day=event.all_day,
            timezone=event.timezone,
            start_date=first,
            end_date=last,
            title=title,
            lang=lang,
            color=category_color or calendar_color,
            url=self.ctx.editor_url(event.id) if editable else None,
            status=(
                constants.OCCURRENCE_CANCELLED
                if cancelled or event.cancelled
                else constants.OCCURRENCE_CONFIRMED
            ),  # type: ignore[arg-type]
            type=event.type,
            editable=editable,
            event_id=event.id,
            original_start=original_start,
            event_status=event.status,
        )


def _instance_key(event_id: uuid.UUID, original_start: datetime) -> str:
    return f"{event_id}:{original_start.strftime(constants.OCCURRENCE_KEY_STAMP)}"


def _series_stream(
    row: window.Row,
    built: _Builder,
    over: dict[datetime, OccurrenceOverride],
    start: datetime,
    end: datetime,
) -> Iterator[Occurrence]:
    event = row[0]
    try:
        rule = rrule.parse(event.rrule or "", all_day=event.all_day, timezone=event.timezone)
    except InvalidRule:
        logger.warning("event %s has a stored rule that no longer parses; skipped", event.id)
        return
    found: Iterator[Instance] = instances(
        rule=rule,
        span=Span(event.starts_at, event.ends_at),
        all_day=event.all_day,
        timezone=event.timezone,
        window_start=start,
        window_end=end,
        recurrence_until=event.recurrence_until,
    )
    for inst in found:
        change = over.get(inst.original_start)
        kind = change.kind if change is not None else None
        if kind in (OverrideKind.SKIPPED.value, OverrideKind.MOVED.value):
            continue  # a moved one is emitted at its new time by the moved stream
        yield built.build(
            row,
            inst.start,
            inst.end,
            key=_instance_key(event.id, inst.original_start),
            original_start=inst.original_start,
            cancelled=kind == OverrideKind.CANCELLED.value,
        )


def _moved_stream(
    rows: dict[uuid.UUID, window.Row],
    over: dict[uuid.UUID, dict[datetime, OccurrenceOverride]],
    built: _Builder,
    start: datetime,
    end: datetime,
) -> Iterator[Occurrence]:
    found: list[Occurrence] = []
    for event_id, changes in over.items():
        row = rows.get(event_id)
        if row is None:
            continue
        for change in changes.values():
            if change.kind != OverrideKind.MOVED.value:
                continue
            if change.starts_at is None or change.ends_at is None:
                continue
            if change.starts_at < end and change.ends_at > start:
                found.append(
                    built.build(
                        row,
                        change.starts_at,
                        change.ends_at,
                        key=_instance_key(event_id, change.original_start),
                        original_start=change.original_start,
                        cancelled=False,
                    )
                )
    return iter(sorted(found, key=sort_key))


class EventsSource:
    """The module's own events: one-offs from SQL, series expanded lazily."""

    id = constants.SOURCE_EVENTS

    async def occurrences(
        self,
        db: Any,
        ctx: SourceContext,
        start: datetime,
        end: datetime,
        filters: OccurrenceFilters,
    ) -> AsyncIterator[Occurrence]:
        singles = await window.one_offs(db, ctx.viewer, start, end, filters)
        recurring, over_cap = await window.series(
            db, ctx.viewer, ctx.tenant_id, start, end, filters
        )
        if over_cap:
            ctx.flags.add(TRUNCATED)
        ids = [r[0].id for r in singles + recurring]
        titles = await window.texts(db, ids)
        series_ids = [r[0].id for r in recurring]
        over = await window.overrides(db, series_ids, start, end)
        built = _Builder(ctx, titles, await window.writable_calendars(db, ctx.viewer))
        one_offs = sorted(
            (
                built.build(
                    row,
                    row[0].starts_at,
                    row[0].ends_at,
                    key=str(row[0].id),
                    original_start=None,
                    cancelled=False,
                )
                for row in singles
            ),
            key=sort_key,
        )
        streams = [iter(one_offs)]
        streams.extend(
            _series_stream(row, built, over.get(row[0].id, {}), start, end) for row in recurring
        )
        streams.append(_moved_stream({r[0].id: r for r in recurring}, over, built, start, end))
        for item in heapq.merge(*streams, key=sort_key):
            yield item


EVENTS_SOURCE = EventsSource()
SOURCES: dict[str, Source] = {EVENTS_SOURCE.id: EVENTS_SOURCE}
