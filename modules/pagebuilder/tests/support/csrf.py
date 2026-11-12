"""The admin API refuses a write without the session's CSRF token (#10, #126).

The check is the framework's ``RequiresCsrf``, the one billing, news and
records use. The token reaches the console as the framework's ``csrfToken``
Inertia prop on every signed-in page, and these tests take it from there, the
way the console's own client does. No cookie is set any more.
"""

from __future__ import annotations

from httpx import AsyncClient
from pagebuilder.web.csrf import CSRF_PROP
from simple_module_hosting.csrf import CSRF_HEADER

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
