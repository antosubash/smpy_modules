"""Whether records runs single- or multi-tenant, read off the built stack.

Split out of :mod:`sm_records.tenancy`, which re-exports every name here.
Design: ``docs/plans/2026-09-23-records-multitenancy.md`` §A.3.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from enum import StrEnum
from typing import Any, Final

from simple_module_hosting.tenancy import single_tenant_id, tenancy_mode

from sm_records import constants

__all__ = [
    "DEFAULT_TENANT",
    "TenancyMode",
    "configure",
    "detect_mode",
    "mode_of",
    "mounted",
    "request_mode",
    "scope_mode",
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


def _opaque_middleware(app: Any) -> bool:
    """Whether the stack has an entry built by a factory rather than a class.

    ``Middleware(factory)`` hides what it installs — a ``TenantMiddleware``
    composed inside it is invisible to :func:`_tenant_middleware`.
    """
    return any(not isinstance(e.cls, type) for e in getattr(app, "user_middleware", None) or ())


def _framework_mode(app: Any) -> TenancyMode | None:
    """The framework's own public answer (``simple_module_hosting.tenancy``),
    or ``None`` without one.

    ``tenancy_mode`` says ``SINGLE`` for any app built outside ``create_app``,
    so its ``SINGLE`` is an answer only on an app ``create_app`` built — one
    carrying ``state.sm``. An app without it (a child mounted under a foreign
    parent, a bare test app) has no answer, and the stack reading decides.
    """
    if str(tenancy_mode(app)) == TenancyMode.MULTI:
        return TenancyMode.MULTI
    return TenancyMode.SINGLE if getattr(app.state, "sm", None) is not None else None


def mounted(scope: Mapping[str, Any]) -> bool:
    """Whether this request reached the app through a parent's ``Mount``.

    Starlette's ``Mount`` keeps the outermost ``root_path`` as
    ``app_root_path`` and extends ``root_path``; a proxy's ``--root-path``
    alone sets no ``app_root_path``.
    """
    outer = scope.get("app_root_path")
    return outer is not None and scope.get("root_path", "") != outer


def scope_mode(app: Any, scope: Mapping[str, Any], stored: TenancyMode) -> TenancyMode:
    """*stored* (the app's mode), unless it says ``SINGLE`` for a mounted app
    the framework has no answer for — the parent may well be multi-tenant and
    nothing visible from here says otherwise, so that is ``MULTI`` (#210, the
    rule news and pagebuilder follow since #192)."""
    ambiguous = mounted(scope) and _framework_mode(app) is None
    return TenancyMode.MULTI if stored is TenancyMode.SINGLE and ambiguous else stored


def request_mode(request: Any, stored: TenancyMode) -> TenancyMode:
    """:func:`scope_mode` for a ``Request``."""
    return scope_mode(request.app, getattr(request, "scope", None) or {}, stored)


def pinned_tenants(app: Any) -> dict[str, str]:
    """Every tenant the host pins its requests to, keyed by where the pin is.

    Both sources count (#212): a ``create_app`` host's public
    ``single_tenant_id`` (its ``default_tenant``, else ``"default"``) under
    ``"default_tenant"``, and an explicit ``TenantMiddleware(fixed=...)`` under
    ``"fixed"``. Requests follow the middleware and background work the
    framework's answer, so ``configure`` refuses any pin other than
    ``DEFAULT_TENANT`` — and with it two that disagree — rather than let the
    two drift apart.
    """
    pins = (
        {"default_tenant": single_tenant_id(app)}
        if _framework_mode(app) is TenancyMode.SINGLE
        else {}
    )
    fixed = _fixed_tenant(_tenant_middleware(app))
    if fixed is not None:
        pins["fixed"] = fixed
    return pins


_PIN_SHOWN: Final = {
    "default_tenant": "default_tenant={!r}",
    "fixed": "TenantMiddleware(fixed={!r})",
}


def stray_pins(app: Any) -> str | None:
    """The host's pins to a tenant other than ``DEFAULT_TENANT``, each named
    by where it is set, or ``None`` when there are none."""
    stray = [
        _PIN_SHOWN[source].format(tenant)
        for source, tenant in pinned_tenants(app).items()
        if tenant != DEFAULT_TENANT
    ]
    return " and ".join(stray) or None


def detect_mode(app: Any) -> TenancyMode:
    """``MULTI`` iff ``TenantMiddleware`` is in the stack and resolves tenants
    per request; a ``fixed`` one is a single-tenant host.

    Fails safe (#125): an entry whose arguments are not recognised counts as
    ``MULTI`` — reads stay filtered, and a fixed middleware still puts its one
    tenant on ``request.state``, which is all ``MULTI`` resolution reads — as
    does the framework's own ``tenancy_mode`` saying ``MULTI``, and a stack
    with a factory-built entry the framework has no answer for (#210).
    """
    entry = _tenant_middleware(app)
    framework = _framework_mode(app)
    if framework is TenancyMode.MULTI:
        return TenancyMode.MULTI
    if entry is not None:
        if _kwargs(entry) is None:
            return TenancyMode.MULTI
        return TenancyMode.SINGLE if _fixed_tenant(entry) else TenancyMode.MULTI
    if framework is None and _opaque_middleware(app):
        return TenancyMode.MULTI
    return TenancyMode.SINGLE


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
    # Straight off the keywords, not through ``_kwargs``: its ``None`` for an
    # unknown keyword would drop the header and fail the cache key open.
    kwargs = getattr(_tenant_middleware(app), "kwargs", None)
    header = kwargs.get("header") if isinstance(kwargs, Mapping) else None
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
    stray = stray_pins(app)
    if stray is not None:
        raise RuntimeError(
            f"records: the host pins every request to {stray}, but records "
            f"runs a single-tenant host in {DEFAULT_TENANT!r}. Unset default_tenant and any "
            f"TenantMiddleware(fixed=...), set them "
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
