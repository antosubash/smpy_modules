"""The stand-in for the host's auth middleware that the test apps mount.

Split out of ``conftest.py``, which sits on the repo's 300-line cap.
``conftest`` re-exports both names, so ``from conftest import
_StubAuthMiddleware`` keeps working.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware


def _stub_user(roles: tuple[str, ...] = ("admin",)) -> SimpleNamespace:
    return SimpleNamespace(
        id="test-user",
        email="test@example.com",
        name="Test User",
        roles=list(roles),
    )


class _StubAuthMiddleware(BaseHTTPMiddleware):
    """Populate ``request.state.user`` the way the host's auth middleware would.

    Production runs ``simple_module_auth``'s session middleware before
    every request and stashes a ``UserContext`` on ``request.state``.
    The pagebuilder test harness doesn't mount that middleware, so we
    drop a minimal stand-in here whenever a fixture wants requests to
    look authenticated. Without it, ``simple_module_hosting``'s
    ``RequiresPermission`` would 401 every protected endpoint.
    """

    def __init__(self, app: Any, user: Any) -> None:
        super().__init__(app)
        self._user = user

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if "x-test-anonymous" not in request.headers:
            request.state.user = self._user
        return await call_next(request)
