"""``describe``: what one occurrence of an event offers for registration.

**Who may see it.** The answer is for a *public* event with registration open to the module that
owns the registrants: it carries counts at most (never a name, an address or a holder id), and for
everything that is not public it is **one answer, ``unavailable``, with no event**. The event is
read through :func:`~sm_events.core.access.public.public_events` and nothing else, so a draft, a
scheduled or in-review event, a trashed one, an internal or private calendar, a trashed calendar
and another tenant's are the same absence the public page gives (PR 4 Ruling 1: no predicate of
its own). A mode other than ``builtin``, another provider or target than the caller's, and a key
that is not an occurrence (a skipped date included) are that absence too.

**States**, in the order they are decided: ``cancelled`` (the event, or this occurrence),
``closed`` (the window has passed, or the occurrence has started), ``not_open_yet``, ``full`` and
``open``. ``seats_left`` is shown only when the event says so.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select

from sm_events.content.public_read import pick_text
from sm_events.content.texts import texts_of
from sm_events.core import constants, locales
from sm_events.core.access.public import public_events
from sm_events.core.clock import utcnow
from sm_events.core.tenancy import tenant_scope
from sm_events.core.web_urls import is_web_url
from sm_events.models import Event, EventText, RegistrationCount
from sm_events.registration import args
from sm_events.registration.occurrence import ResolvedOccurrence, load_resolved
from sm_events.reminders import formatting
from sm_events.web.endpoints.public import _urls

__all__ = [
    "Availability",
    "Found",
    "RegistrationEvent",
    "choose_text",
    "describe",
    "lookup",
    "make_event",
    "state_of",
]

_ONLINE_MODES = ("online", "hybrid")
_UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class RegistrationEvent:
    """The public facts a confirmation or a "my registrations" row needs about an occurrence."""

    event_id: uuid.UUID
    occurrence_key: str
    title: str
    starts_at: datetime
    ends_at: datetime
    all_day: bool
    timezone: str
    when_text: str
    """The occurrence's date and time in the **event's** zone, in the caller's language."""
    venue_name: str | None
    address: str | None
    online_url: str | None
    page_path: str
    """Site-relative; the caller adds the origin it is allowed to use."""
    ics_path: str
    lang: str
    """The language of ``title`` and of the two paths."""


@dataclass(frozen=True)
class Availability:
    state: str
    seats_left: int | None
    opens_at: datetime | None
    closes_at: datetime | None
    event: RegistrationEvent | None
    capacity: int | None = None
    """The event's seat limit (``None``: unlimited, or unavailable). For the provider's own
    bounds (how many unconfirmed holds one occurrence may carry); not for a public page."""


@dataclass(frozen=True)
class Found:
    event: Event
    occurrence: ResolvedOccurrence


def _absent() -> Availability:
    return Availability(_UNAVAILABLE, None, None, None, None)


async def lookup(
    db: Any,
    event_id: uuid.UUID,
    key: str,
    provider: str,
    target: str,
    *,
    lock: bool = False,
) -> Found | None:
    """The public event and the occurrence ``key`` names, when this provider and target own its
    registration; ``None`` otherwise (the one absent answer). ``lock`` takes ``FOR SHARE`` on the
    event row (Postgres), so a change that unpublishes or cancels it serialises with the caller."""
    stmt = public_events().where(Event.id == event_id)
    if lock:
        stmt = stmt.with_for_update(read=True, of=Event)
    event = (await db.execute(stmt)).scalars().first()
    if (
        event is None
        or event.registration_mode != constants.REGISTRATION_MODE_BUILTIN
        or event.registration_provider != provider
        or event.registration_target != target
    ):
        return None
    occurrence = await load_resolved(db, event, key)
    return None if occurrence is None else Found(event, occurrence)


def state_of(found: Found, taken: int, now: datetime) -> str:
    event, occurrence = found.event, found.occurrence
    if event.cancelled or occurrence.cancelled:
        return "cancelled"
    if (event.registration_closes_at and now >= event.registration_closes_at) or (
        now >= occurrence.start
    ):
        return "closed"
    if event.registration_opens_at and now < event.registration_opens_at:
        return "not_open_yet"
    if event.registration_capacity is not None and taken >= event.registration_capacity:
        return "full"
    return "open"


async def _taken(db: Any, event_id: uuid.UUID, key: str) -> int:
    stmt = select(RegistrationCount.taken).where(
        RegistrationCount.event_id == event_id, RegistrationCount.occurrence_key == key
    )
    return (await db.execute(stmt)).scalar_one_or_none() or 0


def _online(event: Event) -> str | None:
    if event.attendance_mode in _ONLINE_MODES and event.online_url and is_web_url(event.online_url):
        return event.online_url
    return None


def make_event(
    event: Event, occurrence: ResolvedOccurrence, text: EventText, locale: str
) -> RegistrationEvent:
    """The public facts about one occurrence, in the text chosen for the caller's language."""
    return RegistrationEvent(
        event_id=event.id,
        occurrence_key=occurrence.key,
        title=text.title,
        starts_at=occurrence.start,
        ends_at=occurrence.end,
        all_day=event.all_day,
        timezone=event.timezone,
        when_text=formatting.format_when(
            start=occurrence.start,
            end=occurrence.end,
            all_day=event.all_day,
            timezone=event.timezone,
            locale=locale,
        ),
        venue_name=event.venue_name,
        address=event.address,
        online_url=_online(event),
        page_path=_urls.event_path(text.slug, text.locale, occurrence.date_param),
        ics_path=_urls.event_ics_path(text.slug, text.locale),
        lang=text.locale,
    )


def choose_text(texts: Mapping[str, EventText], locale: str) -> EventText:
    """The text to show a reader in ``locale``: theirs, else the site's default language's, among
    the languages the site serves (a language it does not serve has no page to link to)."""
    served = {name: text for name, text in texts.items() if name in locales.supported()}
    return pick_text(served or texts, locale, locales.default())


async def registration_event(
    db: Any, event: Event, occurrence: ResolvedOccurrence, locale: str
) -> RegistrationEvent:
    texts = (await texts_of(db, [event.id]))[event.id]
    return make_event(event, occurrence, choose_text(texts, locale), locale)


async def describe(
    db: Any,
    *,
    tenant_id: str,
    event_id: uuid.UUID | str,
    occurrence_key: str,
    provider: str,
    target: str,
    locale: str,
    now: datetime | None = None,
) -> Availability:
    """What one occurrence offers. Pins ``tenant_id`` (naming another tenant than the one bound
    raises ``TenantIsolationError``), reads, never writes."""
    eid = args.event_id(event_id)
    key = args.occurrence_key(occurrence_key)
    who = args.text(provider, "provider", maximum=constants.REGISTRATION_PROVIDER_MAX)
    what = args.text(target, "target", maximum=constants.REGISTRATION_TARGET_MAX)
    lang = args.text(locale, "locale", maximum=constants.LOCALE_MAX)
    with tenant_scope(tenant_id):
        found = await lookup(db, eid, key, who, what)
        if found is None:
            return _absent()
        event = found.event
        taken = await _taken(db, eid, key)
        state = state_of(found, taken, now or utcnow())
        left = None
        if event.registration_show_seats and event.registration_capacity is not None:
            left = max(event.registration_capacity - taken, 0)
        return Availability(
            state=state,
            seats_left=left,
            opens_at=event.registration_opens_at,
            closes_at=event.registration_closes_at,
            event=await registration_event(db, event, found.occurrence, lang),
            capacity=event.registration_capacity,
        )
