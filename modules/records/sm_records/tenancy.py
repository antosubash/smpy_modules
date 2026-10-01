"""Which tenant a records statement runs in, and the refusal when there is none.

Design: ``docs/plans/2026-09-23-records-multitenancy.md`` §A. Every tenant-owned
records table carries the framework's ``MultiTenantMixin``, and the framework's
answer to "queried with no tenant set" is *every tenant's rows* (FACT 1b) while
a write with none is a ``NOT NULL`` failure (FACT 1a). So records binds a tenant
at each of its own entry points and never relies on one happening to be set.

**Mode** (§A.3) is read off the *built* middleware stack, not the setting: the
stack is built once at boot, so a later edit of ``multi_tenant`` does not
reach it until a restart.

* ``SINGLE`` (no ``TenantMiddleware``, or one ``fixed`` to :data:`DEFAULT_TENANT`)
  — everything runs in :data:`DEFAULT_TENANT`,
  whatever a user's ``tenant_id`` or a header says.
* ``MULTI`` — the admin surface runs in the *user's own* tenant and refuses a
  user with none (403 ``tenant_required``), even when a header named one —
  unless the operator turned ``admin_header_tenant`` on, which lets an
  ``admin`` act in the header's tenant; the public surface runs in the
  framework-resolved tenant and answers 404 without one. Neither ever falls
  back to :data:`DEFAULT_TENANT`.

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

from sm_records import constants
from sm_records._tenancy_mode import (
    DEFAULT_TENANT,
    TenancyMode,
    configure,
    detect_mode,
    mode_of,
    tenant_header,
)
from sm_records.services.errors import TenantRequired

__all__ = [
    "ADMIN_ROLE",
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
    "resolve_admin",
    "resolve_public",
    "tenant_header",
    "tenant_scope",
    "valid_tenant",
    "view_props",
]

ALL_TENANTS: Final = "records_all_tenants"
"""Execution option marking an **explicit** cross-tenant read — health, the CLI's
enumeration. Only lets a statement past the guard; with a tenant bound, the
framework's filter still applies."""

TENANT_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,49}$")
"""What a tenant id may be: at most 50 characters (the mixin's column width),
starting alphanumeric. A header failing it is *no tenant*, never a 500."""

ADMIN_ROLE: Final = "admin"
"""The role ``admin_header_tenant`` lets act in the header's tenant — the
framework's own wildcard role (``DEFAULT_ROLE_PERMISSIONS``)."""


class TenantUnbound(RuntimeError):  # noqa: N818 - the design's name for it
    """A records statement ran with no tenant bound. Always a bug, never a user
    error: the entry point that reached it forgot to bind one."""


def valid_tenant(value: object) -> bool:
    return isinstance(value, str) and TENANT_RE.match(value) is not None


# --- binding -----------------------------------------------------------------


@contextmanager
def tenant_scope(tenant_id: str) -> Iterator[str]:
    """Bind ``tenant_id`` for the block, and always unbind it.

    Re-entering the tenant already bound is a no-op (a router dependency inside
    a request the framework already bound). Binding a *different* one is
    refused with ``TenantIsolationError``: nothing in records moves between
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
        raise TenantUnbound("no tenant is bound for this records operation")
    return tenant


def _header_tenant_for(request: Any, user: Any) -> str | None:
    """The header's tenant for an ``admin`` with none of their own, when the
    operator opted in with ``admin_header_tenant``; otherwise ``None``.

    Off by default. For operators who administer several tenants from one
    account, and only for holders of the ``admin`` role. Records reads the
    header itself: since framework 0.0.35 (#358) ``TenantMiddleware`` resolves
    it for anonymous requests only, so ``request.state.tenant_id`` is ``None``
    for every signed-in user without a tenant.
    """
    services = getattr(request.app.state, constants.PACKAGE, None)
    if not getattr(getattr(services, "settings", None), "admin_header_tenant", False):
        return None
    if ADMIN_ROLE not in (getattr(user, "roles", None) or ()):
        return None
    header = getattr(services, "tenant_header", None)
    tenant = request.headers.get(header) if header else None
    return tenant if valid_tenant(tenant) else None


def resolve_admin(request: Any) -> str:
    """The admin surface's tenant (§A.3's table).

    Multi mode binds the **user's own** ``tenant_id``, never the header: the
    framework lets a tenant-less user pick any tenant by header (FACT 3-prime), and
    the legacy data sits in :data:`DEFAULT_TENANT`, so guessing would hand the
    bootstrap admin that tenant. The one exception is opt-in
    (:func:`_header_tenant_for`). No user at all is the framework's 401 — its
    ``AuthMiddleware`` answers first in production.
    """
    if mode_of(request.app) is TenancyMode.SINGLE:
        return DEFAULT_TENANT
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    tenant = getattr(user, "tenant_id", None)
    if valid_tenant(tenant):
        return tenant
    header = _header_tenant_for(request, user) if tenant is None else None
    if header is not None:
        return header
    raise TenantRequired(
        "this account has no tenant; an administrator has to assign one before "
        "it can use records on a multi-tenant host"
    )


def resolve_public(request: Any) -> str | None:
    """The anonymous surface's tenant, or ``None`` — which the caller answers
    with the same 404 an unknown type gets, so it is no oracle."""
    if mode_of(request.app) is TenancyMode.SINGLE:
        return DEFAULT_TENANT
    tenant = getattr(request.state, "tenant_id", None)
    return tenant if valid_tenant(tenant) else None


async def bind_admin(request: Request) -> AsyncIterator[str]:
    """Router dependency: the admin surface's tenant for the whole request.

    Must be **first** in a router's ``dependencies``: yield dependencies exit
    in reverse, and ``get_db``'s commit has to run while this is still bound or
    an unflushed ``add()`` reaches the database unbound (§A.4, FACT 2‴).
    """
    with tenant_scope(resolve_admin(request)) as tenant:
        yield tenant


async def bind_public(request: Request) -> AsyncIterator[str]:
    """Router dependency for the anonymous surface; 404 without a tenant."""
    tenant = resolve_public(request)
    if tenant is None:
        from sm_records.services.errors import NotFound
        from sm_records.services.public import NOT_FOUND

        raise NotFound(NOT_FOUND)
    with tenant_scope(tenant):
        yield tenant


def view_props(request: Any) -> dict[str, str]:
    """``tenant`` and ``tenancy_mode`` for every records screen: read-only, so
    the UI can say which tenant an admin is working in (§J). Called inside
    :func:`bind_admin`'s scope, so the tenant is the one the request runs in."""
    return {"tenant": bound_tenant(), "tenancy_mode": mode_of(request.app).value}


def all_tenants(stmt: Any) -> Any:
    """Tag ``stmt`` as a deliberate cross-tenant read, past :func:`install_guard`."""
    return stmt.execution_options(**{ALL_TENANTS: True})


def install_guard(sync_session_class: Any) -> None:
    """Refuse records ORM work with no tenant bound (§A.4, spike 1g). Idempotent."""
    from sm_records._tenant_guard import install

    install(sync_session_class)
