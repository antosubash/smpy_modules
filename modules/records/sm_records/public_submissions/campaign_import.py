"""Newsletter's Mailchimp import, records' half (newsletter PR 7, rulings R3-R5, D1, D5).

The contract, :mod:`sm_records.contracts.newsletter_import`, checks the
arguments and binds the tenant; this module runs a batch. Nothing here commits.

The caller takes :func:`lock_batch` first (every address's opt-out lock, then
the list's type lock), before its opt-out reads. A batch takes the type lock
again (the lock every record write of the list takes, PR 6's ``row_lock``
order: type, then row; re-taking it is free), so the addresses it
looks up in one indexed query (trash included) stay as read for the rest of
the caller's transaction, then decides each row with
:func:`.campaign_import_rows.apply`. The whole batch runs inside
``events.muted``: an import publishes nothing (R5), so it cannot announce a
``pending -> confirmed`` change even by mistake, and it never makes one.

:func:`opted_out` answers D1: the addresses ``unsubscribed`` on any of the
tenant's lists, trash included.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import Field, SQLModel

from sm_records.contracts.public_submissions import KIND_SUBSCRIPTION
from sm_records.core import events
from sm_records.core.settings import RecordsSettings
from sm_records.models import Record, RecordType, tables_for
from sm_records.public_submissions import campaign_import_rows, campaign_reads
from sm_records.public_submissions.address_lock import lock_addresses
from sm_records.public_submissions.campaign_reads import SubscriberFilterError
from sm_records.public_submissions.definition import EMAIL_KEY
from sm_records.public_submissions.subscribe import UNSUBSCRIBED, normalise
from sm_records.records.index._predicates import QueryError
from sm_records.records.index.query import Filter, FilterOp, build_query
from sm_records.records.services._lock import lock_type

__all__ = [
    "CONSENT_TEMPLATE",
    "MAX_IMPORT_BATCH",
    "ImportOutcome",
    "ImportResult",
    "ImportRow",
    "ImportStatus",
    "checked_emails",
    "checked_rows",
    "lock_batch",
    "opted_out",
    "run",
]

ImportStatus = Literal["confirmed", "unsubscribed"]
ImportOutcome = Literal[
    "created",
    "created_unsubscribed",
    "updated",
    "unchanged",
    "unsubscribed",
    "kept_confirmed",
    "kept_pending",
    "kept_unsubscribed",
    "trashed",
    "invalid",
]
MAX_IMPORT_BATCH = 500
CONSENT_TEMPLATE = campaign_import_rows.CONSENT_TEMPLATE
_STATUSES = ("confirmed", "unsubscribed")
_CHUNK = 200
"""Addresses per ``IN`` lookup: records' own cap on one ``in`` filter
(``max_in_values``), which keeps SQLite's expression tree small."""
_MAX_SOURCE = 100


class ImportRow(SQLModel):
    email: str
    status: ImportStatus
    fields: dict[str, str] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    confirmed_at: datetime | None = None
    consent_at: datetime | None = None
    unsubscribed_at: datetime | None = None


class ImportResult(SQLModel):
    email: str
    outcome: ImportOutcome
    dropped: list[str] = Field(default_factory=list)


def _aware(value: object, name: str) -> None:
    if value is None:
        return
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{name} must be an aware datetime, got {value!r}")


def checked_rows(rows: object, now: object, source: object) -> list[tuple[ImportRow, str]]:
    """Each row with its normalised address; ``ValueError`` for anything a
    batch refuses as a whole, before any query runs."""
    if isinstance(rows, str | bytes) or not isinstance(rows, Sequence):
        raise ValueError("rows must be a sequence of ImportRow")
    if len(rows) > MAX_IMPORT_BATCH:
        raise ValueError(f"at most {MAX_IMPORT_BATCH} rows per call, got {len(rows)}")
    _aware(now, "now")
    if now is None:
        raise ValueError("now is required")
    if not isinstance(source, str) or not 1 <= len(source) <= _MAX_SOURCE:
        raise ValueError(f"source must be 1-{_MAX_SOURCE} characters")
    out: list[tuple[ImportRow, str]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, ImportRow):
            raise ValueError(f"rows must be ImportRow, got {type(row).__name__}")
        if row.status not in _STATUSES:
            raise ValueError(f"status must be one of {_STATUSES}, got {row.status!r}")
        for name in ("confirmed_at", "consent_at", "unsubscribed_at"):
            _aware(getattr(row, name), name)
        if not isinstance(row.fields, dict) or not isinstance(row.tags, list):
            raise ValueError("fields must be a dict and tags a list")
        email = normalise(row.email)
        if email and email in seen:
            raise ValueError(f"the address in row {len(out)} appears twice in the batch")
        seen.add(email)
        out.append((row, email))
    return out


