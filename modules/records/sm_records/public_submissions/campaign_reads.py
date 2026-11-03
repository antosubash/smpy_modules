"""The queries behind the newsletter contract's subscriber reads.

No FastAPI, no response shapes: this module returns ORM rows and the contract
(:mod:`sm_records.contracts.newsletter`) turns them into DTOs.

Every query names the tenant as a ``WHERE`` of its own. The framework filters
by the bound tenant only while one is bound, and a single-tenant host binds
none, so an unpinned read would list every tenant's subscribers.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.contracts.public_submissions import KIND_SUBSCRIPTION
from sm_records.core.settings import RecordsSettings
from sm_records.models import Record, RecordType, tables_for
from sm_records.records._grammar import FilterTermError, parse_term
from sm_records.records.index._predicates import QueryError
from sm_records.records.index.query import Filter, FilterOp, build_query, count_query

__all__ = [
    "WALKABLE",
    "SubscriberFilterError",
    "count",
    "list_type",
    "lookup",
    "moment",
    "page",
    "stored_tags",
]

WALKABLE: Final = ("confirmed", "unsubscribed")
"""The statuses a walk may ask for: who is mailed, and who left (the
newsletter's reconcile). ``pending`` is nobody's audience."""


class SubscriberFilterError(ValueError):
    """A filter the list cannot answer, or a type that is not a list.

    ``reason`` is records' own (``unknown``, ``not_indexed``, ``reindexing``),
    ``malformed`` for a term that does not parse, or ``not_a_list``.
    """

    def __init__(self, reason: str, message: str | None = None) -> None:
        super().__init__(message or reason)
        self.reason = reason


async def list_type(db: AsyncSession, tenant_id: str, type_key: str) -> RecordType | None:
    """The tenant's newsletter list ``type_key``, or ``None`` when that tenant
    has no such type (a caller naming another tenant learns nothing about it).

    A type that is not a subscription list raises ``not_a_list``."""
    stmt = select(RecordType).where(RecordType.tenant_id == tenant_id, RecordType.key == type_key)
    rtype = (await db.execute(stmt)).scalars().first()
    if rtype is None:
        return None
    if (rtype.public_submissions or {}).get("kind") != KIND_SUBSCRIPTION:
        raise SubscriberFilterError("not_a_list", f"{type_key!r} is not a newsletter list")
    return rtype


def moment(value: Any) -> datetime | None:
    """A stored ``sm_*_at`` value as an aware datetime, ``None`` if it is none.

    The payload is JSON, so it is normally an ISO string; a naive one is UTC,
    which is what records writes (``utcnow``)."""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def stored_tags(value: Any) -> list[str]:
    """The string tags of a stored ``tags`` value; ``[]`` when it is not a list."""
    return [t for t in value if isinstance(t, str)] if isinstance(value, list) else []


def _filters(raw: Sequence[str], status: str) -> list[Filter]:
    settings = RecordsSettings()
    if isinstance(raw, str) or len(raw) > settings.max_filter_terms:
        raise SubscriberFilterError("malformed", "too many filter terms")
    try:
        parsed = [parse_term(term, settings) for term in raw]
    except FilterTermError as exc:
        raise SubscriberFilterError("malformed", str(exc)) from exc
    return [Filter("sm_status", FilterOp.EQ, status), *parsed]


def _live(stmt, record, tenant_id: str):
    return stmt.where(record.tenant_id == tenant_id, record.is_deleted.is_(False))


def _query(rtype: RecordType, tenant_id: str, filters: Sequence[str], status: str, builder):
    """``builder``'s statement (``build_query``/``count_query``) for the terms,
    pinned to the tenant's untrashed rows; with the type's record table."""
    terms = _filters(filters, status)
    record = tables_for(rtype).record
    try:
        stmt = builder(rtype, list(rtype.fields or []), terms)
    except QueryError as exc:
        raise SubscriberFilterError(exc.reason, str(exc)) from exc
    return _live(stmt, record, tenant_id), record


async def page(
    db: AsyncSession,
    rtype: RecordType,
    tenant_id: str,
    *,
    filters: Sequence[str],
    after: int,
    limit: int,
    status: str,
) -> tuple[list[Record], int | None]:
    """Untrashed records in ``status`` matching every term, ``Record.id`` order.

    One row more than ``limit`` is read to know whether anything follows, so
    ``next_after`` is ``None`` exactly when the walk is over."""
    stmt, record = _query(rtype, tenant_id, filters, status, build_query)
    stmt = stmt.where(record.id > after).limit(limit + 1)
    rows = list((await db.execute(stmt)).scalars().all())
    if len(rows) <= limit:
        return rows, None
    rows = rows[:limit]
    return rows, rows[-1].id


async def count(
    db: AsyncSession, rtype: RecordType, tenant_id: str, filters: Sequence[str], status: str
) -> int:
    stmt, _ = _query(rtype, tenant_id, filters, status, count_query)
    return int((await db.execute(stmt)).scalar_one())


async def lookup(
    db: AsyncSession, rtype: RecordType, tenant_id: str, uuids: Sequence[str]
) -> list[Record]:
    """Records by uuid, any status, the trash included."""
    record = tables_for(rtype).record
    stmt = select(record).where(
        record.tenant_id == tenant_id, record.type_id == rtype.id, record.uuid.in_(list(uuids))
    )
    return list((await db.execute(stmt.execution_options(include_deleted=True))).scalars().all())
