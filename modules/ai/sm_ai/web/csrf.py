"""Hand the settings screen the CSRF token the AI API checks (#126).

This module stores provider API keys, and its write surface can redirect
``chat_base_url``. A forged cross-site PUT could point the stored key at an
attacker's server. So the API router carries the framework's ``RequiresCsrf``,
as billing's, news' and records' do: every ``POST``/``PUT``/``PATCH``/``DELETE``
under ``/api/ai`` needs the session's token in ``X-CSRF-Token``.

The settings page talks to the API through module-level fetch helpers, which
get no props from a page. So the view router *shares* the token: the screen
carries ``csrf_token`` in its Inertia props, and ``utils/csrf.ts`` keeps the
latest value for the helpers. The prop name and the token are the framework's,
so every module agrees on both without importing another.
"""

from __future__ import annotations

from fastapi import Request
from simple_module_hosting.csrf import get_csrf_token
from simple_module_hosting.inertia_deps import InertiaDep

CSRF_PROP = "csrf_token"


async def share_csrf_token(request: Request, inertia: InertiaDep) -> None:
    """Share the session's token with every page the view router renders.

    Shares nothing without a session (a bare test app): there is no token to
    hand out, and ``RequiresCsrf`` checks nothing either.
    """
    token = get_csrf_token(request)
    if token:
        inertia.share(**{CSRF_PROP: token})
