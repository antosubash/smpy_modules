"""The public origin absolute URLs are built from, and what follows when it is guessed.

Canonical links, ``og:url``, ``og:image``, ``hreflang`` alternates, the sitemap
and ``robots.txt``'s ``Sitemap:`` line all need an origin. ``public_base_url``
names it (on a single-tenant host the host's own ``public_base_url`` stands
in for a blank one); left blank, the origin is read off the request, and the ``Host``
header is chosen by the client (#355). On a deployment whose proxy forwards
only known hosts that is harmless, and on a multi-tenant host it is the point:
each organisation's site is its own host. On one that does not, a shared cache
that keys without ``Host`` can store a page whose canonical and sitemap links
name a host of the requester's choosing and serve it to everyone.

So while the origin is guessed, every response whose body carries it adds
``Host`` to ``Vary`` (:func:`vary_on_host`), and a single-tenant production
host logs a warning at startup (:func:`warn_if_unset`). The setting stays
optional: a host that sets it gets neither.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Request, Response
from simple_module_core.environments import NON_PROD_ENVIRONMENTS

from pagebuilder.core.settings import PagebuilderSettings
from pagebuilder.core.tenancy import TenancyMode, mode_of

__all__ = ["configured_origin", "guessed", "public_origin", "vary_on_host", "warn_if_unset"]

_log = logging.getLogger(__name__)


def _host(app: Any) -> Any:
    return getattr(getattr(app.state, "sm", None), "settings", None)


def configured_origin(app: Any, settings: PagebuilderSettings) -> str:
    """The configured origin, or ``""``: this module's ``public_base_url``, else
    on a single-tenant host the host's own ``public_base_url``.

    Not the host's on a multi-tenant host: it names one origin, and each
    organisation's site is its own host there."""
    own = (settings.public_base_url or "").strip()
    if own or mode_of(app) is not TenancyMode.SINGLE:
        return own.rstrip("/")
    return str(getattr(_host(app), "public_base_url", "") or "").strip().rstrip("/")


def guessed(app: Any, settings: PagebuilderSettings) -> bool:
    """True while absolute URLs come from the request's ``Host``."""
    return not configured_origin(app, settings)


def public_origin(request: Request, settings: PagebuilderSettings) -> str:
    """The configured origin if there is one, else the request's own; never a
    trailing slash, so callers can append a path."""
    return configured_origin(request.app, settings) or (
        f"{request.url.scheme}://{request.url.netloc}".rstrip("/")
    )


def vary_on_host(response: Response, request: Request, settings: PagebuilderSettings) -> Response:
    """Add ``Host`` to ``Vary`` while the origin is guessed (see the module docstring)."""
    if not guessed(request.app, settings):
        return response
    listed = [f.strip() for f in response.headers.get("vary", "").split(",") if f.strip()]
    if "host" not in {f.lower() for f in listed}:
        response.headers["Vary"] = ", ".join([*listed, "Host"])
    return response


def _environment(app: Any) -> str | None:
    return getattr(_host(app), "environment", None)


def warn_if_unset(app: Any, settings: PagebuilderSettings) -> bool:
    """Log once at startup when a production single-tenant host has no
    ``public_base_url`` (its own or the host's). Returns whether it warned.

    Not on a multi-tenant host, where blank is the right value; not in
    development or testing, where the request's host is the developer's.
    """
    if not guessed(app, settings) or _environment(app) in NON_PROD_ENVIRONMENTS:
        return False
    if mode_of(app) is not TenancyMode.SINGLE:
        return False
    _log.warning(
        "pagebuilder: neither pagebuilder's public_base_url nor the host's "
        "public_base_url is set, so canonical, og:url, hreflang and sitemap links are "
        "built from each request's Host header, which the client chooses. Set either one "
        "on the Settings screen (e.g. https://example.com); until then public pages vary "
        "on Host"
    )
    return True
