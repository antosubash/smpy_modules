"""External items as a built-in, read-only source of the occurrences read.

**Who sees what.** Exactly the calendars the viewer may see (the access policy's own filter), so
the audience of an external item is the audience of its calendar. On a public read (no user) only
subscriptions marked ``public`` count, and never an item the feed classed ``PRIVATE`` or
``CONFIDENTIAL``. Paused, failing and disabled subscriptions keep showing what was cached.

**What an entry is.** ``source`` is ``subscriptions`` and its key is namespaced by the
subscription (``<subscription hex>:<hash of the feed's UID>[:<original start>]``), so it can
never collide with an event or a plugin's entry, and the feed's UID stays an opaque value. It is
read-only (``editable`` false, no event id), carries the subscription's label as ``origin_label``
and links to the feed's own ``URL`` when it has one.

**Bounds.** Two statements; one-offs and series are limited in SQL; each series is expanded
lazily by PR 2's :func:`~sm_events.calendar.expand.instances` with the window as its upper bound;
the merge stops at the read's cap.
"""

from __future__ import annotations

import hashlib
import heapq
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import datetime
from itertools import islice
from typing import Any, Final

from sqlmodel import col

from sm_events.calendar import rrule
from sm_events.calendar.expand import instances
from sm_events.calendar.occurrence import Occurrence, OccurrenceFilters
from sm_events.calendar.sources import TRUNCATED, ReadContext, sort_key
from sm_events.calendar.times import Span, all_day_dates
from sm_events.core import constants
from sm_events.core.access import visible_calendars
from sm_events.core.errors import InvalidRule
from sm_events.feeds.subscriptions import window
from sm_events.models import Calendar, ExternalItem, Subscription

__all__ = ["SUBSCRIPTIONS_SOURCE", "SubscriptionsSource", "item_key"]

_SKIPPED: Final = "skipped"
_CANCELLED: Final = "cancelled"
_MOVED: Final = "moved"


def item_key(sub_id: uuid.UUID, uid: str, original_start: datetime | None) -> str:
    digest = hashlib.sha256(uid.encode()).hexdigest()[:24]
    key = f"{sub_id.hex}:{digest}"
    if original_start is None:
        return key
    return f"{key}:{original_start.strftime(constants.OCCURRENCE_KEY_STAMP)}"


class _Builder:
    def __init__(self, subs: dict[uuid.UUID, Subscription], cals: dict[uuid.UUID, Calendar]):
        self.subs, self.cals = subs, cals

    def build(
        self,
        item: ExternalItem,
        start: datetime,
        end: datetime,
        *,
        original_start: datetime | None,
        cancelled: bool,
    ) -> Occurrence:
        sub = self.subs[item.subscription_id]
        cal = self.cals[sub.calendar_id]
        first = last = None
        if item.all_day:
            first, last = all_day_dates(Span(start, end), item.timezone)
        return Occurrence(
            source=constants.SOURCE_SUBSCRIPTIONS,
            key=item_key(sub.id, item.uid, original_start),
            calendar_id=cal.id,
            start=start,
            end=end,
            all_day=item.all_day,
            timezone=item.timezone,
            start_date=first,
            end_date=last,
            title=item.title,
            lang="",
            color=sub.color or cal.color,
            url=item.url,
            status=_CANCELLED if cancelled or item.cancelled else "confirmed",  # type: ignore[arg-type]
            type=constants.BUILTIN_TYPE,
            editable=False,
            original_start=original_start,
            origin_label=sub.label,
        )


def _changes(item: ExternalItem) -> dict[datetime, dict[str, Any]]:
    return {datetime.fromisoformat(o["original_start"]): o for o in item.overrides}


def _series(item: ExternalItem, built: _Builder, start: datetime, end: datetime):
    try:
        rule = rrule.parse(item.rrule or "", all_day=item.all_day, timezone=item.timezone)
    except InvalidRule:
        return  # a stored rule that no longer parses shows nothing, never an error
    over = _changes(item)
    for inst in instances(
        rule=rule,
        span=Span(item.starts_at, item.ends_at),
        all_day=item.all_day,
        timezone=item.timezone,
        window_start=start,
        window_end=end,
        recurrence_until=item.recurrence_until,
    ):
        kind = over.get(inst.original_start, {}).get("kind")
        if kind in (_SKIPPED, _MOVED):
            continue  # a moved one is emitted at its new time by the moved stream
        yield built.build(
            item,
            inst.start,
            inst.end,
            original_start=inst.original_start,
            cancelled=kind == _CANCELLED,
        )


def _moved(items: list[ExternalItem], built: _Builder, start: datetime, end: datetime):
    found: list[Occurrence] = []
    for item in items:
        for original, change in _changes(item).items():
            if change["kind"] != _MOVED or not change["starts_at"] or not change["ends_at"]:
                continue
            new_start = datetime.fromisoformat(change["starts_at"])
            new_end = datetime.fromisoformat(change["ends_at"])
            if new_start < end and new_end > start:
                found.append(
                    built.build(item, new_start, new_end, original_start=original, cancelled=False)
                )
    return iter(sorted(found, key=sort_key))


class SubscriptionsSource:
    id = constants.SOURCE_SUBSCRIPTIONS
    label_key = constants.SUBSCRIPTIONS_SOURCE_LABEL_KEY
    public = True
    color = None
    icon = constants.SUBSCRIPTIONS_SOURCE_ICON
    settings_model = None

    def _applies(self, filters: OccurrenceFilters) -> bool:
        """A narrower filter drops external entries: they are of the default type, have no
        category and no event id."""
        if filters.sources is not None and self.id not in filters.sources:
            return False
        if self.id in filters.exclude_sources:
            return False
        if filters.types is not None and constants.BUILTIN_TYPE not in filters.types:
            return False
        return filters.category_ids is None and filters.event_ids is None

    async def occurrences(
        self, db: Any, ctx: ReadContext, start: datetime, end: datetime, filters: OccurrenceFilters
    ) -> AsyncIterator[Occurrence]:
        if not self._applies(filters):
            return
        stmt = visible_calendars(ctx.viewer)
        if filters.calendar_ids is not None:
            stmt = stmt.where(col(Calendar.id).in_(filters.calendar_ids))
        stmt = stmt.limit(constants.CALENDARS_MAX)
        cals = {c.id: c for c in (await db.execute(stmt)).scalars().all()}
        anonymous = ctx.viewer.user_id is None
        subs = {s.id: s for s in await window.live_subscriptions(db, cals, public_only=anonymous)}
        if not subs:
            return
        one_offs, series, truncated = await window.items_in_window(
            db, subs, start, end, limit=constants.MAX_OCCURRENCES, public_only=anonymous
        )
        if truncated:
            ctx.flags.add(TRUNCATED)
        built = _Builder(subs, cals)
        singles = sorted(
            (
                built.build(i, i.starts_at, i.ends_at, original_start=None, cancelled=False)
                for i in one_offs
            ),
            key=sort_key,
        )
        streams: list[Iterator[Occurrence]] = [iter(singles), _moved(series, built, start, end)]
        streams.extend(_series(item, built, start, end) for item in series)
        for occurrence in islice(
            heapq.merge(*streams, key=sort_key), constants.MAX_OCCURRENCES + 1
        ):
            yield occurrence


SUBSCRIPTIONS_SOURCE = SubscriptionsSource()
