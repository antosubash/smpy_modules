"""Detecting the tenancy mode once at boot, and refusing a host it cannot serve.

Split from :mod:`news.core.tenancy` (#335) so that module stays under the
line cap; re-exported there, where every caller imports it from.
"""

from __future__ import annotations

import logging
from typing import Any

from news.core.tenancy._mode import (
    _PACKAGE,
    DEFAULT_TENANT,
    TenancyMode,
    _warn_if_unrecognised,
    detect_mode,
    stray_pins,
)

__all__ = ["configure"]

_log = logging.getLogger("simple_module.news")


def configure(app: Any) -> TenancyMode:
    """Detect the mode once and store it on ``app.state.news``.

    Called from ``NewsModule.on_startup`` before anything touches the
    database. A host pinned to a ``default_tenant`` other than
    :data:`DEFAULT_TENANT` is refused: the migration filed every existing row
    under :data:`DEFAULT_TENANT`, so the framework would bind one tenant and
    news's data would sit in another.
    """
    stray = stray_pins(app)
    if stray is not None:
        raise RuntimeError(
            f"news: the host pins every request to {stray}, but "
            f"news runs a single-tenant host in {DEFAULT_TENANT!r}. Unset "
            f"default_tenant and any TenantMiddleware(fixed=...), set them to "
            f"{DEFAULT_TENANT!r}, or turn multi_tenant on"
        )
    mode = detect_mode(app)
    _warn_if_unrecognised(app)
    services = getattr(app.state, _PACKAGE, None)
    if services is not None:
        services.tenancy = mode
    else:
        app.state.news_tenancy = mode
    host = getattr(getattr(app.state, "host", None), "settings", None)
    if getattr(host, "multi_tenant", False) is True and mode is TenancyMode.SINGLE:
        _log.warning(
            "news: the host setting multi_tenant is on but the middleware stack has "
            "no TenantMiddleware, so news runs single-tenant. Restart to apply it"
        )
    settings = getattr(getattr(app.state, _PACKAGE, None), "settings", None)
    if mode is TenancyMode.MULTI and getattr(settings, "public_base_url", ""):
        _log.warning(
            "news: public_base_url is set on a multi-tenant host, so every "
            "tenant's canonical, feed and sitemap links point at %s. Leave it "
            "blank to build them from each request's host",
            settings.public_base_url,
        )
    return mode
