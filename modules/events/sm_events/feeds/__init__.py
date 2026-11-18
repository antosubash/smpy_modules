"""ICS feeds: public calendar files and single-event files.

Feeds read event **rows** with their rules and overrides, through the public gate
(:func:`sm_events.core.access.public.public_events`), never through the occurrences read: a
series is emitted as ``RRULE`` plus ``EXDATE`` and ``RECURRENCE-ID`` and the client expands it.
Everything is built with the ``icalendar`` library (BSD-2-Clause), which owns escaping, line
folding and CRLF. ``recurring-ical-events`` (LGPL) is never used.
"""
