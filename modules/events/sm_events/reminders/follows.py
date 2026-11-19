"""Following an event for reminders: the request-side service.

A follow is **personal data of one user**. Every statement here carries the bound tenant and the
caller's own ``user_id``; there is no function that reads or changes someone else's follow, and
no manager view (managers get counts from :mod:`sm_events.reminders.stats`, never identities).

**Who may follow** (the module's one access function, :func:`visible_events`): a signed-in
caller with ``events.view`` and an event they can currently see that is published. Anything else
is the same :class:`NotFound` a missing event gets, so an invisible event cannot be probed; a
writer who sees an unpublished event gets :class:`NotPublished` (nothing leaks: they can see it).
Losing access later keeps the follow (a re-grant resumes it) but never produces a reminder; that
is decided when a reminder falls due, from current state, so nothing here stores a snapshot of
rights or of the event's content.

A follow request names the **whole set** of leads for one event and replaces the caller's: the
empty set unfollows. At most :data:`~sm_events.core.constants.reminders_limits.FOLLOWS_PER_USER`
distinct events per user; a user's writes are serialised on Postgres by an advisory lock, so
two requests cannot both slip past the limit. Nothing here commits: the caller's request
session does.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Any

from simple_module_core.resources import ResourcePrincipal
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from sm_events.calendar.slugs import is_slug_conflict
from sm_events.core import constants
from sm_events.core.access.events import visible_events
from sm_events.core.constants.reminders_limits import FOLLOWS_PER_USER
from sm_events.core.errors import NotFound
from sm_events.core.errors_reminders import FollowLimit, NotPublished
from sm_events.core.settings import EventsSettings
from sm_events.core.tenancy import bound_tenant
from sm_events.core.user_ids import canonical_user_id
from sm_events.models import Calendar, Event, EventFollow
from sm_events.models.enums import EventStatus
from sm_events.models.reminders import FOLLOW_CONSTRAINT
from sm_events.reminders import candidates, due
from sm_events.reminders import leads as lead_rules

__all__ = [
    "FollowState",
    "delete_follow",
    "delete_follow_by_id",
    "get_follow",
    "request_locale",
    "set_follow",
]

_F = EventFollow.__table__


@dataclass(frozen=True)
class FollowState:
    leads: tuple[int, ...]
    defaults: tuple[int, ...]
    next_due: dict[int, datetime | None]
    """Per chosen lead, when its next reminder falls due (``None``: too late for the next
    occurrence, or none is coming)."""


def request_locale(request: Any, default: str) -> str:
    """The console language the request is in (what the follow records), else ``default``.
    Shape-checked: it is stored and later used to pick a message catalogue."""
    raw = getattr(getattr(request, "state", None), "locale", None)
    ok = isinstance(raw, str) and 2 <= len(raw) <= constants.LOCALE_MAX
    return raw if ok and raw.replace("-", "").isalnum() and raw.isascii() else default


def _user(who: ResourcePrincipal) -> str:
    """The caller's id, or ``NotFound``: an anonymous caller and one without ``events.view`` can
    follow nothing."""
    if who.user_id is None or not who.has(constants.PERM_VIEW):
        raise NotFound
    return canonical_user_id(who.user_id)


async def _event(
    db: Any, who: ResourcePrincipal, event_id: uuid.UUID, *, published_only: bool
) -> Event:
    stmt = visible_events(who, include_unpublished=not published_only).where(
        Event.id == event_id  # type: ignore[arg-type]
    )
    found = (await db.execute(stmt)).scalar_one_or_none()
    if found is None:
        raise NotFound
    return found


async def _calendar(db: Any, event: Event) -> Calendar:
    return (
        await db.execute(select(Calendar).where(Calendar.id == event.calendar_id))  # type: ignore[arg-type]
    ).scalar_one()


def _mine() -> tuple[Any, ...]:
    return (_F.c.tenant_id == bound_tenant(),)


async def _own_leads(db: Any, user_id: str) -> dict[uuid.UUID, set[int]]:
    """The caller's follows as ``{event: leads}`` (columns only, so nothing sits stale in the
    session's identity map)."""
    rows = await db.execute(
        select(_F.c.event_id, _F.c.lead_minutes).where(*_mine(), _F.c.user_id == user_id)
    )
    found: dict[uuid.UUID, set[int]] = {}
    for event_id, lead in rows:
        found.setdefault(event_id, set()).add(lead)
    return found


async def _lock_user(db: Any, user_id: str) -> None:
    """Serialise one user's follow writes (Postgres; SQLite has one writer). The lock is taken
    before the count is read, so a statement that follows it sees what the winner committed."""
    if db.get_bind().dialect.name != "postgresql":
        return
    digest = sha256(f"events.follows:{bound_tenant()}:{user_id}".encode()).digest()
    key = int.from_bytes(digest[:8], "big", signed=True)
    await db.execute(select(func.pg_advisory_xact_lock(key)))


