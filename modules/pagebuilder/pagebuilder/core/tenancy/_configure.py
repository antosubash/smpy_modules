"""Detecting the tenancy mode once at boot, and refusing a host it cannot serve.

Split from :mod:`pagebuilder.core.tenancy` (#335) so that module stays under the
line cap; re-exported there, where every caller imports it from.
"""

from __future__ import annotations

import logging
from typing import Any

from pagebuilder.core.tenancy._mode import (
    _PACKAGE,
    DEFAULT_TENANT,
    TenancyMode,
    _warn_if_unrecognised,
    detect_mode,
    stray_pins,
)

__all__ = ["configure"]

_log = logging.getLogger("simple_module.pagebuilder")


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
