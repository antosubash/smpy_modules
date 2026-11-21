"""``VEVENT`` groups mapped onto events (Rulings 22 to 27). Pure: no database, no clock.

Components with one ``UID`` form a group: the master (no ``RECURRENCE-ID``) and its children.
Two masters with one ``UID``: the higher ``SEQUENCE`` wins, then the later; the other is skipped
``duplicate_uid``. Children without a master, or of a master that does not recur, are skipped
``override_without_master`` one by one. Series, rules and overrides are
:mod:`~sm_events.feeds.importing.mapper_series`; times :mod:`~sm_events.feeds.importing.values`;
text :mod:`~sm_events.feeds.importing.text`.

**What is dropped is counted by property name, never stored.** ``ATTENDEE`` and ``ORGANIZER``
carry addresses: only how many there were reaches the preview. An ``X-`` property is counted as
``X-*`` and anything unnamed as ``other``, so a file cannot invent report keys. Housekeeping the
module has no use for (``DTSTAMP``, ``CREATED``, ``LAST-MODIFIED``, ``SEQUENCE``, ``TRANSP``)
is not reported.
"""

from __future__ import annotations

import time
import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from sm_events.calendar.times import to_span
from sm_events.core import constants
from sm_events.core.errors import ImportFailure
from sm_events.core.text_safety import strip_unsafe
from sm_events.feeds.importing.mapper_props import (
    PRIVATE,
    category_of,
    count_dropped,
    geo_of,
    one,
    sequence_of,
    text_of,
    title_of,
    uid_of,
)
from sm_events.feeds.importing.mapper_series import map_series
from sm_events.feeds.importing.model import MappedEvent
from sm_events.feeds.importing.scan import Prop, RawEvent
from sm_events.feeds.importing.text import (
    description_html,
    http_url,
    place_truncated,
    venue,
)
from sm_events.feeds.importing.values import ItemSkip, read_when

__all__ = ["Mapped", "MappedItem", "map_calendar"]


@dataclass(frozen=True)
class MappedItem:
    """One row of the preview: a mapped event, or why there is none."""

    uid: str
    title: str
    event: MappedEvent | None
    skip: str | None
    notes: tuple[str, ...]
    starts_at: datetime | None = None
    all_day: bool = False
    recurring: bool = False


@dataclass(frozen=True)
class Mapped:
    items: list[MappedItem]
    dropped: Counter[str]


def _refused(raw: RawEvent) -> MappedItem:
    """An event that broke a per-event limit: skipped, named by its place in the file (``#17``)
    and by the ``SUMMARY`` it had before the limit tripped, when it had one."""
    uid = uid_of(raw.props)[0]
    summary = text_of(raw.props, "SUMMARY").strip()
    title = f"#{raw.position} {title_of(raw.props)[0]}" if summary else f"#{raw.position}"
    return MappedItem(uid[: constants.UID_MAX], title, None, raw.refused, ())


def _skipped(uid: str, props: Sequence[Prop], code: str, notes: tuple[str, ...] = ()) -> MappedItem:
    return MappedItem(uid[: constants.UID_MAX], title_of(props)[0], None, code, notes)


def _event(
    raw: RawEvent, children: list[RawEvent], uid: str, generated: bool, ctx
) -> tuple[MappedItem, tuple[RawEvent, ...]]:
    props = raw.props
    title, notes = title_of(props)
    calendar_tz, categories = ctx
    try:
        when = read_when(
            props,
            calendar_tz=calendar_tz,
            recurring=any(p.name == "RRULE" for p in props),
        )
        series = map_series(props, children, when, calendar_tz=calendar_tz)
    except ItemSkip as skip:
        return _skipped(uid, props, skip.code), ()
    location = text_of(props, "LOCATION").strip()
    online = http_url(location)
    lat, lon = geo_of(props)
    category, category_missed = category_of(props, categories)
    klass = one(props, "CLASS").value.strip().upper() if one(props, "CLASS") else ""
    url = one(props, "URL")
    html, html_notes = description_html(text_of(props, "DESCRIPTION"), url.value if url else None)
    status = one(props, "STATUS").value.strip().upper() if one(props, "STATUS") else ""
    extra = [
        *notes,
        *when.notes,
        *series.notes,
        *html_notes,
        *(["place_truncated"] if not online and place_truncated(location) else []),
        *(["uid_generated"] if generated else []),
        *(["category_dropped"] if category_missed else []),
        *(["kept_draft_private"] if klass in PRIVATE else []),
    ]
    mapped = MappedEvent(
        uid=uid,
        times=series.times,
        rrule=series.rrule,
        cancelled=status == "CANCELLED",
        attendance_mode="online" if online else "in_person",
        venue_name=None if online else venue(location),
        online_url=online,
        url=http_url(url.value) if url else None,
        latitude=lat,
        longitude=lon,
        category_id=category,
        title=title,
        description=html,
        private_class=klass in PRIVATE,
        overrides=series.overrides,
    )
    span = to_span(
        all_day=mapped.times.all_day,
        timezone=mapped.times.timezone,
        start=mapped.times.start,
        end=mapped.times.end,
        recurring=mapped.rrule is not None,
    )
    item = MappedItem(
        uid,
        title,
        mapped,
        None,
        tuple(dict.fromkeys(extra)),
        span.starts_at,
        mapped.times.all_day,
        mapped.rrule is not None,
    )
    return item, series.orphans


def map_calendar(
    events: Sequence[RawEvent],
    *,
    calendar_tz: str,
    categories: Mapping[str, uuid.UUID],
    deadline: float | None = None,
) -> Mapped:
    """Every group of ``events`` as items, in file order, and what was dropped."""
    dropped: Counter[str] = Counter()
    groups: dict[str, tuple[list[tuple[int, RawEvent, bool]], list[RawEvent]]] = {}
    refused: list[MappedItem] = []
    for index, raw in enumerate(events):
        if raw.refused is not None:
            refused.append(_refused(raw))
            continue
        count_dropped(raw, dropped)
        uid, generated = uid_of(raw.props)
        masters, children = groups.setdefault(uid, ([], []))
        if one(raw.props, "RECURRENCE-ID") is not None:
            children.append(raw)
        else:
            masters.append((index, raw, generated))
    items: list[MappedItem] = []
    ctx = (calendar_tz, categories)
    for uid, (masters, children) in groups.items():
        if deadline is not None and time.monotonic() > deadline:
            raise ImportFailure("too_complex", "parse_time")  # a file this costly is refused
        if not masters:
            items += [_skipped(uid, c.props, "override_without_master") for c in children]
            continue
        winner = max(masters, key=lambda m: (sequence_of(m[1]), m[0]))
        orphans: tuple[RawEvent, ...] = ()
        for index, raw, generated in masters:
            if (index, raw, generated) is winner or index == winner[0]:
                if len(uid) > constants.UID_MAX:
                    items.append(_skipped(uid, raw.props, "uid_too_long"))
                elif not uid.strip() or strip_unsafe(uid, newlines=False) != uid:
                    items.append(_skipped(uid, raw.props, "uid_invalid"))
                else:
                    item, orphans = _event(raw, children, uid, generated, ctx)
                    items.append(item)
            else:
                items.append(_skipped(uid, raw.props, "duplicate_uid"))
        items += [_skipped(uid, c.props, "override_without_master") for c in orphans]
    return Mapped(items + refused, dropped)
