"""Reading a newsletter list's subscribers from another module (newsletter PR 1).

The newsletter module sends to the people on a records list and never imports
records' tables. What crosses the boundary is a small read-only
:class:`SubscriberHit`: no ``sm_nonce``, no consent text, no IP hash.

**Tenant.** The caller names it; it is validated, bound with ``tenant_context``
and pinned again as a ``WHERE`` in every query, because on a single-tenant
host nothing is bound and the framework's filter then does nothing. A tenant
with no such list reads as empty, the same as an unknown address.

**Filters.** ``"field:op:value"`` terms in records' own grammar, ANDed. A term
the index cannot answer raises :class:`SubscriberFilterError` with records'
reason, instead of returning everyone.

**Limit.** An ``int`` from 1 to :data:`MAX_SUBSCRIBER_BATCH`; ``bool`` and
anything else raise ``ValueError`` before a query runs.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from simple_module_db import is_valid_tenant_id, tenant_context
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel

from sm_records.models import Record, RecordType
from sm_records.public_submissions import campaign_reads
from sm_records.public_submissions.campaign_reads import SubscriberFilterError

__all__ = [
    "MAX_SUBSCRIBER_BATCH",
    "SubscriberFilterError",
    "SubscriberHit",
    "count_subscribers",
    "iter_subscribers",
    "subscribers_by_uuid",
]

MAX_SUBSCRIBER_BATCH = 1000
"""The most subscribers one call returns or looks up."""


class SubscriberHit(SQLModel):
    uuid: str
    email: str
    locale: str
    status: str  # "pending" | "confirmed" | "unsubscribed"
    confirmed_at: datetime | None
    first_name: str | None = None
    last_name: str | None = None
    tags: list[str] = []
    trashed: bool = False


def _checked_limit(limit: object) -> int:
    # `bool` is an `int`; `True` as a limit is a caller bug, not "one row".
    if not isinstance(limit, int) or isinstance(limit, bool):
        raise ValueError(f"limit must be an int, got {type(limit).__name__}")
    if not 1 <= limit <= MAX_SUBSCRIBER_BATCH:
        raise ValueError(f"limit must be between 1 and {MAX_SUBSCRIBER_BATCH}, got {limit}")
    return limit


def _checked_tenant(tenant_id: object) -> str:
    if not isinstance(tenant_id, str) or not is_valid_tenant_id(tenant_id):
        raise ValueError(f"not a valid tenant id: {tenant_id!r}")
    return tenant_id


def _moment(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _hit(rtype: RecordType, record: Record) -> SubscriberHit:
    declared = {f.get("key") for f in rtype.fields or []}
    data = record.data or {}
    tags = data.get("tags") if "tags" in declared else None
    return SubscriberHit(
        uuid=record.uuid,
        email=str(data.get("sm_email") or ""),
        locale=str(data.get("sm_locale") or ""),
        status=str(data.get("sm_status") or ""),
        confirmed_at=_moment(data.get("sm_confirmed_at")),
        first_name=_text(data.get("first_name")) if "first_name" in declared else None,
        last_name=_text(data.get("last_name")) if "last_name" in declared else None,
        tags=[t for t in tags if isinstance(t, str)] if isinstance(tags, list) else [],
        trashed=bool(record.is_deleted),
    )


async def iter_subscribers(
    session: AsyncSession,
    *,
    tenant_id: str,
    type_key: str,
    filters: Sequence[str] = (),
    after: int = 0,
    limit: int = 500,
) -> tuple[list[SubscriberHit], int | None]:
    """Confirmed, untrashed subscribers matching every term, by record id.

    Returns ``(hits, next_after)``; pass ``next_after`` back as ``after`` for
    the next page. It is ``None`` once nothing follows."""
    tenant = _checked_tenant(tenant_id)
    limit = _checked_limit(limit)
    with tenant_context(tenant):
        rtype = await campaign_reads.list_type(session, tenant, type_key)
        if rtype is None:
            return [], None
        rows, nxt = await campaign_reads.page(
            session, rtype, tenant, filters=filters, after=after, limit=limit
        )
        return [_hit(rtype, row) for row in rows], nxt


async def count_subscribers(
    session: AsyncSession, *, tenant_id: str, type_key: str, filters: Sequence[str] = ()
) -> int:
    """How many subscribers :func:`iter_subscribers` would walk."""
    tenant = _checked_tenant(tenant_id)
    with tenant_context(tenant):
        rtype = await campaign_reads.list_type(session, tenant, type_key)
        if rtype is None:
            return 0
        return await campaign_reads.count(session, rtype, tenant, filters)


async def subscribers_by_uuid(
    session: AsyncSession, *, tenant_id: str, type_key: str, uuids: Sequence[str]
) -> dict[str, SubscriberHit]:
    """Subscribers by uuid, in any status and trashed ones included
    (``trashed=True``). Unknown uuids are absent."""
    tenant = _checked_tenant(tenant_id)
    if len(uuids) > MAX_SUBSCRIBER_BATCH:
        raise ValueError(f"at most {MAX_SUBSCRIBER_BATCH} uuids per call, got {len(uuids)}")
    with tenant_context(tenant):
        rtype = await campaign_reads.list_type(session, tenant, type_key)
        if rtype is None or not uuids:
            return {}
        rows = await campaign_reads.lookup(session, rtype, tenant, uuids)
        return {row.uuid: _hit(rtype, row) for row in rows}
