"""The at-most-once ledger: claim a reminder before sending it, and every mark after.

A reminder goes to a recipient at most once per ``(event, occurrence key, start, recipient,
lead)``: the unique key of ``events_reminder_sent`` (tenant first) is the arbiter, so two
workers, a redelivered beat message or an overlapping late tick can all compute the same
candidate and exactly one of them gets to send. Every statement here carries its own
``tenant_id`` predicate (a Core statement; the tenant tag does not reach it) and runs in a session
of its own that is **committed before this function returns**, so a claim is durable before any
mail is attempted (newsletter's rule: the attempt row is committed before its SMTP call).

State machine (each arrow is one conditional statement; anything else is refused)::

    (no row) --claim--------------------------> claimed     claimed_at = now, the lease starts
    claimed  --claim, lease expired (reclaim)--> claimed     claimed_at = now, a new holder
    claimed  --begin_send (holder only)--------> sending     SMTP is about to be called
    sending  --mark_sent----------------------> sent         final
    sending  --mark_failed--------------------> failed       final, with a stable code

* ``claimed`` is committed and nothing has been handed to the transport: a crash here provably
  sent nothing, so after ``REMINDER_CLAIM_LEASE`` the next tick may reclaim it. Holding the claim
  means holding its exact ``claimed_at``; ``begin_send`` matches it, so a slow first holder whose
  lease passed cannot also send.
* ``sending`` is committed just before the transport is called. A crash after it may or may not
  have sent, and a duplicate is the one outcome that is never allowed, so such a row is **never
  reclaimed and never retried**: that reminder is lost (counted *unfinished* once it is older than
  ``REMINDER_UNFINISHED_AFTER``). ``sent`` and ``failed`` are final too.

The **guard** re-reads the event row (``id``, tenant, ``revision``, published, not cancelled, not
trashed) in the claim's own transaction; a change since the candidate was computed returns
``None`` and the next tick recomputes. On Postgres the read is ``FOR SHARE``, so a cancel or a
reschedule that holds the row makes the claim wait, and it then sees the committed change. What
remains is the window between this commit and the transport call, one send long: an occurrence
cancelled in that instant is still reminded (only the change notices of #401 could correct it).

No ``SKIP LOCKED`` is needed: ``INSERT ... ON CONFLICT DO NOTHING`` and the conditional ``UPDATE``
never wait for each other's rows, they only fail to match.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from simple_module_db import finalize_session
from sqlalchemy import select, update
from sqlalchemy.dialects import postgresql, sqlite

from sm_events.core.tenancy import tenant_scope
from sm_events.models import Event, ReminderSent
from sm_events.models.enums import EventStatus
from sm_events.reminders.candidates import Candidate
from sm_events.reminders.limits import REMINDER_CLAIM_LEASE

__all__ = ["Claim", "begin_send", "claim", "mark_failed", "mark_sent"]

_T = ReminderSent.__table__
_E = Event.__table__
_KEY = ("tenant_id", "event_id", "occurrence_key", "starts_at", "recipient_id", "lead_minutes")

CLAIMED, SENDING, SENT, FAILED = "claimed", "sending", "sent", "failed"


@dataclass(frozen=True)
class Claim:
    """Proof of holding a claim: the row and the exact ``claimed_at`` that is the lease."""

    id: int
    claimed_at: datetime


def _insert(db: Any) -> Any:
    name = db.get_bind().dialect.name
    if name == "postgresql":
        return postgresql.insert
    if name == "sqlite":
        return sqlite.insert
    raise RuntimeError(f"reminders cannot claim on the {name} dialect")


def _identity(c: Candidate, tenant_id: str) -> tuple[Any, ...]:
    return (
        _T.c.tenant_id == tenant_id,
        _T.c.event_id == c.event_id,
        _T.c.occurrence_key == c.occurrence_key,
        _T.c.starts_at == c.start,
        _T.c.recipient_id == c.user_id,
        _T.c.lead_minutes == c.lead,
    )


async def _guard(db: Any, c: Candidate, tenant_id: str) -> bool:
    stmt = select(_E.c.id).where(
        _E.c.id == c.event_id,
        _E.c.tenant_id == tenant_id,
        _E.c.revision == c.revision,
        _E.c.status == EventStatus.PUBLISHED.value,
        _E.c.cancelled.is_(False),
        _E.c.is_deleted.is_(False),
    )
    if db.get_bind().dialect.name == "postgresql":
        stmt = stmt.with_for_update(read=True)
    return (await db.execute(stmt)).first() is not None


async def _claim(db: Any, c: Candidate, tenant_id: str, now: datetime) -> Claim | None:
    if not await _guard(db, c, tenant_id):
        return None
    insert = (
        _insert(db)(_T)
        .values(
            tenant_id=tenant_id,
            event_id=c.event_id,
            occurrence_key=c.occurrence_key,
            starts_at=c.start,
            recipient_id=c.user_id,
            lead_minutes=c.lead,
            state=CLAIMED,
            claimed_at=now,
        )
        .on_conflict_do_nothing(index_elements=list(_KEY))
        .returning(_T.c.id)
    )
    if (row_id := (await db.execute(insert)).scalar_one_or_none()) is not None:
        return Claim(row_id, now)
    # Someone has it. An expired claim that never began sending is the only thing to take over.
    reclaim = (
        update(_T)
        .where(
            *_identity(c, tenant_id),
            _T.c.state == CLAIMED,
            _T.c.claimed_at < now - REMINDER_CLAIM_LEASE,
        )
        .values(claimed_at=now)
        .returning(_T.c.id)
    )
    row_id = (await db.execute(reclaim)).scalar_one_or_none()
    return None if row_id is None else Claim(row_id, now)


async def claim(factory: Any, c: Candidate, *, tenant_id: str, now: datetime) -> Claim | None:
    """Claim ``c`` for sending, or ``None``: someone else holds it, it was already sent (or
    failed, or may have been), or the event changed since the candidate was computed. Committed
    before it returns."""
    with tenant_scope(tenant_id):
        async with factory() as db:
            got = await _claim(db, c, tenant_id, now)
            await finalize_session(db)
    return got


async def _mark(factory: Any, tenant_id: str, statement: Any) -> bool:
    with tenant_scope(tenant_id):
        async with factory() as db:
            changed = (await db.execute(statement)).rowcount
            await finalize_session(db)
    return bool(changed)


async def begin_send(factory: Any, tenant_id: str, held: Claim) -> bool:
    """``claimed`` to ``sending``, only for the current holder (the exact ``claimed_at``).
    ``False``: do not send. Committed before it returns, i.e. before the transport is called."""
    return await _mark(
        factory,
        tenant_id,
        update(_T)
        .where(
            _T.c.tenant_id == tenant_id,
            _T.c.id == held.id,
            _T.c.state == CLAIMED,
            _T.c.claimed_at == held.claimed_at,
        )
        .values(state=SENDING),
    )


async def mark_sent(factory: Any, tenant_id: str, row_id: int, *, now: datetime) -> bool:
    return await _mark(
        factory,
        tenant_id,
        update(_T)
        .where(_T.c.tenant_id == tenant_id, _T.c.id == row_id, _T.c.state == SENDING)
        .values(state=SENT, sent_at=now),
    )


async def mark_failed(factory: Any, tenant_id: str, row_id: int, code: str) -> bool:
    return await _mark(
        factory,
        tenant_id,
        update(_T)
        .where(_T.c.tenant_id == tenant_id, _T.c.id == row_id, _T.c.state == SENDING)
        .values(state=FAILED, code=code),
    )
