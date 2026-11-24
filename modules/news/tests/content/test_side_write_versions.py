"""Every edit-screen side write checks its base before changing anything (#444)."""

import pytest
from news.content._fresh import STALE_DETAIL
from news.core.constants import ROUTE_PREFIX_API

pytestmark = pytest.mark.asyncio
ARTICLES = f"{ROUTE_PREFIX_API}/articles"
CASES = [
    "seo", "tags", "schedule", "publish", "unpublish", "submit", "approve", "reject", "revision"
]


async def prepare(client, action):
    article = (await client.post(ARTICLES, json={"title": "Headline A"})).json()
    url = f"{ARTICLES}/{article['id']}"
    if action in ("unpublish", "revision"):
        response = await client.post(f"{url}/publish")
        assert response.status_code == 200, response.text
    if action in ("approve", "reject"):
        response = await client.post(f"{url}/submit")
        assert response.status_code == 200, response.text
    suffix = action
    payload = {}
    method = "post"
    if action == "seo":
        suffix, method = "", "put"
        payload = {"meta_description": "Search summary"}
    elif action == "tags":
        method = "put"
        payload = {"tags": ["Edited"]}
    elif action == "schedule":
        payload = {"publish_at": "2030-01-01T00:00:00Z"}
    elif action == "reject":
        payload = {"note": "Needs work"}
    elif action == "revision":
        revisions = (await client.get(f"{url}/revisions")).json()
        suffix = f"revisions/{revisions[0]['id']}/restore"
        await client.put(url, json={"title": "Working draft"})
    detail = (await client.get(f"{url}/detail")).json()
    return url, f"{url}/{suffix}" if suffix else url, method, payload, detail


@pytest.mark.parametrize("action", CASES)
async def test_stale_side_write_changes_neither_article_nor_history(editor_client, action):
    url, target, method, payload, base = await prepare(editor_client, action)
    saved = await editor_client.put(url, json={"title": "Headline B"})
    assert saved.status_code == 200, saved.text
    before = (await editor_client.get(f"{url}/detail")).json()
    history = (await editor_client.get(f"{url}/revisions")).json()
    response = await getattr(editor_client, method)(
        target, json={**payload, "expected_updated_at": base["updated_at"]}
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == STALE_DETAIL
    assert (await editor_client.get(f"{url}/detail")).json() == before
    assert (await editor_client.get(f"{url}/revisions")).json() == history


@pytest.mark.parametrize("action", CASES)
@pytest.mark.parametrize("version", ["current", "omitted", "null"])
async def test_side_write_accepts_current_or_optional_version(editor_client, action, version):
    url, target, method, payload, base = await prepare(editor_client, action)
    if version != "omitted":
        payload["expected_updated_at"] = base["updated_at"] if version == "current" else None
    response = await getattr(editor_client, method)(
        target, **({"json": payload} if payload else {})
    )
    assert response.status_code == 200, response.text
    detail = (await editor_client.get(f"{url}/detail")).json()
    if action == "tags":
        assert detail["tags"] == ["Edited"]
        return
    assert detail["updated_at"] == response.json()["updated_at"]
    assert detail["updated_at"] != base["updated_at"]
    if action == "seo":
        assert detail["meta_description"] == "Search summary"
    elif action == "schedule":
        assert detail["publish_at"].startswith("2030-01-01T00:00:00")
    elif action in ("publish", "approve"):
        assert detail["status"] == "published"
    elif action == "submit":
        assert detail["status"] == "submitted_for_review"
    elif action in ("unpublish", "reject"):
        assert detail["status"] == "draft"
    else:
        assert detail["title"] == "Headline A"
