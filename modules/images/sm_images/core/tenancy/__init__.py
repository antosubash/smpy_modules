"""Which tenant an images statement runs in, and the refusal when there is none.

A copy of ``sm_records.tenancy`` (records' tenancy plan, §A), with images' own
errors. Every tenant-owned images table carries the framework's
``MultiTenantMixin``, and the framework's answer to "queried with no tenant
set" is *every tenant's rows* (FACT 1b) while a write with none is a ``NOT NULL``
failure (FACT 1a). So images binds a tenant at each of its own entry points and
never relies on one happening to be set.

**Mode** (§A.3) is read off the *built* middleware stack, not the setting: the
stack is built once at boot, so a later edit of ``multi_tenant`` does not
reach it until a restart.

* ``SINGLE`` (no ``TenantMiddleware``, or one ``fixed`` to :data:`DEFAULT_TENANT`)
  — everything runs in :data:`DEFAULT_TENANT`, whatever a user's
  ``tenant_id`` or a header says — *unless something upstream already
  resolved a tenant for the request*, which always wins: the mode only fills
  a gap, so a wrong ``SINGLE`` detection fails closed rather than binding
  every request to the default.
* ``MULTI`` — every entry point runs in the tenant the framework resolved
  (``request.state.tenant_id``: subdomain for visitors, membership for
  members), the rule pagebuilder, news and billing follow too (#112). The
  admin surface refuses a signed-in request with none (403
  ``tenant_required``, pagebuilder's status and code); the public surface
  answers it with the same 404 an unknown type gets. Neither ever falls back
  to :data:`DEFAULT_TENANT`.

**Binding rules.** :func:`tenant_scope` is the only way this module sets the
contextvar: it always resets (a bare ``set()`` in awaited code leaks into the
caller's task, FACT 1f), and it refuses to re-bind to a *different* tenant, so
a loop over tenants has to open a fresh session per tenant — ``session.get()``
returns an object already in the identity map without applying any filter
(FACT 1e), and one session serving two tenants is how that becomes a leak.

The guard (:func:`install_guard`) is what makes "bound" an invariant. It sees
ORM statements only: Core statements over ``__table__``, ``text()`` and DML
still need the explicit ``tenant_id`` predicate of §E.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from typing import Any, Final

from fastapi import HTTPException, Request
from simple_module_db import tenant_context
from simple_module_db.listeners import TenantIsolationError, current_tenant_id

from sm_images.core.constants import NOT_FOUND_DETAIL
from sm_images.core.errors import TenantRequired
from sm_images.core.tenancy._mode import (
    DEFAULT_TENANT,
    TenancyMode,
    configure,
    detect_mode,
    mode_of,
    request_mode,
    tenant_header,
)

__all__ = [
    "ALL_TENANTS",
    "DEFAULT_TENANT",
    "TENANT_RE",
    "TenancyMode",
    "TenantRequired",
    "TenantUnbound",
    "all_tenants",
    "bind_admin",
    "bind_public",
    "bound_tenant",
    "configure",
    "detect_mode",
    "install_guard",
    "mode_of",
    "note_tenant_source",
    "resolve_admin",
    "resolve_public",
    "tenant_from_request",
    "tenant_header",
    "tenant_scope",
    "valid_tenant",
    "view_props",
]

ALL_TENANTS: Final = "images_all_tenants"
"""Execution option marking an **explicit** cross-tenant read — health, the CLI's
enumeration. Only lets a statement past the guard; with a tenant bound, the
framework's filter still applies."""

TENANT_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,49}$")
"""What a tenant id may be: at most 50 characters (the mixin's column width),
starting alphanumeric. A header failing it is *no tenant*, never a 500."""


class TenantUnbound(RuntimeError):  # noqa: N818 - the design's name for it
    """An images statement ran with no tenant bound. Always a bug, never a user
    error: the entry point that reached it forgot to bind one."""


def valid_tenant(value: object) -> bool:
    return isinstance(value, str) and TENANT_RE.match(value) is not None


# --- binding -----------------------------------------------------------------


@contextmanager
def tenant_scope(tenant_id: str) -> Iterator[str]:
    """Bind ``tenant_id`` for the block, and always unbind it.

    Re-entering the tenant already bound is a no-op (a router dependency inside
    a request the framework already bound). Binding a *different* one is
    refused with ``TenantIsolationError``: nothing in images moves between
    tenants mid-scope, and a caller that needs a second tenant opens a second
    scope, and a second session, after this one closes.
    """
    if not valid_tenant(tenant_id):
        raise ValueError(f"not a valid tenant id: {tenant_id!r}")
    current = current_tenant_id.get()
    if current is not None and current != tenant_id:
        raise TenantIsolationError(
            f"cannot bind tenant {tenant_id!r} inside a scope bound to {current!r}"
        )
    # The framework's binding, not a bare ``set()``: it also lifts an enclosing
    # ``all_tenants()`` waiver, so strict isolation applies inside the scope.
    with tenant_context(tenant_id):
        yield tenant_id


def bound_tenant() -> str:
    """The tenant this code runs in; :class:`TenantUnbound` if there is none."""
    tenant = current_tenant_id.get()
    if tenant is None:
        raise TenantUnbound("no tenant is bound for this images operation")
    return tenant


