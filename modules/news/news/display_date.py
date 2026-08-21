"""``published_at`` is a display date that arrives as an instant.

The API has always accepted a full timestamp, and the list, the feed block and
the public page all render the date part in UTC. Those two facts did not agree:
``2026-02-01T23:00:00-06:00`` — 6pm on the 1st where it was sent from — stored
as ``2026-02-02T05:00:00Z`` and listed as the 2nd.

Its own module rather than a helper in the service because it is a rule about
the *contract*, applied where the value enters, and because the one thing it
must not do is drift between the three DTOs that carry the field.
"""

from __future__ import annotations

from datetime import UTC, datetime


def as_display_date(value: datetime | None) -> datetime | None:
    """Midnight UTC on the calendar day the sender wrote.

    The offset is deliberately *not* applied first. A display date means the
    day its author picked in a date field; converting to UTC before truncating
    would roll that day forward for everyone west of UTC, which is the bug this
    exists to remove rather than a rounding detail.

    ``None`` passes through: an undated article is work in progress, and that
    is a real value rather than a missing one.
    """
    if value is None:
        return None
    return value.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=UTC)
