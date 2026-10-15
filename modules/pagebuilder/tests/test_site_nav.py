"""Pages flagged for the site nav reach the public page, and ``meta_title`` its title.

``show_in_header_nav`` / ``show_in_footer`` and ``meta_title`` were stored and
edited but never read by the public viewer. The props asserted here are what
``PublicPage`` hands the SiteHeader / SiteFooter widgets and ``<title>``.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from pagebuilder import public_claims

pytestmark = pytest.mark.asyncio

API = "/api/pagebuilder/pages"
INERTIA = {"X-Inertia": "true", "X-Inertia-Version": "1.0"}


@pytest.fixture(autouse=True)
def _no_leaked_claims():
    public_claims.reset()
    yield
    public_claims.reset()


async def _page(client: AsyncClient, slug: str, *, publish: bool = True, **extra) -> int:
    payload = {"title": slug.title(), "slug": slug, "draft_data": {"content": []}}
    payload.update(extra)
    created = await client.post(API, json=payload)
    assert created.status_code == 201, created.text
    page_id = created.json()["id"]
    if publish:
        assert (await client.post(f"{API}/{page_id}/publish")).status_code == 200
    return page_id


async def _props(client: AsyncClient, path: str = "/p/home") -> dict:
    response = await client.get(path, headers=INERTIA)
    assert response.status_code == 200, response.text
    return response.json()["props"]


async def test_flagged_published_pages_are_listed_by_title(authed_client: AsyncClient) -> None:
    await _page(authed_client, "home")
    await _page(authed_client, "zebra", show_in_header_nav=True)
    await _page(authed_client, "about", show_in_header_nav=True, show_in_footer=True)
    await _page(authed_client, "imprint", show_in_footer=True)

    nav = (await _props(authed_client))["site_nav"]

    assert nav["header"] == [
        {"label": "About", "href": "/p/about"},
        {"label": "Zebra", "href": "/p/zebra"},
    ]
    assert nav["footer"] == [
        {"label": "About", "href": "/p/about"},
        {"label": "Imprint", "href": "/p/imprint"},
    ]


async def test_order_ignores_case(authed_client: AsyncClient) -> None:
    await _page(authed_client, "home")
    await _page(authed_client, "zulu", title="Zulu", show_in_footer=True)
    await _page(authed_client, "apple", title="apple", show_in_footer=True)

    footer = (await _props(authed_client))["site_nav"]["footer"]

    assert [link["label"] for link in footer] == ["apple", "Zulu"]


async def test_drafts_and_trashed_pages_are_left_out(authed_client: AsyncClient) -> None:
    await _page(authed_client, "home")
    await _page(authed_client, "draft", publish=False, show_in_header_nav=True)
    trashed = await _page(authed_client, "gone", show_in_header_nav=True)
    assert (await authed_client.delete(f"{API}/{trashed}")).status_code == 204

    assert (await _props(authed_client))["site_nav"] == {"header": [], "footer": []}


async def test_a_claimed_page_links_to_the_claimant(authed_client: AsyncClient) -> None:
    async def claim(session, slugs, locale):
        return {slug: f"/news/{slug}" for slug in slugs if slug == "story"}

    await _page(authed_client, "home")
    await _page(authed_client, "story", show_in_footer=True)
    public_claims.register(claim)

    footer = (await _props(authed_client))["site_nav"]["footer"]

    assert footer == [{"label": "Story", "href": "/news/story"}]


async def test_only_the_pages_own_language_is_listed(bilingual_client: AsyncClient) -> None:
    await _page(bilingual_client, "home")
    await _page(bilingual_client, "about", show_in_header_nav=True)
    await _page(bilingual_client, "start", locale="de")
    await _page(bilingual_client, "ueber", locale="de", show_in_header_nav=True)

    english = (await _props(bilingual_client))["site_nav"]["header"]
    german = (await _props(bilingual_client, "/de/p/start"))["site_nav"]["header"]

    assert english == [{"label": "About", "href": "/p/about"}]
    assert german == [{"label": "Ueber", "href": "/de/p/ueber"}]


async def test_flagging_another_page_changes_the_etag(authed_client: AsyncClient) -> None:
    """The chrome changed while neither this page nor the layout did."""
    await _page(authed_client, "home")
    before = (await authed_client.get("/p/home")).headers["etag"]

    await _page(authed_client, "about", show_in_header_nav=True)
    after = (await authed_client.get("/p/home")).headers["etag"]

    assert before != after


async def test_meta_title_is_the_document_title(authed_client: AsyncClient) -> None:
    await _page(authed_client, "home", meta_title="Welcome | Example Co")

    assert (await _props(authed_client))["title"] == "Welcome | Example Co"


async def test_title_falls_back_to_the_page_title(authed_client: AsyncClient) -> None:
    await _page(authed_client, "home")

    assert (await _props(authed_client))["title"] == "Home"


async def test_preview_carries_meta_title_and_nav(authed_client: AsyncClient) -> None:
    page_id = await _page(authed_client, "home", publish=False, meta_title="Draft title")
    await _page(authed_client, "about", show_in_header_nav=True)

    props = await _props(authed_client, f"/pagebuilder/{page_id}/preview")

    assert props["title"] == "Draft title"
    assert props["site_nav"]["header"] == [{"label": "About", "href": "/p/about"}]
