"""Version checks serialize competing edit-screen requests (#444)."""

import asyncio

import pytest
from news.content._fresh import STALE_DETAIL

from tests.content.test_article_write_races import racing_client as racing_client
from tests.content.test_side_write_versions import CASES, prepare

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("action", [action for action in CASES if action != "tags"])
async def test_only_one_writer_can_use_a_base_version(racing_client, action):
    url, target, method, payload, base = await prepare(racing_client, action)
    expected = {"expected_updated_at": base["updated_at"]}
    side, main = await asyncio.gather(
        getattr(racing_client, method)(target, json={**payload, **expected}),
        racing_client.put(url, json={"title": "Concurrent headline", **expected}),
    )
    assert sorted([side.status_code, main.status_code]) == [200, 409], (side.text, main.text)
    refused = side if side.status_code == 409 else main
    assert refused.json()["detail"] == STALE_DETAIL
    detail = (await racing_client.get(f"{url}/detail")).json()
    if main.status_code == 200:
        assert detail["title"] == "Concurrent headline"
        assert detail["publish_at"] == base["publish_at"]
        assert detail["status"] == base["status"]
    else:
        assert detail["title"] == ("Headline A" if action == "revision" else base["title"])
