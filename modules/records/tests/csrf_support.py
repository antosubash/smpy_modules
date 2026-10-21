"""The CSRF harness the records suites share (#111).

The rest of the suite's harness mounts no ``SessionMiddleware``, and
``RequiresCsrf`` exempts a session-less app, so ``session_client`` adds one
where the host has it (outermost). ``_token`` takes the token only through the
channel the console's own client uses: the ``csrf_token`` prop a records
screen shares.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from simple_module_hosting.csrf import CSRF_HEADER
from sm_records.constants import ROUTE_PREFIX_API, VIEW_PREFIX
from sm_records.csrf import CSRF_PROP
from starlette.middleware.sessions import SessionMiddleware

from tests.app_harness import ADMIN, build_app, roles

TYPES = f"{ROUTE_PREFIX_API}/types"
INERTIA = {"X-Inertia": "true", "X-Inertia-Version": "1.0"}
AS_ADMIN = roles(ADMIN)


@pytest_asyncio.fixture
async def session_client(tmp_path) -> AsyncIterator[AsyncClient]:
    app, db_state = await build_app(tmp_path)
    app.add_middleware(SessionMiddleware, secret_key="records-tests")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        client.app = app  # type: ignore[attr-defined]
        yield client
    await db_state.engine.dispose()


async def _token(client: AsyncClient) -> str:
    response = await client.get(f"{VIEW_PREFIX}/", headers={**INERTIA, **AS_ADMIN})
    assert response.status_code == 200, response.text
    token = response.json()["props"][CSRF_PROP]
    assert token
    return token


def _type_body(key: str) -> dict:
    field = {"key": "name", "type": "text", "label": "Name"}
    return {"key": key, "label": key.title(), "fields": [field]}


async def _create_type(client: AsyncClient, token: str, key: str) -> dict:
    response = await client.post(
        TYPES, json=_type_body(key), headers={**AS_ADMIN, CSRF_HEADER: token}
    )
    assert response.status_code == 201, response.text
    return response.json()
