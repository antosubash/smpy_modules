"""The queries behind the newsletter contract's admin reads (newsletter PR 6).

Browsing is not an audience: it lists subscribers in *any* status, newest
first, with offset paging, where :mod:`campaign_reads` walks confirmed or
unsubscribed ones by id. Every query pins the tenant as a ``WHERE`` of its own.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.core.settings import RecordsSettings
from sm_records.models import Record, RecordType, tables_for
from sm_records.public_submissions.campaign_reads import SubscriberFilterError
from sm_records.public_submissions.spec import INTERNAL
from sm_records.public_submissions.subscribe import CONFIRMED, PENDING, UNSUBSCRIBED
from sm_records.records._grammar import FilterTermError, parse_term
from sm_records.records.index._filters import filtered
from sm_records.records.index._predicates import QueryError
from sm_records.records.index.query import Filter, FilterOp
from sm_records.schema.types import FieldType

__all__ = ["STATUSES", "browse", "declared_fields", "status_counts"]

STATUSES = (PENDING, CONFIRMED, UNSUBSCRIBED)


def declared_fields(rtype: RecordType) -> list[dict[str, Any]]:
    """The declared fields a segment can filter on: indexed, not internal, not
    a relation, in declared order."""
    return [
        f
        for f in rtype.fields or []
        if isinstance(f, dict)
        and f.get("indexed")
        and f.get("system") != INTERNAL
        and f.get("type") != FieldType.RELATION.value
    ]


def _terms(raw: Sequence[str], search: str | None) -> list[Filter]:
    settings = RecordsSettings()
    if isinstance(raw, str):
        raise SubscriberFilterError(
            "malformed", "filters must be a sequence of terms, not a string"
        )
    if len(raw) > settings.max_filter_terms:
        raise SubscriberFilterError("malformed", "too many filter terms")
    try:
        terms = [parse_term(term, settings) for term in raw]
    except FilterTermError as exc:
        raise SubscriberFilterError("malformed", str(exc)) from exc
    if search:
        terms.append(Filter("sm_email", FilterOp.CONTAINS, search.lower()))
    return terms


def _select(rtype: RecordType, tenant_id: str, what: Any, terms: list[Filter]):
    record = tables_for(rtype).record
    stmt = select(what(record)).where(record.type_id == rtype.id, record.tenant_id == tenant_id)
    try:
        return filtered(stmt, rtype, list(rtype.fields or []), terms), record
    except QueryError as exc:
        raise SubscriberFilterError(exc.reason, str(exc)) from exc


async def browse(
    db: AsyncSession,
    rtype: RecordType,
    tenant_id: str,
    *,
    filters: Sequence[str],
    status: str | None,
    search: str | None,
    offset: int,
    limit: int,
) -> tuple[list[Record], int]:
    """One page of untrashed subscribers (newest first) and the exact total."""
    terms = _terms(filters, search)
    if status is not None:
        terms.append(Filter("sm_status", FilterOp.EQ, status))
    stmt, record = _select(rtype, tenant_id, lambda r: r, terms)
    counted, _ = _select(rtype, tenant_id, lambda r: func.count(r.id), terms)
    total = int((await db.execute(counted)).scalar_one())
    page = stmt.order_by(record.id.desc()).offset(offset).limit(limit)
    return list((await db.execute(page)).scalars().all()), total


async def status_counts(
    db: AsyncSession,
    rtype: RecordType,
    tenant_id: str,
    *,
    filters: Sequence[str],
    search: str | None,
) -> dict[str, int]:
    """Untrashed subscribers per status, over the same filters and search."""
    base = _terms(filters, search)
    out: dict[str, int] = {}
    for status in STATUSES:
        stmt, _ = _select(
            rtype,
            tenant_id,
            lambda r: func.count(r.id),
            [*base, Filter("sm_status", FilterOp.EQ, status)],
        )
        out[status] = int((await db.execute(stmt)).scalar_one())
    return out
