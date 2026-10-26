"""The public site's not-found page, for another module's public routes (#248).

News serves articles at its own addresses, but they are the same site: a
visitor who follows a dead article link should land on the site's 404 — its
header, footer, branding and design pack, in the address's language — rather
than on the host's generic error page. That page is pagebuilder's
(``PageBuilder/PublicNotFound``, #89), so this is the one way in.

**Tenant.** The caller names it, as with :mod:`pagebuilder.contracts.search`,
and the layout and nav are read with it bound *here*. ``None`` (a request that
resolved no tenant) renders the page with no layout at all, never the default
tenant's, and runs no query.

``tenant_id`` must be the tenant the *framework* resolved for this request —
what the caller's own tenant binder answered — and never anything taken from
client input (a header, a query parameter, a body field). As a guard, when the
request carries a resolved tenant (``request.state.tenant_id``) and
``tenant_id`` names a different one, the call raises
:class:`TenantMismatchError` rather than render another tenant's site frame.

**Mounted.** Pagebuilder can be installed without being mounted on the app
serving the request. Then there is no site frame to render and this answers
``None``, so the caller falls back to its own 404.
"""

from __future__ import annotations

from fastapi import Request, Response
from simple_module_db import is_valid_tenant_id, tenant_context
from simple_module_hosting.inertia_deps import InertiaDep
from sqlalchemy.ext.asyncio import AsyncSession

from pagebuilder.endpoints.public_not_found import NOT_FOUND_DETAIL
from pagebuilder.endpoints.public_not_found import render_not_found as _render
from pagebuilder.settings import PagebuilderSettings

__all__ = ["NOT_FOUND_DETAIL", "TenantMismatchError", "render_not_found"]


class TenantMismatchError(RuntimeError):
    """``tenant_id`` is not the tenant the framework resolved for the request."""


def _check_tenant(request: Request, tenant_id: str | None) -> None:
    """Refuse a ``tenant_id`` that contradicts the request's resolved tenant.

    ``None`` is always allowed: it renders no layout at all, which shows no
    tenant's site.
    """
    resolved = getattr(getattr(request, "state", None), "tenant_id", None)
    if tenant_id is not None and is_valid_tenant_id(resolved) and resolved != tenant_id:
        raise TenantMismatchError(
            f"pagebuilder: render_not_found was asked for tenant {tenant_id!r} on a "
            f"request resolved to {resolved!r}; pass the request's own tenant"
        )


async def render_not_found(
    request: Request,
    inertia: InertiaDep,
    db: AsyncSession,
    *,
    locale: str,
    tenant_id: str | None,
    detail: str = NOT_FOUND_DETAIL,
) -> Response | None:
    """The site's 404 for ``request``, or ``None`` where pagebuilder is not mounted.

    The same answer pagebuilder's own viewer gives a missing page: status 404,
    ``Cache-Control: no-store``, ``Vary`` on whatever picks the tenant,
    ``Content-Language: locale``. A caller asking for JSON and not HTML gets
    ``{"detail": detail}``.

    Raises :class:`TenantMismatchError` when ``tenant_id`` is not the tenant
    the request resolved, checked before anything else.
    """
    _check_tenant(request, tenant_id)
    services = getattr(request.app.state, "pagebuilder", None)
    settings = getattr(services, "settings", None)
    if not isinstance(settings, PagebuilderSettings):
        return None
    if tenant_id is None:
        return await _render(request, inertia, settings, locale=locale, db=None, detail=detail)
    with tenant_context(tenant_id):
        return await _render(request, inertia, settings, locale=locale, db=db, detail=detail)
