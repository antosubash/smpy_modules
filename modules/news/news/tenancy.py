"""Which tenant a news request runs in.

Design: ``docs/superpowers/specs/2026-10-08-news-multitenancy-design.md``.
Every news table carries the framework's ``MultiTenantMixin``. The
framework's answer to "queried with no tenant bound" is every tenant's rows
(or, on a strict host, an error), and a write with none is a ``NOT NULL``
failure — so news binds a tenant at each of its own entry points and
never relies on one happening to be set.

**Mode** is read off the *built* middleware stack, as records does: the stack
is built once at boot, so a later edit of ``multi_tenant`` does not reach it
until a restart.

* ``SINGLE`` — no ``TenantMiddleware``, or one ``fixed`` to
  :data:`DEFAULT_TENANT`. Everything runs in :data:`DEFAULT_TENANT`.
* ``MULTI`` — every entry point runs in the tenant the framework resolved
  (``request.state.tenant_id``: subdomain for visitors, membership for
  members). The admin surface refuses a request with none (403
  ``tenant_required``); the public surface answers it with the same 404 an
  unknown slug gets, so it is no oracle. Neither falls back to the default.

The framework filters ORM statements and Core statements over
``Model.__table__``; a ``text()`` statement on a news table would need
its own ``tenant_id`` predicate (there are none today).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from enum import StrEnum
from typing import Any, Final

from fastapi import HTTPException, Request
from simple_module_db import current_tenant_id, is_valid_tenant_id, tenant_context

__all__ = [
    "DEFAULT_TENANT",
    "TENANT_REQUIRED",
    "TenancyMode",
    "bind_admin",
    "bind_public",
    "configure",
    "detect_mode",
    "mode_of",
    "resolve_admin",
    "resolve_public",
    "search_tenant",
    "tenant_vary",
    "vary_on_tenant",
]

_log = logging.getLogger("simple_module.news")

_PACKAGE = "news"

DEFAULT_TENANT: Final = "default"
"""The tenant of a single-tenant host, and of every row that predates tenancy.

A constant, not a setting: the ``tenant_id`` migration backfills this literal,
and records uses the same one, so one host has one notion of it."""

TENANT_REQUIRED: Final = "tenant_required"
"""The 403 detail for an admin request that resolved no tenant."""

_NOT_FOUND: Final = "Article not found"
"""What the public viewer answers for an unknown slug — and, word for word, for
a request that resolved no tenant."""


class TenancyMode(StrEnum):
    SINGLE = "single"
    MULTI = "multi"


def _tenant_middleware(app: Any) -> Any:
    """The ``TenantMiddleware`` entry of the built stack, or ``None``."""
    from simple_module_hosting.middleware import TenantMiddleware

    entries = getattr(app, "user_middleware", ())
    return next((e for e in entries if getattr(e, "cls", None) is TenantMiddleware), None)


def _fixed_tenant(entry: Any) -> str | None:
    """The tenant a single-tenant host pins every request to, or ``None``."""
    return (getattr(entry, "kwargs", None) or {}).get("fixed") if entry else None


def detect_mode(app: Any) -> TenancyMode:
    """``MULTI`` iff ``TenantMiddleware`` is in the stack and resolves tenants
    per request; a ``fixed`` one is a single-tenant host."""
    entry = _tenant_middleware(app)
    return TenancyMode.SINGLE if entry is None or _fixed_tenant(entry) else TenancyMode.MULTI


def configure(app: Any) -> TenancyMode:
    """Detect the mode once and store it on ``app.state.news``.

    Called from ``NewsModule.on_startup`` before anything touches the
    database. A host pinned to a ``default_tenant`` other than
    :data:`DEFAULT_TENANT` is refused: the migration filed every existing row
    under :data:`DEFAULT_TENANT`, so the framework would bind one tenant and
    news's data would sit in another.
    """
    fixed = _fixed_tenant(_tenant_middleware(app))
    if fixed is not None and fixed != DEFAULT_TENANT:
        raise RuntimeError(
            f"news: the host pins every request to default_tenant={fixed!r}, but "
            f"news runs a single-tenant host in {DEFAULT_TENANT!r}. Unset "
            f"default_tenant, set it to {DEFAULT_TENANT!r}, or turn multi_tenant on"
        )
    mode = detect_mode(app)
    services = getattr(app.state, _PACKAGE, None)
    if services is not None:
        services.tenancy = mode
    else:
        app.state.news_tenancy = mode
    host = getattr(getattr(app.state, "host", None), "settings", None)
    if getattr(host, "multi_tenant", False) is True and mode is TenancyMode.SINGLE:
        _log.warning(
            "news: the host setting multi_tenant is on but the middleware stack has "
            "no TenantMiddleware, so news runs single-tenant. Restart to apply it"
        )
    settings = getattr(getattr(app.state, _PACKAGE, None), "settings", None)
    if mode is TenancyMode.MULTI and getattr(settings, "public_base_url", ""):
        _log.warning(
            "news: public_base_url is set on a multi-tenant host, so every "
            "tenant's canonical, feed and sitemap links point at %s. Leave it "
            "blank to build them from each request's host",
            settings.public_base_url,
        )
    return mode


def tenant_vary(app: Any) -> tuple[str, ...]:
    """The request headers that pick a public response's tenant.

    ``SINGLE``: none. ``MULTI``: on the apex host the framework falls back to
    a member's session (``Cookie``) or the configured tenant header, so the
    same Host + URL answers with different tenants' content and a shared
    cache has to key on them too.
    """
    if mode_of(app) is TenancyMode.SINGLE:
        return ()
    header = (getattr(_tenant_middleware(app), "kwargs", None) or {}).get("header")
    return ("Cookie", header) if header else ("Cookie",)


def vary_on_tenant(response: Any, app: Any) -> Any:
    """Append :func:`tenant_vary` to *response*'s ``Vary``; a no-op in SINGLE."""
    listed = [f.strip() for f in response.headers.get("vary", "").split(",") if f.strip()]
    seen = {f.lower() for f in listed}
    added = [f for f in tenant_vary(app) if f.lower() not in seen]
    if added:
        response.headers["Vary"] = ", ".join(listed + added)
    return response


