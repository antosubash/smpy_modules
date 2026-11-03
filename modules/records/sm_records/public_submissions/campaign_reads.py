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

from simple_module_db import is_valid_tenant_id
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.contracts.public_submissions import KIND_SUBSCRIPTION
from sm_records.core.settings import RecordsSettings
from sm_records.core.tenancy._cross_tenant import read_all
from sm_records.models import Record, RecordType, tables_for
from sm_records.public_submissions.subscribe import CONFIRMED, UNSUBSCRIBED
from sm_records.records._grammar import FilterTermError, parse_term
from sm_records.records.index._predicates import QueryError
from sm_records.records.index.query import Filter, FilterOp, build_query, count_query

__all__ = [
    "WALKABLE",
    "SubscriberFilterError",
    "count",
    "list_keys",
    "list_tenants",
    "list_type",
    "lookup",
    "moment",
    "page",
    "stored_tags",
]

WALKABLE: Final = (CONFIRMED, UNSUBSCRIBED)
"""The statuses a walk may ask for: who is mailed, and who left (the
newsletter's reconcile). ``pending`` is nobody's audience."""


class SubscriberFilterError(ValueError):
    """A filter the list cannot answer, or a type that is not a list.

    ``reason`` is records' own ``QueryError.reason`` (``unknown``, ``not_indexed``,
    ``reindexing``, ``bad_value``, ``unsupported_op``),
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
    if not _is_list(rtype.public_submissions):
        raise SubscriberFilterError("not_a_list", f"{type_key!r} is not a newsletter list")
    return rtype


def _is_list(config: Any) -> bool:
    """Whether a type's ``public_submissions`` makes it a newsletter list."""
    return isinstance(config, dict) and config.get("kind") == KIND_SUBSCRIPTION


async def list_keys(db: AsyncSession, tenant_id: str) -> list[str]:
    """The keys of the tenant's newsletter lists, sorted. Types are few, so
    the kind is checked here rather than in JSON SQL both backends agree on.
    A deleted type is gone (types are hard-deleted), so every row is live."""
    stmt = select(RecordType.key, RecordType.public_submissions).where(
        RecordType.tenant_id == tenant_id
    )
    return sorted(str(key) for key, config in (await db.execute(stmt)).all() if _is_list(config))


async def list_tenants(db: AsyncSession) -> list[str]:
    """Every valid tenant id owning at least one newsletter list, sorted.

    The one cross-tenant read here: :func:`read_all` runs it inside the
    framework's ``all_tenants()`` and tags it past records' guard. The caller
    refuses to run it under a bound tenant. An id is kept only if the
    framework's ``is_valid_tenant_id`` accepts it — the check the per-tenant
    contract calls make — so each result can be passed straight back to them
    (records' ``valid_tenant`` would keep ``"platform"`` and ``"a\\n"``)."""
    stmt = select(RecordType.tenant_id, RecordType.public_submissions)
    rows = (await read_all(db, stmt)).all()
    return sorted({str(t) for t, config in rows if _is_list(config) and is_valid_tenant_id(t)})


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
    if isinstance(raw, str):
        raise SubscriberFilterError(
            "malformed", "filters must be a sequence of terms, not a string"
        )
    if len(raw) > settings.max_filter_terms:
        raise SubscriberFilterError("malformed", "too many filter terms")
    try:
        parsed = [parse_term(term, settings) for term in raw]
    except FilterTermError as exc:
        raise SubscriberFilterError("malformed", str(exc)) from exc
    return [Filter("sm_status", FilterOp.EQ, status), *parsed]


def _query(
    rtype: RecordType,
    tenant_id: str,
    filters: Sequence[str],
    status: str,
    builder,
    include_trashed: bool = False,
):
    """``builder``'s statement (``build_query``/``count_query``) for the terms,
    pinned to the tenant (the framework's soft-delete filter keeps the trash
    out unless ``include_trashed`` lifts it); with the type's record table."""
    terms = _filters(filters, status)
    record = tables_for(rtype).record
    try:
        stmt = builder(rtype, list(rtype.fields or []), terms)
    except QueryError as exc:
        raise SubscriberFilterError(exc.reason, str(exc)) from exc
    stmt = stmt.where(record.tenant_id == tenant_id)
    if include_trashed:
        stmt = stmt.execution_options(include_deleted=True)
    return stmt, record


async def page(
    db: AsyncSession,
    rtype: RecordType,
    tenant_id: str,
    *,
    filters: Sequence[str],
    after: int,
    limit: int,
    status: str,
    include_trashed: bool = False,
) -> tuple[list[Record], int | None]:
    """Records in ``status`` matching every term, ``Record.id`` order; the
    trash only with ``include_trashed``.

    One row more than ``limit`` is read to know whether anything follows, so
    ``next_after`` is ``None`` exactly when the walk is over."""
    stmt, record = _query(rtype, tenant_id, filters, status, build_query, include_trashed)
    stmt = stmt.where(record.id > after).limit(limit + 1)
    rows = list((await db.execute(stmt)).scalars().all())
    if len(rows) <= limit:
        return rows, None
    rows = rows[:limit]
    return rows, rows[-1].id


async def count(
    db: AsyncSession,
    rtype: RecordType,
    tenant_id: str,
    filters: Sequence[str],
    status: str,
    include_trashed: bool = False,
) -> int:
    stmt, _ = _query(rtype, tenant_id, filters, status, count_query, include_trashed)
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
