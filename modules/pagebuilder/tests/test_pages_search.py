"""Search, status filter and paging on the page list.

The admin list paged everything into one response before this; the query
parameters below are what let it show 25 rows at a time without lying about
how many there are.
"""

from __future__ import annotations

from httpx import AsyncClient

LIST = "/api/pagebuilder/pages"


async def _create(client: AsyncClient, title: str, slug: str) -> int:
    response = await client.post(
        LIST, json={"title": title, "slug": slug, "draft_data": {"content": []}}
    )
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


async def test_search_matches_title_and_slug(authed_client: AsyncClient) -> None:
    await _create(authed_client, "About us", "about-us")
    await _create(authed_client, "Contact", "reach-us")
    await _create(authed_client, "Privacy", "privacy")

    by_title = await authed_client.get(LIST, params={"search": "about"})
    assert [p["slug"] for p in by_title.json()["items"]] == ["about-us"]

    # "us" is in the About title and in the Contact slug, but not in Privacy.
    by_either = await authed_client.get(LIST, params={"search": "us"})
    assert sorted(p["slug"] for p in by_either.json()["items"]) == ["about-us", "reach-us"]


async def test_search_is_case_insensitive(authed_client: AsyncClient) -> None:
    await _create(authed_client, "About Us", "about")
    response = await authed_client.get(LIST, params={"search": "ABOUT"})
    assert len(response.json()["items"]) == 1


async def test_search_treats_wildcards_literally(authed_client: AsyncClient) -> None:
    """A '%' in the box is a character to find, not "match everything"."""
    await _create(authed_client, "50% off", "sale")
    await _create(authed_client, "Ordinary page", "ordinary")

    response = await authed_client.get(LIST, params={"search": "%"})
    assert [p["slug"] for p in response.json()["items"]] == ["sale"]


async def test_status_filter(authed_client: AsyncClient) -> None:
    draft_id = await _create(authed_client, "Draft page", "draft-page")
    published_id = await _create(authed_client, "Live page", "live-page")
    await authed_client.post(f"{LIST}/{published_id}/publish", json={})

    published = await authed_client.get(LIST, params={"status": "published"})
    assert [p["id"] for p in published.json()["items"]] == [published_id]

    drafts = await authed_client.get(LIST, params={"status": "draft"})
    assert [p["id"] for p in drafts.json()["items"]] == [draft_id]


async def test_limit_and_offset_page_through_while_total_stays_whole(
    authed_client: AsyncClient,
) -> None:
    for index in range(5):
        await _create(authed_client, f"Page {index}", f"page-{index}")

    first = await authed_client.get(LIST, params={"limit": 2, "offset": 0})
    second = await authed_client.get(LIST, params={"limit": 2, "offset": 2})

    assert len(first.json()["items"]) == 2
    assert len(second.json()["items"]) == 2
    # `total` counts every match, not the slice — that is what sizes a pager.
    assert first.json()["total"] == 5
    assert second.json()["total"] == 5
    assert {p["id"] for p in first.json()["items"]}.isdisjoint(
        p["id"] for p in second.json()["items"]
    )


async def test_total_reflects_the_filter_not_the_table(authed_client: AsyncClient) -> None:
    await _create(authed_client, "Keep me", "keep")
    await _create(authed_client, "Other", "other")

    response = await authed_client.get(LIST, params={"search": "keep", "limit": 1})
    assert response.json()["total"] == 1


async def test_listing_is_unbounded_by_default(authed_client: AsyncClient) -> None:
    """A seed builds its slug-to-id map from this; truncating it would make it
    recreate pages that already exist."""
    for index in range(30):
        await _create(authed_client, f"Page {index}", f"page-{index}")

    response = await authed_client.get(LIST)
    assert len(response.json()["items"]) == 30
    assert response.json()["total"] == 30
