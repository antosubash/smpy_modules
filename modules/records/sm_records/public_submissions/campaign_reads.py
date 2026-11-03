"""The queries behind the newsletter contract's subscriber reads.

No FastAPI, no response shapes: this module returns ORM rows and the contract
(:mod:`sm_records.contracts.newsletter`) turns them into DTOs.

Every query names the tenant as a ``WHERE`` of its own. The framework filters
by the bound tenant only while one is bound, and a single-tenant host binds
none, so an unpinned read would list every tenant's subscribers.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.contracts.public_submissions import KIND_SUBSCRIPTION
from sm_records.core.settings import RecordsSettings
from sm_records.models import Record, RecordType, tables_for
from sm_records.records._grammar import FilterTermError, parse_term
from sm_records.records.index._predicates import QueryError
from sm_records.records.index.query import Filter, FilterOp, build_query, count_query

__all__ = [
    "CONFIRMED_ONLY",
    "SubscriberFilterError",
    "count",
    "list_type",
    "lookup",
    "page",
]

CONFIRMED_ONLY: Final = Filter("sm_status", FilterOp.EQ, "confirmed")


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


def _filters(raw: Sequence[str]) -> list[Filter]:
    settings = RecordsSettings()
    if isinstance(raw, str) or len(raw) > settings.max_filter_terms:
        raise SubscriberFilterError("malformed", "too many filter terms")
    try:
        parsed = [parse_term(term, settings) for term in raw]
    except FilterTermError as exc:
        raise SubscriberFilterError("malformed", str(exc)) from exc
    return [CONFIRMED_ONLY, *parsed]


def _live(stmt, record, tenant_id: str):
    return stmt.where(record.tenant_id == tenant_id, record.is_deleted.is_(False))


async def page(
    db: AsyncSession,
    rtype: RecordType,
    tenant_id: str,
    *,
    filters: Sequence[str],
    after: int,
    limit: int,
) -> tuple[list[Record], int | None]:
    """Confirmed, untrashed records matching every term, ``Record.id`` order.

    One row more than ``limit`` is read to know whether anything follows, so
    ``next_after`` is ``None`` exactly when the walk is over."""
    terms = _filters(filters)
    record = tables_for(rtype).record
    try:
        stmt = build_query(rtype, list(rtype.fields or []), terms)
    except QueryError as exc:
        raise SubscriberFilterError(exc.reason, str(exc)) from exc
    stmt = _live(stmt, record, tenant_id).where(record.id > after).limit(limit + 1)
    rows = list((await db.execute(stmt)).scalars().all())
    if len(rows) <= limit:
        return rows, None
    rows = rows[:limit]
    return rows, rows[-1].id


async def count(db: AsyncSession, rtype: RecordType, tenant_id: str, filters: Sequence[str]) -> int:
    terms = _filters(filters)
    record = tables_for(rtype).record
    try:
        stmt = count_query(rtype, list(rtype.fields or []), terms)
    except QueryError as exc:
        raise SubscriberFilterError(exc.reason, str(exc)) from exc
    return int((await db.execute(_live(stmt, record, tenant_id))).scalar_one())


async def lookup(
    db: AsyncSession, rtype: RecordType, tenant_id: str, uuids: Sequence[str]
) -> list[Record]:
    """Records by uuid, any status, the trash included."""
    record = tables_for(rtype).record
    stmt = select(record).where(
        record.tenant_id == tenant_id, record.type_id == rtype.id, record.uuid.in_(list(uuids))
    )
    return list((await db.execute(stmt.execution_options(include_deleted=True))).scalars().all())
