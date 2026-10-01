"""Whether records runs single- or multi-tenant, read off the built stack.

Split out of :mod:`sm_records.tenancy`, which re-exports every name here.
Design: ``docs/plans/2026-09-23-records-multitenancy.md`` §A.3.
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import Any, Final

from sm_records import constants

__all__ = [
    "DEFAULT_TENANT",
    "TenancyMode",
    "configure",
    "detect_mode",
    "mode_of",
    "tenant_header",
]

logger = logging.getLogger("sm_records.tenancy")

DEFAULT_TENANT: Final = "default"
"""The tenant of a single-tenant host, and of every row that predates tenancy.

A constant, not a setting: the ``tenant_id`` migration backfills this literal,
so a setting that could drift from it would strand the legacy data (§A.3)."""


class TenancyMode(StrEnum):
    SINGLE = "single"
    MULTI = "multi"


def _tenant_middleware(app: Any) -> Any:
    """The ``TenantMiddleware`` entry of the built stack, or ``None``."""
    from simple_module_hosting.middleware import TenantMiddleware

    entries = getattr(app, "user_middleware", ())
    return next((e for e in entries if getattr(e, "cls", None) is TenantMiddleware), None)


def _fixed_tenant(entry: Any) -> str | None:
    """The tenant a single-tenant host pins every request to, or ``None``.

    Framework 0.0.35 (#359) installs ``TenantMiddleware(fixed=default_tenant)``
    on a host that sets ``default_tenant`` without ``multi_tenant``: the
    middleware is in the stack, but there is only ever one tenant.
    """
    return (getattr(entry, "kwargs", None) or {}).get("fixed") if entry else None


def detect_mode(app: Any) -> TenancyMode:
    """``MULTI`` iff the framework's ``TenantMiddleware`` is in the built stack
    and resolves tenants per request; a ``fixed`` one is a single-tenant host."""
    entry = _tenant_middleware(app)
    return TenancyMode.SINGLE if entry is None or _fixed_tenant(entry) else TenancyMode.MULTI


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

    One direction only: ``multi_tenant`` is on but the stack has no
    ``TenantMiddleware``, which since framework 0.0.35 means the setting
    changed after the process started (the stack is built once, at boot).

    A host pinned to a ``default_tenant`` other than :data:`DEFAULT_TENANT`
    is refused here: records' single mode, its sidebar sync and its CLI all
    run in :data:`DEFAULT_TENANT`, where the migration put existing rows, so
    the framework would bind one tenant and records another.
    """
    fixed = _fixed_tenant(_tenant_middleware(app))
    if fixed is not None and fixed != DEFAULT_TENANT:
        raise RuntimeError(
            f"records: the host pins every request to default_tenant={fixed!r}, but records "
            f"runs a single-tenant host in {DEFAULT_TENANT!r}. Unset default_tenant, set it "
            f"to {DEFAULT_TENANT!r}, or turn multi_tenant on"
        )
    mode = detect_mode(app)
    services = getattr(app.state, constants.PACKAGE, None)
    if services is not None:
        services.tenancy = mode
        services.tenant_header = tenant_header(app)
    host = getattr(getattr(app.state, "host", None), "settings", None)
    if getattr(host, "multi_tenant", False) is True and mode is TenancyMode.SINGLE:
        logger.warning(
            "records: the host setting multi_tenant is on but the middleware stack has no "
            "TenantMiddleware, so records runs single-tenant. The stack is built once, when "
            "the process starts: restart it to apply the setting"
        )
    return mode


def mode_of(app: Any) -> TenancyMode:
    """The stored mode, or a fresh detection before ``on_startup`` has run."""
    services = getattr(app.state, constants.PACKAGE, None)
    mode = getattr(services, "tenancy", None)
    return mode if isinstance(mode, TenancyMode) else detect_mode(app)
