"""Reading a newsletter list's subscribers from another module (newsletter PR 1).

The newsletter module sends to the people on a records list and never imports
records' tables. What crosses the boundary is a small read-only
:class:`SubscriberHit`: no ``sm_nonce``, no consent text, no IP hash.

**Tenant.** The caller names it; it is validated, bound with records'
``tenant_scope`` — re-entering the tenant already bound is a no-op, naming
another one raises ``TenantIsolationError`` — and pinned again as a ``WHERE``
in every query, because on a single-tenant host nothing is bound and the
framework's filter then does nothing. A tenant with no such list reads as
empty, the same as an unknown address.

**Filters.** ``"field:op:value"`` terms in records' own grammar, ANDed. A term
the index cannot answer raises :class:`SubscriberFilterError` with records'
reason, instead of returning everyone.

**Limit.** An ``int`` from 1 to :data:`MAX_SUBSCRIBER_BATCH`; ``bool`` and
anything else raise ``ValueError`` before a query runs. ``after`` is a
non-negative ``int`` the same way.

**Writes** (:func:`unsubscribe`, :func:`set_tags`) run in the caller's
transaction and never commit; the caller finishes it with
``simple_module_db.finalize_session`` (or records' ``events.commit``), and only
then are ``SubscriptionChanged``/``RecordUpdated`` published, to ``bus`` when
one is given. :func:`can_read_list` is records' own per-type narrowing.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Literal

from simple_module_db import is_valid_tenant_id
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel

from sm_records.core import events
from sm_records.core.settings import RecordsSettings
from sm_records.core.tenancy import tenant_scope
from sm_records.models import Record, RecordType
from sm_records.public_submissions import campaign_reads, campaign_writes
from sm_records.public_submissions.campaign_reads import SubscriberFilterError, moment
from sm_records.public_submissions.campaign_writes import SubscriberNotFound
from sm_records.records.services._access import CallerRoles, role_blocked

__all__ = [
    "MAX_SUBSCRIBER_BATCH",
    "CallerRoles",
    "SubscriberFilterError",
    "SubscriberHit",
    "SubscriberNotFound",
    "can_read_list",
    "count_subscribers",
    "iter_subscribers",
    "set_tags",
    "subscribers_by_uuid",
    "unsubscribe",
]

Status = Literal["confirmed", "unsubscribed"]

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


def _checked_after(after: object) -> int:
    if not isinstance(after, int) or isinstance(after, bool) or after < 0:
        raise ValueError(f"after must be a non-negative int, got {after!r}")
    return after


def _checked_status(status: object) -> str:
    if status not in campaign_reads.WALKABLE:
        raise ValueError(f"status must be one of {campaign_reads.WALKABLE}, got {status!r}")
    return str(status)


def _checked_tags(tags: Sequence[str], name: str) -> list[str]:
    # A bare string is a sequence of one-letter tags: a caller bug.
    if isinstance(tags, str) or not all(isinstance(t, str) for t in tags):
        raise ValueError(f"{name} must be a sequence of tag strings, not {tags!r}")
    return list(tags)


def _checked_tenant(tenant_id: object) -> str:
    if not isinstance(tenant_id, str) or not is_valid_tenant_id(tenant_id):
        raise ValueError(f"not a valid tenant id: {tenant_id!r}")
    return tenant_id


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
        confirmed_at=moment(data.get("sm_confirmed_at")),
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
    status: Status = "confirmed",
) -> tuple[list[SubscriberHit], int | None]:
    """Untrashed subscribers in ``status`` (``confirmed``, the default, or
    ``unsubscribed``) matching every term, by record id.

    Returns ``(hits, next_after)``; pass ``next_after`` back as ``after`` for
    the next page. It is ``None`` once nothing follows."""
    tenant = _checked_tenant(tenant_id)
    limit, after, status = _checked_limit(limit), _checked_after(after), _checked_status(status)
    with tenant_scope(tenant):
        rtype = await campaign_reads.list_type(session, tenant, type_key)
        if rtype is None:
            return [], None
        rows, nxt = await campaign_reads.page(
            session, rtype, tenant, filters=filters, after=after, limit=limit, status=status
        )
        return [_hit(rtype, row) for row in rows], nxt


async def count_subscribers(
    session: AsyncSession,
    *,
    tenant_id: str,
    type_key: str,
    filters: Sequence[str] = (),
    status: Status = "confirmed",
) -> int:
    """How many subscribers :func:`iter_subscribers` would walk."""
    tenant, status = _checked_tenant(tenant_id), _checked_status(status)
    with tenant_scope(tenant):
        rtype = await campaign_reads.list_type(session, tenant, type_key)
        if rtype is None:
            return 0
        return await campaign_reads.count(session, rtype, tenant, filters, status)


async def subscribers_by_uuid(
    session: AsyncSession, *, tenant_id: str, type_key: str, uuids: Sequence[str]
) -> dict[str, SubscriberHit]:
    """Subscribers by uuid, in any status and trashed ones included
    (``trashed=True``). Unknown uuids are absent."""
    tenant = _checked_tenant(tenant_id)
    if isinstance(uuids, str):
        raise ValueError("uuids must be a sequence of uuids, not one string")
    if len(uuids) > MAX_SUBSCRIBER_BATCH:
        raise ValueError(f"at most {MAX_SUBSCRIBER_BATCH} uuids per call, got {len(uuids)}")
    with tenant_scope(tenant):
        rtype = await campaign_reads.list_type(session, tenant, type_key)
        if rtype is None or not uuids:
            return {}
        rows = await campaign_reads.lookup(session, rtype, tenant, uuids)
        return {row.uuid: _hit(rtype, row) for row in rows}


async def unsubscribe(
    session: AsyncSession,
    *,
    tenant_id: str,
    type_key: str,
    uuid: str,
    unless_confirmed_after: datetime | None,
    settings: RecordsSettings,
    bus: Any | None = None,
) -> bool:
    """Unsubscribe ``uuid``, as the subscriber's own link would.

    ``True`` only if *this* call wrote. ``False``, and nothing written, for an
    unknown or trashed subscriber, one ``pending`` or already ``unsubscribed``,
    or one confirmed after ``unless_confirmed_after`` (a re-signup since the
    mail; ``None`` means unconditionally). The cutoff must be aware.

    Raises ``SubscriberFilterError("not_a_list")`` when ``type_key`` is an
    existing type that is not a newsletter list."""
    tenant = _checked_tenant(tenant_id)
    cutoff = unless_confirmed_after
    if cutoff is not None and (not isinstance(cutoff, datetime) or cutoff.tzinfo is None):
        raise ValueError(f"unless_confirmed_after must be an aware datetime, got {cutoff!r}")
    with tenant_scope(tenant):
        events.attach(session, bus)
        return await campaign_writes.unsubscribe(session, tenant, type_key, uuid, cutoff, settings)


async def set_tags(
    session: AsyncSession,
    *,
    tenant_id: str,
    type_key: str,
    uuid: str,
    add: Sequence[str] = (),
    remove: Sequence[str] = (),
    settings: RecordsSettings,
    bus: Any | None = None,
) -> SubscriberHit:
    """Add and remove tags on a live subscriber; the subscriber as written.

    The stored order is kept, new tags appended, duplicates dropped, and a tag
    in both ``add`` and ``remove`` removed. :class:`SubscriberNotFound` for an
    unknown or trashed one; a tag outside the field's choices raises records'
    ``ValidationFailed`` unchanged, with nothing written. A merge that leaves the
    stored tags as they are writes nothing (no version bump, no event).

    Raises ``SubscriberFilterError("not_a_list")`` for an existing type that is
    not a newsletter list. The write is one ``update_record`` at the version
    read, retried once if the row moved; a second ``Conflict`` is re-raised."""
    tenant = _checked_tenant(tenant_id)
    add, remove = _checked_tags(add, "add"), _checked_tags(remove, "remove")
    with tenant_scope(tenant):
        events.attach(session, bus)
        rtype, record = await campaign_writes.set_tags(
            session, tenant, type_key, uuid, add, remove, settings
        )
        return _hit(rtype, record)


async def can_read_list(
    session: AsyncSession,
    *,
    tenant_id: str,
    type_key: str,
    roles: Sequence[str] | CallerRoles | None,
) -> bool:
    """Whether a caller holding ``roles`` may read list ``type_key`` — records'
    own ``allowed_roles`` narrowing, widened by a ``records.type.<key>`` grant
    (pass :class:`CallerRoles` for that). ``roles=None`` is no caller (a
    worker, the CLI). ``False`` when the tenant has no such list."""
    tenant = _checked_tenant(tenant_id)
    with tenant_scope(tenant):
        try:
            rtype = await campaign_reads.list_type(session, tenant, type_key)
        except SubscriberFilterError:
            return False
        return rtype is not None and not role_blocked(rtype, roles)
