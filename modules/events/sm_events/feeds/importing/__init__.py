"""Importing an ``.ics`` file into a calendar (plan Rulings 17 to 30, in brief).

* The upload is **hostile input**. :mod:`~sm_events.feeds.importing.scan` reads it once, in
  bounded work and memory, before anything interprets a value: size, line count, line length
  (unfolded), nesting, component, property and event counts. It is also the only parser: no
  iCalendar library ever sees the file, so nothing in it is fetched, evaluated or resolved
  (``ATTACH``, ``URL``, ``TZURL`` and an alarm's ``ACTION`` are text), and a ``VTIMEZONE`` is
  counted and thrown away, never evaluated.
* :mod:`~sm_events.feeds.importing.values` and ``mapper`` turn each ``VEVENT`` into what the
  module's own validators accept (zones only from the IANA database, rules only from PR 2's
  allow-list, text through the sanitiser) or into a skip with a reason.
* The bytes live on the ``events_import`` row until the parse step has staged the items, then
  are deleted. Apply writes leased slices through the normal write path, one savepoint per
  item, with no bus attached.
* Personal data in the file (``ATTENDEE``, ``ORGANIZER``) is counted by property name and
  stored nowhere.
"""
