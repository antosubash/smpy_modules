"""Which reminders are due now, found without expanding the world.

One tick asks, per lead time in use (at most four): *which followed events can have an
occurrence starting in this lead's narrow window?* The window is
:func:`~sm_events.reminders.due.start_window`, at most six hours and a minute wide. Two indexed
statements answer it (one-offs from ``ix_events_event_start``, series from the follow index
``ix_events_follow_lead``), then **the module's own occurrences read** expands exactly those
events over exactly that window: no second recurrence engine, so a series' instances, a moved
occurrence (at its *new* time, under its *original* key), a skipped or cancelled occurrence, an
all-day event at local midnight of its zone and a DST gap or fold are whatever the calendar
shows. The read runs as a system viewer that sees every published event; **who may be reminded
is decided afterwards, per user, at send time** (:mod:`~sm_events.reminders.recipients`), never
here.

Cost per tick and tenant: one ``DISTINCT lead`` statement, per lead two prefilter statements and
the read's own few (chunked by :data:`CHUNK` events), and one follower statement capped at
``cap + 1`` rows. Candidates are returned ordered closest-to-stale first, at most ``cap`` of
them; the rest are counted as ``deferred`` and found again on the next tick while still inside
the catch-up.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from simple_module_core.resources import ResourcePrincipal
from sqlalchemy import exists, func, or_, select

from sm_events.calendar.occurrence import Occurrence, OccurrenceFilters
from sm_events.calendar.occurrences import occurrences
from sm_events.core import constants
from sm_events.core.constants.reminders_limits import (
    MAX_LEAD_MINUTES,
    REMINDER_CANDIDATES_MAX,
    REMINDER_CLAIM_LEASE,
    REMINDER_LEADS,
)
from sm_events.core.tenancy import bound_tenant
from sm_events.models import Event, EventFollow, OccurrenceOverride, ReminderSent
from sm_events.models.enums import EventStatus
from sm_events.reminders import due

__all__ = ["CHUNK", "Candidate", "candidates", "next_starts", "stale_candidates"]

logger = logging.getLogger(__name__)

CHUNK = 500
"""Events per occurrences read: well under its occurrence cap, whatever a window holds."""
NEAR = timedelta(days=MAX_LEAD_MINUTES // 1440 + 35)
"""How far ahead :func:`next_starts` looks first; sparse series are found by a second, wider
read."""
FAR = timedelta(days=constants.MAX_RANGE_DAYS)
_SERIES_CHUNK = 25
_LOCALE = "en"

SYSTEM = ResourcePrincipal(
    user_id="system:reminders", permissions=frozenset({constants.PERM_VIEW, constants.PERM_MANAGE})
)
"""Sees every published event; used only to expand occurrences, never to decide who is told."""

_F, _L = EventFollow.__table__, ReminderSent.__table__


@dataclass(frozen=True)
class Candidate:
    event_id: uuid.UUID
    revision: int
    occurrence_key: str
    start: datetime
    end: datetime
    lead: int
    user_id: str
    locale: str
    moved_from: datetime | None = None
    """Where this occurrence was before it was moved, when it was."""

    @property
    def due(self) -> datetime:
        return due.due_at(self.start, self.lead)


def _live_events(*extra: Any) -> Any:
    return (
        Event.tenant_id == bound_tenant(),
        Event.status == EventStatus.PUBLISHED.value,
        Event.cancelled.is_(False),  # type: ignore[attr-defined]
        Event.is_deleted.is_(False),  # type: ignore[attr-defined]
        *extra,
    )


async def _followed_events(db: Any, lead: int, lo: datetime, hi: datetime) -> dict[uuid.UUID, int]:
    """``{event: revision}`` of followed events that may have an occurrence starting in
    ``[lo, hi)``: one-offs starting in it, and series that run through it (or have an
    occurrence moved into it). A prefilter: the occurrences read has the last word."""
    tenant = bound_tenant()
    followed = exists().where(
        _F.c.tenant_id == tenant, _F.c.lead_minutes == lead, _F.c.event_id == Event.id
    )
    one_offs = select(Event.id, Event.revision).where(
        *_live_events(Event.rrule.is_(None), Event.starts_at >= lo, Event.starts_at < hi),  # type: ignore[union-attr]
        followed,
    )
    moved = exists().where(
        OccurrenceOverride.tenant_id == tenant,
        OccurrenceOverride.event_id == Event.id,
        OccurrenceOverride.kind == "moved",
        OccurrenceOverride.starts_at < hi,  # type: ignore[operator]
        OccurrenceOverride.ends_at > lo,  # type: ignore[operator]
    )
    series = (
        select(Event.id, Event.revision)
        .join(_F, (_F.c.event_id == Event.id) & (_F.c.tenant_id == tenant))
        .where(
            *_live_events(
                Event.rrule.is_not(None),  # type: ignore[union-attr]
                Event.starts_at < hi,
                or_(Event.recurrence_until.is_(None), Event.recurrence_until > lo),  # type: ignore[union-attr]
            ),
            _F.c.lead_minutes == lead,
        )
        .distinct()
    )
    found: dict[uuid.UUID, int] = {}
    for stmt in (one_offs, series):
        for event_id, revision in await db.execute(stmt):
            found[event_id] = revision
    moved_series = select(Event.id, Event.revision).where(
        *_live_events(Event.rrule.is_not(None)),
        followed,
        moved,  # type: ignore[union-attr]
    )
    for event_id, revision in await db.execute(moved_series):
        found[event_id] = revision
    return found


async def _expand(
    db: Any, event_ids: Sequence[uuid.UUID], start: datetime, end: datetime
) -> list[Occurrence]:
    """The occurrences read over ``[start, end)`` for these events, chunked; cancelled ones
    (an occurrence's, or the whole event's) are left out."""
    kept: list[Occurrence] = []
    for i in range(0, len(event_ids), CHUNK):
        page = await occurrences(
            db,
            tenant_id=bound_tenant(),
            viewer=SYSTEM,
            start=start,
            end=end,
            filters=OccurrenceFilters(
                event_ids=frozenset(event_ids[i : i + CHUNK]),
                include_unpublished=False,
                sources=frozenset({constants.SOURCE_EVENTS}),
            ),
            default_locale=_LOCALE,
        )
        if page.truncated:
            logger.warning("events: a reminder window was truncated by the occurrences read")
        kept.extend(o for o in page.items if o.status != constants.OCCURRENCE_CANCELLED)
    return kept


async def _followers(
    db: Any, lead: int, event_ids: Iterable[uuid.UUID], limit: int
) -> tuple[list[tuple[uuid.UUID, str, str]], int]:
    """``(event, user, locale)`` of this lead's followers of these events, at most ``limit``
    rows in a stable order, and how many there are in all when that was not every row."""
    ids = list(event_ids)
    where = (_F.c.tenant_id == bound_tenant(), _F.c.lead_minutes == lead, _F.c.event_id.in_(ids))
    rows = [
        tuple(r)
        for r in await db.execute(
            select(_F.c.event_id, _F.c.user_id, _F.c.locale)
            .where(*where)
            .order_by(_F.c.event_id, _F.c.user_id)
            .limit(limit + 1)
        )
    ]
    if len(rows) <= limit:
        return rows, len(rows)  # type: ignore[return-value]
    total = (await db.execute(select(func.count()).select_from(_F).where(*where))).scalar_one()
    return rows[:limit], int(total)  # type: ignore[return-value]


def _moved_from(occ: Occurrence) -> datetime | None:
    original = occ.original_start
    return original if original is not None and original != occ.start else None


async def candidates(
    db: Any, *, now: datetime, cap: int = REMINDER_CANDIDATES_MAX
) -> tuple[list[Candidate], int]:
    """The reminders due at ``now`` in the bound tenant, ordered by due time, event and user,
    at most ``cap`` of them, and how many more were left for the next tick."""
    tenant = bound_tenant()
    in_use = {
        lead
        for (lead,) in await db.execute(
            select(_F.c.lead_minutes).where(_F.c.tenant_id == tenant).distinct()
        )
        if lead in REMINDER_LEADS
    }
    found: list[Candidate] = []
    total = 0
    for lead in sorted(in_use):
        lo, hi = due.start_window(now, lead)
        revisions = await _followed_events(db, lead, lo, hi)
        if not revisions:
            continue
        by_event: dict[uuid.UUID, list[Occurrence]] = defaultdict(list)
        for occ in await _expand(db, list(revisions), lo, hi):
            if occ.event_id in revisions and lo <= occ.start < hi:
                by_event[occ.event_id].append(occ)
        if not by_event:
            continue
        rows, count = await _followers(db, lead, by_event, cap)
        total += count
        handled = await _ledger_keys(
            db, lead, list(by_event), lo, hi, reclaimable_before=now - REMINDER_CLAIM_LEASE
        )  # already sent, failed or in flight: nothing left to do, so no render and no claim
        for event_id, user_id, locale in rows:
            for occ in by_event[event_id]:
                if (event_id, occ.key, occ.start, user_id) in handled:
                    continue
                found.append(
                    Candidate(
                        event_id,
                        revisions[event_id],
                        occ.key,
                        occ.start,
                        occ.end,
                        lead,
                        user_id,
                        locale,
                        _moved_from(occ),
                    )
                )
    found.sort(key=lambda c: (c.due, c.event_id, c.user_id))
    kept = found[:cap]
    return kept, max(total, len(found)) - len(kept)


async def next_starts(
    db: Any, events: Sequence[Event], *, now: datetime
) -> dict[uuid.UUID, list[datetime]]:
    """Each event's coming starts (after ``now``, ascending, cancelled left out), from the
    occurrences read: a one-off needs none, a series is read over the next weeks in chunks and,
    when that finds nothing, over a year, so a yearly series is still found. Bounded: the read
    caps what it returns."""
    out: dict[uuid.UUID, list[datetime]] = {e.id: [] for e in events}
    series = []
    for event in events:
        if event.rrule is not None:
            series.append(event)
        elif event.starts_at > now and not event.cancelled and event.status == "published":
            out[event.id] = [event.starts_at]
    for horizon, wanted in ((NEAR, series), (FAR, None)):
        pending = [e for e in series if not out[e.id]] if wanted is None else wanted
        step = _SERIES_CHUNK if wanted is not None else 1
        for i in range(0, len(pending), step):
            ids = [e.id for e in pending[i : i + step]]
            for occ in await _expand(db, ids, now, now + horizon):
                if occ.event_id in out and occ.start > now:
                    out[occ.event_id].append(occ.start)
    for starts in out.values():
        starts.sort()
    return out


async def _ledger_keys(
    db: Any, lead: int, event_ids: Sequence[uuid.UUID], lo: datetime, hi: datetime,
    *, reclaimable_before: datetime | None = None,
) -> set[tuple[uuid.UUID, str, datetime, str]]:  # fmt: skip
    """``(event, occurrence key, start, recipient)`` of the ledger rows for this lead among these
    events starting in ``[lo, hi)``. With ``reclaimable_before``, a ``claimed`` row older than it
    (its lease expired, so another tick may take it over) is not counted."""
    where = [
        _L.c.tenant_id == bound_tenant(),
        _L.c.lead_minutes == lead,
        _L.c.event_id.in_(list(event_ids)),
        _L.c.starts_at >= lo,
        _L.c.starts_at < hi,
    ]
    if reclaimable_before is not None:
        where.append(or_(_L.c.state != "claimed", _L.c.claimed_at >= reclaimable_before))
    stmt = select(_L.c.event_id, _L.c.occurrence_key, _L.c.starts_at, _L.c.recipient_id)
    return {(r[0], r[1], _utc(r[2]), r[3]) for r in await db.execute(stmt.where(*where))}


async def stale_candidates(
    db: Any, *, now: datetime, lead: int, lo: datetime, hi: datetime, cap: int
) -> list[Candidate]:
    """Occurrences starting in ``[lo, hi)`` (and not yet started) whose ``lead`` reminder was due
    and has gone stale, with the followers who were already following when it was due: what
    :mod:`~sm_events.reminders.too_late` records. At most ``cap``, in a stable order."""
    revisions = await _followed_events(db, lead, lo, hi)
    if not revisions:
        return []
    by_event: dict[uuid.UUID, list[Occurrence]] = defaultdict(list)
    for occ in await _expand(db, list(revisions), lo, hi):
        if occ.event_id in revisions and lo <= occ.start < hi and occ.start > now:
            by_event[occ.event_id].append(occ)
    if not by_event:
        return []
    rows = await db.execute(
        select(_F.c.event_id, _F.c.user_id, _F.c.locale, _F.c.created_at)
        .where(
            _F.c.tenant_id == bound_tenant(),
            _F.c.lead_minutes == lead,
            _F.c.event_id.in_(list(by_event)),
        )
        .order_by(_F.c.event_id, _F.c.user_id)
    )
    have = await _ledger_keys(db, lead, list(by_event), lo, hi)  # recorded: left out before the cap
    found: list[Candidate] = []
    for event_id, user_id, locale, created_at in rows:
        for occ in by_event[event_id]:
            if (event_id, occ.key, occ.start, user_id) in have:
                continue
            made = created_at if created_at.tzinfo else created_at.replace(tzinfo=UTC)
            if made > due.due_at(occ.start, lead):
                continue  # not following yet when it was due: never owed
            found.append(
                Candidate(
                    event_id, revisions[event_id], occ.key, occ.start, occ.end, lead, user_id,
                    locale, _moved_from(occ),
                )
            )  # fmt: skip
            if len(found) >= cap:
                return found
    return found


def _utc(value: datetime) -> datetime:
    """A stored instant as read back (SQLite drops the zone), for comparing with a computed one."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)
