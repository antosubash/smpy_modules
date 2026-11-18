"""The calendar file: ``VCALENDAR`` properties, the ``VTIMEZONE``s, the components in order.

Built only with ``icalendar``. The body is deterministic (``DTSTAMP`` is the row's own
timestamp, components are ordered by ``(starts_at, uid, recurrence-id)``), so the response's
``ETag`` can be a digest of it. The caps are applied by the read
(:mod:`~sm_events.feeds.select`), so nothing here cuts.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta

import icalendar

from sm_events.core import constants
from sm_events.feeds import ics_tz
from sm_events.feeds.ics_event import FeedEvent, components, tzids

__all__ = ["build"]

_REFRESH = timedelta(hours=1)
_TTL = "PT1H"


def build(
    items: Sequence[FeedEvent], *, name: str, timezone: str, first: datetime, last: datetime
) -> bytes:
    """One ``VCALENDAR`` holding ``items``. ``first`` and ``last`` bound the ``VTIMEZONE``s,
    widened to every event's own span so a series' start is always covered."""
    ordered = sorted(items, key=lambda i: (i.event.starts_at, i.event.uid))
    cal = icalendar.Calendar()
    cal.add("prodid", constants.PRODID)
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("x-wr-calname", name)
    cal.add("x-wr-timezone", timezone)
    cal.add("refresh-interval", _REFRESH, parameters={"VALUE": "DURATION"})
    cal.add("x-published-ttl", _TTL)
    if ordered:
        first = min(first, *(i.event.starts_at for i in ordered))
        last = max(last, *(i.event.ends_at for i in ordered))
    for zone in sorted(tzids(ordered)):
        cal.add_component(ics_tz.vtimezone(zone, first, last))
    for item in ordered:
        for component in components(item):
            cal.add_component(component)
    return cal.to_ical()
