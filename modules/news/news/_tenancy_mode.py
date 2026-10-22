"""Whether a news host is single- or multi-tenant, and which tenant a request
already carries (#125, #192).

Split out of :mod:`news.tenancy`, which re-exports what callers use.

**Mode** is read off the *built* middleware stack: the stack is built once at
boot, so a later edit of ``multi_tenant`` does not reach it until a restart.
Every reading fails safe — a stack it cannot see into is ``MULTI``, never
``SINGLE``, because ``SINGLE`` binds :data:`DEFAULT_TENANT` and an unfiltered
read in the wrong tenant is a leak.

**Request time.** The mode only fills a gap: a tenant something upstream
already resolved for the request (``request.state.tenant_id``, or the
framework's tenant contextvar) always wins, so a wrong ``SINGLE`` — a child
app mounted under a multi-tenant parent, which has neither the parent's
``TenantMiddleware`` nor its ``state.sm`` — still binds the parent's tenant.
A mounted app with no framework answer of its own and no upstream tenant is
treated as ``MULTI`` and refused, rather than handed the default.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from enum import StrEnum
from typing import Any, Final

from simple_module_db import current_tenant_id, is_valid_tenant_id
from simple_module_hosting.tenancy import single_tenant_id, tenancy_mode

_log = logging.getLogger("simple_module.news")

_PACKAGE = "news"

DEFAULT_TENANT: Final = "default"
"""The tenant of a single-tenant host, and of every row that predates tenancy.

A constant, not a setting: the ``tenant_id`` migration backfills this literal,
and records uses the same one, so one host has one notion of it."""


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


def _opaque_middleware(app: Any) -> bool:
    """Whether the stack has an entry built by a factory rather than a class.

    ``Middleware(factory)`` hides what it installs — a ``TenantMiddleware``
    composed inside it is invisible to :func:`_tenant_middleware`.
    """
    return any(not isinstance(e.cls, type) for e in getattr(app, "user_middleware", None) or ())


def _kwargs(entry: Any) -> dict[str, Any] | None:
    """*entry*'s keywords, or ``None`` when their shape is not one read here
    (positional arguments, or a keyword outside :data:`_KNOWN_KWARGS`)."""
    kwargs = getattr(entry, "kwargs", None)
    if not isinstance(kwargs, Mapping) or getattr(entry, "args", ()):
        return None
    return dict(kwargs) if set(kwargs) <= _KNOWN_KWARGS else None


def _fixed_tenant(entry: Any) -> str | None:
    """The tenant a single-tenant host pins every request to, or ``None``."""
    return (_kwargs(entry) or {}).get("fixed") if entry else None


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
    with a factory-built entry the framework has no answer for.
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
        _log.warning(
            "%s: TenantMiddleware was installed with arguments this version does not "
            "recognise (args=%r, kwargs=%r); running multi-tenant so reads stay filtered",
            _PACKAGE,
            getattr(entry, "args", None),
            getattr(entry, "kwargs", None),
        )


def upstream_tenant(request: Any) -> str | None:
    """The tenant something upstream already chose for this request, or ``None``.

    ``request.state.tenant_id`` (``TenantMiddleware``'s answer, or a parent
    app's), else the framework's tenant contextvar if an enclosing layer bound
    one. Both resolvers consult this *before* the mode.
    """
    tenant = getattr(request.state, "tenant_id", None)
    if is_valid_tenant_id(tenant):
        return tenant
    bound = current_tenant_id.get()
    return bound if is_valid_tenant_id(bound) else None


def mounted(scope: Mapping[str, Any], own_prefix: str = "") -> bool:
    """Whether this request reached the app through a parent's ``Mount``.

    Starlette's ``Mount`` keeps the outermost ``root_path`` as
    ``app_root_path`` and extends ``root_path``; a proxy's ``--root-path``
    alone sets no ``app_root_path``. *own_prefix* is a mount the app itself
    made (pagebuilder's media), which does not count.
    """
    outer = scope.get("app_root_path")
    if outer is None:
        return False
    return scope.get("root_path", "") != outer + own_prefix.rstrip("/")


def scope_mode(
    app: Any, scope: Mapping[str, Any], stored: TenancyMode, own_prefix: str = ""
) -> TenancyMode:
    """*stored* (the app's mode), unless it says ``SINGLE`` for a mounted app
    the framework has no answer for — the parent may well be multi-tenant,
    and nothing visible from here says otherwise, so that is ``MULTI``."""
    ambiguous = mounted(scope, own_prefix) and _framework_mode(app) is None
    return TenancyMode.MULTI if stored is TenancyMode.SINGLE and ambiguous else stored


def request_mode(request: Any, stored: TenancyMode) -> TenancyMode:
    """:func:`scope_mode` for a ``Request``."""
    return scope_mode(request.app, getattr(request, "scope", None) or {}, stored)
