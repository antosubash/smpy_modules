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

import hashlib
import math
import time
import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from sm_events.calendar.times import to_span
from sm_events.core import constants
from sm_events.core.errors import ImportFailure
from sm_events.feeds.importing.mapper_series import map_series
from sm_events.feeds.importing.model import MappedEvent
from sm_events.feeds.importing.scan import Prop, RawEvent
from sm_events.feeds.importing.text import (
    clean_title,
    description_html,
    http_url,
    unescape,
    venue,
)
from sm_events.feeds.importing.values import ItemSkip, read_when
from sm_events.web.schemas._fields import strip_unsafe

__all__ = ["Mapped", "MappedItem", "map_calendar"]

_USED: Final = frozenset(
    [
        "UID",
        "DTSTART",
        "DTEND",
        "DURATION",
        "SUMMARY",
        "DESCRIPTION",
        "URL",
        "LOCATION",
        "GEO",
        "STATUS",
        "CATEGORIES",
        "CLASS",
        "RRULE",
        "EXDATE",
        "RECURRENCE-ID",
    ]
)
_QUIET: Final = frozenset(["DTSTAMP", "CREATED", "LAST-MODIFIED", "SEQUENCE", "TRANSP"])
_REPORTED: Final = frozenset(["ATTENDEE", "ORGANIZER", "ATTACH", "RELATED-TO", "X-ALT-DESC"])
_PRIVATE: Final = frozenset({"PRIVATE", "CONFIDENTIAL"})


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


def _one(props: Sequence[Prop], name: str) -> Prop | None:
    return next((p for p in props if p.name == name), None)


def _text(props: Sequence[Prop], name: str) -> str:
    prop = _one(props, name)
    return unescape(prop.value) if prop is not None else ""


def _uid(props: Sequence[Prop]) -> tuple[str, bool]:
    prop = _one(props, "UID")
    if prop is not None and prop.value.strip():
        return prop.value, False
    start = _one(props, "DTSTART")
    line = (
        ""
        if start is None
        else ";".join([start.name, *(f"{k}={v}" for k, v in start.params.items())])
        + ":"
        + start.value
    )
    digest = hashlib.sha256(f"{line}\n{_text(props, 'SUMMARY')}".encode()).hexdigest()[:32]
    return f"{digest}@import{constants.UID_SUFFIX}", True


def _sequence(raw: RawEvent) -> int:
    prop = _one(raw.props, "SEQUENCE")
    try:
        return max(0, min(int(prop.value.strip()), 10**9)) if prop is not None else 0
    except ValueError:
        return 0


def _count_dropped(raw: RawEvent, dropped: Counter[str]) -> None:
    for prop in raw.props:
        if prop.name in _USED or prop.name in _QUIET:
            continue
        dropped[
            prop.name
            if prop.name in _REPORTED
            else "X-*"
            if prop.name.startswith("X-")
            else "other"
        ] += 1
    dropped.update(raw.children)


def _geo(props: Sequence[Prop]) -> tuple[float | None, float | None]:
    prop = _one(props, "GEO")
    parts = prop.value.split(";") if prop is not None else []
    if len(parts) != 2:
        return None, None
    try:
        lat, lon = float(parts[0]), float(parts[1])
    except ValueError:
        return None, None
    if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
        return None, None
    return lat, lon


def _category(
    props: Sequence[Prop], categories: Mapping[str, uuid.UUID]
) -> tuple[uuid.UUID | None, bool]:
    prop = _one(props, "CATEGORIES")
    if prop is None:
        return None, False
    for name in prop.value.split(","):
        found = categories.get(unescape(name).strip().lower())
        if found is not None:
            return found, False
    return None, True


def _title(props: Sequence[Prop]) -> tuple[str, tuple[str, ...]]:
    return clean_title(_text(props, "SUMMARY"))


def _skipped(uid: str, props: Sequence[Prop], code: str, notes: tuple[str, ...] = ()) -> MappedItem:
    return MappedItem(uid[: constants.UID_MAX], _title(props)[0], None, code, notes)


def _event(
    raw: RawEvent, children: list[RawEvent], uid: str, generated: bool, ctx
) -> tuple[MappedItem, tuple[RawEvent, ...]]:
    props = raw.props
    title, notes = _title(props)
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
    location = _text(props, "LOCATION").strip()
    online = http_url(location)
    lat, lon = _geo(props)
    category, category_missed = _category(props, categories)
    klass = _one(props, "CLASS").value.strip().upper() if _one(props, "CLASS") else ""
    url = _one(props, "URL")
    html, html_notes = description_html(_text(props, "DESCRIPTION"), url.value if url else None)
    status = _one(props, "STATUS").value.strip().upper() if _one(props, "STATUS") else ""
    extra = [
        *notes,
        *when.notes,
        *series.notes,
        *html_notes,
        *(["uid_generated"] if generated else []),
        *(["category_dropped"] if category_missed else []),
        *(["kept_draft_private"] if klass in _PRIVATE else []),
    ]
    mapped = MappedEvent(
        uid=uid,
        times=series.times,
        rrule=series.rrule,
        cancelled=status == "CANCELLED",
        attendance_mode="online" if online else "in_person",
        venue_name=None if online else venue(location),
        online_url=online,
        latitude=lat,
        longitude=lon,
        category_id=category,
        title=title,
        description=html,
        private_class=klass in _PRIVATE,
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
    for index, raw in enumerate(events):
        _count_dropped(raw, dropped)
        uid, generated = _uid(raw.props)
        masters, children = groups.setdefault(uid, ([], []))
        if _one(raw.props, "RECURRENCE-ID") is not None:
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
        winner = max(masters, key=lambda m: (_sequence(m[1]), m[0]))
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
    return Mapped(items, dropped)