def checked_emails(emails: object, *, cap: int | None = MAX_IMPORT_BATCH) -> list[str]:
    if isinstance(emails, str | bytes) or not isinstance(emails, Sequence):
        raise ValueError("emails must be a sequence of str")
    if cap is not None and len(emails) > cap:
        raise ValueError(f"at most {MAX_IMPORT_BATCH} addresses per call, got {len(emails)}")
    if not all(isinstance(e, str) for e in emails):
        raise ValueError("emails must be a sequence of str")
    return sorted({normalise(e) for e in emails} - {""})


async def _matching(
    db: AsyncSession, rtype: RecordType, tenant: str, emails: Sequence[str], *extra: Filter
) -> list[Record]:
    """The records of ``rtype`` holding any of ``emails`` (and every ``extra``
    term), trash included, pinned to the tenant; one indexed query a chunk."""
    cls = tables_for(rtype).record
    out: list[Record] = []
    for start in range(0, len(emails), _CHUNK):
        terms = [Filter(EMAIL_KEY, FilterOp.IN, list(emails[start : start + _CHUNK])), *extra]
        try:
            stmt = build_query(rtype, list(rtype.fields or []), terms)
        except QueryError as exc:
            raise SubscriberFilterError(exc.reason, str(exc)) from exc
        stmt = stmt.where(cls.tenant_id == tenant).execution_options(include_deleted=True)
        out.extend((await db.execute(stmt)).scalars().all())
    return out


async def lock_batch(db: AsyncSession, tenant: str, type_key: str, emails: list[str]) -> None:
    """The batch's locks, to the end of the transaction: every address's
    opt-out lock (ascending key order), then the list's type lock. On SQLite the
    type lock's ``UPDATE`` is the database's write lock, taken before the
    caller's opt-out reads. ``LookupError`` for no such list in the tenant."""
    rtype = await campaign_reads.list_type(db, tenant, type_key)
    if rtype is None:
        raise LookupError(f"no newsletter list {type_key!r}")
    await lock_addresses(db, tenant, emails)
    await lock_type(db, rtype)


async def run(
    db: AsyncSession,
    tenant: str,
    type_key: str,
    rows: list[tuple[ImportRow, str]],
    *,
    settings: RecordsSettings,
    now: datetime,
    source: str,
) -> list[ImportResult]:
    """One batch, in input order. ``LookupError`` for no such list in the
    tenant, ``SubscriberFilterError("not_a_list")`` for a type that is not one."""
    rtype = await campaign_reads.list_type(db, tenant, type_key)
    if rtype is None:
        raise LookupError(f"no newsletter list {type_key!r}")
    with events.muted(db):
        await lock_type(db, rtype)
        emails = sorted({email for _, email in rows if email})
        held: dict[str, Record] = {}
        for record in await _matching(db, rtype, tenant, emails):
            held.setdefault(normalise((record.data or {}).get(EMAIL_KEY)), record)
        results: list[ImportResult] = []
        for row, email in rows:
            if not email:
                results.append(ImportResult(email=email, outcome="invalid"))
                continue
            outcome, dropped = await campaign_import_rows.apply(
                db,
                rtype,
                row,
                email,
                held.get(email),
                settings=settings,
                now=now,
                source=source,
            )
            results.append(ImportResult(email=email, outcome=outcome, dropped=dropped))
    return results


async def opted_out(db: AsyncSession, tenant: str, emails: list[str]) -> set[str]:
    """The addresses among ``emails`` (normalised) ``unsubscribed`` on any of
    the tenant's lists, trash included."""
    if not emails:
        return set()
    stmt = select(RecordType).where(RecordType.tenant_id == tenant).order_by(RecordType.id)
    found: set[str] = set()
    for rtype in (await db.execute(stmt)).scalars().all():
        if (rtype.public_submissions or {}).get("kind") != KIND_SUBSCRIPTION:
            continue
        left = Filter("sm_status", FilterOp.EQ, UNSUBSCRIBED)
        for record in await _matching(db, rtype, tenant, emails, left):
            found.add(normalise((record.data or {}).get(EMAIL_KEY)))
    return found & set(emails)
