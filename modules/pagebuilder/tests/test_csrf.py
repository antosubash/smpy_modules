"""The admin API refuses a write without the session's CSRF token (#10, #126).

The check is the framework's ``RequiresCsrf``, the one billing, news and
records use. The token reaches the console as the ``csrf_token`` Inertia prop
on every pagebuilder screen, and these tests take it from there, the way the
console's own client does. No cookie is set any more.
"""

from __future__ import annotations

import pytest
from conftest import PNG_BYTES
from httpx import AsyncClient
from pagebuilder.csrf import CSRF_PROP
from simple_module_hosting.csrf import CSRF_HEADER

pytestmark = pytest.mark.asyncio

INERTIA = {"X-Inertia": "true", "X-Inertia-Version": "1.0"}
PAGES = "/api/pagebuilder/pages"
UPLOADS = "/api/pagebuilder/uploads"


async def token_from_console(client: AsyncClient, url: str = "/pagebuilder/") -> str:
    """The token a pagebuilder screen hands the console."""
    response = await client.get(url, headers=INERTIA)
    assert response.status_code == 200, response.text
    token = response.json()["props"][CSRF_PROP]
    assert token
    return token


async def create_page(client: AsyncClient, token: str, slug: str) -> dict:
    response = await client.post(
        PAGES,
        json={"title": slug, "slug": slug, "draft_data": {}},
        headers={CSRF_HEADER: token},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _slugs(client: AsyncClient) -> list[str]:
    response = await client.get(PAGES)
    assert response.status_code == 200, response.text
    return [p["slug"] for p in response.json()["items"]]


async def test_a_write_without_the_token_is_refused_and_writes_nothing(csrf_client) -> None:
    await token_from_console(csrf_client)  # the session has a token; the request omits it
    response = await csrf_client.post(
        PAGES, json={"title": "Forged", "slug": "forged", "draft_data": {}}
    )
    assert response.status_code == 403
    assert "CSRF" in response.json()["detail"]
    assert await _slugs(csrf_client) == []


async def test_a_wrong_token_is_refused(csrf_client) -> None:
    await token_from_console(csrf_client)
    response = await csrf_client.post(
        PAGES,
        json={"title": "wrong", "slug": "wrong-token", "draft_data": {}},
        headers={CSRF_HEADER: "obviously-not-the-real-token"},
    )
    assert response.status_code == 403
    assert await _slugs(csrf_client) == []


async def test_a_write_before_any_token_exists_is_refused(csrf_client) -> None:
    response = await csrf_client.post(
        PAGES,
        json={"title": "early", "slug": "early", "draft_data": {}},
        headers={CSRF_HEADER: "guessed"},
    )
    assert response.status_code == 403


@pytest.mark.parametrize("method", ["PUT", "DELETE"])
async def test_every_unsafe_method_is_checked(csrf_client, method) -> None:
    token = await token_from_console(csrf_client)
    page = await create_page(csrf_client, token, f"target-{method.lower()}")
    response = await csrf_client.request(method, f"{PAGES}/{page['id']}", json={"title": "Forged"})
    assert response.status_code == 403
    detail = await csrf_client.get(f"{PAGES}/{page['id']}")
    assert detail.status_code == 200
    assert detail.json()["title"] == page["title"]


async def test_a_media_upload_without_the_token_is_refused_and_stores_nothing(
    csrf_client,
) -> None:
    await token_from_console(csrf_client)
    response = await csrf_client.post(UPLOADS, files={"file": ("hero.png", PNG_BYTES, "image/png")})
    assert response.status_code == 403
    listing = await csrf_client.get(UPLOADS)
    assert listing.json()["items"] == []


async def test_the_screens_token_is_accepted(csrf_client) -> None:
    token = await token_from_console(csrf_client)
    page = await create_page(csrf_client, token, "ok")

    updated = await csrf_client.put(
        f"{PAGES}/{page['id']}", json={"title": "Renamed"}, headers={CSRF_HEADER: token}
    )
    assert updated.status_code == 200, updated.text

    uploaded = await csrf_client.post(
        UPLOADS,
        files={"file": ("hero.png", PNG_BYTES, "image/png")},
        headers={CSRF_HEADER: token},
    )
    assert uploaded.status_code == 201, uploaded.text

    deleted = await csrf_client.delete(f"{PAGES}/{page['id']}", headers={CSRF_HEADER: token})
    assert deleted.status_code in (200, 204), deleted.text


async def test_every_screen_shares_the_same_token(csrf_client) -> None:
    first = await token_from_console(csrf_client)
    assert await token_from_console(csrf_client, "/pagebuilder/media") == first


async def test_no_cookie_mirrors_the_token(csrf_client) -> None:
    """The old ``pagebuilder_csrf`` cookie is gone: the prop is the only channel."""
    response = await csrf_client.get("/pagebuilder/", headers=INERTIA)
    names = {c.split("=", 1)[0] for c in response.headers.get_list("set-cookie")}
    assert "pagebuilder_csrf" not in names


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
async def test_safe_methods_are_not_checked(csrf_client, method) -> None:
    response = await csrf_client.request(method, PAGES)
    assert response.status_code != 403


async def test_csrf_disabled_passes_without_token(authed_client: AsyncClient) -> None:
    """``csrf_protect=False`` (the default in ``authed_client``) lets POSTs
    through with no token at all."""
    response = await authed_client.post(
        PAGES, json={"title": "no csrf", "slug": "no-csrf", "draft_data": {}}
    )
    assert response.status_code == 201


async def test_the_switch_is_read_per_request(csrf_client) -> None:
    """Saving ``csrf_protect`` on the Settings screen takes effect without a restart."""
    settings = csrf_client._transport.app.state.pagebuilder.settings
    settings.csrf_protect = False
    response = await csrf_client.post(
        PAGES, json={"title": "after save", "slug": "after-save", "draft_data": {}}
    )
    assert response.status_code == 201, response.text
