"""Hand the console the CSRF token the newsletter API checks.

The API router is mounted under the framework's ``RequiresCsrf``, so every
``POST``/``PUT``/``PATCH``/``DELETE`` under ``/api/newsletter`` needs the
session's token in ``X-CSRF-Token``. The view routers *share* it: every
newsletter screen carries ``csrf_token`` in its Inertia props (the name and the
token are the framework's, as in news and records).
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
