"""Writes on the editor leave a usable optimistic-concurrency stamp (#444)."""

import pytest
from news.core.constants import ROUTE_PREFIX_API

pytestmark = pytest.mark.asyncio
ARTICLES = f"{ROUTE_PREFIX_API}/articles"


@pytest.mark.parametrize(
    "invalid",
    [
        {"title": ""},
        {"canonical_url": "javascript:alert(1)"},
        {"slug": "Not a slug"},
    ],
)
async def test_rejected_metadata_does_not_change_the_version(editor_client, invalid):
    created = await editor_client.post(ARTICLES, json={"title": "Original"})
    article = created.json()
    url = f"{ARTICLES}/{article['id']}"
    stamp = article["updated_at"]
    rejected = await editor_client.put(url, json={**invalid, "expected_updated_at": stamp})
    assert rejected.status_code == 422, rejected.text
    detail = (await editor_client.get(f"{url}/detail")).json()
    assert detail["updated_at"] == stamp
    assert detail["title"] == "Original"
    saved = await editor_client.put(url, json={"title": "Corrected", "expected_updated_at": stamp})
    assert saved.status_code == 200, saved.text


async def test_partial_save_returns_the_current_version(editor_client):
    article = (await editor_client.post(ARTICLES, json={"title": "Original"})).json()
    url = f"{ARTICLES}/{article['id']}"
    seo = await editor_client.put(
        url,
        json={
            "meta_description": "Summary",
            "expected_updated_at": article["updated_at"],
        },
    )
    assert seo.status_code == 200, seo.text
    stamp = seo.json()["updated_at"]
    assert stamp != article["updated_at"]
    assert (await editor_client.get(f"{url}/detail")).json()["updated_at"] == stamp
    saved = await editor_client.put(url, json={"title": "Changed", "expected_updated_at": stamp})
    assert saved.status_code == 200, saved.text
    stale = await editor_client.put(
        url, json={"title": "Someone else", "expected_updated_at": stamp}
    )
    assert stale.status_code == 409, stale.text
    assert "changed somewhere else" in stale.json()["detail"]


async def test_rejected_schedule_keeps_the_current_version(editor_client):
    article = (await editor_client.post(ARTICLES, json={"title": "Original"})).json()
    url = f"{ARTICLES}/{article['id']}"
    rejected = await editor_client.post(
        f"{url}/schedule",
        json={
            "publish_at": "2030-02-02T00:00:00Z",
            "unpublish_at": "2030-01-01T00:00:00Z",
        },
    )
    assert rejected.status_code == 422, rejected.text
    assert (await editor_client.get(f"{url}/detail")).json()["updated_at"] == article["updated_at"]


@pytest.mark.parametrize(
    "actions",
    [
        ["publish"],
        ["publish", "unpublish"],
        ["submit"],
        ["submit", "approve"],
        ["submit", "reject"],
    ],
)
async def test_workflow_response_carries_the_current_version(editor_client, actions):
    article = (await editor_client.post(ARTICLES, json={"title": "Original"})).json()
    url = f"{ARTICLES}/{article['id']}"
    for action in actions:
        response = await editor_client.post(f"{url}/{action}", json={})
        assert response.status_code == 200, response.text
        article = response.json()
        detail = (await editor_client.get(f"{url}/detail")).json()
        assert article["updated_at"] == detail["updated_at"]
    saved = await editor_client.put(
        url,
        json={
            "title": "Changed",
            "expected_updated_at": article["updated_at"],
        },
    )
    assert saved.status_code == 200, saved.text


async def test_rejected_tags_after_metadata_save_keeps_the_metadata_version(editor_client):
    article = (await editor_client.post(ARTICLES, json={"title": "Original"})).json()
    url = f"{ARTICLES}/{article['id']}"
    saved = await editor_client.put(
        url,
        json={
            "title": "Saved headline",
            "expected_updated_at": article["updated_at"],
        },
    )
    assert saved.status_code == 200, saved.text
    stamp = saved.json()["updated_at"]
    rejected = await editor_client.put(f"{url}/tags", json={"tags": ["!!!"]})
    assert rejected.status_code == 422, rejected.text
    detail = (await editor_client.get(f"{url}/detail")).json()
    assert detail["updated_at"] == stamp
    assert detail["title"] == "Saved headline"
    retried = await editor_client.put(
        url, json={"author": "Corrected", "expected_updated_at": stamp}
    )
    assert retried.status_code == 200, retried.text


async def test_slug_collision_is_not_a_stale_write_envelope(editor_client):
    await editor_client.post(ARTICLES, json={"title": "Taken", "slug": "taken"})
    article = (await editor_client.post(ARTICLES, json={"title": "Original"})).json()
    url = f"{ARTICLES}/{article['id']}"
    collision = await editor_client.put(
        url, json={"slug": "taken", "expected_updated_at": article["updated_at"]}
    )
    assert collision.status_code == 409, collision.text
    assert collision.json() == {"detail": "Slug already in use"}
    saved = await editor_client.put(
        url, json={"slug": "available", "expected_updated_at": article["updated_at"]}
    )
    assert saved.status_code == 200, saved.text
