"""Binding a tenant for a cross-module read, without ever replacing one."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from simple_module_db import current_tenant_id, is_valid_tenant_id, tenant_context
from simple_module_db.listeners import TenantIsolationError

__all__ = ["TenantIsolationError", "tenant_scope"]


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
