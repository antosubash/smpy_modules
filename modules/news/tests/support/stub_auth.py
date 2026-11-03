"""What stands in for ``simple_module_auth`` in these tests.

Lifted out of ``conftest`` when that file crossed the repo's 300-line cap. It
is a coherent piece to lift: everything here is about who the request is, and
nothing else in the harness is.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware


def stub_user(roles: tuple[str, ...]) -> SimpleNamespace:
    """Stand in for ``auth.UserContext``.

    Deliberately carries no ``permissions`` attribute — the real UserContext has
    none either, and a fixture that invented one would hide exactly the bug
    ``may_see_drafts`` used to have.
    """
    return SimpleNamespace(
        id="test-user",
        email="test@example.com",
        name="Test User",
        roles=list(roles),
    )


class StubAuthMiddleware(BaseHTTPMiddleware):
    """Populate ``request.state.user`` the way the host's auth middleware would.

    ``user=None`` leaves the request anonymous, which is what the public feed
    block looks like.
    """

    def __init__(self, app: Any, user: Any) -> None:
        super().__init__(app)
        self._user = user

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if self._user is not None:
            request.state.user = self._user
        return await call_next(request)
