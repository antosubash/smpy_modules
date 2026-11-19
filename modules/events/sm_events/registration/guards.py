"""What a change to an event may not do to the seats that exist.

* **The form is fixed while people hold seats**: the mode, the provider and the target cannot
  change (409 ``registration_has_seats``). Capacity, the window, "show seats left" and the
  reminder lead can: lowering the capacity below the seats taken never evicts anyone, the
  occurrence is simply full until seats free.
* **A series change cannot strand seats**: if the rule, the start, the timezone or the all-day flag
  changes so that an occurrence holding seats is no longer one, the change is refused (409
  ``registrations_orphaned``). There is no override flag: cancel those occurrences instead.

Both read the seat table and nothing else, and both run inside the write's savepoint after the
stale guard, so a refusal writes nothing.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Collection
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from sm_events.calendar import rrule
from sm_events.calendar.expand import is_occurrence
from sm_events.content.schedule import Schedule
from sm_events.core import constants
from sm_events.core.errors_registration import RegistrationHasSeats, RegistrationsOrphaned
from sm_events.models import Event, RegistrationSeat
from sm_events.web.schemas.registration import RegistrationIn

__all__ = ["guard_seats", "has_seats", "seat_keys", "seat_keys_orphaned_by"]

_STAMPED = re.compile(r"^(?P<id>[0-9a-f-]{36}):(?P<stamp>\d{8}T\d{6}Z)$")


async def seat_keys(db: Any, event_id: uuid.UUID) -> list[str]:
    """The occurrence keys of ``event_id`` that hold at least one seat."""
    stmt = (
        select(RegistrationSeat.occurrence_key)
        .where(RegistrationSeat.event_id == event_id)
        .distinct()
        .order_by(RegistrationSeat.occurrence_key)
    )
    return list((await db.execute(stmt)).scalars().all())


async def has_seats(db: Any, event_id: uuid.UUID) -> bool:
    stmt = select(RegistrationSeat.id).where(RegistrationSeat.event_id == event_id).limit(1)
    return (await db.execute(stmt)).first() is not None


def _still_an_occurrence(key: str, event_id: uuid.UUID, plan: Schedule) -> bool:
    if plan.rrule is None:
        return key == str(event_id)
    found = _STAMPED.fullmatch(key)
    if found is None or found["id"] != str(event_id):
        return False
    original = datetime.strptime(found["stamp"], constants.OCCURRENCE_KEY_STAMP).replace(tzinfo=UTC)
    rule = rrule.parse(plan.rrule, all_day=plan.all_day, timezone=plan.timezone)
    return is_occurrence(
        original,
        rule=rule,
        span=plan.span,
        all_day=plan.all_day,
        timezone=plan.timezone,
        recurrence_until=plan.recurrence_until,
    )


async def seat_keys_orphaned_by(db: Any, event: Event, plan: Schedule) -> list[str]:
    """The keys holding seats that are not occurrences of ``plan`` (empty when nobody holds one)."""
    return [
        key
        for key in await seat_keys(db, event.id)
        if not _still_an_occurrence(key, event.id, plan)
    ]


async def guard_seats(
    db: Any, event: Event, *, new: RegistrationIn | None, orphaned_keys: Collection[str]
) -> None:
    """Refuse a change that would strand or re-point seats. ``new`` is the registration settings
    about to be applied (``None``: not being changed); ``orphaned_keys`` the keys a series change
    would orphan (:func:`seat_keys_orphaned_by`)."""
    if orphaned_keys:
        raise RegistrationsOrphaned
    if new is None:
        return
    same_form = (new.mode, new.provider, new.target) == (
        event.registration_mode,
        event.registration_provider,
        event.registration_target,
    )
    if not same_form and await has_seats(db, event.id):
        raise RegistrationHasSeats
