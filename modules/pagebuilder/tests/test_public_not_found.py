"""The public viewer's own 404 (#89).

Every address a visitor cannot see — unknown, draft, trashed, scheduled but not
yet live — answers with the same ``PublicNotFound`` page in the site's frame,
so the response says nothing about which case applied, and nothing caches it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

API = "/api/pagebuilder/pages"
INERTIA = {"X-Inertia": "true", "X-Inertia-Version": "1.0"}
COMPONENT = "PageBuilder/PublicNotFound"
HEADER = {"content": [{"type": "Heading", "props": {"id": "h", "text": "Site header"}}]}
FOOTER = {"content": [{"type": "Heading", "props": {"id": "f", "text": "Site footer"}}]}


async def _page(client: AsyncClient, slug: str, *, publish: bool = False) -> dict:
    response = await client.post(
        API, json={"title": slug, "slug": slug, "draft_data": {"content": []}}
    )
    assert response.status_code == 201, response.text
    page = response.json()
    if publish:
        done = await client.post(f"{API}/{page['id']}/publish", json={})
        assert done.status_code == 200, done.text
    return page


async def _seed_every_cause(client: AsyncClient) -> list[str]:
    """One address per reason a visitor gets the 404."""
    await _page(client, "a-draft")
    trashed = await _page(client, "trashed", publish=True)
    assert (await client.delete(f"{API}/{trashed['id']}")).status_code in (200, 204)
    later = await _page(client, "later")
    when = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    scheduled = await client.post(f"{API}/{later['id']}/schedule", json={"publish_at": when})
    assert scheduled.status_code == 200, scheduled.text
    return ["/p/never-existed", "/p/a-draft", "/p/trashed", "/p/later"]


async def test_every_cause_gets_the_same_page(authed_client: AsyncClient) -> None:
    await authed_client.put(
        "/api/pagebuilder/layout", json={"header_data": HEADER, "footer_data": FOOTER}
    )
    paths = await _seed_every_cause(authed_client)

    bodies = []
    for path in paths:
        response = await authed_client.get(path, headers=INERTIA)
        assert response.status_code == 404, (path, response.text)
        page = response.json()
        assert page["component"] == COMPONENT
        bodies.append({k: v for k, v in page["props"].items() if k in _NOT_FOUND_PROPS})

    # No oracle: nothing in the answer tells a draft from a typo.
    assert all(body == bodies[0] for body in bodies)
    assert bodies[0]["layout_header"] == HEADER
    assert bodies[0]["layout_footer"] == FOOTER
    assert bodies[0]["locale"] == "en"
    assert bodies[0]["home_href"] == "/"


_NOT_FOUND_PROPS = {
    "locale",
    "home_href",
    "site_name",
    "copy",
    "layout_header",
    "layout_footer",
    "site_nav",
}


async def test_the_404_is_never_cached(authed_client: AsyncClient) -> None:
    response = await authed_client.get("/p/nope", headers=INERTIA)
    assert response.status_code == 404
    assert response.headers["Cache-Control"] == "no-store"
    assert "ETag" not in response.headers
    assert response.headers["Content-Language"] == "en"


async def test_a_full_document_is_the_page_in_its_language(
    authed_client: AsyncClient,
) -> None:
    response = await authed_client.get("/p/nope", headers={"Accept": "text/html"})
    assert response.status_code == 404
    assert "text/html" in response.headers["content-type"]
    assert '<html lang="en"' in response.text


@pytest.mark.parametrize(
    "accept",
    [
        "application/json",
        # HTML explicitly refused.
        "application/json, text/html;q=0",
        # JSON preferred, HTML only a fallback.
        "application/json, text/html;q=0.5",
    ],
)
async def test_a_json_caller_still_gets_json(authed_client: AsyncClient, accept: str) -> None:
    """The framework's own negotiation, q-values included (#89 review)."""
    response = await authed_client.get("/p/nope", headers={"Accept": accept})
    assert response.status_code == 404
    assert response.json() == {"detail": "Page not found"}
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize(
    "headers",
    [
        # What a browser sends on a navigation.
        {"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"},
        {"Accept": "*/*"},
        # An Inertia visit gets the page component whatever its Accept says.
        {**INERTIA, "Accept": "application/json"},
        {**INERTIA, "Accept": "application/json, text/html;q=0"},
    ],
)
async def test_a_browser_or_inertia_caller_gets_the_page(
    authed_client: AsyncClient, headers: dict[str, str]
) -> None:
    response = await authed_client.get("/p/nope", headers=headers)
    assert response.status_code == 404
    if "X-Inertia" in headers:
        assert response.json()["component"] == COMPONENT
    else:
        assert "text/html" in response.headers["content-type"]
    assert response.headers["Cache-Control"] == "no-store"


async def test_the_404_speaks_the_addresses_language(bilingual_client: AsyncClient) -> None:
    response = await bilingual_client.get("/de/p/nope", headers=INERTIA)
    assert response.status_code == 404
    assert response.json()["component"] == COMPONENT
    assert response.json()["props"]["locale"] == "de"
    # The address's language, not the visitor's UI language.
    assert response.json()["props"]["copy"]["not_found"]["title"] == "Diese Seite gibt es nicht"
    assert response.headers["Content-Language"] == "de"

    full = await bilingual_client.get("/de/p/nope", headers={"Accept": "text/html"})
    assert '<html lang="de"' in full.text


async def test_a_redirect_still_wins_over_the_404(authed_client: AsyncClient) -> None:
    page = await _page(authed_client, "old-name", publish=True)
    await authed_client.put(f"{API}/{page['id']}", json={"slug": "new-name"})
    await authed_client.post(f"{API}/{page['id']}/publish", json={})
    moved = await authed_client.get("/p/old-name", headers=INERTIA)
    assert moved.status_code == 301


async def test_public_copy_falls_back_by_language_then_to_english() -> None:
    from pagebuilder.public_copy import public_copy

    assert public_copy("de")["skip_to_content"] == "Zum Inhalt springen"
    assert public_copy("de-at") == public_copy("de")
    assert public_copy("fr") == public_copy("en")
    # A tag is never a path.
    assert public_copy("../en") == public_copy("en")