def mode_of(app: Any) -> TenancyMode:
    """The stored mode, or a fresh detection before ``on_startup`` has run."""
    mode = getattr(getattr(app.state, _PACKAGE, None), "tenancy", None)
    if not isinstance(mode, TenancyMode):
        mode = getattr(app.state, "news_tenancy", None)
    return mode if isinstance(mode, TenancyMode) else detect_mode(app)


def _resolved(request: Any) -> str | None:
    tenant = getattr(request.state, "tenant_id", None)
    return tenant if is_valid_tenant_id(tenant) else None


def resolve_admin(request: Any) -> str:
    """The admin surface's tenant; 403 ``tenant_required`` in MULTI mode
    when the framework resolved none."""
    if mode_of(request.app) is TenancyMode.SINGLE:
        return DEFAULT_TENANT
    tenant = _resolved(request)
    if tenant is None:
        raise HTTPException(status_code=403, detail=TENANT_REQUIRED)
    return tenant


def resolve_public(request: Any) -> str | None:
    """The anonymous surface's tenant, or ``None``."""
    if mode_of(request.app) is TenancyMode.SINGLE:
        return DEFAULT_TENANT
    return _resolved(request)


async def bind_admin(request: Request) -> AsyncIterator[str]:
    """Router dependency: the admin surface's tenant for the whole request.

    Must come before ``get_db`` in the dependency order — yield dependencies
    exit in reverse, and ``get_db``'s commit has to run while this is still
    bound. Router-level dependencies always precede the endpoint's own, so
    listing it on the router is enough. In MULTI mode ``TenantMiddleware`` has
    already bound the same tenant; re-entering it is harmless.
    """
    tenant = resolve_admin(request)
    with tenant_context(tenant):
        yield tenant


async def bind_public(request: Request) -> AsyncIterator[str]:
    """Router dependency for the anonymous surface; 404 without a tenant."""
    tenant = resolve_public(request)
    if tenant is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    with tenant_context(tenant):
        yield tenant


def search_tenant() -> str:
    """The tenant a cross-module read runs in: the bound one, else the
    single-tenant host's. A host with multi_tenant off binds none, and
    an unfiltered read there would be every tenant's rows."""
    return current_tenant_id.get() or DEFAULT_TENANT
