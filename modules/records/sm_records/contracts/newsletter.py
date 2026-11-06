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
one is given. With ``bus=None`` nothing is published: a caller in a web process
must pass ``app.state.sm.event_bus``.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from simple_module_db.listeners import TenantIsolationError, current_tenant_id
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.contracts._newsletter_args import (
    MAX_SUBSCRIBER_BATCH,
    Status,
    SubscriberHit,
    _checked_after,
    _checked_limit,
    _checked_status,
    _checked_tags,
    _checked_tenant,
    _checked_trash,
    _hit,
)
from sm_records.core import events
from sm_records.core.settings import RecordsSettings
from sm_records.core.tenancy import tenant_scope
from sm_records.public_submissions import campaign_reads, campaign_writes
from sm_records.public_submissions.campaign_reads import SubscriberFilterError
from sm_records.public_submissions.campaign_writes import SubscriberNotFound
from sm_records.records.services._access import CallerRoles, role_blocked
from sm_records.records.services.errors import ValidationFailed

__all__ = [
    "MAX_SUBSCRIBER_BATCH",
    "CallerRoles",
    "SubscriberFilterError",
    "SubscriberHit",
    "SubscriberNotFound",
    "ValidationFailed",
    "caller_roles",
    "can_read_list",
    "count_subscribers",
    "iter_subscribers",
    "set_tags",
    "subscribers_by_uuid",
    "subscription_list_tenants",
    "subscription_lists",
    "unsubscribe",
]


async def subscription_list_tenants(session: AsyncSession) -> list[str]:
    """Every valid tenant id that owns at least one newsletter list, sorted —
    which tenants the newsletter reconcile walks.

    The contract's one cross-tenant read, for a worker: it runs with no tenant
    bound (or inside ``no_tenant()``/``all_tenants()``) and enters the
    framework's ``all_tenants()`` itself. Under a bound tenant it raises
    ``TenantIsolationError``, as ``tenant_scope`` does for a second tenant: a
    request never enumerates other tenants. Use a fresh session."""
    bound = current_tenant_id.get()
    if bound is not None:
        raise TenantIsolationError(f"cannot enumerate tenants inside a scope bound to {bound!r}")
    return await campaign_reads.list_tenants(session)


async def subscription_lists(session: AsyncSession, *, tenant_id: str) -> list[str]:
    """The keys of the tenant's newsletter lists (record types of kind
    ``subscription``), sorted; ``[]`` for a tenant with none."""
    tenant = _checked_tenant(tenant_id)
    with tenant_scope(tenant):
        return await campaign_reads.list_keys(session, tenant)


async def iter_subscribers(
    session: AsyncSession,
    *,
    tenant_id: str,
    type_key: str,
    filters: Sequence[str] = (),
    after: int = 0,
    limit: int = 500,
    status: Status = "confirmed",
    include_trashed: bool = False,
) -> tuple[list[SubscriberHit], int | None]:
    """Untrashed subscribers in ``status`` (``confirmed``, the default, or
    ``unsubscribed``) matching every term, by record id.

    ``include_trashed=True`` (only with ``status="unsubscribed"``) walks the
    trash as well, each such hit ``trashed=True``: an opt-out still counts
    while its record waits in the trash to be purged.

    Returns ``(hits, next_after)``; pass ``next_after`` back as ``after`` for
    the next page. It is ``None`` once nothing follows."""
    tenant = _checked_tenant(tenant_id)
    limit, after, status = _checked_limit(limit), _checked_after(after), _checked_status(status)
    trash = _checked_trash(include_trashed, status)
    with tenant_scope(tenant):
        rtype = await campaign_reads.list_type(session, tenant, type_key)
        if rtype is None:
            return [], None
        rows, nxt = await campaign_reads.page(
            session,
            rtype,
            tenant,
            filters=filters,
            after=after,
            limit=limit,
            status=status,
            include_trashed=trash,
        )
        return [_hit(rtype, row) for row in rows], nxt


async def count_subscribers(
    session: AsyncSession,
    *,
    tenant_id: str,
    type_key: str,
    filters: Sequence[str] = (),
    status: Status = "confirmed",
    include_trashed: bool = False,
) -> int:
    """How many subscribers :func:`iter_subscribers` would walk, with the
    same ``include_trashed`` rule."""
    tenant, status = _checked_tenant(tenant_id), _checked_status(status)
    trash = _checked_trash(include_trashed, status)
    with tenant_scope(tenant):
        rtype = await campaign_reads.list_type(session, tenant, type_key)
        if rtype is None:
            return 0
        return await campaign_reads.count(session, rtype, tenant, filters, status, trash)


async def subscribers_by_uuid(
    session: AsyncSession, *, tenant_id: str, type_key: str, uuids: Sequence[str]
) -> dict[str, SubscriberHit]:
    """Subscribers by uuid, in any status and trashed ones included
    (``trashed=True``). Unknown uuids are absent."""
    tenant = _checked_tenant(tenant_id)
    if isinstance(uuids, str):
        raise ValueError("uuids must be a sequence of uuids, not one string")
    if not all(isinstance(u, str) for u in uuids):
        raise ValueError("every uuid must be a str")
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
    mail; ``None`` means unconditionally). A confirmed subscriber whose
    ``sm_confirmed_at`` is missing or unparseable *is* unsubscribed: a re-signup
    after the cutoff cannot be proven, and not honouring an unsubscribe is the
    worse error. The cutoff must be aware.

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
    ``ValidationFailed`` (re-exported here) unchanged, with nothing written. A merge that leaves the
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


def caller_roles(request: Any) -> CallerRoles:
    """The request's caller as :class:`CallerRoles`: their roles plus the
    ``records.type.<key>`` grants, with records' wildcard rule applied (an
    admin holds no per-type grants). Anonymous is ``CallerRoles([])``.

    What :func:`can_read_list` needs and another module cannot build itself.
    Reads the permission set the framework resolved for the request."""
    from sm_records.web.deps import caller_roles as _caller_roles

    return _caller_roles(request)
