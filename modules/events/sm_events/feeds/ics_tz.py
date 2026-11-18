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
    """The ``VTIMEZONE`` of ``tzid`` covering the dates ``first`` to ``last``.
    Callers pass a range wider than the events (a year either side), so a client expanding a
    series past the last instant still finds a rule."""
    return icalendar.Timezone.from_tzid(tzid, first_date=first.date(), last_date=last.date())
