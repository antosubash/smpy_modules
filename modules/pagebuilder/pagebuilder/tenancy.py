"""Which tenant a pagebuilder request runs in.

Design: ``docs/superpowers/specs/2026-10-05-pagebuilder-tenancy-design.md``.
Every pagebuilder table carries the framework's ``MultiTenantMixin``. The
framework's answer to "queried with no tenant bound" is every tenant's rows
(or, on a strict host, an error), and a write with none is a ``NOT NULL``
failure — so pagebuilder binds a tenant at each of its own entry points and
never relies on one happening to be set.

**Mode** is read off the *built* middleware stack, as records does: the stack
is built once at boot, so a later edit of ``multi_tenant`` does not reach it
until a restart.

* ``SINGLE`` — no ``TenantMiddleware``, or one ``fixed`` to
  :data:`DEFAULT_TENANT`. Everything runs in :data:`DEFAULT_TENANT` —
  *unless something upstream already resolved a tenant for the request*,
  which always wins (#192): the mode only fills a gap, so a wrong ``SINGLE``
  (a child app mounted under a multi-tenant parent) fails closed. Detection
  and the request-time rule live in :mod:`pagebuilder._tenancy_mode`.
* ``MULTI`` — every entry point runs in the tenant the framework resolved
  (``request.state.tenant_id``: subdomain for visitors, membership for
  members). The admin surface refuses a request with none (403
  ``tenant_required``); the public surface answers it with the same 404 an
  unknown slug gets, so it is no oracle. Neither falls back to the default.

The framework filters ORM statements and Core statements over
``Model.__table__``; a ``text()`` statement on a pagebuilder table would need
its own ``tenant_id`` predicate (there are none today).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Mapping
from typing import Any, Final

from fastapi import HTTPException, Request
from simple_module_db import tenant_context
from simple_module_hosting.tenancy import tenant_vary as recorded_vary

from pagebuilder._tenancy_mode import (  # noqa: F401 - tests read the private names here
    _KNOWN_KWARGS,
    _PACKAGE,
    DEFAULT_TENANT,
    TenancyMode,
    _fixed_tenant,
    _framework_mode,
    _kwargs,
    _tenant_middleware,
    _warn_if_unrecognised,
    detect_mode,
    request_mode,
    stray_pins,
    upstream_tenant,
)

__all__ = [
    "DEFAULT_TENANT",
    "TENANT_REQUIRED",
    "TenancyMode",
    "bind_admin",
    "bind_public",
    "bind_public_viewer",
    "configure",
    "detect_mode",
    "mode_of",
    "request_vary",
    "resolve_admin",
    "resolve_public",
    "tenant_vary",
    "vary_on_tenant",
]

_log = logging.getLogger("simple_module.pagebuilder")

TENANT_REQUIRED: Final = "tenant_required"
"""The 403 detail for an admin request that resolved no tenant."""

_NOT_FOUND: Final = "Page not found"
"""What the public viewer answers for an unknown slug — and, word for word, for
a request that resolved no tenant."""


def configure(app: Any) -> TenancyMode:
    """Detect the mode once and store it on ``app.state.pagebuilder``.

    Called from ``PagebuilderModule.on_startup`` before anything touches the
    database. A host pinned to a ``default_tenant`` other than
    :data:`DEFAULT_TENANT` is refused: the migration filed every existing row
    under :data:`DEFAULT_TENANT`, so the framework would bind one tenant and
    pagebuilder's data would sit in another.
    """
    stray = stray_pins(app)
    if stray is not None:
        raise RuntimeError(
            f"pagebuilder: the host pins every request to {stray}, but "
            f"pagebuilder runs a single-tenant host in {DEFAULT_TENANT!r}. Unset "
            f"default_tenant and any TenantMiddleware(fixed=...), set them to "
            f"{DEFAULT_TENANT!r}, or turn multi_tenant on"
        )
    mode = detect_mode(app)
    _warn_if_unrecognised(app)
    services = getattr(app.state, _PACKAGE, None)
    if services is not None:
        services.tenancy = mode
    host = getattr(getattr(app.state, "host", None), "settings", None)
    if getattr(host, "multi_tenant", False) is True and mode is TenancyMode.SINGLE:
        _log.warning(
            "pagebuilder: the host setting multi_tenant is on but the middleware stack has "
            "no TenantMiddleware, so pagebuilder runs single-tenant. Restart to apply it"
        )
    return mode


def tenant_vary(app: Any) -> tuple[str, ...]:
    """The request headers that pick a public response's tenant.

    ``SINGLE``: none. ``MULTI``: on the apex host the framework falls back to
    a member's session (``Cookie``) or the configured tenant header, so the
    same Host + URL answers with different tenants' content and a shared
    cache has to key on them too.
    """
    return () if mode_of(app) is TenancyMode.SINGLE else _multi_vary(app)


def _multi_vary(app: Any) -> tuple[str, ...]:
    """``Cookie``, plus the tenant header read straight off the entry's
    keywords — not through :func:`_kwargs`, whose ``None`` for an unknown
    keyword would drop the header and fail the cache key open."""
    kwargs = getattr(_tenant_middleware(app), "kwargs", None)
    header = kwargs.get("header") if isinstance(kwargs, Mapping) else None
    return ("Cookie", header) if header else ("Cookie",)


def request_vary(request: Any) -> tuple[str, ...]:
    """:func:`tenant_vary` for one request, following the resolvers (#192).

    A tenant upstream chose, or a request-level ``MULTI``, varies like
    ``MULTI`` even on an app detected ``SINGLE`` (a child mounted under a
    multi-tenant parent), plus whatever headers the framework recorded as
    having picked it (its public ``tenant_vary``).
    """
    app = request.app
    tenant = upstream_tenant(request)
    single = request_mode(request, mode_of(app)) is TenancyMode.SINGLE
    if single and tenant in (None, DEFAULT_TENANT):
        return ()
    recorded = recorded_vary(request)
    return tuple(dict.fromkeys(_multi_vary(app) + recorded))


def vary_on_tenant(response: Any, request: Any) -> Any:
    """Append :func:`request_vary` to *response*'s ``Vary``; a no-op for a
    single-tenant host serving its default tenant.

    An app detected ``SINGLE`` that serves another tenant has no cache key it
    can trust — the parent's resolver is invisible from here — so the
    response is also marked ``private``, out of every shared cache.
    """
    listed = [f.strip() for f in response.headers.get("vary", "").split(",") if f.strip()]
    seen = {f.lower() for f in listed}
    added = [f for f in request_vary(request) if f.lower() not in seen]
    if added:
        response.headers["Vary"] = ", ".join(listed + added)
    tenant = upstream_tenant(request)
    if mode_of(request.app) is TenancyMode.SINGLE and tenant not in (None, DEFAULT_TENANT):
        _make_private(response)
    return response


def _make_private(response: Any) -> None:
    kept = [
        d.strip()
        for d in response.headers.get("cache-control", "").split(",")
        if d.strip() and d.strip().split("=")[0].lower() not in ("public", "private", "s-maxage")
    ]
    response.headers["Cache-Control"] = ", ".join(["private", *kept])


def mode_of(app: Any) -> TenancyMode:
    """The stored mode, or a fresh detection before ``on_startup`` has run."""
    mode = getattr(getattr(app.state, _PACKAGE, None), "tenancy", None)
    return mode if isinstance(mode, TenancyMode) else detect_mode(app)


def resolve_admin(request: Any) -> str:
    """The admin surface's tenant; 403 ``tenant_required`` in MULTI mode
    when nothing upstream resolved one.

    A tenant already on the request always wins — the mode only fills a gap
    (#192), so a wrong ``SINGLE`` binds the parent's tenant, not the default.
    """
    tenant = upstream_tenant(request)
    if tenant is not None:
        return tenant
    if request_mode(request, mode_of(request.app)) is TenancyMode.SINGLE:
        return DEFAULT_TENANT
    raise HTTPException(status_code=403, detail=TENANT_REQUIRED)


def resolve_public(request: Any) -> str | None:
    """The anonymous surface's tenant, or ``None``. An upstream tenant wins
    over the mode, as in :func:`resolve_admin`."""
    tenant = upstream_tenant(request)
    if tenant is None and request_mode(request, mode_of(request.app)) is TenancyMode.SINGLE:
        return DEFAULT_TENANT
    return tenant


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


async def bind_public_viewer(request: Request) -> AsyncIterator[str | None]:
    """:func:`bind_public` for the page viewer: ``None`` instead of raising.

    The viewer answers a request that resolved no tenant with its own branded
    404 rather than the host's error page (#89) — rendered *without* a site
    layout, because there is no tenant to read one from, and never the
    default tenant's, which would brand another organisation's address with
    the default site. Nothing is bound in that case, so the endpoint must not
    query.
    """
    tenant = resolve_public(request)
    if tenant is None:
        yield None
        return
    with tenant_context(tenant):
        yield tenant
