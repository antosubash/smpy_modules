"""The ``VTIMEZONE`` a timed event's ``TZID`` refers to.

Installed ``icalendar`` 7.3.0: ``icalendar.Timezone.from_tzid(tzid, first_date=..., last_date=...)``
builds a ``VTIMEZONE`` with ``STANDARD`` and ``DAYLIGHT`` sub-components for the transitions in
the range, from the ``zoneinfo`` database. This is the only place that calls it.
"""

from __future__ import annotations

from datetime import datetime

import icalendar

__all__ = ["vtimezone"]


def vtimezone(tzid: str, first: datetime, last: datetime) -> icalendar.Timezone:
    """The ``VTIMEZONE`` of ``tzid`` with explicit ``STANDARD``/``DAYLIGHT`` transitions from the
    dates ``first`` to ``last`` (``icalendar`` emits ``RDATE`` lists, no ``RRULE``).

    Correct only inside that range: the file is the one source of offsets for a client that
    expands the event's ``RRULE``, so the caller covers the first start, the end of a bounded
    series and, for an open-ended one, a fixed horizon (``FEED_ZONE_YEARS_AHEAD`` years). Past
    the horizon a client applies the last offset, which a zone with daylight saving then gets
    wrong for half the year."""
    return icalendar.Timezone.from_tzid(tzid, first_date=first.date(), last_date=last.date())
