"""Two tenants over HTTP, for the isolation matrix.

``acme`` and ``globex`` are two organisations on one multi-tenant app. Nothing
is seeded yet: the collection and image tables arrive with later tasks, which
extend :func:`seed` so every probe asks as ``globex`` for one of ``acme``'s
things and expects exactly what asking for nothing gets.

:func:`covers` records which route a test is the isolation case for, so a later
``test_every_route_has_an_isolation_case`` can fail for a route nobody covered.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Any

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from tests.support.app_harness import ADMIN_PERMS, TEST_TENANT_HEADER, as_user, build_app

ACME, GLOBEX = "acme", "globex"


def as_(tenant: str | None, user_id: str = "admin", perms: tuple[str, ...] = ADMIN_PERMS):
    """A signed-in caller whose account is in ``tenant``."""
    headers = as_user(user_id, perms)
    if tenant is not None:
        headers[TEST_TENANT_HEADER] = tenant
    return headers


async def seed(client: AsyncClient) -> None:
    """Fill both tenants. Empty until the first tenant-owned table exists."""


@pytest_asyncio.fixture
async def two_tenants(tmp_path) -> AsyncIterator[AsyncClient]:
    """A multi-tenant app holding the two tenants of the module docstring."""
    app, db_state = await build_app(tmp_path, tenancy="multi")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        client.app = app  # type: ignore[attr-defined]
        client.db_state = db_state  # type: ignore[attr-defined]
        await seed(client)
        yield client
    await db_state.engine.dispose()


COVERED: set[tuple[str, str]] = set()


def covers(*routes: str) -> Callable[[Any], Any]:
    """``@covers("GET /api/images/collections/{id}")`` - this test is that
    route's isolation case."""

    def mark(fn: Any) -> Any:
        for route in routes:
            method, path = route.split(" ", 1)
            COVERED.add((method, path))
        return fn

    return mark
