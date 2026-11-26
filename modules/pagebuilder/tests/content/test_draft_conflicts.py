"""Draft saves guard the version loaded by an editor (#448)."""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def create(client: AsyncClient) -> tuple[str, dict]:
    response = await client.post(
        "/api/pagebuilder/pages",
        json={"title": "Original", "slug": "conflict", "draft_data": {"content": []}},
    )
    assert response.status_code == 201, response.text
    page = response.json()
    return f"/api/pagebuilder/pages/{page['id']}", page


async def test_stale_save_leaves_content_seo_and_slug_unchanged(authed_client):
    path, page = await create(authed_client)
    first = await authed_client.put(path, json={"title": "Other editor"})
    assert first.status_code == 200
    stale = await authed_client.put(path, json={
        "expected_updated_at": page["updated_at"],
        "title": "Stale title", "slug": "stale", "meta_title": "Stale SEO",
        "draft_data": {"content": [{"type": "Heading", "props": {"text": "Lost"}}]},
    })
    assert stale.status_code == 409, stale.text
    assert stale.json() == {
        "detail": "This page was changed elsewhere",
        "code": "page_conflict",
    }
    stored = (await authed_client.get(path)).json()
    assert stored == first.json()


async def test_current_token_and_returned_token_allow_successive_saves(authed_client):
    path, page = await create(authed_client)
    for title in ("First save", "Second save"):
        saved = await authed_client.put(path, json={
            "title": title, "expected_updated_at": page["updated_at"],
        })
        assert saved.status_code == 200, saved.text
        assert saved.json()["title"] == title
        assert saved.json()["updated_at"] != page["updated_at"]
        page = saved.json()


async def test_no_token_still_deliberately_overwrites(authed_client):
    path, _ = await create(authed_client)
    await authed_client.put(path, json={"title": "Other editor"})
    saved = await authed_client.put(path, json={"title": "Overwrite"})
    assert saved.status_code == 200, saved.text
    assert (await authed_client.get(path)).json()["title"] == "Overwrite"


async def test_equivalent_offset_is_the_same_token(authed_client):
    path, _ = await create(authed_client)
    page = (await authed_client.put(path, json={"title": "First"})).json()
    instant = datetime.fromisoformat(page["updated_at"])
    offset = instant.astimezone(timezone(timedelta(hours=2))).isoformat()
    response = await authed_client.put(path, json={
        "title": "Second", "expected_updated_at": offset,
    })
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("action", [
    "publish", "unpublish", "submit", "approve", "reject", "schedule", "restore",
    "settings", "template",
])
async def test_screen_writes_return_the_token_for_the_next_draft_save(authed_client, action):
    path, _ = await create(authed_client)
    if action == "unpublish":
        await authed_client.post(f"{path}/publish")
    if action in {"approve", "reject"}:
        await authed_client.post(f"{path}/submit")
    revision = None
    if action == "restore":
        await authed_client.post(f"{path}/publish")
        revision = (await authed_client.get(f"{path}/revisions")).json()["items"][0]["id"]
        await authed_client.put(path, json={"title": "After revision"})
    before = (await authed_client.get(path)).json()
    if action in {"settings", "template"}:
        body = {"meta_title": "SEO title"} if action == "settings" else {"is_template": True}
        response = await authed_client.put(path, json=body)
    elif action == "restore":
        response = await authed_client.post(f"{path}/revisions/{revision}/restore")
    else:
        body = {"note": "Please revise"} if action == "reject" else {}
        if action == "schedule":
            body = {"publish_at": "2099-01-01T09:00:00Z"}
        response = await authed_client.post(f"{path}/{action}", json=body)
    assert response.status_code == 200, response.text
    token = response.json()["updated_at"]
    assert token != before["updated_at"]
    stale = await authed_client.put(path, json={
        "title": "Stale", "expected_updated_at": before["updated_at"],
    })
    assert stale.status_code == 409, stale.text
    saved = await authed_client.put(path, json={
        "title": "Next draft", "expected_updated_at": token,
    })
    assert saved.status_code == 200, saved.text
    assert saved.json()["title"] == "Next draft"


@pytest.mark.parametrize("action", [
    "publish", "unpublish", "submit", "approve", "reject", "schedule", "restore",
])
async def test_stale_side_write_cannot_mask_another_edit(authed_client, action):
    path, page = await create(authed_client)
    if action in {"approve", "reject"}:
        page = (await authed_client.post(f"{path}/submit")).json()
    revision = None
    if action in {"unpublish", "restore"}:
        page = (await authed_client.post(f"{path}/publish")).json()
        revision = (await authed_client.get(f"{path}/revisions")).json()["items"][0]["id"]
    current = (await authed_client.put(path, json={"title": "Other editor"})).json()
    body = {"expected_updated_at": page["updated_at"]}
    if action == "reject":
        body["note"] = "Please revise"
    if action == "schedule":
        body["publish_at"] = "2099-01-01T09:00:00Z"
    endpoint = f"revisions/{revision}/restore" if action == "restore" else action
    refused = await authed_client.post(f"{path}/{endpoint}", json=body)
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "page_conflict"
    assert (await authed_client.get(path)).json() == current
