"""Lifting a suppression, with an audit row (PR 6, Task 7: G12, G13, C2, C3).

:func:`lift` runs in the request's one write transaction and checks, in order:
the note and the version, the row (tenant-pinned; a row of an unreadable list
is as absent as a missing one), the version against the row (``suppression_changed``),
the typed address against the row's hash (``lift_email_mismatch``; before the
reason, so the endpoint is no oracle for the kind of a row whose address the
caller does not know), the reason (``lift_not_allowed`` for a complaint) and,
for an opt-out, records' confirmation under its row lock (``opt_out_stands``).
Then a conditional delete on the version read, and the audit row.

**Lock order: the subscriber's records row, then the suppression row, then the
lift insert** - the order of the unsubscribe page's transaction (records'
``unsubscribe``, then ``suppress``), so the two cannot deadlock. The records
row is locked only for an opt-out (``lock_confirmation``), and held until this
transaction ends, so a records unsubscribe cannot land between the check and
the delete. These paths never touch campaign, send or click rows.
"""

from __future__ import annotations

import unicodedata
from datetime import datetime

from simple_module_db import mark_written
from simple_module_db.listeners import current_user_id
from sm_records.contracts.newsletter import (
    SubscriberFilterError,
    SubscriberHit,
    iter_subscribers,
)
from sm_records.contracts.newsletter_admin import lock_confirmation
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.campaigns.access import MAX_BIG_ID, Roles
from sm_newsletter.core.constants import LIFTABLE, REASON_UNSUBSCRIBED
from sm_newsletter.core.errors import NotFound
from sm_newsletter.core.errors_audience import (
    InvalidQuery,
    LiftEmailMismatch,
    LiftNotAllowed,
    OptOutStands,
    SuppressionChanged,
)
from sm_newsletter.core.suppression import lookup_hashes, records_form
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.core.upsert import affected_rows
from sm_newsletter.models import Suppression, SuppressionLift
from sm_newsletter.subscribers.suppressions import (
    SuppressionRow,
    as_row,
    lift_block,
    visible,
    visible_lists,
)

__all__ = ["NOTE_MAX", "lift", "list_lifts", "subscriber_on_list"]

NOTE_MAX = 500
_T = Suppression.__table__
_L = SuppressionLift


def _note(note: object) -> str:
    if not isinstance(note, str):
        raise InvalidQuery("note: required")
    text = note.strip()
    if not 1 <= len(text) <= NOTE_MAX:
        raise InvalidQuery(f"note: 1 to {NOTE_MAX} characters")
    if any(c != "\n" and unicodedata.category(c) == "Cc" for c in text):
        raise InvalidQuery("note: control characters")
    return text


def _version(version: object) -> datetime:
    try:
        parsed = datetime.fromisoformat(version) if isinstance(version, str) else None
    except ValueError:
        parsed = None
    if parsed is None or parsed.utcoffset() is None:
        raise InvalidQuery("version: not a row version")
    return parsed


async def subscriber_on_list(
    session: AsyncSession, *, tenant_id: str, list_type_key: str, email: str
) -> SubscriberHit | None:
    """The address's confirmed subscriber on the list, for display only - never
    used to decide a lift."""
    try:
        term = f"sm_email:eq:{records_form(email)}"  # records' own normalisation
        hits, _ = await iter_subscribers(
            session, tenant_id=tenant_id, type_key=list_type_key, filters=[term], limit=1
        )
    except (SubscriberFilterError, ValueError):
        return None
    return hits[0] if hits else None


async def _visible_row(
    session: AsyncSession, *, tenant_id: str, roles: Roles, suppression_id: int
) -> SuppressionRow:
    if not 0 < suppression_id <= MAX_BIG_ID:
        raise NotFound()
    stmt = select(_T).where(_T.c.id == suppression_id, _T.c.tenant_id == tenant_id)
    raw = (await session.execute(stmt)).first()
    if raw is None:
        raise NotFound()
    row = as_row(raw)
    if row.list_type_key and row.list_type_key not in await visible_lists(
        session, tenant_id=tenant_id, roles=roles
    ):
        raise NotFound()
    return row


async def lift(
    session: AsyncSession,
    *,
    tenant_id: str,
    roles: Roles,
    suppression_id: int,
    version: str,
    email: str,
    note: str,
    now: datetime,
) -> SuppressionLift:
    """Delete one suppression and record who lifted it and why; the audit row.
    Does not commit."""
    text, seen = _note(note), _version(version)
    with tenant_scope(tenant_id):
        row = await _visible_row(
            session, tenant_id=tenant_id, roles=roles, suppression_id=suppression_id
        )
        if row.created_at != seen:
            raise SuppressionChanged()
        try:
            same = row.email_hash in lookup_hashes(email)
        except ValueError:
            same = False
        if not same:
            raise LiftEmailMismatch()
        if row.reason not in LIFTABLE:
            raise LiftNotAllowed()
        if row.reason == REASON_UNSUBSCRIBED:
            proof = await lock_confirmation(
                session, tenant_id=tenant_id, type_key=row.list_type_key, email=email
            )
            if lift_block(row, confirmed_at=proof.confirmed_at if proof else None):
                raise OptOutStands()
        gone = await session.execute(
            delete(_T)
            .where(_T.c.id == row.id, _T.c.tenant_id == tenant_id, _T.c.created_at == seen)
            .execution_options(synchronize_session=False)
        )
        if affected_rows(gone, session.get_bind().dialect.name) == 0:
            raise SuppressionChanged()
        audit = SuppressionLift(
            tenant_id=tenant_id,
            email_hash=row.email_hash,
            reason=row.reason,
            list_type_key=row.list_type_key,
            source=row.source,
            suppressed_at=row.created_at,
            lifted_at=now,
            lifted_by=current_user_id.get(),
            note=text,
        )
        session.add(audit)
        await session.flush()
        mark_written(session)
    return audit


async def list_lifts(
    session: AsyncSession, *, tenant_id: str, roles: Roles, offset: int, limit: int
) -> tuple[list[SuppressionLift], int]:
    """The tenant's lifts the caller may see, newest first, and their total."""
    with tenant_scope(tenant_id):
        keys = await visible_lists(session, tenant_id=tenant_id, roles=roles)
        where = [
            _L.tenant_id == tenant_id,
            visible(keys, column=_L.__table__.c.list_type_key),
        ]
        stmt = (
            select(_L)
            .where(*where)
            .order_by(_L.lifted_at.desc(), _L.id.desc())
            .offset(offset)
            .limit(limit)
        )
        items = list((await session.execute(stmt)).scalars())
        total = (
            await session.execute(select(func.count()).select_from(_L).where(*where))
        ).scalar_one()
    return items, int(total)
