"""Which tenant a records statement runs in, and the refusal when there is none.

Design: ``docs/plans/2026-09-23-records-multitenancy.md`` §A. Every tenant-owned
records table carries the framework's ``MultiTenantMixin``, and the framework's
answer to "queried with no tenant set" is *every tenant's rows* (FACT 1b) while
a write with none is a ``NOT NULL`` failure (FACT 1a). So records binds a tenant
at each of its own entry points and never relies on one happening to be set.

**Mode** (§A.3) is read off the *built* middleware stack, not the setting: in
framework 0.0.26 a DB edit of ``multi_tenant`` does not rebuild the stack.

* ``SINGLE`` (no ``TenantMiddleware``) — everything runs in :data:`DEFAULT_TENANT`,
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

import logging
import re
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from enum import StrEnum
from typing import Any, Final

from fastapi import HTTPException, Request
from simple_module_db.listeners import TenantIsolationError, current_tenant_id

from sm_records import constants
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

logger = logging.getLogger(__name__)

DEFAULT_TENANT: Final = "default"
"""The tenant of a single-tenant host, and of every row that predates tenancy.

A constant, not a setting: the ``tenant_id`` migration backfills this literal,
so a setting that could drift from it would strand the legacy data (§A.3)."""

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


class TenancyMode(StrEnum):
    SINGLE = "single"
    MULTI = "multi"


class TenantUnbound(RuntimeError):  # noqa: N818 - the design's name for it
    """A records statement ran with no tenant bound. Always a bug, never a user
    error: the entry point that reached it forgot to bind one."""


def valid_tenant(value: object) -> bool:
    return isinstance(value, str) and TENANT_RE.match(value) is not None


# --- mode --------------------------------------------------------------------


def _tenant_middleware(app: Any) -> Any:
    """The ``TenantMiddleware`` entry of the built stack, or ``None``."""
    from simple_module_hosting.middleware import TenantMiddleware

    entries = getattr(app, "user_middleware", ())
    return next((e for e in entries if getattr(e, "cls", None) is TenantMiddleware), None)


def detect_mode(app: Any) -> TenancyMode:
    """``MULTI`` iff the framework's ``TenantMiddleware`` is in the built stack."""
    return TenancyMode.SINGLE if _tenant_middleware(app) is None else TenancyMode.MULTI


def tenant_header(app: Any) -> str | None:
    """The header that middleware resolves a tenant from — its own ``header``
    argument, as the host passed it — or ``None`` (single mode, or no header)."""
    entry = _tenant_middleware(app)
    header = (getattr(entry, "kwargs", None) or {}).get("header") if entry else None
    return header or None


def configure(app: Any) -> TenancyMode:
    """Detect the mode once, store it on the services container, and warn when
    the host's setting asked for tenancy the stack does not have. Called from
    ``RecordsModule.on_startup``.

    One direction only: ``multi_tenant`` is on in the database and the stack
    has no ``TenantMiddleware``. That is the 0.0.26 behaviour of an edit made
    in the admin UI — the setting changed, the stack did not, and records
    follows the stack because the stack is what resolves tenants. The other
    direction is every host that sets ``SM_MULTI_TENANT`` in the environment:
    ``HostSettings`` reads no environment variable, so its ``multi_tenant`` is
    ``False`` there on every boot (framework gap L14), and warning about it
    would be noise.
    """
    mode = detect_mode(app)
    services = getattr(app.state, constants.PACKAGE, None)
    if services is not None:
        services.tenancy = mode
        services.tenant_header = tenant_header(app)
    host = getattr(getattr(app.state, "host", None), "settings", None)
    if getattr(host, "multi_tenant", False) is True and mode is TenancyMode.SINGLE:
        logger.warning(
            "records: the host setting multi_tenant is on but the middleware stack has no "
            "TenantMiddleware, so records runs single-tenant. The stack is built once, from "
            "SM_MULTI_TENANT, when the process starts"
        )
    return mode


def mode_of(app: Any) -> TenancyMode:
    """The stored mode, or a fresh detection before ``on_startup`` has run."""
    services = getattr(app.state, constants.PACKAGE, None)
    mode = getattr(services, "tenancy", None)
    return mode if isinstance(mode, TenancyMode) else detect_mode(app)


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
    token = current_tenant_id.set(tenant_id)
    try:
        yield tenant_id
    finally:
        current_tenant_id.reset(token)


def bound_tenant() -> str:
    """The tenant this code runs in; :class:`TenantUnbound` if there is none."""
    tenant = current_tenant_id.get()
    if tenant is None:
        raise TenantUnbound("no tenant is bound for this records operation")
    return tenant


def _header_tenant_for(request: Any, user: Any) -> str | None:
    """The header's tenant for an ``admin`` with none of their own, when the
    operator opted in with ``admin_header_tenant``; otherwise ``None``.

    Off by default because it is FACT 3-prime on purpose: the framework already
    resolved ``request.state.tenant_id`` from the header for this user, and
    this lets records honour it — for operators who administer several
    tenants from one account, and only for holders of the ``admin`` role.
    """
    services = getattr(request.app.state, constants.PACKAGE, None)
    if not getattr(getattr(services, "settings", None), "admin_header_tenant", False):
        return None
    if ADMIN_ROLE not in (getattr(user, "roles", None) or ()):
        return None
    tenant = getattr(request.state, "tenant_id", None)
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
