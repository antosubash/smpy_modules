"""The admin API's CSRF check, and the token the console sends back (#126).

Pagebuilder shipped the first CSRF design in this repo, its own token under its
own session key, mirrored to a ``pagebuilder_csrf`` cookie by a middleware. The
framework later took that design over as ``simple_module_hosting.csrf``, and
billing, news and records use it. Pagebuilder now uses it too: one session key,
one header (``X-CSRF-Token``), one prop name. A fix to the check lands in one
place for every module.

The API router checks every ``POST``/``PUT``/``PATCH``/``DELETE`` with the
framework's ``RequiresCsrf``. The token reaches the console as the framework's
``csrfToken`` shared prop, which every signed-in page carries (#342), and
``utils/csrf.ts`` reads it through ``currentCsrfToken`` for the fetch and
upload helpers. No cookie is involved.

The framework leaves the prop off an anonymous page, which is fine even with
``requires_auth`` off: every write also needs a pagebuilder permission, which an
anonymous visitor never holds (401 before the token would matter).

``csrf_protect`` still switches the check off, for a host that guards writes at
a layer above the application. It is read per request, because the routers are
built before the host hydrates settings from the database.
"""

from __future__ import annotations

from fastapi import Request
from simple_module_hosting.csrf import RequiresCsrf

#: The framework's shared-prop name for the token (``CSRF_SHARED_PROP``).
CSRF_PROP = "csrfToken"

_check = RequiresCsrf()


async def verify_csrf_if_configured(request: Request) -> None:
    """Run the framework's check unless ``csrf_protect`` is off."""
    if request.app.state.pagebuilder.settings.csrf_protect:
        await _check(request)