def _resolved(request: Any) -> str | None:
    """The tenant something upstream already chose for this request, or ``None``.

    ``request.state.tenant_id`` (``TenantMiddleware``'s answer), else the
    framework's tenant contextvar if an enclosing layer bound one. Both
    resolvers consult this *before* the mode, so the mode only ever fills a
    gap: a mode detection that wrongly says ``SINGLE`` (a mounted child app, a
    composed middleware stack — see #125/#192) still binds the tenant the
    parent resolved instead of handing every request :data:`DEFAULT_TENANT`.
    """
    tenant = getattr(request.state, "tenant_id", None)
    if valid_tenant(tenant):
        return tenant
    bound = current_tenant_id.get()
    return bound if valid_tenant(bound) else None


def resolve_admin(request: Any) -> str:
    """The admin surface's tenant (§A.3's table, as revised by #112).

    Multi mode binds the tenant the framework resolved — the member's active
    organisation, not ``user.tenant_id`` — so images edits the same tenant as
    the member's pages and news. The framework never lets a signed-in user pick
    a tenant they are not a member of by header (``TenantMiddleware`` reads it
    raw for anonymous requests only, since 0.0.35; the tenants module honours
    it only among the user's active memberships), so following its answer
    hands a tenant-less user nothing: they resolve no tenant and get
    :class:`TenantRequired`. No user at all is a 401 in multi mode — the
    framework's ``AuthMiddleware`` answers first in
    production, and an anonymous request's header tenant never reaches the
    admin surface.
    """
    single = mode_of(request.app) is TenancyMode.SINGLE
    if not single and getattr(request.state, "user", None) is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    tenant = _resolved(request)
    if tenant is None and request_mode(request, mode_of(request.app)) is TenancyMode.SINGLE:
        return DEFAULT_TENANT
    if tenant is None:
        raise TenantRequired(
            "no organisation is active for this account; pick one (or have an "
            "administrator assign one) before using images on a multi-tenant host"
        )
    return tenant


def resolve_public(request: Any) -> str | None:
    """The anonymous surface's tenant, or ``None`` — which the caller answers
    with the same 404 an unknown type gets, so it is no oracle. An upstream
    tenant wins over the mode, as in :func:`resolve_admin`."""
    tenant = _resolved(request)
    if tenant is None and request_mode(request, mode_of(request.app)) is TenancyMode.SINGLE:
        return DEFAULT_TENANT
    return tenant


async def bind_admin(request: Request) -> AsyncIterator[str]:
    """Router dependency: the admin surface's tenant for the whole request.

    Must be **first** in a router's ``dependencies``: yield dependencies exit
    in reverse, and ``get_db``'s commit has to run while this is still bound or
    an unflushed ``add()`` reaches the database unbound (§A.4, FACT 2‴).
    """
    with tenant_scope(resolve_admin(request)) as tenant:
        yield tenant


_UPSTREAM_ATTR: Final = "images_tenant_from_request"


def note_tenant_source(request: Any) -> None:
    """Record whether something request-specific chose this request's tenant.

    Called by :func:`bind_public` *before* its fallback: once the scope is
    bound, the tenant contextvar holds :data:`DEFAULT_TENANT` either way and
    the two cases look alike. Both sources :func:`_resolved` accepts count -
    ``request.state.tenant_id`` (a subdomain, a header, a parent app) and a
    tenant an enclosing layer already bound in the contextvar - and either is
    request-specific even when its value is ``default``: the rule of records
    #196 is about *who* chose, not what.
    """
    upstream = (
        getattr(request.state, "tenant_id", None) is not None or current_tenant_id.get() is not None
    )
    setattr(request.state, _UPSTREAM_ATTR, upstream)


def tenant_from_request(request: Any) -> bool:
    """What :func:`note_tenant_source` recorded; ``True`` (fail closed) if it
    never ran for this request."""
    return getattr(request.state, _UPSTREAM_ATTR, True) is not False


async def bind_public(request: Request) -> AsyncIterator[str]:
    """Router dependency for the anonymous surface; 404 without a tenant."""
    note_tenant_source(request)
    tenant = resolve_public(request)
    if tenant is None:
        from sm_images.core.errors import NotFound

        raise NotFound(NOT_FOUND_DETAIL)
    with tenant_scope(tenant):
        yield tenant


def view_props(request: Any) -> dict[str, str]:
    """``tenant`` and ``tenancy_mode`` for every images screen: read-only, so
    the UI can say which tenant an admin is working in (§J). Called inside
    :func:`bind_admin`'s scope, so the tenant is the one the request runs in."""
    mode = request_mode(request, mode_of(request.app))
    return {"tenant": bound_tenant(), "tenancy_mode": mode.value}


def all_tenants(stmt: Any) -> Any:
    """Tag ``stmt`` as a deliberate cross-tenant read, past :func:`install_guard`."""
    return stmt.execution_options(**{ALL_TENANTS: True})


def install_guard(sync_session_class: Any) -> None:
    """Refuse images ORM work with no tenant bound (§A.4, spike 1g). Idempotent."""
    from sm_images.core.tenancy._guard import install

    install(sync_session_class)
