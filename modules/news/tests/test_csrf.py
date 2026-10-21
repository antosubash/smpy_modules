"""The admin API refuses a write without the session's CSRF token (#110).

The API used to rely on the session cookie's ``SameSite=Lax`` alone, which does
not separate the console from an organisation's public site on a multi-tenant
host — the two are same-site. These clients are built *unarmed* (the shared
fixtures send the token on every request) and arm themselves only through the
channel the console's own client uses: the ``csrf_token`` prop a news screen
shares.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from conftest import ROLE_EDITOR, _build_app
from httpx import ASGITransport, AsyncClient
from news.constants import ADMIN_SEARCH_PREFIX, ROUTE_PREFIX_API, VIEW_PREFIX
from news.csrf import CSRF_PROP
from simple_module_hosting.csrf import CSRF_HEADER
from stub_auth import stub_user

pytestmark = pytest.mark.asyncio

ARTICLES = f"{ROUTE_PREFIX_API}/articles"
INERTIA = {"X-Inertia": "true", "X-Inertia-Version": "1.0"}


@pytest_asyncio.fixture
async def bare() -> AsyncIterator[AsyncClient]:
    """An editor's session that has not been handed a token yet."""
    app, state = await _build_app(stub_user((ROLE_EDITOR,)))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        client.app = app  # type: ignore[attr-defined]
        yield client
    await state.engine.dispose()


async def _token_from_console(client: AsyncClient, url: str = f"{VIEW_PREFIX}/") -> str:
    response = await client.get(url, headers=INERTIA)
    assert response.status_code == 200, response.text
    token = response.json()["props"][CSRF_PROP]
    assert token
    return token


async def _create(client: AsyncClient, token: str, slug: str) -> dict:
    response = await client.post(
        ARTICLES, json={"title": slug, "slug": slug}, headers={CSRF_HEADER: token}
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_a_write_without_the_token_is_refused_and_writes_nothing(bare) -> None:
    await _token_from_console(bare)  # the session has a token; the request omits it
    response = await bare.post(ARTICLES, json={"title": "Forged", "slug": "forged"})
    assert response.status_code == 403
    assert "CSRF" in response.json()["detail"]
    listing = await bare.get(ARTICLES, params={"q": "forged"})
    assert listing.json()["items"] == []


@pytest.mark.parametrize("method", ["PUT", "DELETE"])
async def test_every_unsafe_method_is_checked(bare, method) -> None:
    token = await _token_from_console(bare)
    article = await _create(bare, token, f"target-{method.lower()}")
    url = f"{ARTICLES}/{article['id']}"
    response = await bare.request(method, url, json={"title": "Forged"})
    assert response.status_code == 403
    # Untouched: the forged request reached no handler.
    listing = await bare.get(ARTICLES, params={"q": article["slug"]})
    assert [a["title"] for a in listing.json()["items"]] == [article["title"]]


async def test_patch_is_checked_too(bare) -> None:
    """No news route takes PATCH today; one added under the router would be checked.

    Mounted with the API router's own dependency list, which is what every
    route included from it inherits.
    """
    from news.endpoints.api import router

    async def _patch() -> dict[str, bool]:
        return {"patched": True}

    path = f"{ROUTE_PREFIX_API}/__patch__"
    bare.app.add_api_route(path, _patch, methods=["PATCH"], dependencies=router.dependencies)
    token = await _token_from_console(bare)
    assert (await bare.patch(path)).status_code == 403
    allowed = await bare.patch(path, headers={CSRF_HEADER: token})
    assert allowed.status_code == 200, allowed.text


async def test_a_wrong_token_is_refused(bare) -> None:
    await _token_from_console(bare)
    response = await bare.post(
        ARTICLES, json={"title": "Wrong"}, headers={CSRF_HEADER: "not-the-token"}
    )
    assert response.status_code == 403


async def test_a_write_before_any_view_is_refused(bare) -> None:
    """No token minted yet is a refusal, not a pass."""
    response = await bare.post(ARTICLES, json={"title": "Early"}, headers={CSRF_HEADER: ""})
    assert response.status_code == 403


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
async def test_safe_methods_need_no_token(bare, method) -> None:
    """The feed block reads this API anonymously from public pages."""
    response = await bare.request(method, ARTICLES)
    assert response.status_code != 403


async def test_the_shared_token_is_what_the_api_accepts(bare) -> None:
    token = await _token_from_console(bare)
    article = await _create(bare, token, "real")
    url = f"{ARTICLES}/{article['id']}"
    updated = await bare.put(url, json={"title": "Renamed"}, headers={CSRF_HEADER: token})
    assert updated.status_code == 200, updated.text
    assert updated.json()["title"] == "Renamed"
    deleted = await bare.delete(url, headers={CSRF_HEADER: token})
    assert deleted.status_code == 204, deleted.text


async def test_the_search_screen_shares_the_same_token(bare) -> None:
    """One session, one token — the screen mounted outside VIEW_PREFIX has it too."""
    from news.endpoints.views import admin_router

    bare.app.include_router(admin_router, prefix=ADMIN_SEARCH_PREFIX)  # on_startup does this
    first = await _token_from_console(bare)
    assert await _token_from_console(bare, f"{ADMIN_SEARCH_PREFIX}/search") == first
