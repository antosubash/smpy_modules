"""Shared stubs for the AI module suite.

A uniquely named module (not ``conftest``): the repo's root testpaths collect
several ``tests/`` directories without packages, so ``from conftest import
...`` resolves to whichever suite's conftest loaded first — pagebuilder's,
when run from the repo root.
"""

from __future__ import annotations

from types import SimpleNamespace

from sm_ai import constants
from starlette.middleware.base import BaseHTTPMiddleware


class GrantAll(BaseHTTPMiddleware):
    """Auth stub: every request is an admin holding ``ai.manage``."""

    async def dispatch(self, request, call_next):
        request.state.user = SimpleNamespace(
            id="test-user", email="t@example.com", name="T", roles=["admin"]
        )
        request.state.resolved_permissions = {constants.PERM_MANAGE}
        return await call_next(request)
