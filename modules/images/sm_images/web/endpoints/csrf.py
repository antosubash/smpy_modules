"""Hand the console the CSRF token the images API checks.

The API router carries the framework's ``RequiresCsrf`` (``endpoints.api``):
every ``POST``/``PUT``/``PATCH``/``DELETE`` under ``/api/images`` needs the
session's token in ``X-CSRF-Token``. The console's writes go through
module-level fetch helpers no page threads a prop into, so the view router
*shares* the token: every screen carries ``csrf_token`` in its Inertia props and
``utils/csrf.ts`` keeps the latest value for the helpers. The prop name and the
token are the framework's, as in records and news. The sharing API
(``/api/sharing/shares``) does not check it; sending it is harmless.
"""

from __future__ import annotations

from fastapi import Request
from simple_module_hosting.csrf import get_csrf_token
from simple_module_hosting.inertia_deps import InertiaDep

CSRF_PROP = "csrf_token"


async def share_csrf_token(request: Request, inertia: InertiaDep) -> None:
    """Share the session's token; nothing without a session (a bare test app)."""
    token = get_csrf_token(request)
    if token:
        inertia.share(**{CSRF_PROP: token})
