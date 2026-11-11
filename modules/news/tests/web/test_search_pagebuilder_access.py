"""The search screen shows pagebuilder's sections only to its readers (pagebuilder #346).

Pagebuilder's drafts and media library need one of its own permissions. A news
editor without one would otherwise find draft pages here, excerpts included,
behind links into screens that answer 403.
"""

from __future__ import annotations

import pytest
from news.integrations import pagebuilder as pb

from tests.support.search import _page

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not pb.available(), reason="pagebuilder is an optional extra"),
]

SEARCH = "/api/news/search?q=quartz"


async def _seed(client) -> None:
    async with client.db_state.session_factory() as db:
        await _page(db, "quartz-page", title="Quartz page")


async def test_a_news_editor_without_pagebuilder_sees_no_pages_or_media(editor_client):
    await _seed(editor_client)
    response = await editor_client.get(SEARCH)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["pages"] == [] and body["page_total"] == 0
    assert body["media"] == [] and body["media_total"] == 0
    assert body["pages_more_url"] == "" and body["media_more_url"] == ""


async def test_a_pagebuilder_reader_still_sees_them(admin_client):
    await _seed(admin_client)
    body = (await admin_client.get(SEARCH)).json()
    assert [hit["title"] for hit in body["pages"]] == ["Quartz page"]
    assert body["pages_more_url"]


@pytest.mark.parametrize(
    ("held", "expected"),
    [
        (set(), False),
        ({"news.edit"}, False),
        ({"pagebuilder.edit"}, True),
        ({"pagebuilder.approve"}, True),
        ({"*"}, True),
    ],
)
async def test_may_read_is_pagebuilders_rule(held, expected):
    assert pb.may_read(held) is expected
