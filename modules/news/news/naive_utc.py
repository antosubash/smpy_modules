"""A stored instant may come back without its timezone.

SQLite drops tz info on round-trip: every timestamp this module writes is UTC,
but a value read back from a SQLite-backed dev database is naive. Comparing
that against an aware ``datetime.now(UTC)`` — or handing it to
``email.utils.format_datetime``, which treats a naive value as local time —
is wrong in two different ways depending on where it happens. Both call
through here instead of repeating the same three-line fixup.

Its own module rather than a helper on one caller because both a workflow
transition and the RSS feed need it, and neither is upstream of the other.
"""

from __future__ import annotations

from datetime import UTC, datetime


def as_utc(value: datetime | None) -> datetime | None:
    """Attach UTC to a naive instant, leave an aware one alone.

    Every value this module writes was UTC, so assuming UTC for one that came
    back naive matches how it was stored.
    """
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value
