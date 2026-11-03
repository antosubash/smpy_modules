"""Hand the console the CSRF token the news API checks (#110).

The API router carries the framework's ``RequiresCsrf``, as billing's does:
every ``POST``/``PUT``/``PATCH``/``DELETE`` under ``/api/news`` needs the
session's token in ``X-CSRF-Token``. ``SameSite=Lax`` on the session cookie is
not enough on its own — on a multi-tenant host every organisation's public site
is same-site with the console.

Billing passes the token to each page as a prop. News' writes go through one
module-level fetch wrapper that no page threads a prop into, so the view
routers *share* it instead: every news screen carries ``csrf_token`` in its
Inertia props, and ``utils/csrf.ts`` keeps the latest value for the wrapper.
The prop name and the token are the framework's, so records — which does the
same — and news agree on both without importing each other.
"""

from __future__ import annotations

from fastapi import Request
from simple_module_hosting.csrf import get_csrf_token
from simple_module_hosting.inertia_deps import InertiaDep

CSRF_PROP = "csrf_token"


async def share_csrf_token(request: Request, inertia: InertiaDep) -> None:
    """Share the session's token with every page the router renders.

    Shares nothing without a session (a bare test app): there is no token to
    hand out, and ``RequiresCsrf`` checks nothing either.
    """
    token = get_csrf_token(request)
    if token:
        inertia.share(**{CSRF_PROP: token})
