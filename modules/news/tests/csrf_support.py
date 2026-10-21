"""Give a test client the session's CSRF token, the way the console has it.

The harness mounts ``SessionMiddleware`` (the public viewer needs it), so the
API's ``RequiresCsrf`` is live and every write needs ``X-CSRF-Token``. A test
about an article's workflow should not have to know that, so every client the
fixtures build is armed once, up front, through a test-only route that returns
:func:`get_csrf_token` — independent of permissions and tenancy, which a real
console view would drag in. ``test_csrf`` covers the real channel (the
``csrf_token`` prop a view shares) and what happens to a write without it.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from httpx import AsyncClient
from simple_module_hosting.csrf import CSRF_HEADER, get_csrf_token

TOKEN_PATH = "/__test__/csrf-token"


def add_token_route(app: FastAPI) -> None:
    @app.get(TOKEN_PATH)
    async def _token(request: Request) -> dict[str, str]:
        return {"token": get_csrf_token(request)}


async def arm_csrf(client: AsyncClient) -> str:
    """Fetch the session's token and send it on every later request."""
    response = await client.get(TOKEN_PATH)
    assert response.status_code == 200, response.text
    token = response.json()["token"]
    client.headers[CSRF_HEADER] = token
    return token
