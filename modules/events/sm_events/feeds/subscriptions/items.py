"""A mapped event as the columns of ``events_external_item``.

Everything goes through PR 2's own checks (``to_span``, ``rrule.parse`` and ``validate``); the
mapper has run them already, so a failure here is defence in depth and skips the item with that
error's code. Only plain text survives: no description, attendees, organiser, alarms or ``X-``
property is ever a value.

``span_start`` / ``span_end`` are the prefilter that lets one predicate find one-off items and
series alike without expanding anything: the earliest start (a moved instance can lie before the
series) and, for a series, the last end (``NULL`` for an endless rule).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, fields
from datetime import datetime
from typing import Any

from sm_events.calendar import rrule
from sm_events.calendar.times import to_span
from sm_events.core import constants
from sm_events.core.errors import InvalidRule, InvalidTimes
from sm_events.core.web_urls import is_web_url
from sm_events.feeds.importing.model import MappedEvent, MappedOverride
from sm_events.feeds.importing.text import clean_line
from sm_events.feeds.importing.values import ItemSkip

__all__ = ["ItemValues", "hash_of", "to_values"]


@dataclass(frozen=True)
class ItemValues:
    uid: str
    all_day: bool
    starts_at: datetime
    ends_at: datetime
    timezone: str
    rrule: str | None
    recurrence_until: datetime | None
    overrides: list[dict[str, Any]]
    span_start: datetime
    span_end: datetime | None
    title: str
    location: str | None
    url: str | None
    cancelled: bool
    private_class: bool
    content_hash: str = ""

    def columns(self) -> dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}


def hash_of(values: ItemValues) -> str:
    """SHA-256 of every stored field but the hash itself, as canonical JSON."""
    payload = {f.name: getattr(values, f.name) for f in fields(values) if f.name != "content_hash"}
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=_iso)
    return hashlib.sha256(text.encode()).hexdigest()


def _iso(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(type(value).__name__)


def _override(item: MappedOverride, mapped: MappedEvent) -> dict[str, Any]:
    start = end = None
    if item.kind == "moved":
        span = to_span(
            all_day=mapped.times.all_day,
            timezone=mapped.times.timezone,
            start=item.start or "",
            end=item.end or "",
            recurring=True,
            fields=("start", "end"),
        )
        start, end = span.starts_at, span.ends_at
    return {
        "original_start": item.original_start.isoformat(),
        "kind": item.kind,
        "starts_at": None if start is None else start.isoformat(),
        "ends_at": None if end is None else end.isoformat(),
    }


def to_values(mapped: MappedEvent) -> ItemValues:
    """The columns for ``mapped``; raises :class:`ItemSkip` when the module's own checks refuse
    its times or rule."""
    times = mapped.times
    try:
        span = to_span(
            all_day=times.all_day,
            timezone=times.timezone,
            start=times.start,
            end=times.end,
            recurring=mapped.rrule is not None,
        )
        rule_text = until = None
        overrides: list[dict[str, Any]] = []
        if mapped.rrule:
            rule = rrule.parse(mapped.rrule, all_day=times.all_day, timezone=times.timezone)
            until = rrule.validate(rule, span, all_day=times.all_day, timezone=times.timezone)
            rule_text = rule.text
            overrides = [_override(o, mapped) for o in mapped.overrides][
                : constants.IMPORT_MAX_OVERRIDES
            ]
    except (InvalidTimes, InvalidRule) as exc:
        raise ItemSkip(exc.code) from None
    moved = [
        (datetime.fromisoformat(o["starts_at"]), datetime.fromisoformat(o["ends_at"]))
        for o in overrides
        if o["kind"] == "moved"
    ]
    span_start = min([span.starts_at, *(start for start, _ in moved)])
    if rule_text is None:
        span_end = span.ends_at
    elif until is None:
        span_end = None
    else:
        span_end = max([until, *(end for _, end in moved)])
    url = (
        mapped.url
        if mapped.url and len(mapped.url) <= constants.SUBSCRIPTION_ITEM_URL_MAX
        else None
    )
    if mapped.private_class:  # the feed's own word: keep the time, never the text
        title, location, url = constants.SUBSCRIPTION_BUSY_TITLE, None, None
    else:
        title = clean_line(mapped.title, constants.SUBSCRIPTION_ITEM_TITLE_MAX)
        location = (
            clean_line(mapped.venue_name or "", constants.SUBSCRIPTION_ITEM_LOCATION_MAX) or None
        )
        url = url if url and is_web_url(url) else None
    values = ItemValues(
        uid=mapped.uid,
        all_day=times.all_day,
        starts_at=span.starts_at,
        ends_at=span.ends_at,
        timezone=times.timezone,
        rrule=rule_text,
        recurrence_until=until,
        overrides=overrides,
        span_start=span_start,
        span_end=span_end,
        title=title,
        location=location,
        url=url,
        cancelled=mapped.cancelled,
        private_class=mapped.private_class,
    )
    return ItemValues(**{**values.columns(), "content_hash": hash_of(values)})
