"""The calendar file: ``VCALENDAR`` properties, the ``VTIMEZONE``s, the components in order.

Built only with ``icalendar``. The body is deterministic (``DTSTAMP`` is the row's own
timestamp, components are ordered by ``(starts_at, uid, recurrence-id)``), so the response's
``ETag`` can be a digest of it. The caps are applied by the read
(:mod:`~sm_events.feeds.select`), so nothing here cuts.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import icalendar

from sm_events.core import constants
from sm_events.feeds import ics_tz
from sm_events.feeds.ics_event import FeedEvent, components, tzids
from sm_events.feeds.sanitize import single_line

__all__ = ["build"]

_REFRESH = timedelta(hours=1)
_TTL = "PT1H"
_LATEST = datetime(constants.FEED_ZONE_LAST_YEAR, 12, 31, tzinfo=UTC)


def build(
    items: Sequence[FeedEvent], *, name: str, timezone: str, first: datetime, last: datetime
) -> bytes:
    """One ``VCALENDAR`` holding ``items``. ``first`` and ``last`` bound the ``VTIMEZONE``s, which
    list explicit transitions only (``icalendar`` writes no ``RRULE`` for them), so they are widened
    to every event's first start and to the end of every series (``recurrence_until``). The caller
    passes a horizon for open-ended ones; a client expanding past it would apply the last offset."""
    ordered = sorted(items, key=lambda i: (i.event.starts_at, i.event.uid))
    cal = icalendar.Calendar()
    cal.add("prodid", constants.PRODID)
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("x-wr-calname", single_line(name))
    cal.add("x-wr-timezone", timezone)
    cal.add("refresh-interval", _REFRESH, parameters={"VALUE": "DURATION"})
    cal.add("x-published-ttl", _TTL)
    if ordered:
        first = min(first, *(i.event.starts_at for i in ordered))
        ends = [i.event.recurrence_until or i.event.ends_at for i in ordered]
        last = min(max(last, *ends), _LATEST)
    for zone in sorted(tzids(ordered)):
        cal.add_component(ics_tz.vtimezone(zone, first, last))
    for item in ordered:
        for component in components(item):
            cal.add_component(component)
    return cal.to_ical()
