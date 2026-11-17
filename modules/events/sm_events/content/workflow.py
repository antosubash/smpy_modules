"""Review and publishing: draft, in review, published, now or on a schedule.

- ``submit``: draft to in_review (write).
- ``withdraw``: in_review to draft (write).
- ``approve``: draft or in_review to published now, or scheduled for a future
  ``publish_at`` with the status unchanged (write and publish).
- ``reject`` (with a note): in_review to draft (write and publish).
- ``unschedule``: a scheduled event keeps its status and loses ``publish_at``
  (write and publish).
- ``unpublish``: published to draft, ``published_at`` kept as history (write and
  publish).

*Scheduled* is not a status: it is a draft or in-review event with ``publish_at``
set. Every action but ``unschedule`` needs the event **not** scheduled (unschedule
first), so a state change never leaves a stale ``publish_at`` behind. Anything else
is 409 ``invalid_transition`` and changes nothing. Every action takes
``expected_revision`` and writes a revision; ``approve`` that publishes announces
:class:`~sm_events.contracts.events.EventPublished` after the commit.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from simple_module_core.resources import ResourcePrincipal

from sm_events.calendar.times import is_nonexistent, localize
from sm_events.content import bus, notices, revisions
from sm_events.content.guard import claim
from sm_events.core import constants
from sm_events.core.access.events import load_event, require
from sm_events.core.errors import InvalidTimes, InvalidTransition
from sm_events.models import Event
from sm_events.models.enums import EventStatus

__all__ = ["TRANSITIONS", "publish_scheduled", "transition"]

_DRAFT, _REVIEW, _LIVE = (s.value for s in EventStatus)
TRANSITIONS: Mapping[str, tuple[frozenset[str], bool]] = {
    "submit": (frozenset({_DRAFT}), False),
    "withdraw": (frozenset({_REVIEW}), False),
    "approve": (frozenset({_DRAFT, _REVIEW}), True),
    "reject": (frozenset({_REVIEW}), True),
    "unschedule": (frozenset({_DRAFT, _REVIEW}), True),
    "unpublish": (frozenset({_LIVE}), True),
}
"""action -> (the statuses it starts from, whether it needs ``events.publish``)."""
_SCHEDULED_ONLY = frozenset({"unschedule"})
_RECORDED = {
    "submit": "submitted",
    "withdraw": "withdrawn",
    "reject": "rejected",
    "unschedule": "unscheduled",
    "unpublish": "unpublished",
}
"""The history action each action records; ``approve`` decides its own."""
_LOCAL = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")


def _publish_at(local: str, timezone: str) -> datetime:
    """A wall-clock instant on the event's clock, as UTC. A time inside a DST gap
    is refused, because a person typed something that does not exist."""
    tz = ZoneInfo(timezone)
    bad = InvalidTimes(constants.INVALID_LOCAL_TIME_DETAIL, code=constants.INVALID_LOCAL_TIME_CODE)
    if not _LOCAL.match(local):
        raise bad
    try:
        naive = datetime.fromisoformat(local)
    except ValueError:
        raise bad from None
    if is_nonexistent(naive, tz):
        raise bad
    return localize(naive, tz)


def _check_state(action: str, event: Event) -> None:
    statuses, _needs = TRANSITIONS[action]
    scheduled = event.publish_at is not None
    if event.status not in statuses or scheduled != (action in _SCHEDULED_ONLY):
        raise InvalidTransition


def _approve(event: Event, local: str | None, now: datetime) -> str:
    """Publish now or schedule; the revision action it is."""
    at = _publish_at(local, event.timezone) if local is not None else None
    if at is not None and at > now:
        event.publish_at = at
        return "scheduled"
    event.status, event.publish_at, event.published_at = _LIVE, None, now
    return "approved"


async def transition(
    db: Any,
    who: ResourcePrincipal,
    event_id: uuid.UUID,
    action: str,
    *,
    expected: int,
    now: datetime,
    publish_at_local: str | None = None,
    note: str | None = None,
) -> Event:
    """Run ``action`` on the event. 404 for an event the caller cannot see, 403
    ``forbidden`` without write on its calendar, 403 ``publish_required`` for an
    action that needs it (or any action on a locked event), then the stale guard
    (409 ``stale``), then 409 ``invalid_transition``."""
    needs = TRANSITIONS[action][1]
    event, rights = await load_event(db, who, event_id)
    require(rights, publish=needs)
    async with db.begin_nested():
        await claim(db, event, expected, actor=who.user_id)
        _check_state(action, event)
        recorded = _RECORDED.get(action, "")
        if action == "submit":
            event.status = _REVIEW
        elif action in ("withdraw", "reject"):
            event.status = _DRAFT
        elif action == "unschedule":
            event.publish_at = None
        elif action == "unpublish":
            event.status, event.publish_at = _DRAFT, None
        else:
            recorded = _approve(event, publish_at_local, now)
        await db.flush()
        await revisions.record(
            db, event, action=recorded, actor=who.user_id, note=note if action == "reject" else None
        )
        if recorded == "approved":
            bus.emit(db, notices.published(event, at=now))
    return event


async def publish_scheduled(db: Any, event: Event, *, now: datetime) -> None:
    """The beat's publish of an event whose ``publish_at`` has come, with no actor.

    The stale guard holds: it is claimed at the revision the caller read, so an
    event somebody edited, unscheduled or published since is ``Stale`` and left
    for the next tick. The revision is written as ``published_scheduled`` with no
    actor. The scheduler's right is not re-checked: the ``scheduled`` revision
    records who scheduled it.

    **No bus event.** A worker has no in-process bus, so unlike ``approve`` this
    announces no :class:`~sm_events.contracts.events.EventPublished`: a
    subscriber only sees publishes made through the web process (open point 2 of
    the design; a cross-process bus is a framework matter)."""
    async with db.begin_nested():
        await claim(db, event, event.revision, actor=None)
        event.status, event.publish_at, event.published_at = _LIVE, None, now
        await db.flush()
        await revisions.record(db, event, action="published_scheduled", actor=None)
