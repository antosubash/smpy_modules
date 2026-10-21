"""A valid CSRF token is not a permission (#110).

``RequiresCsrf`` runs before the permission check, so a write without a token
is refused before the permission check is reached. These sessions send their
*real* token, taken from a news screen they may see, and the refusal they get
must be the permission check's, not the CSRF one.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from conftest import ROLE_AUTHOR, ROLE_VIEWER, _build_app
from httpx import ASGITransport, AsyncClient
from news.constants import ROUTE_PREFIX_API
from simple_module_hosting.csrf import CSRF_HEADER
from simple_module_hosting.permissions import PERMISSION_DENIED_PREFIX
from stub_auth import stub_user
from test_csrf import _create, _token_from_console

pytestmark = pytest.mark.asyncio

ARTICLES = f"{ROUTE_PREFIX_API}/articles"


async def _session(role: str) -> AsyncIterator[AsyncClient]:
    app, state = await _build_app(stub_user((role,)))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    await state.engine.dispose()


@pytest_asyncio.fixture
async def viewer() -> AsyncIterator[AsyncClient]:
    async for client in _session(ROLE_VIEWER):
        yield client


@pytest_asyncio.fixture
async def author() -> AsyncIterator[AsyncClient]:
    async for client in _session(ROLE_AUTHOR):
        yield client


def _assert_permission_refusal(response, permission: str) -> None:
    assert response.status_code == 403, response.text
    detail = response.json()["detail"]
    assert "CSRF" not in detail
    assert detail == f"{PERMISSION_DENIED_PREFIX}{permission}"


async def test_a_viewer_with_a_valid_token_cannot_write(viewer) -> None:
    token = await _token_from_console(viewer)
    response = await viewer.post(
        ARTICLES, json={"title": "Nope", "slug": "nope"}, headers={CSRF_HEADER: token}
    )
    _assert_permission_refusal(response, "news.edit")
    listing = await viewer.get(ARTICLES, params={"q": "nope"})
    assert listing.json()["items"] == []


async def test_an_author_with_a_valid_token_cannot_publish(author) -> None:
    token = await _token_from_console(author)
    article = await _create(author, token, "draft")  # news.edit is enough for this
    response = await author.post(
        f"{ARTICLES}/{article['id']}/publish", headers={CSRF_HEADER: token}
    )
    _assert_permission_refusal(response, "news.publish")