async def _insert_missing(
    db: Any,
    user_id: str,
    event_id: uuid.UUID,
    wanted: list[int],
    *,
    locale: str,
    now: datetime,
) -> None:
    """Insert each lead, in a savepoint of its own. The follow's own unique key violated means a
    concurrent request wrote the same lead first, which is the state asked for; any other
    integrity error is real and propagates."""
    for lead in wanted:
        row = EventFollow(
            event_id=event_id, user_id=user_id, lead_minutes=lead, locale=locale, created_at=now
        )
        try:
            async with db.begin_nested():
                db.add(row)
                await db.flush()
        except IntegrityError as exc:
            if not is_slug_conflict(exc, FOLLOW_CONSTRAINT):
                raise


async def _state(
    db: Any, event: Event, chosen: tuple[int, ...], defaults: tuple[int, ...], *, now: datetime
) -> FollowState:
    """The state, with when each chosen lead is next due (``None``: too late for the next
    occurrence, or none is coming), from the occurrences read."""
    if not chosen:
        return FollowState(leads=(), defaults=defaults, next_due={})
    starts = (await candidates.next_starts(db, [event], now=now))[event.id]
    return FollowState(
        leads=chosen,
        defaults=defaults,
        next_due={lead: due.next_due(starts, lead, now) for lead in chosen},
    )


async def get_follow(
    db: Any, who: ResourcePrincipal, event_id: uuid.UUID, *, settings: EventsSettings, now: datetime
) -> FollowState:
    """The caller's leads on a published event they can see (``NotFound`` otherwise), what
    "Remind me" would preselect on its calendar and when each lead is next due."""
    user_id = _user(who)
    event = await _event(db, who, event_id, published_only=True)
    chosen = tuple(sorted((await _own_leads(db, user_id)).get(event.id, ())))
    defaults = lead_rules.effective_defaults(settings, await _calendar(db, event))
    return await _state(db, event, chosen, defaults, now=now)


async def set_follow(
    db: Any,
    who: ResourcePrincipal,
    event_id: uuid.UUID,
    leads: Any,
    *,
    locale: str,
    settings: EventsSettings,
    now: datetime,
) -> FollowState:
    """Make ``leads`` the caller's whole set on the event (empty: unfollow).

    ``NotFound`` for an event they cannot see, ``NotPublished`` for one they see but is not
    published, ``InvalidLead`` for a lead outside the set, ``FollowLimit`` for one event too
    many. Nothing is written unless everything is valid."""
    user_id = _user(who)
    chosen = lead_rules.validate_leads(leads)
    event = await _event(db, who, event_id, published_only=False)
    if event.status != EventStatus.PUBLISHED.value:
        raise NotPublished
    defaults = lead_rules.effective_defaults(settings, await _calendar(db, event))
    if not chosen:
        await _delete_event_rows(db, user_id, event.id)
        return await _state(db, event, (), defaults, now=now)
    await _lock_user(db, user_id)
    own = await _own_leads(db, user_id)
    if event.id not in own and len(own) >= FOLLOWS_PER_USER:
        raise FollowLimit
    have = own.get(event.id, set())
    stale = have - set(chosen)
    if stale:
        await db.execute(
            delete(_F).where(
                *_mine(),
                _F.c.user_id == user_id,
                _F.c.event_id == event.id,
                _F.c.lead_minutes.in_(stale),
            )
        )
    kept = have & set(chosen)
    if kept:
        await db.execute(
            update(_F)
            .where(
                *_mine(),
                _F.c.user_id == user_id,
                _F.c.event_id == event.id,
                _F.c.lead_minutes.in_(kept),
                _F.c.locale != locale,
            )
            .values(locale=locale)
        )
    await _insert_missing(
        db, user_id, event.id, [lead for lead in chosen if lead not in have], locale=locale, now=now
    )
    return await _state(db, event, chosen, defaults, now=now)


async def _delete_event_rows(db: Any, user_id: str, event_id: uuid.UUID) -> int:
    done = await db.execute(
        delete(_F).where(*_mine(), _F.c.user_id == user_id, _F.c.event_id == event_id)
    )
    return int(done.rowcount or 0)


async def delete_follow(db: Any, who: ResourcePrincipal, event_id: uuid.UUID) -> None:
    """Remove the caller's follow on the event. Idempotent. Works after access was lost (the
    follow is theirs to remove); with no follow of theirs to remove, an event they cannot see is
    the usual ``NotFound``, so the route is no probe."""
    if who.user_id is None:
        raise NotFound
    if await _delete_event_rows(db, canonical_user_id(who.user_id), event_id):
        return
    if not who.has(constants.PERM_VIEW):
        raise NotFound
    await _event(db, who, event_id, published_only=False)


async def delete_follow_by_id(db: Any, who: ResourcePrincipal, follow_id: uuid.UUID) -> None:
    """Remove the caller's follow(s) on the event that ``follow_id`` belongs to: the handle the
    "My reminders" list gives every row, including the opaque row for an event the caller can no
    longer see. Someone else's follow id and a missing one are the same ``NotFound``."""
    if who.user_id is None:
        raise NotFound
    user_id = canonical_user_id(who.user_id)
    event_id = (
        await db.execute(
            select(_F.c.event_id).where(*_mine(), _F.c.user_id == user_id, _F.c.id == follow_id)
        )
    ).scalar_one_or_none()
    if event_id is None:
        raise NotFound
    await _delete_event_rows(db, user_id, event_id)
