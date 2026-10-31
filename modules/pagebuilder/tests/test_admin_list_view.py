"""The admin page-list view route and its filter query string.

The filters live in the URL so a filtered list survives a reload and can be
linked to. That only holds if every shape the UI puts in the query string is
one the route accepts — including ``status=`` with no value, which is what an
unset status pill serializes to.
"""

from __future__ import annotations

from httpx import AsyncClient

VIEW = "/pagebuilder/"
API = "/api/pagebuilder/pages"


async def _create(client: AsyncClient, title: str, slug: str) -> int:
    response = await client.post(
        API, json={"title": title, "slug": slug, "draft_data": {"content": []}}
    )
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


async def test_empty_status_param_is_accepted(authed_client: AsyncClient) -> None:
    """An unset status pill sends ``status=``; that must not 422."""
    response = await authed_client.get(VIEW, params={"search": "x", "status": "", "offset": 0})
    assert response.status_code == 200, response.text


async def test_a_status_that_is_not_a_status_is_still_rejected(
    authed_client: AsyncClient,
) -> None:
    """Treating "" as "no filter" must not turn into accepting anything."""
    response = await authed_client.get(VIEW, params={"status": "nonsense"})
    assert response.status_code == 422
    api = await authed_client.get(API, params={"status": "nonsense"})
    assert api.status_code == 422


async def test_filters_round_trip_into_the_props(authed_client: AsyncClient) -> None:
    await _create(authed_client, "Alpha", "alpha")
    await _create(authed_client, "Beta", "beta")

    response = await authed_client.get(
        VIEW, params={"search": "Beta", "status": ""}, headers={"X-Inertia": "true"}
    )
    assert response.status_code == 200, response.text
    props = response.json()["props"]
    assert [p["slug"] for p in props["pages"]["items"]] == ["beta"]
    assert props["pages"]["total"] == 1
    # Echoed back so the search box can render what is actually being filtered
    # on after a reload, rather than resetting itself to empty.
    assert props["filters"]["search"] == "Beta"
    assert props["filters"]["status"] == ""


async def test_status_filter_round_trips(authed_client: AsyncClient) -> None:
    await _create(authed_client, "Draft one", "draft-one")
    published = await _create(authed_client, "Live one", "live-one")
    await authed_client.post(f"{API}/{published}/publish", json={})

    response = await authed_client.get(
        VIEW, params={"status": "published"}, headers={"X-Inertia": "true"}
    )
    props = response.json()["props"]
    assert [p["slug"] for p in props["pages"]["items"]] == ["live-one"]
    assert props["filters"]["status"] == "published"


async def test_an_offset_past_the_end_steps_back_to_the_last_page(
    authed_client: AsyncClient,
) -> None:
    """Deleting the last row of the last page leaves the offset stranded."""
    await _create(authed_client, "Only page", "only-page")

    response = await authed_client.get(
        VIEW, params={"offset": 100}, headers={"X-Inertia": "true"}
    )
    props = response.json()["props"]
    assert props["filters"]["offset"] == 0
    assert [p["slug"] for p in props["pages"]["items"]] == ["only-page"]


async def test_the_language_filter_narrows_the_board_too(
    bilingual_client: AsyncClient,
) -> None:
    """The board is the *default* view, so a language pill the board ignored
    would be a control that visibly does nothing on the screen an author
    lands on."""
    for title, slug, locale in (("About", "about", "en"), ("Ueber", "ueber", "de")):
        response = await bilingual_client.post(
            API,
            json={
                "title": title,
                "slug": slug,
                "locale": locale,
                "draft_data": {"content": []},
            },
        )
        assert response.status_code == 201, response.text

    props = (
        await bilingual_client.get(
            VIEW, params={"locale": "de"}, headers={"X-Inertia": "true"}
        )
    ).json()["props"]

    board_slugs = {
        item["slug"] for stage in props["board"] for item in stage["items"]
    }
    assert board_slugs == {"ueber"}

