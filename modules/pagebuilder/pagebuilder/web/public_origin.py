"""The public origin absolute URLs are built from, and what follows when it is guessed.

Canonical links, ``og:url``, ``og:image``, ``hreflang`` alternates, the sitemap
and ``robots.txt``'s ``Sitemap:`` line all need an origin. ``public_base_url``
names it; left blank, the origin is read off the request, and the ``Host``
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

__all__ = ["guessed", "public_origin", "vary_on_host", "warn_if_unset"]

_log = logging.getLogger(__name__)


def guessed(settings: PagebuilderSettings) -> bool:
    """True while absolute URLs come from the request's ``Host``."""
    return not (settings.public_base_url or "").strip()


def public_origin(request: Request, settings: PagebuilderSettings) -> str:
    """The setting if there is one, else the request's own origin; never a
    trailing slash, so callers can append a path."""
    if not guessed(settings):
        return str(settings.public_base_url).strip().rstrip("/")
    return f"{request.url.scheme}://{request.url.netloc}".rstrip("/")


def vary_on_host(response: Response, settings: PagebuilderSettings) -> Response:
    """Add ``Host`` to ``Vary`` while the origin is guessed (see the module docstring)."""
    if not guessed(settings):
        return response
    listed = [f.strip() for f in response.headers.get("vary", "").split(",") if f.strip()]
    if "host" not in {f.lower() for f in listed}:
        response.headers["Vary"] = ", ".join([*listed, "Host"])
    return response


def _environment(app: Any) -> str | None:
    host = getattr(getattr(app.state, "sm", None), "settings", None)
    return getattr(host, "environment", None)


def warn_if_unset(app: Any, settings: PagebuilderSettings) -> bool:
    """Log once at startup when a production single-tenant host has no
    ``public_base_url``. Returns whether it warned.

    Not on a multi-tenant host, where blank is the right value; not in
    development or testing, where the request's host is the developer's.
    """
    if not guessed(settings) or _environment(app) in NON_PROD_ENVIRONMENTS:
        return False
    if mode_of(app) is not TenancyMode.SINGLE:
        return False
    _log.warning(
        "pagebuilder: public_base_url is not set, so canonical, og:url, hreflang and "
        "sitemap links are built from each request's Host header, which the client "
        "chooses. Set it on the Settings screen (e.g. https://example.com); until then "
        "public pages vary on Host"
    )
    return True
