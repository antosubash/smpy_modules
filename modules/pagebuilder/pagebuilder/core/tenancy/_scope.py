"""Binding a tenant outside a request, without ever replacing one, and the guard
that makes "bound" an invariant (#335).

:func:`install_guard` puts the fail-closed guard of records, images and
newsletter (:mod:`pagebuilder.core.tenancy._guard`, the same file) on the
host's session class: an ORM statement or flush on a pagebuilder table with no
tenant bound raises :class:`TenantUnbound` instead of reading or writing every
tenant's rows. A deliberate cross-tenant read — the scheduler's tenant
enumeration, the boot-time media scan — is tagged with :func:`all_tenants`.
The guard sees ORM statements only: a Core statement over ``__table__`` or
``text()`` still needs its own ``tenant_id`` predicate.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Final

from simple_module_db import current_tenant_id, is_valid_tenant_id, tenant_context
from simple_module_db.listeners import TenantIsolationError

__all__ = [
    "ALL_TENANTS",
    "TenantIsolationError",
    "TenantUnbound",
    "all_tenants",
    "install_guard",
    "tenant_scope",
]

ALL_TENANTS: Final = "pagebuilder_all_tenants"
"""Execution option marking an **explicit** cross-tenant read. Only lets a
statement past the guard; with a tenant bound, the framework's filter still
applies."""


class TenantUnbound(RuntimeError):  # noqa: N818 - records' name for it
    """A pagebuilder statement ran with no tenant bound. Always a bug, never a user
    error: the entry point that reached it forgot to bind one."""


@contextmanager
def tenant_scope(tenant_id: str) -> Iterator[str]:
    """Bind ``tenant_id`` for the block, and always unbind it.

    Same rule as records' ``tenant_scope``: re-entering the tenant already
    bound is a no-op, and naming a *different* one raises
    :class:`TenantIsolationError` — the framework's bare ``tenant_context``
    would silently replace the binding. An invalid id raises ``ValueError``.
    """
    if not is_valid_tenant_id(tenant_id):
        raise ValueError(f"not a valid tenant id: {tenant_id!r}")
    current = current_tenant_id.get()
    if current is not None and current != tenant_id:
        raise TenantIsolationError(
            f"cannot bind tenant {tenant_id!r} inside a scope bound to {current!r}"
        )
    with tenant_context(tenant_id):
        yield tenant_id


def all_tenants(stmt: Any) -> Any:
    """Tag ``stmt`` as a deliberate cross-tenant read, past :func:`install_guard`."""
    return stmt.execution_options(**{ALL_TENANTS: True})


def install_guard(sync_session_class: Any) -> None:
    """Refuse pagebuilder ORM work with no tenant bound. Idempotent."""
    from pagebuilder.core.tenancy._guard import install

    install(sync_session_class)
