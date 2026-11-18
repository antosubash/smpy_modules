"""Which tenant a public request runs in.

Not in ``sm_events/core/tenancy`` (a parity-checked copy): this is a thin layer on its
``note_tenant_source``, ``resolve_public`` and ``tenant_scope``.

Two binders, two kinds of route:

* :func:`public_tenant` is for the pages a person reads. A request that resolved no tenant
  yields ``None`` and binds nothing, so the endpoint answers the site's own 404 *without a
  query* (an unbound ORM statement would raise ``TenantUnbound``, which is the guard doing
  its job). It never falls back to the default tenant: that would answer another
  organisation's address with the default site.
* ``sm_events.core.tenancy.bind_public`` is for machine-read routes (feeds, sitemap, the
  API): no tenant is a plain 404 with the ``{"detail", "code"}`` envelope.

Both record, before any fallback, whether something request-specific chose the tenant
(:func:`~sm_events.core.tenancy.note_tenant_source`), which is what the cache policy asks
(:func:`sm_events.web.endpoints.public._cache.shared_tenant`).

A router lists its binder as its **first** dependency: yield dependencies exit in reverse,
and ``get_db``'s commit has to run while the tenant is still bound.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Request

from sm_events.core.tenancy import note_tenant_source, resolve_public, tenant_scope

__all__ = ["public_tenant"]


async def public_tenant(request: Request) -> AsyncIterator[str | None]:
    """Bind the request's tenant for the page routes; ``None`` when it resolved none."""
    note_tenant_source(request)
    tenant = resolve_public(request)
    if tenant is None:
        yield None
        return
    with tenant_scope(tenant):
        yield tenant
