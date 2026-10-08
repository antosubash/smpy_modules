"""Admin-side isolation between two live tenants.

Ported from pagebuilder's. The bulk Core statements are the part this file
exists for: a category rename, a redirect rewrite and a tag merge are
``UPDATE``/``DELETE ... WHERE`` on a column that is unique only *per tenant*,
so one that escaped the tenant filter would reach into the other tenant.
"""

from __future__ import annotations

import pytest
from conftest import ROLE_EDITOR
from httpx import AsyncClient
from stub_auth import stub_user
from tenant_app import (
    ARTICLES,
    as_tenant,
    create_article,
    create_published,
    multi_client,
    publish,
)

A, B = as_tenant("acme"), as_tenant("globex")
CATEGORIES = "/api/news/taxonomy/categories"
TAGS = "/api/news/taxonomy/tags"

pytestmark = [pytest.mark.asyncio, pytest.mark.unbound_tenant]


@pytest.fixture
async def mt():
    async for client in multi_client(stub_user((ROLE_EDITOR,))):
        yield client


async def _category(client: AsyncClient, headers, name: str) -> dict:
    response = await client.post(CATEGORIES, json={"name": name}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


async def _items(client: AsyncClient, url: str, headers) -> list[dict]:
    return (await client.get(url, headers=headers)).json()["items"]


def _named(items: list[dict]) -> list[str]:
    return [c["name"] for c in items if c["id"]]


async def _tags(client: AsyncClient, headers, article_id: int, tags: list[str]) -> None:
    response = await client.put(
        f"{ARTICLES}/{article_id}/tags", json={"tags": tags}, headers=headers
    )
    assert response.status_code == 200, response.text


async def test_tenant_cannot_see_or_edit_other_tenants_article(mt: AsyncClient) -> None:
    article = await create_article(mt, A, "secret", "Mine")
    url = f"{ARTICLES}/{article['id']}"
    assert (await mt.get(f"{url}/detail", headers=A)).status_code == 200
    assert (await mt.get(f"{url}/detail", headers=B)).status_code == 404
    assert (await mt.put(url, json={"title": "Hacked"}, headers=B)).status_code == 404
    assert (await mt.post(f"{url}/publish", headers=B)).status_code == 404
    assert (await mt.delete(url, headers=B)).status_code == 404
    listed = await mt.get(ARTICLES, headers=B)
    assert listed.status_code == 200
    assert listed.json()["items"] == []
    kept = await mt.get(f"{url}/detail", headers=A)
    assert kept.json()["title"] == "Mine"
    assert [a["slug"] for a in await _items(mt, ARTICLES, A)] == ["secret"]


async def test_same_slugs_in_two_tenants(mt: AsyncClient) -> None:
    ids = {}
    for name, headers in (("a", A), ("b", B)):
        await _category(mt, headers, "Sport")
        tag = await mt.post(TAGS, json={"name": "Local"}, headers=headers)
        assert tag.status_code == 201, tag.text
        article = await create_published(mt, headers, "old", f"{name} old")
        ids[name] = article["id"]
    # ...but not twice in one tenant.
    again = await mt.post(ARTICLES, json={"title": "x", "slug": "old"}, headers=A)
    assert again.status_code == 409

    # B renames first, so it holds a redirect from "old" that A's rename must
    # not delete (the redirect rewrite is a bulk DELETE on from_slug).
    for name, headers in (("b", B), ("a", A)):
        renamed = await mt.put(
            f"{ARTICLES}/{ids[name]}", json={"slug": f"new-{name}"}, headers=headers
        )
        assert renamed.status_code == 200, renamed.text
        await publish(mt, headers, ids[name])

    async with mt.db_state.session_factory() as db:
        from news import redirects
        from simple_module_db import tenant_context

        with tenant_context("acme"):
            assert await redirects.resolve(db, "old", "en") == "new-a"
        with tenant_context("globex"):
            assert await redirects.resolve(db, "old", "en") == "new-b"
        with tenant_context("initech"):
            assert await redirects.resolve(db, "old", "en") is None


async def test_category_rename_stays_in_tenant(mt: AsyncClient) -> None:
    sport_a = await _category(mt, A, "Sport")
    await _category(mt, B, "Sport")
    await create_article(mt, A, "a-match", "A match", category="Sport")
    in_b = await create_article(mt, B, "b-match", "B match", category="Sport")

    renamed = await mt.put(f"{CATEGORIES}/{sport_a['id']}", json={"name": "Football"}, headers=A)
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["article_count"] == 1

    b_article = await mt.get(f"{ARTICLES}/{in_b['id']}/detail", headers=B)
    assert b_article.json()["category"] == "Sport"
    b_names = [c["name"] for c in await _items(mt, CATEGORIES, B)]
    assert "Sport" in b_names and "Football" not in b_names


async def test_category_delete_stays_in_tenant(mt: AsyncClient) -> None:
    sport_a = await _category(mt, A, "Sport")
    await _category(mt, B, "Sport")
    await create_article(mt, A, "a-match", "A match", category="Sport")
    in_b = await create_article(mt, B, "b-match", "B match", category="Sport")

    deleted = await mt.delete(f"{CATEGORIES}/{sport_a['id']}", headers=A)
    assert deleted.status_code == 200, deleted.text

    b_article = await mt.get(f"{ARTICLES}/{in_b['id']}/detail", headers=B)
    assert b_article.json()["category"] == "Sport"


async def test_reorder_and_tag_counts_read_back_per_tenant(mt: AsyncClient) -> None:
    """Same-named rows in two tenants: each reads back only its own position
    and usage count, not a merge of both."""
    for headers in (A, B):
        await _category(mt, headers, "Sport")
        await _category(mt, headers, "Arts")
    b_items = await _items(mt, CATEGORIES, B)
    b_ids = {c["name"]: c["id"] for c in b_items if c["id"]}
    reordered = await mt.post(
        f"{CATEGORIES}/reorder",
        json={"ordered_ids": [b_ids["Arts"], b_ids["Sport"]]},
        headers=B,
    )
    assert reordered.status_code == 204, reordered.text

    a1 = await create_article(mt, A, "a1", "A1")
    a2 = await create_article(mt, A, "a2", "A2")
    await _tags(mt, A, a1["id"], ["Local", "Rare"])
    await _tags(mt, A, a2["id"], ["Local"])
    b1 = await create_article(mt, B, "b1", "B1")
    await _tags(mt, B, b1["id"], ["Rare"])

    assert _named(await _items(mt, CATEGORIES, A)) == ["Sport", "Arts"]
    assert _named(await _items(mt, CATEGORIES, B)) == ["Arts", "Sport"]

    def counts(items):
        return {t["name"]: t["article_count"] for t in items}

    assert counts(await _items(mt, TAGS, A)) == {"Local": 2, "Rare": 1}
    assert counts(await _items(mt, TAGS, B)) == {"Rare": 1}


async def test_reorder_cannot_reach_other_tenants_ids(mt: AsyncClient) -> None:
    """``reorder`` writes whatever ids the body names, unvalidated: only the
    tenant filter on its bulk UPDATE keeps B's request off A's rows."""
    sport = await _category(mt, A, "Sport")
    arts = await _category(mt, A, "Arts")
    hijack = await mt.post(
        f"{CATEGORIES}/reorder", json={"ordered_ids": [arts["id"], sport["id"]]}, headers=B
    )
    assert hijack.status_code == 204, hijack.text
    assert _named(await _items(mt, CATEGORIES, A)) == ["Sport", "Arts"]


async def test_tag_merge_stays_in_tenant(mt: AsyncClient) -> None:
    a1 = await create_article(mt, A, "a1", "A1")
    await _tags(mt, A, a1["id"], ["Town", "City"])
    b1 = await create_article(mt, B, "b1", "B1")
    await _tags(mt, B, b1["id"], ["Town", "City"])
    a_tags = {t["name"]: t["id"] for t in await _items(mt, TAGS, A)}

    merged = await mt.post(
        f"{TAGS}/{a_tags['City']}/merge", json={"source_id": a_tags["Town"]}, headers=A
    )
    assert merged.status_code == 200, merged.text
    assert (await mt.get(f"{ARTICLES}/{b1['id']}/tags", headers=B)).json() == ["City", "Town"]


async def test_admin_without_tenant_is_403(mt: AsyncClient) -> None:
    response = await mt.get(ARTICLES)
    assert response.status_code == 403
    assert response.json()["detail"] == "tenant_required"
