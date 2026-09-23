"""Deliberate cross-tenant reads: health, the CLI's enumeration, the runners.

Tenancy design §A.5. A few records paths have to see *every* tenant: the health
check, ``reindex``/``verify`` without ``--type``, ``records tenants``, and the
reindex runner finding which tenant a type id belongs to.
:func:`sm_records.tenancy.all_tenants` is not enough for them on its own. It
only gets a statement past the guard. When a tenant **is** bound, the
framework's filter still applies, because ``simple_module_db.listeners``
attaches the tenant criteria whenever ``current_tenant_id`` is set and has no
bypass option. That is not hypothetical: on a multi-tenant host
``/health/ready`` runs inside ``TenantMiddleware``, which binds whatever tenant
the caller's header names.

So :func:`read_all` clears the binding for exactly one ``execute``, and tags the
statement with ``all_tenants``. The soft-delete filter still applies unless the
caller passes ``include_deleted``.

**Read-only by construction.** Nothing may be pending on the session. An
autoflush inside the unbound window would reach the guard's ``before_flush``
with no tenant bound, and the guard raises ``TenantUnbound``, so the write
fails instead of landing unstamped. Every caller here uses a fresh session.
"""

from __future__ import annotations

from collections.abc import Collection, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from simple_module_db.listeners import current_tenant_id
from sqlalchemy import func, select

from sm_records.models import RecordType, table_sets
from sm_records.tenancy import all_tenants

__all__ = ["TenantCounts", "read_all", "tenant_counts"]


@contextmanager
def _unbound() -> Iterator[None]:
    token = current_tenant_id.set(None)
    try:
        yield
    finally:
        current_tenant_id.reset(token)


async def read_all(session: Any, stmt: Any) -> Any:
    """Execute ``stmt`` across every tenant, whatever the caller has bound.

    The result is buffered (``AsyncSession.execute``), so the rows can be read
    after the binding is back.
    """
    with _unbound():
        return await session.execute(all_tenants(stmt))


@dataclass(frozen=True, slots=True)
class TenantCounts:
    """What one tenant holds. ``records`` is live rows; ``trashed`` is the rest."""

    types: int = 0
    records: int = 0
    trashed: int = 0


async def tenant_counts(
    session: Any, tenants: Collection[str] | None = None
) -> dict[str, TenantCounts]:
    """``{tenant: TenantCounts}`` for every tenant with at least one type.

    A record cannot be in a tenant its type is not in (the composite foreign
    key, §B), so the types table is the full list of tenants. One ``GROUP BY``
    over the types, and one per table set over the records. ``tenants``
    narrows both to the given ids. The health check passes the tenants it
    found outside ``default``, so it pays for the ``ix_*_tenant_id`` range of
    rows it reports and not for the whole table.
    """
    type_stmt = select(RecordType.tenant_id, func.count(RecordType.id)).group_by(
        RecordType.tenant_id
    )
    if tenants is not None:
        type_stmt = type_stmt.where(RecordType.tenant_id.in_(list(tenants)))
    types = {str(t): int(n) for t, n in (await read_all(session, type_stmt)).all()}
    live: dict[str, int] = {}
    trashed: dict[str, int] = {}
    for tables in table_sets():
        cls = tables.record
        stmt = (
            select(cls.tenant_id, cls.is_deleted, func.count(cls.id))
            .group_by(cls.tenant_id, cls.is_deleted)
            .execution_options(include_deleted=True)
        )
        if tenants is not None:
            stmt = stmt.where(cls.tenant_id.in_(list(tenants)))
        for tenant, deleted, count in (await read_all(session, stmt)).all():
            bucket = trashed if deleted else live
            bucket[str(tenant)] = bucket.get(str(tenant), 0) + int(count)
    return {
        tenant: TenantCounts(
            types=types.get(tenant, 0),
            records=live.get(tenant, 0),
            trashed=trashed.get(tenant, 0),
        )
        for tenant in sorted(set(types) | set(live) | set(trashed))
    }
