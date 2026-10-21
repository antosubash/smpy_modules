"""Whether records runs single- or multi-tenant, read off the built stack.

Split out of :mod:`sm_records.tenancy`, which re-exports every name here.
Design: ``docs/plans/2026-09-23-records-multitenancy.md`` §A.3.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
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

_PACKAGE: Final = "records"
"""The prefix of this file's messages."""

DEFAULT_TENANT: Final = "default"
"""The tenant of a single-tenant host, and of every row that predates tenancy.

A constant, not a setting: the ``tenant_id`` migration backfills this literal,
so a setting that could drift from it would strand the legacy data (§A.3)."""


class TenancyMode(StrEnum):
    SINGLE = "single"
    MULTI = "multi"


_KNOWN_KWARGS: Final = frozenset({"fixed", "header"})
"""The ``TenantMiddleware`` keywords read here. Both are framework internals
(#125); ``tests/test_framework_pins.py`` fails when either stops existing."""

_UNREADABLE: Final = (
    "{pkg}: cannot read the app's middleware stack (app.user_middleware, or "
    "its entries' .cls, is gone), so it cannot tell a single-tenant host from "
    "a multi-tenant one. Refusing to guess: a wrong 'single' leaves every "
    "read unfiltered (#125)"
)


def _tenant_middleware(app: Any) -> Any:
    """The ``TenantMiddleware`` entry of the built stack, or ``None``.

    Raises on a real Starlette app whose stack has no readable shape: finding
    no entry would read as ``SINGLE``, and ``SINGLE`` reads are unfiltered. A
    test double without a stack is simply single-tenant.
    """
    from simple_module_hosting.middleware import TenantMiddleware
    from starlette.applications import Starlette

    entries = getattr(app, "user_middleware", None)
    if entries is None or any(not hasattr(e, "cls") for e in entries):
        if isinstance(app, Starlette):
            raise RuntimeError(_UNREADABLE.format(pkg=_PACKAGE))
        return None
    return next(
        (e for e in entries if isinstance(e.cls, type) and issubclass(e.cls, TenantMiddleware)),
        None,
    )


def _kwargs(entry: Any) -> dict[str, Any] | None:
    """*entry*'s keywords, or ``None`` when their shape is not one read here
    (positional arguments, or a keyword outside :data:`_KNOWN_KWARGS`)."""
    kwargs = getattr(entry, "kwargs", None)
    if not isinstance(kwargs, Mapping) or getattr(entry, "args", ()):
        return None
    return dict(kwargs) if set(kwargs) <= _KNOWN_KWARGS else None


def _fixed_tenant(entry: Any) -> str | None:
    """The tenant a single-tenant host pins every request to, or ``None``.

    Framework 0.0.35 (#359) installs ``TenantMiddleware(fixed=default_tenant)``
    on a host that sets ``default_tenant`` without ``multi_tenant``: the
    middleware is in the stack, but there is only ever one tenant.
    """
    return (_kwargs(entry) or {}).get("fixed") if entry else None


def _framework_says_multi(app: Any) -> bool:
    """Whether the framework's own public answer (0.0.36+) is ``MULTI``.

    It says ``SINGLE`` for any app built outside ``create_app``, so only its
    ``MULTI`` is evidence; on 0.0.35, which lacks it, there is none.
    """
    try:
        from simple_module_hosting.tenancy import tenancy_mode
    except ImportError:
        return False
    return str(tenancy_mode(app)) == TenancyMode.MULTI


def detect_mode(app: Any) -> TenancyMode:
    """``MULTI`` iff ``TenantMiddleware`` is in the stack and resolves tenants
    per request; a ``fixed`` one is a single-tenant host.

    Fails safe (#125): an entry whose arguments are not recognised counts as
    ``MULTI`` — reads stay filtered, and a fixed middleware still puts its one
    tenant on ``request.state``, which is all ``MULTI`` resolution reads — as
    does the framework's own ``tenancy_mode`` saying ``MULTI``.
    """
    entry = _tenant_middleware(app)
    if _framework_says_multi(app):
        return TenancyMode.MULTI
    if entry is None:
        return TenancyMode.SINGLE
    if _kwargs(entry) is None:
        return TenancyMode.MULTI
    return TenancyMode.SINGLE if _fixed_tenant(entry) else TenancyMode.MULTI


def _warn_if_unrecognised(app: Any) -> None:
    entry = _tenant_middleware(app)
    if entry is not None and _kwargs(entry) is None:
        logger.warning(
            "%s: TenantMiddleware was installed with arguments this version does not "
            "recognise (args=%r, kwargs=%r); running multi-tenant so reads stay filtered",
            _PACKAGE,
            getattr(entry, "args", None),
            getattr(entry, "kwargs", None),
        )


def tenant_header(app: Any) -> str | None:
    """The header that middleware resolves a tenant from — its own ``header``
    argument, as the host passed it — or ``None`` (single mode, or no header)."""
    entry = _tenant_middleware(app)
    header = (_kwargs(entry) or {}).get("header") if entry else None
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
    _warn_if_unrecognised(app)
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
