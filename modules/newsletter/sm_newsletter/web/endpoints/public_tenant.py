"""The tenant a public link's request may hold against the link's token (S8).

The unsubscribe, open and click links carry their tenant in the signed token.
Only a tenant the request's *host* resolved (``request.state.tenant_source``
``subdomain`` or ``fixed``) can refuse one: B's site serving A's link is a
forgery. A tenant that came from the visitor - a signed-in member's session,
a header or claim - proves nothing about the link, so it never counts.
"""

from __future__ import annotations

from typing import Any, Final

from sm_newsletter.core import tenancy

__all__ = ["HOST_SOURCES", "host_tenant"]

HOST_SOURCES: Final = frozenset({"subdomain", "fixed"})
"""``TenantMiddleware`` sources that come from the host, not from the visitor."""


def host_tenant(request: Any) -> str | None:
    """The tenant the request's host resolved, or ``None``."""
    if getattr(request.state, "tenant_source", None) not in HOST_SOURCES:
        return None
    tenant = getattr(request.state, "tenant_id", None)
    return tenant if tenancy.valid_tenant(tenant) else None
