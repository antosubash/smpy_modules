"""The admin API's CSRF check, and the token the console sends back (#126).

Pagebuilder shipped the first CSRF design in this repo, its own token under its
own session key, mirrored to a ``pagebuilder_csrf`` cookie by a middleware. The
framework later took that design over as ``simple_module_hosting.csrf``, and
billing, news and records use it. Pagebuilder now uses it too: one session key,
one header (``X-CSRF-Token``), one prop name. A fix to the check lands in one
place for every module.

The API router checks every ``POST``/``PUT``/``PATCH``/``DELETE`` with the
framework's ``RequiresCsrf``. The view router shares ``get_csrf_token`` as the
``csrf_token`` Inertia prop on every pagebuilder screen. ``utils/csrf.ts``
keeps the latest value for the fetch and upload helpers, which sit at module
level and get no props from a page. No cookie is involved.

``csrf_protect`` still switches the check off, for a host that guards writes at
a layer above the application. It is read per request, because the routers are
built before the host hydrates settings from the database.
"""

from __future__ import annotations

from fastapi import Request
from simple_module_hosting.csrf import RequiresCsrf, get_csrf_token
from simple_module_hosting.inertia_deps import InertiaDep

CSRF_PROP = "csrf_token"

_check = RequiresCsrf()


async def share_csrf_token(request: Request, inertia: InertiaDep) -> None:
    """Share the session's token with every page the view router renders.

    Shares nothing without a session (a bare test app): there is no token to
    hand out, and ``RequiresCsrf`` checks nothing either.
    """
    token = get_csrf_token(request)
    if token:
        inertia.share(**{CSRF_PROP: token})


async def verify_csrf_if_configured(request: Request) -> None:
    """Run the framework's check unless ``csrf_protect`` is off."""
    if request.app.state.pagebuilder.settings.csrf_protect:
        await _check(request)
