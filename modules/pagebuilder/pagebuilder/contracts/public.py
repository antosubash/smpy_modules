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

from typing import Any

from fastapi import Request, Response
from simple_module_db import is_valid_tenant_id, tenant_context
from simple_module_hosting.inertia_deps import InertiaDep
from sqlalchemy.ext.asyncio import AsyncSession

from pagebuilder.core.settings import PagebuilderSettings
from pagebuilder.web._public_frame import public_frame
from pagebuilder.web.endpoints.public_not_found import NOT_FOUND_DETAIL
from pagebuilder.web.endpoints.public_not_found import render_not_found as _render

__all__ = ["NOT_FOUND_DETAIL", "TenantMismatchError", "layout_props", "render_not_found"]


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


async def layout_props(
    request: Request,
    db: AsyncSession,
    *,
    locale: str,
    tenant_id: str | None,
) -> dict[str, Any]:
    """The same public frame as ``/p/*``, for another module's reader pages.

    The caller names the framework-resolved tenant. Bind it here, including
    layout creation on an empty site; never commit the caller's transaction.
    No mounted site or no tenant means no props and no database access.
    ``copy`` is in the content language, independent of the viewer's UI locale.
    """
    _check_tenant(request, tenant_id)
    services = getattr(request.app.state, "pagebuilder", None)
    settings = getattr(services, "settings", None)
    if not isinstance(settings, PagebuilderSettings) or tenant_id is None:
        return {}
    with tenant_context(tenant_id):
        return await public_frame(db, settings, locale)
